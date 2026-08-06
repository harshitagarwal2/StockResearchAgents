from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.company_analytics_v1 import CompanyAnalyticsV1Provider, analytics_run_id
from stock_research_agents.company_lifecycle import CompanyAnalyticsCoordinator
from stock_research_agents.contracts import EventKind, RunEvent
from stock_research_agents.lifecycle import LifecycleStore
from stock_research_agents.lifecycle_profiles import CompanyAnalyticsLifecycleProfile
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.state_migrations import STATE_SCHEMA_VERSION, migrate_state, plan_state_migration
from stock_research_agents.store import RunStore


def _write_unversioned_event_state(root: Path, run_id: str = "fixture-run") -> None:
    RunStore(root).put_events(
        run_id,
        (
            RunEvent(
                id=f"{run_id}:1",
                run_id=run_id,
                sequence=1,
                timestamp="2026-01-01T00:00:00+00:00",
                kind=EventKind.RUN,
                status="running",
                message="Fixture event.",
            ),
        ),
    )


def _write_unversioned_completed_state(root: Path) -> str:
    result, events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=RunStore(),
        quality_store=QualityStore(),
    )
    RunStore(root).put(result, events)
    return result.run_id


def _write_completed_lifecycle_state(root: Path, symbol: str = "ORCL") -> str:
    coordinator = CompanyAnalyticsCoordinator(
        LifecycleStore(root),
        RunStore(),
        profile=CompanyAnalyticsLifecycleProfile(QualityStore()),
    )
    submission = complete_analytics_submission(symbol)
    request = submission["company_research"]["request"]  # type: ignore[index]
    control = coordinator.create(request, decision_memory_enabled=False)
    advanced = coordinator.start(control["run_id"], control["revision"])
    revision = int(advanced["control"]["revision"])
    for stage in CompanyAnalyticsV1Provider().load_manifest()["stages"]:
        refs = stage["output_refs"]
        assert isinstance(refs, list)
        output_refs: dict[str, object] = {
            str(ref): {
                "reference_id": f"host-ref-{hashlib.sha256(str(ref).encode()).hexdigest()[:16]}",
                "media_type": "application/json",
                "sha256": hashlib.sha256(f"output:{ref}".encode()).hexdigest(),
                "byte_length": 0,
                "summary": "Validated analytics stage output retained by the host.",
            }
            for ref in refs
        }
        if stage["id"] == "publish.completed":
            output_refs = {str(refs[0]): submission}
        envelope = {"schema_version": "1.0.0", "stage_id": stage["id"], "output_refs": output_refs}
        advanced = coordinator.commit_stage(control["run_id"], stage["id"], envelope, revision)
        revision = int(advanced["control"]["revision"])
    coordinator.finalize(control["run_id"], revision)
    return str(control["run_id"])


def _replace_run_id(value: object, previous_run_id: str, run_id: str) -> object:
    if isinstance(value, dict):
        return {key: _replace_run_id(item, previous_run_id, run_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_run_id(item, previous_run_id, run_id) for item in value]
    if isinstance(value, str):
        return value.replace(previous_run_id, run_id)
    return value


def _coherently_tamper_commitment(record: dict[str, object], field: str) -> None:
    commitments = record["stage_commitments"]
    final_submission = record["final_submission"]
    assert isinstance(commitments, list) and isinstance(commitments[0], dict)
    assert isinstance(final_submission, dict)
    run_card = final_submission["run_card"]
    quality_receipt = final_submission["quality_receipt"]
    assert isinstance(run_card, dict) and isinstance(quality_receipt, dict)
    final_commitments = run_card["coordinator_commitments"]
    assert isinstance(final_commitments, list) and isinstance(final_commitments[0], dict)
    commitments[0][field] = "0" * 64
    final_commitments[0][field] = "0" * 64
    if field == "envelope_digest":
        stages = run_card["stages"]
        stage_digests = quality_receipt["stage_digests"]
        assert isinstance(stages, list) and isinstance(stages[0], dict)
        assert isinstance(stage_digests, list) and isinstance(stage_digests[0], dict)
        stages[0]["output_digest"] = "0" * 64
        stage_digests[0]["sha256"] = "0" * 64
    previous_run_id = run_card["run_id"]
    assert isinstance(previous_run_id, str)
    rebound_run_id = analytics_run_id(final_submission)
    record["final_submission"] = _replace_run_id(final_submission, previous_run_id, rebound_run_id)
    record["result_run_id"] = rebound_run_id


def test_empty_state_dry_run_is_side_effect_free(tmp_path: Path) -> None:
    root = tmp_path / "state"

    plan = plan_state_migration(root)

    assert plan.status == "uninitialized"
    assert plan.source_schema_version is None
    assert plan.target_schema_version == STATE_SCHEMA_VERSION
    assert not root.exists()


def test_legacy_state_requires_backup_and_writes_version_manifest(tmp_path: Path) -> None:
    root = tmp_path / "state"
    _write_unversioned_event_state(root)

    plan = plan_state_migration(root)
    assert plan.status == "migration_required"
    assert plan.validated_json_files == 2
    with pytest.raises(ValueError, match="backup_dir is required"):
        migrate_state(root, apply=True)

    backup = tmp_path / "state-backup"
    applied = migrate_state(root, apply=True, backup_dir=backup)

    assert applied.status == "migrated"
    assert json.loads((root / "state-schema.json").read_text(encoding="utf-8"))["schema_version"] == (
        STATE_SCHEMA_VERSION
    )
    assert json.loads((backup / "current.json").read_text(encoding="utf-8")) == {"run_id": "fixture-run"}
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


def test_state_migration_rejects_dangling_current_pointer_before_backup(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    (root / "current.json").write_text('{"run_id":"missing-run"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="current run pointer references an unknown run"):
        migrate_state(root, apply=True, backup_dir=tmp_path / "backup")

    assert not (root / "state-schema.json").exists()
    assert not (tmp_path / "backup").exists()


def test_state_migration_rejects_corrupt_typed_event_before_backup(tmp_path: Path) -> None:
    root = tmp_path / "state"
    _write_unversioned_event_state(root)
    event_path = root / "events" / "fixture-run.json"
    events = json.loads(event_path.read_text(encoding="utf-8"))
    events[0]["sequence"] = "corrupt"
    event_path.write_text(json.dumps(events), encoding="utf-8")

    with pytest.raises(ValueError, match="sequence"):
        migrate_state(root, apply=True, backup_dir=tmp_path / "backup")

    assert not (root / "state-schema.json").exists()


def test_state_migration_rejects_orphan_completed_result_before_backup(tmp_path: Path) -> None:
    root = tmp_path / "state"
    run_id = _write_unversioned_completed_state(root)
    (root / "events" / f"{run_id}.json").unlink()
    (root / "bundles" / f"{run_id}.json").unlink()
    backup = tmp_path / "backup"

    with pytest.raises(ValueError, match="completed result is missing matching events or bundle"):
        migrate_state(root, apply=True, backup_dir=backup)

    assert not backup.exists()
    assert not (root / "state-schema.json").exists()


def test_state_migration_rejects_orphan_completed_event_stream_before_backup(tmp_path: Path) -> None:
    root = tmp_path / "state"
    run_id = _write_unversioned_completed_state(root)
    (root / "results" / f"{run_id}.json").unlink()
    (root / "bundles" / f"{run_id}.json").unlink()
    backup = tmp_path / "backup"

    with pytest.raises(ValueError, match="completed event stream is missing matching result or bundle"):
        migrate_state(root, apply=True, backup_dir=backup)

    assert not backup.exists()
    assert not (root / "state-schema.json").exists()


def test_state_migration_rejects_conflicting_bundle_and_split_projection(tmp_path: Path) -> None:
    root = tmp_path / "state"
    run_id = _write_unversioned_completed_state(root)
    bundle_path = root / "bundles" / f"{run_id}.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["events"][0]["message"] = "Conflicting but individually valid event."
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(ValueError, match="bundle conflicts with split projections"):
        migrate_state(root, apply=True, backup_dir=tmp_path / "backup")

    assert not (root / "state-schema.json").exists()


def test_state_migration_rejects_corrupt_lifecycle_record_before_backup(tmp_path: Path) -> None:
    root = tmp_path / "state"
    database = root / "lifecycle.sqlite3"
    root.mkdir()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE lifecycle_runs (run_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, "
            "record_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO lifecycle_runs VALUES (?, ?, ?, ?)",
            ("analytics-123456789abc", 0, '{"attempts":"corrupt"}', "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()

    with pytest.raises(ValueError, match="lifecycle record schema_version"):
        migrate_state(root, apply=True, backup_dir=tmp_path / "backup")

    assert not (root / "state-schema.json").exists()


def test_state_migration_rejects_cross_bound_completed_lifecycle_before_backup(tmp_path: Path) -> None:
    root = tmp_path / "state"
    run_id = _write_completed_lifecycle_state(root)
    database = root / "lifecycle.sqlite3"
    meta_submission = complete_analytics_submission("META")
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute("SELECT record_json FROM lifecycle_runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        record = json.loads(row[0])
        record["final_submission"] = meta_submission
        record["result_run_id"] = analytics_run_id(meta_submission)
        connection.execute(
            "UPDATE lifecycle_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), run_id),
        )
        connection.commit()
    backup = tmp_path / "backup"

    with pytest.raises(ValueError, match="final_submission request must exactly match"):
        migrate_state(root, apply=True, backup_dir=backup)

    assert not backup.exists()
    assert not (root / "state-schema.json").exists()


@pytest.mark.parametrize("field", ("envelope_digest", "receipt_digest"))
def test_state_migration_rejects_tampered_stage_commitment_digest_before_backup(
    tmp_path: Path,
    field: str,
) -> None:
    root = tmp_path / "state"
    run_id = _write_completed_lifecycle_state(root)
    database = root / "lifecycle.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute("SELECT record_json FROM lifecycle_runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        record = json.loads(row[0])
        _coherently_tamper_commitment(record, field)
        connection.execute(
            "UPDATE lifecycle_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), run_id),
        )
        connection.commit()
    backup = tmp_path / "backup"

    with pytest.raises(ValueError, match=rf"stage_commitments {field} does not match"):
        migrate_state(root, apply=True, backup_dir=backup)

    assert not backup.exists()
    assert not (root / "state-schema.json").exists()


def test_state_migration_rejects_missing_completed_stage_attempt_before_backup(tmp_path: Path) -> None:
    root = tmp_path / "state"
    run_id = _write_completed_lifecycle_state(root)
    database = root / "lifecycle.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute("SELECT record_json FROM lifecycle_runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        record = json.loads(row[0])
        record["attempts"].pop(record["completed_stage_ids"][0])
        connection.execute(
            "UPDATE lifecycle_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), run_id),
        )
        connection.commit()
    backup = tmp_path / "backup"

    with pytest.raises(ValueError, match="attempts must include every completed stage"):
        migrate_state(root, apply=True, backup_dir=backup)

    assert not backup.exists()
    assert not (root / "state-schema.json").exists()


def test_state_migration_accepts_lifecycle_only_state(tmp_path: Path) -> None:
    root = tmp_path / "state"
    database = root / "lifecycle.sqlite3"
    root.mkdir()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE lifecycle_runs (run_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, "
            "record_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.commit()

    assert plan_state_migration(root).status == "migration_required"


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
