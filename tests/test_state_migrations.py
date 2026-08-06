from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from stock_research_agents.state_migrations import STATE_SCHEMA_VERSION, migrate_state, plan_state_migration


def test_empty_state_dry_run_is_side_effect_free(tmp_path: Path) -> None:
    root = tmp_path / "state"

    plan = plan_state_migration(root)

    assert plan.status == "uninitialized"
    assert plan.source_schema_version is None
    assert plan.target_schema_version == STATE_SCHEMA_VERSION
    assert not root.exists()


def test_legacy_state_requires_backup_and_writes_version_manifest(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    (root / "current.json").write_text('{"run_id":"fixture-run"}\n', encoding="utf-8")

    plan = plan_state_migration(root)
    assert plan.status == "migration_required"
    assert plan.validated_json_files == 1
    with pytest.raises(ValueError, match="backup_dir is required"):
        migrate_state(root, apply=True)

    backup = tmp_path / "state-backup"
    applied = migrate_state(root, apply=True, backup_dir=backup)

    assert applied.status == "migrated"
    assert json.loads((root / "state-schema.json").read_text(encoding="utf-8"))["schema_version"] == (
        STATE_SCHEMA_VERSION
    )
    assert (backup / "current.json").read_text(encoding="utf-8") == '{"run_id":"fixture-run"}\n'
    assert plan_state_migration(root).status == "current"


def test_state_migration_rejects_corrupt_artifacts_before_backup(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    (root / "current.json").write_text("not-json", encoding="utf-8")
    backup = tmp_path / "backup"

    with pytest.raises(ValueError, match="must be valid JSON"):
        migrate_state(root, apply=True, backup_dir=backup)

    assert not backup.exists()
    assert not (root / "state-schema.json").exists()


def test_state_migration_rejects_unknown_future_schema(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    (root / "state-schema.json").write_text(
        json.dumps(
            {
                "schema_version": "99.0.0",
                "source_schema_version": None,
                "migrated_at": "2025-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported state schema version"):
        plan_state_migration(root)


def test_state_migration_rejects_unrecognized_symlink_before_backup(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("private host state\n", encoding="utf-8")
    root = tmp_path / "state"
    root.mkdir()
    (root / "unrecognized.bin").symlink_to(outside)
    backup = tmp_path / "backup"

    with pytest.raises(ValueError, match="must not contain symbolic links"):
        migrate_state(root, apply=True, backup_dir=backup)

    assert not backup.exists()


def test_state_migration_validates_sqlite_path_with_reserved_characters(tmp_path: Path) -> None:
    root = tmp_path / "state #1"
    root.mkdir()
    database = root / "quality?cache.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.commit()

    plan = plan_state_migration(root)

    assert plan.status == "migration_required"
    assert plan.validated_sqlite_databases == 1
