"""Validated, backup-first schema adoption for durable local state."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .contracts import EventKind, RunEvent, RunStatus
from .lifecycle import LifecycleRecordV1
from .publication import validate_completed_publication
from .research_quality_v1 import QualityStore
from .serialization import (
    StoredResult,
    deserialize_run_events,
    deserialize_run_result,
    serialize_run_events,
    serialize_run_result,
)

STATE_SCHEMA_VERSION = "1.0.0"
_MANIFEST_NAME = "state-schema.json"
_MAX_JSON_FILES = 10_000
_MAX_JSON_BYTES = 16_000_000


@dataclass(frozen=True, slots=True)
class StateMigrationPlan:
    status: Literal["uninitialized", "current", "migration_required", "migrated"]
    source_schema_version: str | None
    target_schema_version: str
    validated_json_files: int
    validated_sqlite_databases: int
    backup_required: bool
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"limitations": list(self.limitations)}


def _manifest(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("state schema manifest must be valid JSON") from exc
    fields = {"schema_version", "source_schema_version", "migrated_at"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("state schema manifest must contain exactly the v1 fields")
    if value["schema_version"] != STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported state schema version: {value['schema_version']!r}")
    if value["source_schema_version"] is not None and not isinstance(value["source_schema_version"], str):
        raise ValueError("state schema source_schema_version must be a string or null")
    if not isinstance(value["migrated_at"], str):
        raise ValueError("state schema migrated_at must be a string")
    try:
        timestamp = datetime.fromisoformat(value["migrated_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("state schema migrated_at must be an ISO-8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise ValueError("state schema migrated_at must include a timezone")
    return value


def _reject_symlinks(root: Path) -> None:
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("state must not contain symbolic links")


def _validate_json_artifacts(root: Path) -> int:
    paths = sorted(path for path in root.rglob("*.json") if path.name != _MANIFEST_NAME)
    if len(paths) > _MAX_JSON_FILES:
        raise ValueError(f"state contains more than {_MAX_JSON_FILES} JSON artifacts")
    for path in paths:
        if path.is_symlink():
            raise ValueError("state JSON artifacts must not be symbolic links")
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise ValueError(f"state JSON artifact exceeds {_MAX_JSON_BYTES} bytes: {path.name}")
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"state artifact must be valid JSON: {path.name}") from exc
    return len(paths)


def _validate_sqlite_databases(root: Path) -> int:
    paths = sorted(root.rglob("*.sqlite3"))
    for path in paths:
        if path.is_symlink():
            raise ValueError("state SQLite databases must not be symbolic links")
        uri = f"{path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as exc:
            raise ValueError(f"state SQLite database failed validation: {path.name}") from exc
        if result != ("ok",):
            raise ValueError(f"state SQLite database failed quick_check: {path.name}")
    return len(paths)


def _read_json_value(path: Path, description: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} must be valid JSON: {path.name}") from exc


def _same_publication(
    left: tuple[StoredResult, tuple[RunEvent, ...]],
    right: tuple[StoredResult, tuple[RunEvent, ...]],
) -> bool:
    return serialize_run_result(left[0]) == serialize_run_result(right[0]) and serialize_run_events(
        left[1]
    ) == serialize_run_events(right[1])


def _is_terminal_completed_stream(events: tuple[RunEvent, ...]) -> bool:
    if not events:
        return False
    terminal = events[-1]
    return terminal.status == RunStatus.COMPLETED.value and terminal.kind is EventKind.RUN and terminal.stage_id is None


def _validate_run_state(root: Path) -> None:
    results: dict[str, StoredResult] = {}
    events: dict[str, tuple[RunEvent, ...]] = {}
    for path in sorted((root / "results").glob("*.json")):
        result = deserialize_run_result(path.read_bytes())
        if result.run_id != path.stem:
            raise ValueError(f"persisted result run_id does not match filename: {path.name}")
        results[path.stem] = result
    for path in sorted((root / "events").glob("*.json")):
        decoded = deserialize_run_events(path.read_bytes())
        if any(event.run_id != path.stem for event in decoded):
            raise ValueError(f"persisted events run_id does not match filename: {path.name}")
        events[path.stem] = decoded
    bundles: dict[str, tuple[StoredResult, tuple[RunEvent, ...]]] = {}
    recovery_intent: tuple[StoredResult, tuple[RunEvent, ...]] | None = None
    bundle_paths = [*(root / "bundles").glob("*.json"), *(root / "staged").glob("*.json")]
    direct_put = root / "direct-put.json"
    if direct_put.is_file():
        bundle_paths.append(direct_put)
    for path in sorted(bundle_paths):
        value = _read_json_value(path, "persisted run bundle")
        if not isinstance(value, dict) or set(value) != {"result", "events"}:
            raise ValueError(f"persisted run bundle has an invalid shape: {path.name}")
        result = deserialize_run_result(json.dumps(value["result"]))
        decoded_events = deserialize_run_events(json.dumps(value["events"]))
        validate_completed_publication(result, decoded_events)
        if path != direct_put and result.run_id != path.stem:
            raise ValueError(f"persisted run bundle run_id does not match filename: {path.name}")
        if path.parent.name == "bundles":
            bundles[result.run_id] = (result, decoded_events)
        elif path == direct_put:
            recovery_intent = (result, decoded_events)

    recovery_by_id = {recovery_intent[0].run_id: recovery_intent} if recovery_intent is not None else {}
    completed_sources = bundles | recovery_by_id

    for run_id, result in results.items():
        if run_id in events:
            validate_completed_publication(result, events[run_id])
        elif run_id not in completed_sources:
            raise ValueError(f"persisted completed result is missing matching events or bundle: {run_id}")

    for run_id, decoded_events in events.items():
        if run_id not in results and run_id not in completed_sources and _is_terminal_completed_stream(decoded_events):
            raise ValueError(f"persisted completed event stream is missing matching result or bundle: {run_id}")

    for run_id, publication in completed_sources.items():
        projection_result = results.get(run_id, publication[0])
        projection_events = events.get(run_id, publication[1])
        if not _same_publication(publication, (projection_result, projection_events)):
            raise ValueError(f"persisted run bundle conflicts with split projections: {run_id}")

    for run_id in bundles.keys() & recovery_by_id:
        if not _same_publication(bundles[run_id], recovery_by_id[run_id]):
            raise ValueError(f"direct-put recovery intent conflicts with persisted run bundle: {run_id}")

    current_path = root / "current.json"
    if current_path.is_file():
        current = _read_json_value(current_path, "current run pointer")
        if not isinstance(current, dict) or set(current) != {"run_id"} or not isinstance(current["run_id"], str):
            raise ValueError("current run pointer must contain only a string run_id")
        run_id = current["run_id"]
        if run_id not in events and run_id not in bundles and run_id not in recovery_by_id:
            raise ValueError("current run pointer references an unknown run")


def _validate_lifecycle_database(root: Path) -> None:
    path = root / "lifecycle.sqlite3"
    if not path.exists():
        return
    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(lifecycle_runs)"))
            if columns != ("run_id", "revision", "record_json", "updated_at"):
                raise ValueError("lifecycle SQLite schema is invalid")
            rows = connection.execute("SELECT run_id, revision, record_json, updated_at FROM lifecycle_runs").fetchall()
    except sqlite3.Error as exc:
        raise ValueError("lifecycle SQLite database failed semantic validation") from exc
    for run_id, revision, raw_record, updated_at in rows:
        try:
            value = json.loads(raw_record)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("persisted lifecycle record must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("persisted lifecycle record must be a JSON object")
        record = LifecycleRecordV1.from_mapping(value, expected_run_id=str(run_id))
        if record.revision != revision or record.updated_at != updated_at:
            raise ValueError(f"invalid persisted lifecycle row metadata: {run_id}")


def _validate_memory_database(root: Path) -> None:
    path = root / "decision-memory.sqlite3"
    if not path.exists():
        return
    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            required = {"decisions", "outcomes", "stockresearchagents_metadata"}
            if not required <= tables:
                raise ValueError("decision memory SQLite schema is invalid")
            metadata = connection.execute(
                "SELECT value FROM stockresearchagents_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if metadata != ("1.0.0",):
                raise ValueError("decision memory schema version is unsupported")
            duplicate = connection.execute(
                "SELECT run_id FROM decisions GROUP BY run_id HAVING COUNT(*) > 1 LIMIT 1"
            ).fetchone()
            if duplicate is not None:
                raise ValueError("decision memory contains duplicate run_id entries")
            json_rows = connection.execute("SELECT decision_json, context_json FROM decisions").fetchall()
            outcome_rows = connection.execute("SELECT outcome_json FROM outcomes").fetchall()
    except sqlite3.Error as exc:
        raise ValueError("decision memory SQLite database failed semantic validation") from exc
    try:
        for decision, context in json_rows:
            if not isinstance(json.loads(decision), dict) or not isinstance(json.loads(context), dict):
                raise ValueError("decision memory records must contain JSON objects")
        for (outcome,) in outcome_rows:
            if not isinstance(json.loads(outcome), dict):
                raise ValueError("decision memory outcomes must contain JSON objects")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("decision memory record must be valid JSON") from exc


def _validate_semantic_state(root: Path) -> None:
    _validate_run_state(root)
    _validate_lifecycle_database(root)
    _validate_memory_database(root)
    quality = QualityStore(root / "quality")
    quality._ensure_loaded()


def plan_state_migration(state_root: str | os.PathLike[str]) -> StateMigrationPlan:
    """Validate current artifacts and return a no-write migration decision."""
    root = Path(state_root).expanduser()
    if root.is_symlink():
        raise ValueError("state root must not be a symbolic link")
    if not root.exists():
        return StateMigrationPlan("uninitialized", None, STATE_SCHEMA_VERSION, 0, 0, False, ())
    if not root.is_dir():
        raise ValueError("state root must be a directory")
    _reject_symlinks(root)
    manifest = _manifest(root / _MANIFEST_NAME)
    json_count = _validate_json_artifacts(root)
    sqlite_count = _validate_sqlite_databases(root)
    _validate_semantic_state(root)
    if manifest is not None:
        return StateMigrationPlan(
            "current",
            STATE_SCHEMA_VERSION,
            STATE_SCHEMA_VERSION,
            json_count,
            sqlite_count,
            False,
            (),
        )
    has_artifacts = any(root.iterdir())
    return StateMigrationPlan(
        "migration_required" if has_artifacts else "uninitialized",
        None,
        STATE_SCHEMA_VERSION,
        json_count,
        sqlite_count,
        has_artifacts,
        (
            "Existing unversioned state is adopted only after validation and a complete backup; "
            "no artifact is rewritten.",
        )
        if has_artifacts
        else (),
    )


def _atomic_manifest(root: Path, source_schema_version: str | None) -> None:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".state-schema.", suffix=".tmp", dir=root)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        payload = {
            "schema_version": STATE_SCHEMA_VERSION,
            "source_schema_version": source_schema_version,
            "migrated_at": datetime.now(UTC).isoformat(),
        }
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / _MANIFEST_NAME)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def migrate_state(
    state_root: str | os.PathLike[str],
    *,
    apply: bool = False,
    backup_dir: str | os.PathLike[str] | None = None,
) -> StateMigrationPlan:
    """Adopt the current schema after a dry run and mandatory rollback backup."""
    root = Path(state_root).expanduser()
    plan = plan_state_migration(root)
    if not apply or plan.status == "current":
        return plan
    backup: Path | None = Path(backup_dir).expanduser() if backup_dir is not None else None
    if plan.backup_required and backup is None:
        raise ValueError("backup_dir is required before migrating existing state")
    if backup is not None:
        if backup.exists() or backup.is_symlink():
            raise ValueError("backup_dir must not already exist")
        try:
            backup.resolve().relative_to(root.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("backup_dir must be outside the state root")
        shutil.copytree(root, backup, copy_function=shutil.copy2)
    _atomic_manifest(root, plan.source_schema_version)
    return replace(plan, status="migrated", backup_required=False)


def ensure_runtime_state(state_root: str | os.PathLike[str]) -> None:
    """Require current compatible durable state, initializing only a new/empty root."""
    root = Path(state_root).expanduser().resolve(strict=False)
    plan = plan_state_migration(root)
    if plan.status == "current":
        return
    if plan.status == "migration_required":
        raise ValueError(
            "unversioned non-empty state is not supported at runtime; run the backup-first state migration first"
        )
    _atomic_manifest(root, None)


__all__ = [
    "STATE_SCHEMA_VERSION",
    "StateMigrationPlan",
    "ensure_runtime_state",
    "migrate_state",
    "plan_state_migration",
]
