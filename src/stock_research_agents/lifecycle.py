"""Shared durable lifecycle storage for company analytics runs."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any

from .memory import ResearchHistoryRepository
from .state import DEFAULT_STATE_LAYOUT

LIFECYCLE_SCHEMA_VERSION = "1.0.0"
_RUN_ID_PATTERN = re.compile(r"analytics-[a-f0-9]{12}\Z")
_MAX_LIFECYCLE_RECORD_BYTES = 16_000_000


def is_lifecycle_run_id(run_id: object) -> bool:
    """Return whether a run ID can belong to the durable analytics lifecycle."""

    return isinstance(run_id, str) and _RUN_ID_PATTERN.fullmatch(run_id) is not None


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


@dataclass(frozen=True, slots=True)
class LifecycleRecordV1:
    """Validated aggregate for the stable lifecycle-record wire representation."""

    run_id: str
    revision: int
    status: LifecycleStatus
    created_at: str
    updated_at: str
    _payload: dict[str, Any]

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        expected_run_id: str | None = None,
    ) -> LifecycleRecordV1:
        payload = _json_copy(value)
        if not isinstance(payload, dict):
            raise ValueError("lifecycle record must be a JSON object")
        if payload.get("schema_version") != LIFECYCLE_SCHEMA_VERSION:
            raise ValueError(f"lifecycle record schema_version must be {LIFECYCLE_SCHEMA_VERSION}")
        run_id = payload.get("run_id")
        if not is_lifecycle_run_id(run_id):
            raise ValueError("lifecycle run_id must match analytics- followed by 12 lowercase hexadecimal characters")
        if expected_run_id is not None and run_id != expected_run_id:
            raise ValueError(f"invalid persisted lifecycle record: {expected_run_id}")
        revision = payload.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError("lifecycle revision must be a non-negative integer")
        raw_status = payload.get("status")
        if not isinstance(raw_status, str):
            raise ValueError("lifecycle status is invalid")
        try:
            status = LifecycleStatus(raw_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("lifecycle status is invalid") from exc
        created_at = cls._timestamp(payload.get("created_at"), "created_at")
        updated_at = cls._timestamp(payload.get("updated_at"), "updated_at")
        if datetime.fromisoformat(updated_at) < datetime.fromisoformat(created_at):
            raise ValueError("lifecycle updated_at cannot precede created_at")
        cls._validate_identity(payload)
        cls._validate_topology(payload)
        cls._validate_state(payload, status)
        cls._validate_events(payload, str(run_id))
        return cls(str(run_id), revision, status, created_at, updated_at, payload)

    @staticmethod
    def _timestamp(value: object, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"lifecycle {field} must be a timezone-aware ISO-8601 timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"lifecycle {field} must be a timezone-aware ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"lifecycle {field} must be a timezone-aware ISO-8601 timestamp")
        return value

    @staticmethod
    def _validate_identity(payload: Mapping[str, Any]) -> None:
        for field in ("workflow_profile", "workflow_id"):
            if not isinstance(payload.get(field), str) or not payload[field]:
                raise ValueError(f"lifecycle {field} must be a non-empty string")

    @staticmethod
    def _validate_topology(payload: Mapping[str, Any]) -> None:
        topology = payload.get("topology")
        if not isinstance(topology, Mapping) or not isinstance(topology.get("stages"), list):
            raise ValueError("lifecycle topology.stages must be an array")
        stage_ids = [stage.get("id") for stage in topology["stages"] if isinstance(stage, Mapping)]
        invalid_stage_id = any(not isinstance(item, str) or not item for item in stage_ids)
        if len(stage_ids) != len(topology["stages"]) or invalid_stage_id:
            raise ValueError("lifecycle topology stages must have non-empty string IDs")
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("lifecycle topology stage IDs must be unique")
        completed = payload.get("completed_stage_ids")
        if not isinstance(completed, list) or any(not isinstance(item, str) for item in completed):
            raise ValueError("lifecycle completed_stage_ids must be an array of strings")
        if len(completed) != len(set(completed)) or completed != stage_ids[: len(completed)]:
            raise ValueError("lifecycle completed stages must be a unique topology prefix")
        active_stage = payload.get("active_stage_id")
        active_attempt = payload.get("active_attempt")
        if active_stage is None:
            if active_attempt is not None:
                raise ValueError("lifecycle active_attempt requires active_stage_id")
        elif active_stage not in stage_ids or active_stage in completed:
            raise ValueError("lifecycle active_stage_id must reference an incomplete topology stage")
        if active_attempt is not None and (
            not isinstance(active_attempt, int) or isinstance(active_attempt, bool) or active_attempt < 1
        ):
            raise ValueError("lifecycle active_attempt must be a positive integer")

    @staticmethod
    def _validate_state(payload: Mapping[str, Any], status: LifecycleStatus) -> None:
        final_submission = payload.get("final_submission")
        finalization_at = payload.get("finalization_completed_at")
        result_run_id = payload.get("result_run_id")
        if status in {LifecycleStatus.FINALIZING, LifecycleStatus.COMPLETED}:
            if not isinstance(final_submission, dict):
                raise ValueError("finalizing lifecycle records require final_submission")
            LifecycleRecordV1._timestamp(finalization_at, "finalization_completed_at")
        if status is LifecycleStatus.COMPLETED and not isinstance(result_run_id, str):
            raise ValueError("completed lifecycle records require result_run_id")
        if result_run_id is not None and not isinstance(result_run_id, str):
            raise ValueError("lifecycle result_run_id must be a string or null")

    @staticmethod
    def _validate_events(payload: Mapping[str, Any], run_id: str) -> None:
        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("lifecycle events must be an array")
        for sequence, event in enumerate(events, start=1):
            if not isinstance(event, Mapping):
                raise ValueError("lifecycle events must contain JSON objects")
            if event.get("run_id") != run_id or event.get("sequence") != sequence:
                raise ValueError("lifecycle events must have contiguous sequence values for run_id")

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._payload)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_copy(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


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
        if not is_lifecycle_run_id(run_id):
            raise ValueError("lifecycle run_id must match analytics- followed by 12 lowercase hexadecimal characters")
        return run_id

    @staticmethod
    def _validate_record_size(record: Mapping[str, Any]) -> None:
        if len(json.dumps(record, ensure_ascii=False).encode("utf-8")) > _MAX_LIFECYCLE_RECORD_BYTES:
            raise ValueError("lifecycle record exceeds the 16 MB storage limit")

    def create(self, record: Mapping[str, Any]) -> dict[str, Any]:
        aggregate = LifecycleRecordV1.from_mapping(record)
        candidate = aggregate.to_dict()
        self._validate_record_size(candidate)
        run_id = aggregate.run_id
        if aggregate.revision != 0:
            raise ValueError("new lifecycle records must start at revision 0")
        with self._lock:
            if self.database_path is None:
                if run_id in self._records:
                    raise ValueError(f"lifecycle run already exists: {run_id}")
                self._records[run_id] = candidate
                return deepcopy(candidate)
            connection = self._connect()
            try:
                try:
                    connection.execute(
                        "INSERT INTO lifecycle_runs(run_id, revision, record_json, updated_at) VALUES (?, ?, ?, ?)",
                        (run_id, 0, json.dumps(candidate, sort_keys=True), candidate["updated_at"]),
                    )
                    connection.commit()
                except sqlite3.IntegrityError as exc:
                    connection.rollback()
                    raise ValueError(f"lifecycle run already exists: {run_id}") from exc
            finally:
                connection.close()
        return deepcopy(candidate)

    def get(self, run_id: str) -> dict[str, Any] | None:
        safe_run_id = self._validate_run_id(run_id)
        with self._lock:
            if self.database_path is None:
                record = self._records.get(safe_run_id)
                if record is None:
                    return None
                return LifecycleRecordV1.from_mapping(record, expected_run_id=safe_run_id).to_dict()
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT revision, record_json FROM lifecycle_runs WHERE run_id = ?", (safe_run_id,)
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            return None
        value = json.loads(row[1])
        if not isinstance(value, dict):
            raise ValueError(f"invalid persisted lifecycle record: {safe_run_id}")
        aggregate = LifecycleRecordV1.from_mapping(value, expected_run_id=safe_run_id)
        if aggregate.revision != int(row[0]):
            raise ValueError(f"invalid persisted lifecycle revision: {safe_run_id}")
        return aggregate.to_dict()

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
                validated = LifecycleRecordV1.from_mapping(candidate, expected_run_id=safe_run_id).to_dict()
                self._validate_record_size(validated)
                self._records[safe_run_id] = validated
                return deepcopy(validated)

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
                validated = LifecycleRecordV1.from_mapping(candidate, expected_run_id=safe_run_id).to_dict()
                encoded = json.dumps(validated, ensure_ascii=False, allow_nan=False, sort_keys=True)
                if len(encoded.encode("utf-8")) > _MAX_LIFECYCLE_RECORD_BYTES:
                    raise ValueError("lifecycle record exceeds the 16 MB storage limit")
                cursor = connection.execute(
                    """
                    UPDATE lifecycle_runs
                    SET revision = ?, record_json = ?, updated_at = ?
                    WHERE run_id = ? AND revision = ?
                    """,
                    (validated["revision"], encoded, validated["updated_at"], safe_run_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise RevisionConflict(f"concurrent lifecycle update for {safe_run_id}")
                connection.commit()
                return validated
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()


LIFECYCLE_STORE = LifecycleStore(_state_dir_factory=lambda: DEFAULT_STATE_LAYOUT.root)


def default_decision_memory_store() -> ResearchHistoryRepository:
    """Return the shared durable memory store used by analytics lifecycle adapters."""

    return ResearchHistoryRepository(DEFAULT_STATE_LAYOUT.memory_database)
