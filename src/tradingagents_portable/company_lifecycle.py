"""Durable host-owned lifecycle for ``company-research.v2``.

The coordinator persists only bounded stage envelopes and safe execution
receipts. Retrieval, model execution, provider clients, credentials, and raw
tool inputs/results remain outside the portable package.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from .application_ports import DecisionMemoryPort, LifecycleRepository, ResultPublicationPort
from .company_analytics_v1 import HostSubmissionV4
from .contracts import EventKind, PersistenceMetadata, RunEvent, RunResult, reject_secret_shaped_keys
from .lifecycle import (
    LIFECYCLE_STORE,
    LifecycleStatus,
    RevisionConflict,
    default_decision_memory_store,
)
from .lifecycle_profiles import (
    COMPANY_RESEARCH_LIFECYCLE_PROFILE,
    CompanyAnalyticsLifecycleProfile,
    LifecycleProfileStrategy,
)
from .reporting import build_report_artifacts
from .research_contracts import CompanyResearchRequest
from .research_lab_v1 import StageCommitmentV1
from .store import RUN_STORE

COMPANY_LIFECYCLE_SCHEMA_VERSION = "2.0.0"
STAGE_ENVELOPE_SCHEMA_VERSION = "1.0.0"
_MAX_STAGE_ENVELOPE_BYTES = 1_500_000
_MAX_RECEIPTS_PER_BATCH = 100
_MAX_TOTAL_RECEIPTS = 2048
_MAX_EVIDENCE_IDS_PER_RECEIPT = 256
_MAX_REFERENCE_BYTES = 2**63 - 1
_MAX_MEDIA_TYPE_CHARS = 255
_MAX_RECEIPT_DURATION_MS = 7 * 24 * 60 * 60 * 1000
_DIGEST_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
_SAFE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MEDIA_TYPE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z")
_STATUS_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")
_REFERENCE_FIELDS = frozenset({"reference_id", "media_type", "sha256", "byte_length", "summary"})
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
_DEFAULT_LIFECYCLE_PROFILE = cast(LifecycleProfileStrategy, COMPANY_RESEARCH_LIFECYCLE_PROFILE)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_copy(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


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
    record["events"].append(
        RunEvent(
            id=f"{record['run_id']}:{sequence:04d}",
            run_id=record["run_id"],
            sequence=sequence,
            timestamp=_utc_now(),
            kind=kind,
            stage_id=stage_id,
            status=status,
            message=message,
            data=dict(data or {}),
        ).to_dict()
    )


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def stage_output_digest(output: Mapping[str, object]) -> str:
    """Return the receipt digest for a canonical stage output envelope."""
    return _canonical_digest(dict(output))


def stage_commitment_envelope_digest(output: Mapping[str, object], *, terminal: bool = False) -> str:
    """Digest an envelope without making terminal run-card commitments self-referential."""
    candidate = _json_copy(dict(output))
    if terminal:
        refs = candidate.get("output_refs")
        if isinstance(refs, dict) and len(refs) == 1:
            submission = next(iter(refs.values()))
            if isinstance(submission, dict):
                run_card = submission.get("run_card")
                if isinstance(run_card, dict):
                    run_card["coordinator_commitments"] = []
                    stages = run_card.get("stages")
                    if isinstance(stages, list):
                        for stage in stages:
                            if isinstance(stage, dict):
                                stage["output_digest"] = "0" * 64
                quality = submission.get("quality_receipt")
                if isinstance(quality, dict) and isinstance(quality.get("stage_digests"), list):
                    quality["stage_digests"] = [
                        [item[0], "0" * 64]
                        for item in quality["stage_digests"]
                        if isinstance(item, list | tuple) and len(item) == 2
                    ]
    return _canonical_digest(candidate)


def _stage_commitment(stage: Mapping[str, Any], attempt: int, envelope_digest: str) -> StageCommitmentV1:
    receipt = {
        "schema_version": "coordinator-stage-commit.v1",
        "stage_id": stage["id"],
        "ordinal": stage["ordinal"],
        "attempt": attempt,
        "envelope_digest": envelope_digest,
    }
    return StageCommitmentV1(str(stage["id"]), envelope_digest, _canonical_digest(receipt))


def _record_stage_commitments(record: Mapping[str, Any]) -> tuple[StageCommitmentV1, ...]:
    existing = record.get("stage_commitments")
    completed = record.get("completed_stage_ids", [])
    if isinstance(existing, list) and len(existing) == len(completed):
        return tuple(StageCommitmentV1.from_dict(item) for item in existing)
    outputs = record.get("stage_outputs", [])
    if not isinstance(outputs, list) or len(outputs) != len(completed):
        raise ValueError("durable stage outputs cannot be reconstructed into coordinator commitments")
    reconstructed: list[StageCommitmentV1] = []
    for stage_id, output in zip(completed, outputs, strict=True):
        stage = _stage(record, str(stage_id))
        attempt = int(record.get("attempts", {}).get(stage_id, 1))
        reconstructed.append(
            _stage_commitment(
                stage,
                attempt,
                stage_commitment_envelope_digest(
                    output,
                    terminal=str(stage_id) == record["topology"]["terminal_stage"],
                ),
            )
        )
    return tuple(reconstructed)


def _require_safe_id(candidate: Mapping[str, Any], key: str) -> None:
    value = candidate.get(key)
    if value is not None and (not isinstance(value, str) or _SAFE_ID_PATTERN.fullmatch(value) is None):
        raise ValueError(f"{key} must be a safe identifier no longer than 128 characters")


def _validate_observed_at(value: object) -> None:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("observed_at must be a timezone-aware ISO-8601 timestamp no longer than 64 characters")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a timezone offset")


def _stage_output_contract(
    stage: Mapping[str, Any],
    *,
    terminal_stage_id: str,
    terminal_output_ref: str,
    terminal_kind: str,
) -> dict[str, Any]:
    terminal = stage["id"] == terminal_stage_id
    return {
        "schema_version": STAGE_ENVELOPE_SCHEMA_VERSION,
        "envelope_fields": ["schema_version", "stage_id", "output_refs"],
        "required_output_refs": list(stage["output_refs"]),
        "output_value_contract": (
            {
                "kind": terminal_kind,
                "schema_ref": terminal_output_ref,
            }
            if terminal
            else {
                "kind": "bounded_opaque_reference",
                "fields": ["reference_id", "media_type", "sha256", "byte_length", "summary"],
                "max_reference_id_chars": 128,
                "reference_id_pattern": "[A-Za-z0-9][A-Za-z0-9._:-]*",
                "max_media_type_chars": _MAX_MEDIA_TYPE_CHARS,
                "media_type_format": "ascii-type/ascii-subtype",
                "sha256_format": "64-lowercase-hex-characters",
                "byte_length_type": "non-negative-integer",
                "max_summary_chars": 1000,
                "summary_type": "non-empty-string",
                "max_byte_length": _MAX_REFERENCE_BYTES,
                "nested_values_allowed": False,
                "raw_content_allowed": False,
            }
        ),
    }


def _next_stage(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    completed = set(record["completed_stage_ids"])
    return next((stage for stage in record["topology"]["stages"] if stage["id"] not in completed), None)


def _stage(record: Mapping[str, Any], stage_id: str) -> Mapping[str, Any]:
    try:
        return next(stage for stage in record["topology"]["stages"] if stage["id"] == stage_id)
    except StopIteration as exc:
        raise ValueError(f"unknown company research stage: {stage_id}") from exc


def _checkpoint_hash(record: Mapping[str, Any], key: str) -> str:
    return _canonical_digest(record[key])


class CompanyResearchCoordinator:
    """Optimistic-revision coordinator for a manifest-defined research profile."""

    def __init__(
        self,
        lifecycle_store: LifecycleRepository,
        result_store: ResultPublicationPort,
        *,
        memory_store: DecisionMemoryPort | None = None,
        memory_store_factory: Callable[[], DecisionMemoryPort] | None = None,
        profile: LifecycleProfileStrategy = _DEFAULT_LIFECYCLE_PROFILE,
    ) -> None:
        if memory_store is not None and memory_store_factory is not None:
            raise ValueError("memory_store and memory_store_factory are mutually exclusive")
        self.lifecycle_store = lifecycle_store
        self.result_store = result_store
        self.memory_store = memory_store
        self._memory_store_factory = memory_store_factory
        self.profile = profile

    def _memory(self) -> DecisionMemoryPort | None:
        if self.memory_store is None and self._memory_store_factory is not None:
            self.memory_store = self._memory_store_factory()
        return self.memory_store

    def decision_memory(self) -> DecisionMemoryPort:
        memory = self._memory()
        if memory is None:
            raise RuntimeError("this coordinator has no decision memory store")
        return memory

    def create(
        self,
        request: CompanyResearchRequest | Mapping[str, object],
        *,
        memory_context: object | None = None,
        decision_memory_enabled: bool = True,
        research_pack_id: str | None = None,
        execution_mode: str | None = None,
    ) -> dict[str, Any]:
        parsed = request if isinstance(request, CompanyResearchRequest) else CompanyResearchRequest.from_dict(request)
        plan = self.profile.prepare(
            parsed,
            research_pack_id=research_pack_id,
            execution_mode=execution_mode,
        )
        memory_recall: dict[str, Any] | None = None
        memory = self._memory() if decision_memory_enabled else None
        if decision_memory_enabled and memory is None:
            raise RuntimeError("decision memory was requested but this coordinator has no memory store")
        if memory_context is None and memory is not None:
            memory_recall = memory.recall(parsed.identity.symbol, cutoff_at=parsed.cutoff_at).to_dict()
            memory_context = memory_recall
        reject_secret_shaped_keys(memory_context, ("memory_context",))
        run_id = "host-" + uuid4().hex[:12]
        now = _utc_now()
        record: dict[str, Any] = {
            "schema_version": COMPANY_LIFECYCLE_SCHEMA_VERSION,
            "workflow_profile": self.profile.workflow_profile,
            "workflow_id": plan["workflow_id"],
            "run_id": run_id,
            "status": LifecycleStatus.PREPARED.value,
            "revision": 0,
            "request": parsed.to_dict(),
            "topology": {
                "stages": deepcopy(plan["stages"]),
                "terminal_stage": self.profile.terminal_stage_id,
            },
            "portable_boundary": deepcopy(plan["portable_boundary"]),
            "research_pack_id": research_pack_id,
            "execution_mode": plan.get("execution_mode"),
            "execution_mode_readiness": plan.get("execution_mode_readiness"),
            "execution_mode_locally_ready": plan.get("execution_mode_locally_ready"),
            "completed_stage_ids": [],
            "stage_outputs": [],
            "stage_commitments": [],
            "attempts": {},
            "active_stage_id": None,
            "active_attempt": None,
            "receipts": [],
            "receipt_ids": [],
            "memory_context": _json_copy(memory_context) if memory_context is not None else None,
            "memory_recall": memory_recall,
            "decision_memory_enabled": bool(memory is not None),
            "memory_stage_receipt": None,
            "memory_write_receipt": None,
            "final_submission": None,
            "result_run_id": None,
            "finalization_completed_at": None,
            "cancel_reason": None,
            "cancel_ack_receipt_id": None,
            "failure": None,
            "events": [],
            "created_at": now,
            "updated_at": now,
        }
        _emit(
            record,
            kind=EventKind.RUN,
            status=LifecycleStatus.PREPARED.value,
            message=f"Durable {self.profile.workflow_profile} lifecycle prepared for host-owned execution.",
            data={
                "workflow_profile": self.profile.workflow_profile,
                "request_hash": _checkpoint_hash(record, "request"),
                "topology_hash": _checkpoint_hash(record, "topology"),
                "decision_memory_enabled": record["decision_memory_enabled"],
                "execution_mode": record["execution_mode"],
                "execution_mode_readiness": record["execution_mode_readiness"],
                "external_model_api_keys_accepted": False,
            },
        )
        self.lifecycle_store.create(record)
        return self.control(run_id)

    def _get(self, run_id: str) -> dict[str, Any]:
        record = self.lifecycle_store.get(run_id)
        if record is None:
            raise KeyError(f"unknown lifecycle run: {run_id}")
        if record.get("workflow_id") != self.profile.workflow_id:
            raise ValueError(f"run {run_id} is not a {self.profile.workflow_profile} lifecycle")
        return record

    def owns_record(self, record: Mapping[str, Any]) -> bool:
        """Return whether this profile strategy owns a lifecycle record."""

        return record.get("workflow_id") == self.profile.workflow_id

    def control(self, run_id: str) -> dict[str, Any]:
        record = self._get(run_id)
        result_run_id = record.get("result_run_id")
        result_ready = bool(
            isinstance(result_run_id, str)
            and self.result_store.get_result(result_run_id) is not None
            and self.result_store.get_events(result_run_id) is not None
        )
        memory = self._memory() if record["decision_memory_enabled"] else None
        memory_ready = not record["decision_memory_enabled"] or bool(
            isinstance(result_run_id, str) and memory is not None and memory.is_published(result_run_id)
        )
        sidecars_ready = self.profile.sidecars_ready(record.get("final_submission"))
        publication_pending = record["status"] == LifecycleStatus.FINALIZING.value or (
            record["status"] == LifecycleStatus.COMPLETED.value
            and not (result_ready and memory_ready and sidecars_ready)
        )
        next_stage = _next_stage(record)
        return {
            "schema_version": record["schema_version"],
            "workflow_profile": record["workflow_profile"],
            "run_id": run_id,
            "status": LifecycleStatus.FINALIZING.value if publication_pending else record["status"],
            "storage_status": record["status"],
            "publication_pending": publication_pending,
            "sidecars_ready": sidecars_ready,
            "revision": record["revision"],
            "next_stage_id": next_stage["id"] if next_stage is not None else None,
            "completed_stage_ids": list(record["completed_stage_ids"]),
            "active_stage_id": record["active_stage_id"],
            "active_attempt": record["active_attempt"],
            "cancel_requested": record["status"] == LifecycleStatus.CANCEL_REQUESTED.value,
            "cancel_reason": record["cancel_reason"],
            "result_run_id": record["result_run_id"],
            "execution_mode": record.get("execution_mode"),
            "execution_mode_readiness": record.get("execution_mode_readiness"),
            "execution_mode_locally_ready": record.get("execution_mode_locally_ready"),
            "checkpoint": {
                "request_hash": _checkpoint_hash(record, "request"),
                "topology_hash": _checkpoint_hash(record, "topology"),
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
            _emit(record, kind=EventKind.RUN, status="running", message="Host harness started company research.")

        self.lifecycle_store.update(run_id, expected_revision, mutate)
        return self.next_stage(run_id)

    def next_stage(self, run_id: str) -> dict[str, Any]:
        record = self._get(run_id)
        if record["status"] not in {LifecycleStatus.RUNNING.value, LifecycleStatus.PAUSED.value}:
            raise ValueError(f"run {run_id} is not available for stage execution: {record['status']}")
        stage = _next_stage(record)
        if stage is None:
            return {"ok": True, "control": self.control(run_id), "stage": None, "attempt": None, "context": None}
        return {
            "ok": True,
            "control": self.control(run_id),
            "stage": deepcopy(stage),
            "attempt": int(record["attempts"].get(stage["id"], 0)) + 1,
            "context": {
                "request": deepcopy(record["request"]),
                "prior_stage_outputs": deepcopy(record["stage_outputs"]),
                "optional_past_context": deepcopy(record["memory_context"]),
                "portable_boundary": deepcopy(record["portable_boundary"]),
                "research_pack_id": record.get("research_pack_id"),
                "execution_mode": record.get("execution_mode"),
                "stage_output_contract": _stage_output_contract(
                    stage,
                    terminal_stage_id=self.profile.terminal_stage_id,
                    terminal_output_ref=self.profile.terminal_output_ref,
                    terminal_kind=self.profile.terminal_kind,
                ),
            },
        }

    @staticmethod
    def _validate_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
        candidate = _json_copy(dict(receipt))
        reject_secret_shaped_keys(candidate, ("receipts",))
        unknown = sorted(set(candidate) - _RECEIPT_FIELDS)
        if unknown:
            raise ValueError(f"receipt contains unsupported fields: {unknown}")
        if candidate.get("receipt_id") is None:
            raise ValueError("receipt_id is required")
        for key in ("receipt_id", "stage_id", "capability_id", "host_call_id"):
            _require_safe_id(candidate, key)
        kind = candidate.get("kind")
        if not isinstance(kind, str) or kind not in _RECEIPT_KINDS:
            raise ValueError(f"receipt kind must be one of {sorted(_RECEIPT_KINDS)}")
        observed_at = candidate.get("observed_at")
        if observed_at is not None:
            _validate_observed_at(observed_at)
        status = candidate.get("status")
        if status is not None and (not isinstance(status, str) or _STATUS_PATTERN.fullmatch(status) is None):
            raise ValueError("status must be a safe scalar no longer than 64 characters")
        for key in ("input_digest", "output_digest"):
            value = candidate.get(key)
            if value is not None and (not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None):
                raise ValueError(f"{key} must be a lowercase SHA-256 digest")
        attempt = candidate.get("attempt")
        if attempt is not None and (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1):
            raise ValueError("attempt must be a positive integer")
        duration = candidate.get("duration_ms")
        if duration is not None and (
            not isinstance(duration, int) or isinstance(duration, bool) or not 0 <= duration <= _MAX_RECEIPT_DURATION_MS
        ):
            raise ValueError(f"duration_ms must be an integer between 0 and {_MAX_RECEIPT_DURATION_MS}")
        summary = candidate.get("safe_summary")
        if summary is not None and (not isinstance(summary, str) or len(summary) > 1000):
            raise ValueError("safe_summary must be a string no longer than 1000 characters")
        evidence_ids = candidate.get("evidence_ids")
        if evidence_ids is not None and (
            not isinstance(evidence_ids, list)
            or len(evidence_ids) > _MAX_EVIDENCE_IDS_PER_RECEIPT
            or not all(isinstance(item, str) and _SAFE_ID_PATTERN.fullmatch(item) is not None for item in evidence_ids)
        ):
            raise ValueError(
                f"evidence_ids must be an array of at most {_MAX_EVIDENCE_IDS_PER_RECEIPT} safe identifiers"
            )
        if kind == "stage_completed" and (
            not isinstance(candidate.get("stage_id"), str) or attempt is None or candidate.get("output_digest") is None
        ):
            raise ValueError("stage_completed receipts require stage_id, attempt, and output_digest")
        return candidate

    def append_receipts(
        self,
        run_id: str,
        receipts: Sequence[Mapping[str, Any]],
        expected_revision: int,
    ) -> dict[str, Any]:
        if not receipts or len(receipts) > _MAX_RECEIPTS_PER_BATCH:
            raise ValueError(f"receipts must contain between 1 and {_MAX_RECEIPTS_PER_BATCH} items")
        safe_receipts = [self._validate_receipt(item) for item in receipts]

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] not in {LifecycleStatus.RUNNING.value, LifecycleStatus.CANCEL_REQUESTED.value}:
                raise ValueError(f"run receipts cannot be appended while status is {record['status']}")
            if len(record["receipts"]) + len(safe_receipts) > _MAX_TOTAL_RECEIPTS:
                raise ValueError(f"a lifecycle may retain at most {_MAX_TOTAL_RECEIPTS} safe receipts")
            known_ids = set(record["receipt_ids"])
            next_stage = _next_stage(record)
            for receipt in safe_receipts:
                if receipt["receipt_id"] in known_ids:
                    raise ValueError(f"duplicate receipt_id: {receipt['receipt_id']}")
                stage_id = receipt.get("stage_id")
                stage = _stage(record, stage_id) if isinstance(stage_id, str) else None
                capability_id = receipt.get("capability_id")
                if capability_id is not None:
                    if stage is None or capability_id not in stage["capabilities"]:
                        raise ValueError(f"capability_id {capability_id!r} is not allowed for stage {stage_id!r}")
                if receipt["kind"] == "stage_started":
                    if record["status"] == LifecycleStatus.CANCEL_REQUESTED.value:
                        raise ValueError("a cancel-requested run cannot start another stage")
                    if next_stage is None or stage_id != next_stage["id"]:
                        expected = next_stage["id"] if next_stage is not None else None
                        raise ValueError(f"stage_started must reference next stage {expected!r}")
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
                _emit(
                    record,
                    kind=EventKind.WARNING if receipt["kind"] == "warning" else EventKind.STAGE,
                    status=receipt.get("status") or receipt["kind"],
                    message=receipt.get("safe_summary") or receipt["kind"].replace("_", " ").title(),
                    stage_id=stage_id,
                    data={
                        key: receipt[key]
                        for key in _RECEIPT_FIELDS
                        if key != "safe_summary" and receipt.get(key) is not None
                    },
                )

        self.lifecycle_store.update(run_id, expected_revision, mutate)
        return {"ok": True, "control": self.control(run_id), "accepted": len(safe_receipts)}

    def _validate_envelope(self, stage: Mapping[str, Any], output: Mapping[str, Any]) -> dict[str, Any]:
        candidate = _json_copy(dict(output))
        reject_secret_shaped_keys(candidate, ("stage_output",))
        if set(candidate) != {"schema_version", "stage_id", "output_refs"}:
            raise ValueError("stage output envelope requires only schema_version, stage_id, and output_refs")
        if candidate["schema_version"] != STAGE_ENVELOPE_SCHEMA_VERSION:
            raise ValueError("unsupported stage output envelope schema_version")
        if candidate["stage_id"] != stage["id"]:
            raise ValueError("stage output envelope stage_id does not match the committed stage")
        refs = candidate["output_refs"]
        if not isinstance(refs, dict) or not refs:
            raise ValueError("stage output envelope output_refs must be a non-empty object")
        expected_refs = set(stage["output_refs"])
        if set(refs) != expected_refs:
            missing = sorted(expected_refs - set(refs))
            unknown = sorted(set(refs) - expected_refs)
            raise ValueError(
                f"stage output envelope refs must exactly match the manifest; missing={missing}, unknown={unknown}"
            )
        if stage["id"] != self.profile.terminal_stage_id:
            for ref_name, descriptor in refs.items():
                if not isinstance(descriptor, dict) or set(descriptor) != _REFERENCE_FIELDS:
                    raise ValueError(
                        f"nonterminal output ref {ref_name!r} must be a bounded opaque reference descriptor"
                    )
                _require_safe_id(descriptor, "reference_id")
                if descriptor.get("reference_id") is None:
                    raise ValueError(f"nonterminal output ref {ref_name!r} requires reference_id")
                media_type = descriptor.get("media_type")
                if (
                    not isinstance(media_type, str)
                    or len(media_type) > _MAX_MEDIA_TYPE_CHARS
                    or _MEDIA_TYPE_PATTERN.fullmatch(media_type) is None
                ):
                    raise ValueError(f"nonterminal output ref {ref_name!r} requires a valid media_type")
                digest = descriptor.get("sha256")
                if not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None:
                    raise ValueError(f"nonterminal output ref {ref_name!r} requires a lowercase SHA-256 digest")
                byte_length = descriptor.get("byte_length")
                if (
                    not isinstance(byte_length, int)
                    or isinstance(byte_length, bool)
                    or not 0 <= byte_length <= _MAX_REFERENCE_BYTES
                ):
                    raise ValueError(
                        f"nonterminal output ref {ref_name!r} byte_length must be an integer between 0 and "
                        f"{_MAX_REFERENCE_BYTES}"
                    )
                summary = descriptor.get("summary")
                if not isinstance(summary, str) or not summary or len(summary) > 1000:
                    raise ValueError(f"nonterminal output ref {ref_name!r} summary must contain 1 to 1000 characters")
        encoded = json.dumps(
            candidate, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode()
        if len(encoded) > _MAX_STAGE_ENVELOPE_BYTES:
            raise ValueError(f"stage output envelope exceeds the {_MAX_STAGE_ENVELOPE_BYTES}-byte bound")
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
        if attempt is not None and (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1):
            raise ValueError("attempt must be a positive integer")
        current = self._get(run_id)
        stage = _stage(current, stage_id)
        envelope = self._validate_envelope(stage, output)
        output_digest = stage_output_digest(envelope)
        final_submission: dict[str, Any] | None = None
        committed_attempt = attempt or current["active_attempt"] or int(current["attempts"].get(stage_id, 0)) + 1
        commitment = _stage_commitment(
            stage,
            int(committed_attempt),
            stage_commitment_envelope_digest(
                envelope,
                terminal=stage_id == self.profile.terminal_stage_id,
            ),
        )
        prior_commitments = _record_stage_commitments(current)
        if stage_id == self.profile.terminal_stage_id:
            if set(envelope["output_refs"]) != {self.profile.terminal_output_ref}:
                raise ValueError(
                    f"{self.profile.terminal_stage_id} must contain exactly the manifest terminal output ref"
                )
            parsed = self.profile.parse_terminal(envelope["output_refs"][self.profile.terminal_output_ref])
            submission_request = self.profile.request_from_submission(parsed)
            if _canonical_digest(submission_request.to_dict()) != _canonical_digest(current["request"]):
                raise ValueError(f"{self.profile.terminal_stage_id} request must exactly match the lifecycle request")
            if isinstance(parsed, HostSubmissionV4):
                selected_mode = current.get("execution_mode") or "compatible"
                if parsed.run_card.execution_mode != selected_mode:
                    raise ValueError("terminal run card execution_mode must match the mode selected at run creation")
                commitments = (*prior_commitments, commitment)
                committed_digests = {item.stage_id: item.envelope_digest for item in commitments}
                bound_stages = tuple(
                    replace(stage_receipt, output_digest=committed_digests[stage_receipt.stage_id])
                    for stage_receipt in parsed.run_card.stages
                )
                bound_run_card = replace(
                    parsed.run_card,
                    stages=bound_stages,
                    coordinator_commitments=commitments,
                )
                bound_quality = replace(
                    parsed.quality_receipt,
                    stage_digests=tuple(
                        (stage_receipt.stage_id, stage_receipt.output_digest or "") for stage_receipt in bound_stages
                    ),
                )
                parsed = replace(parsed, run_card=bound_run_card, quality_receipt=bound_quality)
            final_submission = parsed.to_dict()

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] != LifecycleStatus.RUNNING.value:
                raise ValueError(f"stage outputs cannot be committed while status is {record['status']}")
            next_stage = _next_stage(record)
            if next_stage is None or stage_id != next_stage["id"]:
                expected = next_stage["id"] if next_stage is not None else None
                raise ValueError(f"stage commit must reference next stage {expected!r}")
            committed_attempt = attempt or record["active_attempt"] or int(record["attempts"].get(stage_id, 0)) + 1
            if record["active_stage_id"] is not None and record["active_stage_id"] != stage_id:
                raise ValueError("stage commit does not match the active stage")
            if attempt is not None and record["active_attempt"] is not None and attempt != record["active_attempt"]:
                raise ValueError(f"stage {stage_id} commit attempt does not match the active attempt")
            completions = [
                receipt
                for receipt in record["receipts"]
                if receipt.get("kind") == "stage_completed"
                and receipt.get("stage_id") == stage_id
                and receipt.get("attempt") == committed_attempt
            ]
            if completions and any(receipt.get("output_digest") != output_digest for receipt in completions):
                raise ValueError(f"stage {stage_id} completion receipt output digest does not match the envelope")
            starts = [
                receipt
                for receipt in record["receipts"]
                if receipt.get("kind") == "stage_started"
                and receipt.get("stage_id") == stage_id
                and receipt.get("attempt") == committed_attempt
            ]
            matching_completions = [receipt for receipt in completions if receipt.get("output_digest") == output_digest]
            host_completion_attested = bool(starts and matching_completions)
            execution_receipt_ids = [
                str(receipt["receipt_id"]) for receipt in (*starts[-1:], *matching_completions[-1:])
            ]
            record["attempts"][stage_id] = max(int(record["attempts"].get(stage_id, 0)), int(committed_attempt))
            record["stage_outputs"].append(envelope)
            record["stage_commitments"] = [item.to_dict() for item in (*prior_commitments, commitment)]
            record["completed_stage_ids"].append(stage_id)
            record["active_stage_id"] = None
            record["active_attempt"] = None
            if final_submission is not None:
                record["final_submission"] = final_submission
            _emit(
                record,
                kind=EventKind.STAGE,
                status="committed",
                message=(
                    f"Validated terminal envelope for {stage_id} committed at a durable boundary."
                    if final_submission is not None
                    else f"Opaque output envelope for {stage_id} committed; host-owned content remains unverified."
                ),
                stage_id=stage_id,
                data={
                    "ordinal": stage["ordinal"],
                    "attempt": committed_attempt,
                    "output_digest": output_digest,
                    "committed_envelope_digest": commitment.envelope_digest,
                    "committed_receipt_digest": commitment.receipt_digest,
                    "output_refs": list(envelope["output_refs"]),
                    "envelope_observed": True,
                    "output_observed": final_submission is not None,
                    "output_content_verified": final_submission is not None,
                    "host_completion_attested": host_completion_attested,
                    # Portable receives bounded host receipts; it does not
                    # observe the host's private agent/tool execution itself.
                    "execution_observed": False,
                    "execution_receipt_ids": execution_receipt_ids,
                    "checkpoint_ordinal": len(record["completed_stage_ids"]),
                },
            )

        self.lifecycle_store.update(run_id, expected_revision, mutate)
        return self.next_stage(run_id)

    def pause(self, run_id: str, expected_revision: int, reason: str) -> dict[str, Any]:
        return self._transition(run_id, expected_revision, reason, LifecycleStatus.RUNNING, LifecycleStatus.PAUSED)

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
                message="Host harness resumed at the first incomplete stage boundary.",
            )

        self.lifecycle_store.update(run_id, expected_revision, mutate)
        return self.next_stage(run_id)

    def _transition(
        self,
        run_id: str,
        expected_revision: int,
        reason: str,
        source: LifecycleStatus,
        target: LifecycleStatus,
    ) -> dict[str, Any]:
        reason = reason.strip()
        if not reason or len(reason) > 1000:
            raise ValueError("reason must be between 1 and 1000 characters")

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] != source.value:
                raise ValueError(f"only a {source.value} lifecycle can transition to {target.value}")
            record["status"] = target.value
            record["active_stage_id"] = None
            record["active_attempt"] = None
            _emit(record, kind=EventKind.RUN, status=target.value, message=reason)

        self.lifecycle_store.update(run_id, expected_revision, mutate)
        return self.control(run_id)

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
            _emit(record, kind=EventKind.RUN, status="cancel_requested", message=reason, data={"cooperative": True})

        self.lifecycle_store.update(run_id, expected_revision, mutate)
        return self.control(run_id)

    def acknowledge_cancel(self, run_id: str, expected_revision: int, host_receipt_id: str) -> dict[str, Any]:
        if _SAFE_ID_PATTERN.fullmatch(host_receipt_id) is None:
            raise ValueError("host_receipt_id must be a safe, non-empty identifier")

        def mutate(record: dict[str, Any]) -> None:
            if record["status"] != LifecycleStatus.CANCEL_REQUESTED.value:
                raise ValueError("cancellation can only be acknowledged after it is requested")
            record["status"] = LifecycleStatus.CANCELLED.value
            record["cancel_ack_receipt_id"] = host_receipt_id
            record["active_stage_id"] = None
            record["active_attempt"] = None
            _emit(record, kind=EventKind.RUN, status="cancelled", message="Host acknowledged cooperative cancellation.")

        self.lifecycle_store.update(run_id, expected_revision, mutate)
        return self.control(run_id)

    def fail(self, run_id: str, expected_revision: int, message: str, *, resumable: bool) -> dict[str, Any]:
        target = LifecycleStatus.PAUSED if resumable else LifecycleStatus.FAILED
        return self._transition(run_id, expected_revision, message, LifecycleStatus.RUNNING, target)

    def _build_final_result(self, record: Mapping[str, Any]) -> tuple[RunResult, tuple[RunEvent, ...]]:
        submission = record.get("final_submission")
        if not isinstance(submission, dict):
            raise ValueError(f"validated {self.profile.terminal_stage_id} submission is missing")
        draft = self.profile.build_publication(submission)
        imported = draft.result
        completed_at = record.get("finalization_completed_at")
        if not isinstance(completed_at, str):
            raise ValueError("finalization_completed_at must be recorded before publication")
        result = replace(
            imported,
            run_id=str(record["run_id"]),
            started_at=str(record["created_at"]),
            completed_at=completed_at,
            artifacts=tuple(
                artifact
                for artifact in imported.artifacts
                if artifact.kind
                not in {
                    "report_group",
                    "report_provenance",
                    "decision_consistency.v1",
                    "complete_report",
                    "structured_result_descriptor",
                    "structured_events_descriptor",
                }
            ),
            persistence=PersistenceMetadata(
                decision_memory_enabled=bool(record["decision_memory_enabled"]),
                run_logging_enabled=True,
                checkpoint_enabled=True,
                writes_expected=self.lifecycle_store.state_dir is not None or self.result_store.state_dir is not None,
                outputs=self.profile.persistence_outputs,
            ),
        )
        result = replace(result, artifacts=(*build_report_artifacts(result), *result.artifacts))
        events = tuple(_event_from_wire(item) for item in record["events"])
        return result, events

    def finalize(self, run_id: str, expected_revision: int) -> tuple[RunResult, tuple[RunEvent, ...]]:
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
        next_stage = _next_stage(record)
        if next_stage is not None:
            raise ValueError(f"cannot finalize before every stage is committed; next stage is {next_stage['id']}")
        if record["status"] == LifecycleStatus.RUNNING.value:

            def begin(candidate: dict[str, Any]) -> None:
                candidate["status"] = LifecycleStatus.FINALIZING.value
                candidate["finalization_completed_at"] = _utc_now()
                _emit(
                    candidate,
                    kind=EventKind.RUN,
                    status="finalizing",
                    message="Validated dossier staged for recoverable publication.",
                )

            record = self.lifecycle_store.update(run_id, expected_revision, begin)

        result, events = self._build_final_result(record)
        self.result_store.stage(result, events)
        self.profile.stage_sidecars(record["final_submission"])
        if record["decision_memory_enabled"] and record.get("memory_stage_receipt") is None:
            memory = self._memory()
            if memory is None:
                raise RuntimeError("decision memory was enabled but no memory store is available")
            receipt = memory.stage_final_decision(
                result,
                context={
                    "workflow_profile": self.profile.workflow_profile,
                    "research_cutoff": record["request"]["cutoff_at"],
                },
            ).to_dict()

            def retain_memory_stage(candidate: dict[str, Any]) -> None:
                candidate["memory_stage_receipt"] = receipt
                _emit(
                    candidate,
                    kind=EventKind.ARTIFACT,
                    status="staged",
                    message="Decision memory staged outside recall.",
                    data=receipt,
                )

            record = self.lifecycle_store.update(run_id, int(record["revision"]), retain_memory_stage)

        if record["status"] == LifecycleStatus.FINALIZING.value:

            def complete(candidate: dict[str, Any]) -> None:
                candidate["status"] = LifecycleStatus.COMPLETED.value
                candidate["result_run_id"] = result.run_id
                _emit(
                    candidate,
                    kind=EventKind.RUN,
                    status="completed",
                    message=f"{self.profile.workflow_profile} lifecycle completed; publication committed.",
                )

            record = self.lifecycle_store.update(run_id, int(record["revision"]), complete)

        result, events = self._build_final_result(record)
        self.result_store.stage(result, events)
        # Sidecars are part of completed-view readiness. Publish them before the
        # canonical result so a sidecar failure cannot expose a partial run.
        self.profile.publish_sidecars(record["final_submission"])
        published = self.result_store.publish_staged(result.run_id)
        if record["decision_memory_enabled"]:
            memory = self._memory()
            if memory is None:
                raise RuntimeError("decision memory was enabled but no memory store is available")
            receipt = memory.publish_decision(result.run_id).to_dict()
            if record.get("memory_write_receipt") is None:

                def retain_memory_write(candidate: dict[str, Any]) -> None:
                    candidate["memory_write_receipt"] = receipt

                self.lifecycle_store.update(run_id, int(record["revision"]), retain_memory_write)
        return published

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
                if not (item["kind"] == EventKind.RUN.value and item["status"] == LifecycleStatus.COMPLETED.value)
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
        return tuple(deepcopy(self._get(run_id)["receipts"]))


COMPANY_RESEARCH_COORDINATOR = CompanyResearchCoordinator(
    LIFECYCLE_STORE,
    RUN_STORE,
    memory_store_factory=default_decision_memory_store,
)

COMPANY_ANALYTICS_COORDINATOR = CompanyResearchCoordinator(
    LIFECYCLE_STORE,
    RUN_STORE,
    memory_store_factory=default_decision_memory_store,
    profile=cast(LifecycleProfileStrategy, CompanyAnalyticsLifecycleProfile()),
)
