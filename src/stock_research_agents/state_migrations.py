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
    paths = sorted(path for path in root.rglob("*.sqlite3") if not path.name.endswith(("-wal", "-shm")))
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


__all__ = ["STATE_SCHEMA_VERSION", "StateMigrationPlan", "migrate_state", "plan_state_migration"]
