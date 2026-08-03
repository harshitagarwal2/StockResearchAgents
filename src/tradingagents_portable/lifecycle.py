"""Durable, harness-neutral host-run lifecycle coordination.

The terminal ``host-submission.v2`` dossier remains the source of truth for a
completed run.  This module adds a separate stage-boundary control protocol so
any host can execute that workflow incrementally, publish safe receipts, resume
after interruption, and cooperatively acknowledge cancellation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .contracts import (
    CapabilityMetadata,
    EventKind,
    PersistenceMetadata,
    RunEvent,
    RunRequest,
    RunResult,
    StageKind,
    reject_secret_shaped_keys,
)
from .host_native import prepare_host_run, submit_host_run
from .memory import DecisionMemoryStore
from .reporting import build_report_artifacts
from .store import RUN_STORE, RunStore
from .workflow import (
    expand_workflow,
    load_host_submission_schema,
    load_workflow_manifest,
    stage_contract_key,
    stage_runtime_contract,
)

LIFECYCLE_SCHEMA_VERSION = "1.0.0"
_RUN_ID_PATTERN = re.compile(r"host-[a-f0-9]{12}\Z")
_DIGEST_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
_MAX_RECEIPTS_PER_BATCH = 100
_MAX_TOTAL_RECEIPTS = 2048
_MAX_EVIDENCE_IDS_PER_RECEIPT = 256
_MAX_LIFECYCLE_RECORD_BYTES = 16_000_000
_RECEIPT_KINDS = frozenset(
    {
        "stage_started",
        "stage_completed",
        "stage_progress",
        "tool_started",
        "tool_completed",
        "tool_failed",
        "warning",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "receipt_id",
        "observed_at",
        "kind",
        "stage_id",
        "attempt",
        "capability_id",
        "host_call_id",
        "status",
        "duration_ms",
        "input_digest",
        "output_digest",
        "evidence_ids",
        "safe_summary",
    }
)


class LifecycleStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class RevisionConflict(ValueError):
    """Raised when a caller attempts to mutate a stale lifecycle revision."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _default_state_dir() -> Path:
    configured = os.environ.get("TRADINGAGENTS_PORTABLE_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "tradingagents-portable"
    return Path.home() / ".local" / "state" / "tradingagents-portable"


def _json_copy(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _request_from_wire(value: Mapping[str, Any]) -> RunRequest:
    return RunRequest(
        symbol=str(value["symbol"]),
        as_of_date=str(value["as_of_date"]),
        asset_type=str(value["asset_type"]),  # type: ignore[arg-type]
        analysts=tuple(str(item) for item in value["analysts"]),
        debate_rounds=int(value["debate_rounds"]),
        risk_rounds=int(value["risk_rounds"]),
        output_language=str(value["output_language"]),
        executor="host_native",
        checkpoint_enabled=False,
    )


def _event_from_wire(value: Mapping[str, Any]) -> RunEvent:
    return RunEvent(
        id=str(value["id"]),
        run_id=str(value["run_id"]),
        sequence=int(value["sequence"]),
        timestamp=str(value["timestamp"]),
        kind=EventKind(str(value["kind"])),
        stage_id=str(value["stage_id"]) if value.get("stage_id") is not None else None,
        status=str(value["status"]),
        message=str(value["message"]),
        data=dict(value.get("data", {})),
    )


def _emit(
    record: dict[str, Any],
    *,
    kind: EventKind,
    status: str,
    message: str,
    stage_id: str | None = None,
    data: Mapping[str, Any] | None = None,
) -> None:
    sequence = len(record["events"]) + 1
    event = RunEvent(
        id=f"{record['run_id']}:{sequence:04d}",
        run_id=record["run_id"],
        sequence=sequence,
        timestamp=_utc_now(),
        kind=kind,
        stage_id=stage_id,
        status=status,
        message=message,
        data=dict(data or {}),
    )
    record["events"].append(event.to_dict())


class LifecycleStore:
    """In-memory or SQLite/WAL lifecycle records with optimistic revisions."""

    def __init__(
        self,
        state_dir: str | os.PathLike[str] | None = None,
        *,
        _state_dir_factory: Callable[[], Path] | None = None,
    ) -> None:
        if state_dir is not None and _state_dir_factory is not None:
            raise ValueError("state_dir and _state_dir_factory are mutually exclusive")
        self._lock = RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._configured_state_dir = Path(state_dir).expanduser() if state_dir is not None else None
        self._state_dir_factory = _state_dir_factory
        self._resolved_state_dir: Path | None = None

    @property
    def state_dir(self) -> Path | None:
        if self._resolved_state_dir is None:
            self._resolved_state_dir = (
                self._configured_state_dir
                if self._configured_state_dir is not None
                else self._state_dir_factory()
                if self._state_dir_factory is not None
                else None
            )
        return self._resolved_state_dir

    @property
    def database_path(self) -> Path | None:
        return self.state_dir / "lifecycle.sqlite3" if self.state_dir is not None else None

    def _connect(self) -> sqlite3.Connection:
        database_path = self.database_path
        if database_path is None:
            raise RuntimeError("in-memory lifecycle stores do not have a SQLite connection")
        database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(database_path.parent, 0o700)
        connection = sqlite3.connect(database_path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lifecycle_runs (
                run_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                record_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        os.chmod(database_path, 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database_path}{suffix}")
            if sidecar.exists():
                os.chmod(sidecar, 0o600)
        return connection

    @staticmethod
    def _validate_run_id(run_id: str) -> str:
        if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("lifecycle run_id must match host- followed by 12 lowercase hexadecimal characters")
        return run_id

    def create(self, record: Mapping[str, Any]) -> dict[str, Any]:
        candidate = _json_copy(record)
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > _MAX_LIFECYCLE_RECORD_BYTES:
            raise ValueError("lifecycle record exceeds the 16 MB storage limit")
        run_id = self._validate_run_id(candidate["run_id"])
        if candidate.get("revision") != 0:
            raise ValueError("new lifecycle records must start at revision 0")
        with self._lock:
            if self.database_path is None:
                if run_id in self._records:
                    raise ValueError(f"lifecycle run already exists: {run_id}")
                self._records[run_id] = candidate
                return deepcopy(candidate)
            with self._connect() as connection:
                try:
                    connection.execute(
                        "INSERT INTO lifecycle_runs(run_id, revision, record_json, updated_at) VALUES (?, ?, ?, ?)",
                        (run_id, 0, json.dumps(candidate, sort_keys=True), candidate["updated_at"]),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(f"lifecycle run already exists: {run_id}") from exc
        return deepcopy(candidate)

    def get(self, run_id: str) -> dict[str, Any] | None:
        safe_run_id = self._validate_run_id(run_id)
        with self._lock:
            if self.database_path is None:
                record = self._records.get(safe_run_id)
                return deepcopy(record) if record is not None else None
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT record_json FROM lifecycle_runs WHERE run_id = ?", (safe_run_id,)
                ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        if not isinstance(value, dict) or value.get("run_id") != safe_run_id:
            raise ValueError(f"invalid persisted lifecycle record: {safe_run_id}")
        return value

    def update(
        self,
        run_id: str,
        expected_revision: int,
        mutation: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        safe_run_id = self._validate_run_id(run_id)
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        with self._lock:
            if self.database_path is None:
                original = self._records.get(safe_run_id)
                if original is None:
                    raise KeyError(f"unknown lifecycle run: {safe_run_id}")
                if original["revision"] != expected_revision:
                    raise RevisionConflict(
                        f"revision conflict for {safe_run_id}: expected {expected_revision}, "
                        f"current {original['revision']}"
                    )
                candidate = deepcopy(original)
                mutation(candidate)
                candidate["revision"] = expected_revision + 1
                candidate["updated_at"] = _utc_now()
                if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > _MAX_LIFECYCLE_RECORD_BYTES:
                    raise ValueError("lifecycle record exceeds the 16 MB storage limit")
                self._records[safe_run_id] = _json_copy(candidate)
                return deepcopy(candidate)

            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT revision, record_json FROM lifecycle_runs WHERE run_id = ?", (safe_run_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown lifecycle run: {safe_run_id}")
                current_revision = int(row[0])
                if current_revision != expected_revision:
                    raise RevisionConflict(
                        f"revision conflict for {safe_run_id}: expected {expected_revision}, current {current_revision}"
                    )
                candidate = json.loads(row[1])
                mutation(candidate)
                candidate["revision"] = expected_revision + 1
                candidate["updated_at"] = _utc_now()
                encoded = json.dumps(candidate, ensure_ascii=False, allow_nan=False, sort_keys=True)
                if len(encoded.encode("utf-8")) > _MAX_LIFECYCLE_RECORD_BYTES:
                    raise ValueError("lifecycle record exceeds the 16 MB storage limit")
                cursor = connection.execute(
                    """
                    UPDATE lifecycle_runs
                    SET revision = ?, record_json = ?, updated_at = ?
                    WHERE run_id = ? AND revision = ?
                    """,
                    (candidate["revision"], encoded, candidate["updated_at"], safe_run_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise RevisionConflict(f"concurrent lifecycle update for {safe_run_id}")
                connection.commit()
                return candidate
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()


def _topology_hash(record: Mapping[str, Any]) -> str:
    material = json.dumps(record["topology"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _request_hash(record: Mapping[str, Any]) -> str:
    material = json.dumps(record["request"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _next_stage_id(record: Mapping[str, Any]) -> str | None:
    completed = set(record["completed_stage_ids"])
    return next((stage["id"] for stage in record["topology"]["stages"] if stage["id"] not in completed), None)


def _stage_by_id(record: Mapping[str, Any], stage_id: str) -> Mapping[str, Any]:
    try:
        return next(stage for stage in record["topology"]["stages"] if stage["id"] == stage_id)
    except StopIteration as exc:
        raise ValueError(f"unknown workflow stage: {stage_id}") from exc


def _json_equal(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _matches_json_type(value: object, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise ValueError(f"unsupported JSON Schema type: {expected}")


def _validate_json_schema(
    value: object,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    path: str,
) -> None:
    reference = schema.get("$ref")
    if reference is not None:
        if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
            raise ValueError(f"{path} uses an unsupported JSON Schema reference")
        definition_name = reference.rsplit("/", 1)[-1]
        definitions = root_schema.get("$defs")
        if not isinstance(definitions, Mapping) or definition_name not in definitions:
            raise ValueError(f"{path} references an unknown JSON Schema definition")
        definition = definitions[definition_name]
        if not isinstance(definition, Mapping):
            raise ValueError(f"{path} references an invalid JSON Schema definition")
        _validate_json_schema(value, definition, root_schema, path)
        return

    expected_types = schema.get("type")
    if expected_types is not None:
        candidates = [expected_types] if isinstance(expected_types, str) else expected_types
        if not isinstance(candidates, list) or not all(isinstance(item, str) for item in candidates):
            raise ValueError(f"{path} has an invalid JSON Schema type declaration")
        if not any(_matches_json_type(value, item) for item in candidates):
            raise ValueError(f"{path} must have JSON type {' or '.join(candidates)}")

    if "const" in schema and not _json_equal(value, schema["const"]):
        raise ValueError(f"{path} must equal {schema['const']!r}")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not any(_json_equal(value, item) for item in enum)):
        raise ValueError(f"{path} must be one of {enum!r}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError(f"{path} has invalid JSON Schema properties")
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ValueError(f"{path} has an invalid JSON Schema required declaration")
        missing = sorted(item for item in required if item not in value)
        if missing:
            raise ValueError(f"{path} is missing required fields: {missing}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ValueError(f"{path} contains unsupported fields: {unknown}")
        for key, item in value.items():
            property_schema = properties.get(key)
            if property_schema is not None:
                if not isinstance(property_schema, Mapping):
                    raise ValueError(f"{path}.{key} has an invalid JSON Schema declaration")
                _validate_json_schema(item, property_schema, root_schema, f"{path}.{key}")

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            raise ValueError(f"{path} must contain at least {minimum_items} items")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            raise ValueError(f"{path} must contain at most {maximum_items} items")
        if schema.get("uniqueItems") is True:
            canonical = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(canonical) != len(set(canonical)):
                raise ValueError(f"{path} must contain unique items")
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, Mapping):
                raise ValueError(f"{path} has an invalid JSON Schema items declaration")
            for index, item in enumerate(value):
                _validate_json_schema(item, item_schema, root_schema, f"{path}[{index}]")

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise ValueError(f"{path} must contain at least {minimum_length} characters")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            raise ValueError(f"{path} must contain at most {maximum_length} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise ValueError(f"{path} does not match the required pattern")
        value_format = schema.get("format")
        try:
            if value_format == "date":
                date.fromisoformat(value)
            elif value_format == "date-time":
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
            elif value_format == "uri":
                parsed_uri = urlsplit(value)
                if not parsed_uri.scheme or not parsed_uri.netloc:
                    raise ValueError
        except ValueError as exc:
            raise ValueError(f"{path} must be a valid {value_format}") from exc

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        if isinstance(minimum, int | float) and value < minimum:
            raise ValueError(f"{path} must be greater than or equal to {minimum}")
        if isinstance(maximum, int | float) and value > maximum:
            raise ValueError(f"{path} must be less than or equal to {maximum}")
        if isinstance(exclusive_minimum, int | float) and value <= exclusive_minimum:
            raise ValueError(f"{path} must be greater than {exclusive_minimum}")


def _validate_stage_output(stage: Mapping[str, Any], output: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(output, Mapping):
        raise ValueError(f"stage {stage['id']} output must be an object")
    candidate = _json_copy(dict(output))
    reject_secret_shaped_keys(candidate, ("stage_outputs", str(stage["id"])))
    if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > 1_000_000:
        raise ValueError(f"stage {stage['id']} output exceeds the 1 MB lifecycle limit")
    schema = load_host_submission_schema()
    manifest = load_workflow_manifest()
    output_ref = manifest.stage_contracts[stage_contract_key(str(stage["id"]))]["output_ref"]
    definition_name = str(output_ref).rsplit("/", 1)[-1]
    definition = schema["$defs"][definition_name]
    _validate_json_schema(candidate, definition, schema, f"stage {stage['id']} output")
    return candidate


def _apply_stage_output(record: dict[str, Any], stage: Mapping[str, Any], output: Mapping[str, Any]) -> None:
    submission = record["submission"]
    kind = StageKind(stage["kind"])
    stage_id = str(stage["id"])
    if kind is StageKind.ANALYST:
        evidence = output["evidence"]
        report = output["report"]
        if not isinstance(evidence, list) or not isinstance(report, dict):
            raise ValueError(f"{stage_id} evidence must be an array and report must be an object")
        existing_evidence = {item["id"]: item for item in submission["evidence"]}
        for item in evidence:
            evidence_id = item["id"]
            if evidence_id in existing_evidence:
                if existing_evidence[evidence_id] != item:
                    raise ValueError(f"{stage_id} supplied conflicting evidence for id {evidence_id}")
                continue
            copied = deepcopy(item)
            submission["evidence"].append(copied)
            existing_evidence[evidence_id] = copied
        analyst_report = deepcopy(report)
        analyst_report["analyst"] = stage_id.removeprefix("analyst.")
        submission["analyst_reports"].append(analyst_report)
        if output.get("company_of_interest"):
            submission["company_of_interest"] = output["company_of_interest"]
        if output.get("instrument_context") is not None:
            submission["instrument_context"] = output["instrument_context"]
        return
    if kind in {StageKind.RESEARCH_DEBATE, StageKind.RISK_DEBATE}:
        parts = stage_id.split(".")
        debate_key = "research_debate" if kind is StageKind.RESEARCH_DEBATE else "risk_debate"
        submission[debate_key].append({"round": int(parts[1]), "speaker": stage["role"], **deepcopy(output)})
        return
    if kind is StageKind.RESEARCH_MANAGER:
        submission["research_decision"] = deepcopy(output)
    elif kind is StageKind.TRADER:
        submission["trader_decision"] = deepcopy(output)
    elif kind is StageKind.PORTFOLIO:
        submission["risk_decision"] = deepcopy(output["risk_decision"])
        submission["portfolio_decision"] = deepcopy(output["portfolio_decision"])
        submission["final_trade_decision"] = output["final_trade_decision"]
        warnings = output.get("warnings", [])
        if not isinstance(warnings, list):
            raise ValueError("portfolio.warnings must be an array")
        submission["warnings"].extend(deepcopy(warnings))


class HostRunCoordinator:
    """Coordinator that keeps execution host-owned and lifecycle semantics portable."""

    def __init__(
        self,
        lifecycle_store: LifecycleStore | None = None,
        result_store: RunStore = RUN_STORE,
        *,
        memory_store: DecisionMemoryStore | None = None,
        memory_store_factory: Callable[[], DecisionMemoryStore] | None = None,
    ) -> None:
        self.lifecycle_store = lifecycle_store or LifecycleStore()
        self.result_store = result_store
        self.memory_store = memory_store
        self._memory_store_factory = memory_store_factory

    def _memory(self) -> DecisionMemoryStore | None:
        if self.memory_store is None and self._memory_store_factory is not None:
            self.memory_store = self._memory_store_factory()
        return self.memory_store

    def decision_memory(self) -> DecisionMemoryStore:
        """Return the configured memory adapter, creating the durable default lazily."""
        memory = self._memory()
        if memory is None:
            raise RuntimeError("this coordinator has no decision memory store")
        return memory

    def _publish_events(self, record: Mapping[str, Any]) -> tuple[RunEvent, ...]:
        events = tuple(_event_from_wire(item) for item in record["events"])
        self.result_store.put_events(str(record["run_id"]), events)
        return events

    def create(
        self,
        request: RunRequest,
        *,
        memory_context: object | None = None,
        decision_memory_enabled: bool = True,
    ) -> dict[str, Any]:
        plan = prepare_host_run(request)
        memory_recall: dict[str, Any] | None = None
        if memory_context is None and decision_memory_enabled:
            memory = self._memory()
            if memory is not None:
                memory_recall = memory.recall(request.symbol).to_dict()
                memory_context = memory_recall
        run_id = "host-" + uuid4().hex[:12]
        now = _utc_now()
        record: dict[str, Any] = {
            "schema_version": LIFECYCLE_SCHEMA_VERSION,
            "run_id": run_id,
            "status": LifecycleStatus.PREPARED.value,
            "revision": 0,
            "request": deepcopy(plan["request"]),
            "topology": deepcopy(plan["topology"]),
            "submission": {
                "request": deepcopy(plan["request"]),
                "company_of_interest": request.symbol,
                "instrument_context": "",
                "evidence": [],
                "analyst_reports": [],
                "research_debate": [],
                "risk_debate": [],
                "warnings": [],
            },
            "completed_stage_ids": [],
            "attempts": {},
            "active_stage_id": None,
            "active_attempt": None,
            "receipts": [],
            "receipt_ids": [],
            "memory_context": _json_copy(memory_context) if memory_context is not None else None,
            "decision_memory_enabled": bool(decision_memory_enabled and self._memory() is not None),
            "memory_recall": memory_recall,
            "memory_stage_receipt": None,
            "memory_write_receipt": None,
            "cancel_reason": None,
            "cancel_ack_receipt_id": None,
            "failure": None,
            "result_run_id": None,
            "finalization_completed_at": None,
            "events": [],
            "created_at": now,
            "updated_at": now,
        }
        reject_secret_shaped_keys(record.get("memory_context"), ("memory_context",))
        _emit(
            record,
            kind=EventKind.RUN,
            status=LifecycleStatus.PREPARED.value,
            message="Durable host-native research run prepared; execution remains owned by the host harness.",
            data={
                "topology_hash": _topology_hash(record),
                "request_hash": _request_hash(record),
                "external_model_api_keys_accepted": False,
                "decision_memory_enabled": record["decision_memory_enabled"],
            },
        )
        saved = self.lifecycle_store.create(record)
        self._publish_events(saved)
        return self.control(run_id)

    def _get(self, run_id: str) -> dict[str, Any]:
        record = self.lifecycle_store.get(run_id)
        if record is None:
            raise KeyError(f"unknown lifecycle run: {run_id}")
        return record

    def control(self, run_id: str) -> dict[str, Any]:
        record = self._get(run_id)
        stored_status = record["status"]
        result_ready = (
            record["result_run_id"] == run_id
            and self.result_store.get_result(run_id) is not None
            and self.result_store.get_events(run_id) is not None
        )
        memory = self._memory() if record["decision_memory_enabled"] else None
        memory_ready = not record["decision_memory_enabled"] or (memory is not None and memory.is_published(run_id))
        publication_pending = stored_status == LifecycleStatus.FINALIZING.value or (
            stored_status == LifecycleStatus.COMPLETED.value and not (result_ready and memory_ready)
        )
        public_status = LifecycleStatus.FINALIZING.value if publication_pending else stored_status
        return {
            "schema_version": record["schema_version"],
            "run_id": record["run_id"],
            "status": public_status,
            "storage_status": stored_status,
            "publication_pending": publication_pending,
            "revision": record["revision"],
            "next_stage_id": _next_stage_id(record),
            "completed_stage_ids": list(record["completed_stage_ids"]),
            "active_stage_id": record["active_stage_id"],
            "active_attempt": record["active_attempt"],
            "cancel_requested": record["status"] == LifecycleStatus.CANCEL_REQUESTED.value,
            "cancel_reason": record["cancel_reason"],
            "result_run_id": record["result_run_id"],
            "checkpoint": {
                "topology_hash": _topology_hash(record),
                "request_hash": _request_hash(record),
                "last_completed_ordinal": len(record["completed_stage_ids"]),
            },
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

    def start(self, run_id: str, expected_revision: int) -> dict[str, Any]:
        def mutate(record: dict[str, Any]) -> None:
            if record["status"] != LifecycleStatus.PREPARED.value:
                raise ValueError("only a prepared run can be started")
            record["status"] = LifecycleStatus.RUNNING.value
            _emit(
                record,
                kind=EventKind.RUN,
                status=LifecycleStatus.RUNNING.value,
                message="Host harness started the durable workflow.",
            )

        record = self.lifecycle_store.update(run_id, expected_revision, mutate)
        self._publish_events(record)
        return self.next_stage(run_id)

    def next_stage(self, run_id: str) -> dict[str, Any]:
        record = self._get(run_id)
        if record["status"] not in {LifecycleStatus.RUNNING.value, LifecycleStatus.PAUSED.value}:
            raise ValueError(f"run {run_id} is not available for stage execution: {record['status']}")
        stage_id = _next_stage_id(record)
        if stage_id is None:
            return {"ok": True, "control": self.control(run_id), "stage": None, "context": None}
        request = _request_from_wire(record["request"])
        topology = expand_workflow(request)
        stage_spec = next(stage for stage in topology.stages if stage.id == stage_id)
        runtime_contract = stage_runtime_contract(stage_spec, load_workflow_manifest())
        submission = record["submission"]
        instrument_identity = {
            "symbol": request.symbol,
            "asset_type": request.asset_type,
            "as_of_date": request.as_of_date,
            "company_of_interest": submission["company_of_interest"],
            "instrument_context": submission["instrument_context"],
        }
        available_context = {
            "request": deepcopy(record["request"]),
            "instrument_identity": instrument_identity,
            "evidence": deepcopy(submission["evidence"]),
            "analyst_reports": deepcopy(submission["analyst_reports"]),
            "research_debate_so_far": deepcopy(submission["research_debate"]),
            "research_debate": deepcopy(submission["research_debate"]),
            "research_decision": deepcopy(submission.get("research_decision")),
            "trader_decision": deepcopy(submission.get("trader_decision")),
            "risk_debate_so_far": deepcopy(submission["risk_debate"]),
            "risk_debate": deepcopy(submission["risk_debate"]),
            "optional_past_context": deepcopy(record["memory_context"]),
        }
        context = {key: available_context[key] for key in runtime_contract.get("context", ())}
        return {
            "ok": True,
            "control": self.control(run_id),
            "stage": runtime_contract,
            "attempt": int(record["attempts"].get(stage_id, 0)) + 1,
            "context": context,
        }

    def append_receipts(
        self,
        run_id: str,
        receipts: Sequence[Mapping[str, Any]],
        expected_revision: int,
    ) -> dict[str, Any]:
        if not receipts:
            raise ValueError("receipts must be a non-empty sequence")
        if len(receipts) > _MAX_RECEIPTS_PER_BATCH:
            raise ValueError(f"receipt batches may contain at most {_MAX_RECEIPTS_PER_BATCH} items")
        safe_receipts = [self._validate_receipt(item) for item in receipts]

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] not in {
                LifecycleStatus.RUNNING.value,
                LifecycleStatus.CANCEL_REQUESTED.value,
            }:
                raise ValueError(f"run receipts cannot be appended while status is {record['status']}")
            known_ids = set(record["receipt_ids"])
            if len(record["receipts"]) + len(safe_receipts) > _MAX_TOTAL_RECEIPTS:
                raise ValueError(f"a lifecycle may retain at most {_MAX_TOTAL_RECEIPTS} safe receipts")
            next_stage_id = _next_stage_id(record)
            capability_ids = set(load_workflow_manifest().tool_capabilities)
            for receipt in safe_receipts:
                if receipt["receipt_id"] in known_ids:
                    raise ValueError(f"duplicate receipt_id: {receipt['receipt_id']}")
                stage_id = receipt.get("stage_id")
                if stage_id is not None:
                    _stage_by_id(record, stage_id)
                capability_id = receipt.get("capability_id")
                if capability_id is not None and capability_id not in capability_ids:
                    raise ValueError(f"unknown workflow capability_id: {capability_id}")
                if capability_id is not None:
                    if stage_id is None:
                        raise ValueError("tool receipts with capability_id must identify a stage_id")
                    request = _request_from_wire(record["request"])
                    topology = expand_workflow(request)
                    stage_spec = next(item for item in topology.stages if item.id == stage_id)
                    runtime_contract = stage_runtime_contract(stage_spec, load_workflow_manifest())
                    allowed_tools = set(runtime_contract.get("allowed_tools", ()))
                    if capability_id not in allowed_tools:
                        raise ValueError(f"capability_id {capability_id!r} is not allowed for stage {stage_id}")
                if receipt["kind"] == "stage_started":
                    if record["status"] == LifecycleStatus.CANCEL_REQUESTED.value:
                        raise ValueError("a cancelled-requested run cannot start another stage")
                    if stage_id != next_stage_id:
                        raise ValueError(f"stage_started must reference next stage {next_stage_id!r}")
                    expected_attempt = int(record["attempts"].get(stage_id, 0)) + 1
                    if receipt.get("attempt") != expected_attempt:
                        raise ValueError(f"stage {stage_id} attempt must be {expected_attempt}")
                    record["attempts"][stage_id] = expected_attempt
                    record["active_stage_id"] = stage_id
                    record["active_attempt"] = expected_attempt
                elif stage_id is not None and stage_id != record["active_stage_id"]:
                    raise ValueError("non-start receipts must reference the active stage")
                known_ids.add(receipt["receipt_id"])
                record["receipt_ids"].append(receipt["receipt_id"])
                record["receipts"].append(receipt)
                event_kind = EventKind.WARNING if receipt["kind"] == "warning" else EventKind.STAGE
                _emit(
                    record,
                    kind=event_kind,
                    status=receipt.get("status") or receipt["kind"],
                    message=receipt.get("safe_summary") or receipt["kind"].replace("_", " ").title(),
                    stage_id=stage_id,
                    data={
                        key: receipt[key]
                        for key in (
                            "receipt_id",
                            "kind",
                            "attempt",
                            "capability_id",
                            "host_call_id",
                            "duration_ms",
                            "input_digest",
                            "output_digest",
                            "evidence_ids",
                        )
                        if receipt.get(key) is not None
                    },
                )

        record = self.lifecycle_store.update(run_id, expected_revision, mutate)
        self._publish_events(record)
        return {"ok": True, "control": self.control(run_id), "accepted": len(safe_receipts)}

    @staticmethod
    def _validate_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(receipt, Mapping):
            raise ValueError("each receipt must be an object")
        candidate = _json_copy(dict(receipt))
        reject_secret_shaped_keys(candidate, ("receipts",))
        unknown = sorted(set(candidate) - _RECEIPT_FIELDS)
        if unknown:
            raise ValueError(f"receipt contains unsupported fields: {unknown}")
        receipt_id = candidate.get("receipt_id")
        if not isinstance(receipt_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", receipt_id):
            raise ValueError("receipt_id must be a safe, non-empty identifier")
        kind = candidate.get("kind")
        if kind not in _RECEIPT_KINDS:
            raise ValueError(f"receipt kind must be one of {sorted(_RECEIPT_KINDS)}")
        for key in ("input_digest", "output_digest"):
            value = candidate.get(key)
            if value is not None and (not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value)):
                raise ValueError(f"{key} must be a lowercase SHA-256 digest")
        duration = candidate.get("duration_ms")
        if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration < 0):
            raise ValueError("duration_ms must be a non-negative integer")
        attempt = candidate.get("attempt")
        if attempt is not None and (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1):
            raise ValueError("attempt must be a positive integer")
        summary = candidate.get("safe_summary")
        if summary is not None and (not isinstance(summary, str) or len(summary) > 1000):
            raise ValueError("safe_summary must be a string no longer than 1000 characters")
        evidence_ids = candidate.get("evidence_ids")
        if evidence_ids is not None and (
            not isinstance(evidence_ids, list)
            or len(evidence_ids) > _MAX_EVIDENCE_IDS_PER_RECEIPT
            or not all(isinstance(item, str) for item in evidence_ids)
        ):
            raise ValueError(f"evidence_ids must be an array of at most {_MAX_EVIDENCE_IDS_PER_RECEIPT} strings")
        if kind == "stage_completed":
            if not isinstance(candidate.get("stage_id"), str):
                raise ValueError("stage_completed receipts must identify stage_id")
            if attempt is None:
                raise ValueError("stage_completed receipts must identify attempt")
            if candidate.get("output_digest") is None:
                raise ValueError("stage_completed receipts must include output_digest")
        return candidate

    def commit_stage(
        self,
        run_id: str,
        stage_id: str,
        output: Mapping[str, Any],
        expected_revision: int,
        *,
        attempt: int | None = None,
    ) -> dict[str, Any]:
        current = self._get(run_id)
        stage = _stage_by_id(current, stage_id)
        safe_output = _validate_stage_output(stage, output)
        output_digest = hashlib.sha256(
            json.dumps(safe_output, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] != LifecycleStatus.RUNNING.value:
                raise ValueError(f"stage outputs cannot be committed while status is {record['status']}")
            next_stage_id = _next_stage_id(record)
            if stage_id != next_stage_id:
                raise ValueError(f"stage commit must reference next stage {next_stage_id!r}")
            committed_attempt = (
                attempt
                if attempt is not None
                else int(record["active_attempt"])
                if record["active_attempt"] is not None
                else int(record["attempts"].get(stage_id, 0)) + 1
            )
            if record["active_stage_id"] is not None and record["active_stage_id"] != stage_id:
                raise ValueError("stage commit does not match the active stage")
            if attempt is not None and record["active_attempt"] is not None and attempt != record["active_attempt"]:
                raise ValueError(f"stage {stage_id} commit attempt does not match the active attempt")
            record["attempts"][stage_id] = max(int(record["attempts"].get(stage_id, 0)), committed_attempt)
            _apply_stage_output(record, stage, safe_output)
            record["completed_stage_ids"].append(stage_id)
            record["active_stage_id"] = None
            record["active_attempt"] = None
            matching_starts = [
                receipt
                for receipt in record["receipts"]
                if receipt.get("kind") == "stage_started"
                and receipt.get("stage_id") == stage_id
                and receipt.get("attempt") == committed_attempt
            ]
            matching_completions = [
                receipt
                for receipt in record["receipts"]
                if receipt.get("kind") == "stage_completed"
                and receipt.get("stage_id") == stage_id
                and receipt.get("attempt") == committed_attempt
                and receipt.get("output_digest") == output_digest
            ]
            execution_receipt_ids = [
                str(receipt["receipt_id"]) for receipt in (*matching_starts[-1:], *matching_completions[-1:])
            ]
            execution_observed = bool(matching_starts and matching_completions)
            _emit(
                record,
                kind=EventKind.STAGE,
                status="completed",
                message=f"{stage['role']} stage output committed at a durable boundary.",
                stage_id=stage_id,
                data={
                    "role": stage["role"],
                    "kind": stage["kind"],
                    "attempt": committed_attempt,
                    "output_digest": output_digest,
                    "output_observed": True,
                    "execution_observed": execution_observed,
                    "execution_receipt_ids": execution_receipt_ids,
                    "checkpoint_ordinal": len(record["completed_stage_ids"]),
                },
            )

        record = self.lifecycle_store.update(run_id, expected_revision, mutate)
        self._publish_events(record)
        return self.next_stage(run_id)

    def pause(self, run_id: str, expected_revision: int, reason: str) -> dict[str, Any]:
        reason = reason.strip()
        if not reason or len(reason) > 1000:
            raise ValueError("pause reason must be between 1 and 1000 characters")

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] != LifecycleStatus.RUNNING.value:
                raise ValueError("only a running lifecycle can be paused")
            record["status"] = LifecycleStatus.PAUSED.value
            record["active_stage_id"] = None
            record["active_attempt"] = None
            _emit(record, kind=EventKind.RUN, status="paused", message=reason)

        record = self.lifecycle_store.update(run_id, expected_revision, mutate)
        self._publish_events(record)
        return self.control(run_id)

    def resume(self, run_id: str, expected_revision: int) -> dict[str, Any]:
        def mutate(record: dict[str, Any]) -> None:
            if record["status"] not in {LifecycleStatus.PAUSED.value, LifecycleStatus.RUNNING.value}:
                raise ValueError("only a paused or interrupted running lifecycle can be resumed")
            record["status"] = LifecycleStatus.RUNNING.value
            record["active_stage_id"] = None
            record["active_attempt"] = None
            _emit(
                record,
                kind=EventKind.RUN,
                status="resumed",
                message="Host harness resumed from the first incomplete portable stage boundary.",
                data={"next_stage_id": _next_stage_id(record)},
            )

        record = self.lifecycle_store.update(run_id, expected_revision, mutate)
        self._publish_events(record)
        return self.next_stage(run_id)

    def request_cancel(self, run_id: str, expected_revision: int, reason: str) -> dict[str, Any]:
        reason = reason.strip()
        if not reason or len(reason) > 1000:
            raise ValueError("cancellation reason must be between 1 and 1000 characters")

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] not in {
                LifecycleStatus.PREPARED.value,
                LifecycleStatus.RUNNING.value,
                LifecycleStatus.PAUSED.value,
            }:
                raise ValueError(f"cancellation cannot be requested while status is {record['status']}")
            record["status"] = LifecycleStatus.CANCEL_REQUESTED.value
            record["cancel_reason"] = reason
            _emit(
                record,
                kind=EventKind.RUN,
                status=LifecycleStatus.CANCEL_REQUESTED.value,
                message=reason,
                data={"cooperative": True, "host_acknowledgement_required": True},
            )

        record = self.lifecycle_store.update(run_id, expected_revision, mutate)
        self._publish_events(record)
        return self.control(run_id)

    def acknowledge_cancel(self, run_id: str, expected_revision: int, host_receipt_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", host_receipt_id):
            raise ValueError("host_receipt_id must be a safe, non-empty identifier")

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] != LifecycleStatus.CANCEL_REQUESTED.value:
                raise ValueError("cancellation can only be acknowledged after it is requested")
            record["status"] = LifecycleStatus.CANCELLED.value
            record["cancel_ack_receipt_id"] = host_receipt_id
            record["active_stage_id"] = None
            record["active_attempt"] = None
            _emit(
                record,
                kind=EventKind.RUN,
                status=LifecycleStatus.CANCELLED.value,
                message="Host harness acknowledged cooperative cancellation.",
                data={"host_receipt_id": host_receipt_id},
            )

        record = self.lifecycle_store.update(run_id, expected_revision, mutate)
        self._publish_events(record)
        return self.control(run_id)

    def fail(
        self,
        run_id: str,
        expected_revision: int,
        message: str,
        *,
        resumable: bool,
    ) -> dict[str, Any]:
        message = message.strip()
        if not message or len(message) > 2000:
            raise ValueError("failure message must be between 1 and 2000 characters")

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] != LifecycleStatus.RUNNING.value:
                raise ValueError("only a running lifecycle can record an execution failure")
            record["status"] = LifecycleStatus.PAUSED.value if resumable else LifecycleStatus.FAILED.value
            record["failure"] = {"message": message, "resumable": resumable, "recorded_at": _utc_now()}
            record["active_stage_id"] = None
            record["active_attempt"] = None
            _emit(
                record,
                kind=EventKind.WARNING,
                status=record["status"],
                message=message,
                data={"resumable": resumable},
            )

        record = self.lifecycle_store.update(run_id, expected_revision, mutate)
        self._publish_events(record)
        return self.control(run_id)

    def _build_final_result(self, record: Mapping[str, Any]) -> RunResult:
        temporary_store = RunStore()
        imported, _import_events = submit_host_run(
            record["submission"],
            store=temporary_store,
            run_id_override=str(record["run_id"]),
        )
        completed_at = record.get("finalization_completed_at")
        if not isinstance(completed_at, str) or not completed_at:
            raise ValueError("finalization_completed_at must be recorded before building the final result")
        result = replace(
            imported,
            started_at=record["created_at"],
            completed_at=completed_at,
            execution_config=replace(imported.execution_config, checkpoint_enabled=True),
            persistence=PersistenceMetadata(
                decision_memory_enabled=bool(record["decision_memory_enabled"]),
                run_logging_enabled=True,
                checkpoint_enabled=True,
                writes_expected=self.lifecycle_store.state_dir is not None or self.result_store.state_dir is not None,
                outputs=("durable_lifecycle_store", "durable_run_store", "portable_report_bundle"),
            ),
            capability=CapabilityMetadata(
                executor="host_native",
                observation_mode="host_native_submission",
                deterministic=False,
                live_data=imported.capability.live_data,
                external_credentials_required=False,
                portable_boundary_credentials_required=False,
                host_tool_auth="host_owned_unknown",
                upstream_business_logic=False,
            ),
            warnings=(
                "Portable stage events are host-supplied execution receipts; raw prompts, tool arguments, "
                "credentials, and model transcripts are intentionally excluded.",
                "Resume is supported at committed stage boundaries; an interrupted in-flight stage is replayed.",
                *imported.warnings,
            ),
        )
        return replace(result, artifacts=build_report_artifacts(result))

    def finalize(self, run_id: str, expected_revision: int) -> tuple[RunResult, tuple[RunEvent, ...]]:
        """Recoverably stage, persist, and publish a completed host-native dossier."""
        record = self._get(run_id)
        if record["revision"] != expected_revision:
            raise RevisionConflict(
                f"revision conflict for {run_id}: expected {expected_revision}, current {record['revision']}"
            )
        if record["status"] not in {
            LifecycleStatus.RUNNING.value,
            LifecycleStatus.FINALIZING.value,
            LifecycleStatus.COMPLETED.value,
        }:
            raise ValueError(f"run {run_id} cannot be finalized while status is {record['status']}")
        if _next_stage_id(record) is not None:
            raise ValueError(f"cannot finalize before every stage is committed; next stage is {_next_stage_id(record)}")

        if record["status"] == LifecycleStatus.RUNNING.value:

            def begin_finalization(candidate: dict[str, Any]) -> None:
                if candidate["status"] != LifecycleStatus.RUNNING.value or _next_stage_id(candidate) is not None:
                    raise ValueError("lifecycle changed before finalization could begin")
                candidate["status"] = LifecycleStatus.FINALIZING.value
                candidate["finalization_completed_at"] = _utc_now()
                _emit(
                    candidate,
                    kind=EventKind.RUN,
                    status=LifecycleStatus.FINALIZING.value,
                    message="Completed stage outputs validated; recoverable final publication started.",
                )

            record = self.lifecycle_store.update(run_id, expected_revision, begin_finalization)
            self._publish_events(record)

        result = self._build_final_result(record)
        current_events = tuple(_event_from_wire(item) for item in record["events"])
        self.result_store.stage(result, current_events)

        if (
            record["decision_memory_enabled"]
            and record.get("memory_stage_receipt") is None
            and record["memory_write_receipt"] is None
        ):
            memory = self._memory()
            if memory is None:  # pragma: no cover - protected by create-time state
                raise RuntimeError("decision memory was enabled but no memory store is available")
            memory_stage_receipt = memory.stage_final_decision(
                result,
                context={
                    "research_recommendation": result.research_decision.recommendation,
                    "trader_action": result.trader_decision.action,
                    "risk_level": result.risk_decision.risk_level,
                },
            ).to_dict()

            def record_memory_stage(candidate: dict[str, Any]) -> None:
                if candidate["status"] != LifecycleStatus.FINALIZING.value:
                    raise ValueError("lifecycle changed before the staged memory receipt could be recorded")
                candidate["memory_stage_receipt"] = memory_stage_receipt
                _emit(
                    candidate,
                    kind=EventKind.ARTIFACT,
                    status="staged",
                    message="Final research decision staged outside recall pending lifecycle completion.",
                    data=memory_stage_receipt,
                )

            record = self.lifecycle_store.update(run_id, int(record["revision"]), record_memory_stage)
            self._publish_events(record)

        if record["status"] == LifecycleStatus.FINALIZING.value:
            prospective_memory_receipt: dict[str, Any] | None = None
            if record["decision_memory_enabled"]:
                staged_receipt = record.get("memory_stage_receipt")
                if not isinstance(staged_receipt, dict):
                    raise ValueError("decision memory stage receipt is missing before final publication")
                prospective_memory_receipt = deepcopy(staged_receipt)
                prospective_memory_receipt["operation"] = "decision_appended"

            def complete_publication(candidate: dict[str, Any]) -> None:
                if candidate["status"] != LifecycleStatus.FINALIZING.value:
                    raise ValueError("lifecycle changed before final publication")
                if (
                    candidate["decision_memory_enabled"]
                    and candidate.get("memory_stage_receipt") is None
                    and candidate["memory_write_receipt"] is None
                ):
                    raise ValueError("decision memory must be staged before lifecycle completion")
                candidate["status"] = LifecycleStatus.COMPLETED.value
                candidate["memory_write_receipt"] = prospective_memory_receipt
                candidate["result_run_id"] = run_id
                if prospective_memory_receipt is not None:
                    _emit(
                        candidate,
                        kind=EventKind.ARTIFACT,
                        status="publication_committed",
                        message="Decision memory publication committed behind the final visibility gate.",
                        data=prospective_memory_receipt,
                    )
                _emit(
                    candidate,
                    kind=EventKind.RUN,
                    status=LifecycleStatus.COMPLETED.value,
                    message="Durable host-native research dossier completed and published.",
                    data={"artifact_ids": [artifact.id for artifact in result.artifacts]},
                )

            record = self.lifecycle_store.update(run_id, int(record["revision"]), complete_publication)

        events = tuple(_event_from_wire(item) for item in record["events"])
        self.result_store.stage(result, events)
        published_result, published_events = self.result_store.publish_staged(run_id)
        if record["decision_memory_enabled"]:
            memory = self._memory()
            if memory is None:  # pragma: no cover - protected by create-time state
                raise RuntimeError("decision memory was enabled but no memory store is available")
            memory.publish_decision(run_id)
        return published_result, published_events

    def poll_events(self, run_id: str, *, after_sequence: int = 0, limit: int = 100) -> dict[str, Any]:
        if not isinstance(after_sequence, int) or isinstance(after_sequence, bool) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        record = self._get(run_id)
        control = self.control(run_id)
        visible_events = record["events"]
        if control["publication_pending"]:
            visible_events = [
                item
                for item in visible_events
                if not (
                    (item["kind"] == EventKind.RUN.value and item["status"] == LifecycleStatus.COMPLETED.value)
                    or (item["kind"] == EventKind.ARTIFACT.value and item["status"] == "publication_committed")
                )
            ]
        events = [item for item in visible_events if int(item["sequence"]) > after_sequence][:limit]
        last_sequence = int(events[-1]["sequence"]) if events else after_sequence
        return {
            "ok": True,
            "run_id": run_id,
            "status": control["status"],
            "revision": record["revision"],
            "publication_pending": control["publication_pending"],
            "after_sequence": after_sequence,
            "last_sequence": last_sequence,
            "has_more": any(int(item["sequence"]) > last_sequence for item in visible_events),
            "events": deepcopy(events),
        }

    def lifecycle_log(self, run_id: str) -> tuple[dict[str, Any], ...]:
        """Return safe receipts for durable export; never raw host transcripts."""
        record = self._get(run_id)
        return tuple(deepcopy(record["receipts"]))


LIFECYCLE_STORE = LifecycleStore(_state_dir_factory=_default_state_dir)


def _default_memory_store() -> DecisionMemoryStore:
    return DecisionMemoryStore(_default_state_dir() / "decision-memory.sqlite3")


HOST_RUN_COORDINATOR = HostRunCoordinator(
    LIFECYCLE_STORE,
    RUN_STORE,
    memory_store_factory=_default_memory_store,
)
