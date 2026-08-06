"""Shared durable lifecycle storage for company analytics runs."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any

from .memory import DecisionMemoryStore

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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _default_state_dir() -> Path:
    configured = os.environ.get("STOCKRESEARCHAGENTS_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "stock-research-agents"
    return Path.home() / ".local" / "state" / "stock-research-agents"


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
        candidate = _json_copy(record)
        self._validate_record_size(candidate)
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
                self._validate_record_size(candidate)
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


LIFECYCLE_STORE = LifecycleStore(_state_dir_factory=_default_state_dir)


def default_decision_memory_store() -> DecisionMemoryStore:
    """Return the shared durable memory store used by analytics lifecycle adapters."""

    return DecisionMemoryStore(_default_state_dir() / "decision-memory.sqlite3")
