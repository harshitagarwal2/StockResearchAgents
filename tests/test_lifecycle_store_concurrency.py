from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Barrier, Lock, Thread

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics_v1 import CompanyAnalyticsV1Provider, analytics_run_id
from stock_research_agents.company_lifecycle import CompanyAnalyticsCoordinator
from stock_research_agents.lifecycle import LifecycleRecordV1, LifecycleStore, RevisionConflict
from stock_research_agents.lifecycle_profiles import CompanyAnalyticsLifecycleProfile
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore


def _prepared_run(tmp_path: Path) -> tuple[Path, str]:
    lifecycle_dir = tmp_path / "lifecycle"
    coordinator = CompanyAnalyticsCoordinator(
        LifecycleStore(lifecycle_dir),
        RunStore(tmp_path / "runs"),
        profile=CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / "quality")),
    )
    submission = complete_analytics_submission("ORCL")
    request = submission["company_research"]["request"]
    control = coordinator.create(request, decision_memory_enabled=False)
    return lifecycle_dir, str(control["run_id"])


def _stage_envelope(stage: dict[str, object], submission: object | None = None) -> dict[str, object]:
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
    if submission is not None:
        output_refs = {str(refs[0]): submission}
    return {"schema_version": "1.0.0", "stage_id": stage["id"], "output_refs": output_refs}


def _completed_run(tmp_path: Path, symbol: str = "ORCL") -> tuple[Path, str, dict[str, object]]:
    lifecycle_dir = tmp_path / "lifecycle"
    coordinator = CompanyAnalyticsCoordinator(
        LifecycleStore(lifecycle_dir),
        RunStore(tmp_path / "runs"),
        profile=CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / "quality")),
    )
    submission = complete_analytics_submission(symbol)
    request = submission["company_research"]["request"]  # type: ignore[index]
    control = coordinator.create(request, decision_memory_enabled=False)
    advanced = coordinator.start(control["run_id"], control["revision"])
    revision = int(advanced["control"]["revision"])
    for stage in CompanyAnalyticsV1Provider().load_manifest()["stages"]:
        terminal = submission if stage["id"] == "publish.completed" else None
        advanced = coordinator.commit_stage(
            control["run_id"],
            stage["id"],
            _stage_envelope(stage, terminal),
            revision,
        )
        revision = int(advanced["control"]["revision"])
    coordinator.finalize(control["run_id"], revision)
    return lifecycle_dir, str(control["run_id"]), submission


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


def test_two_store_instances_reject_one_stale_revision(tmp_path: Path) -> None:
    lifecycle_dir, run_id = _prepared_run(tmp_path)
    stores = (LifecycleStore(lifecycle_dir), LifecycleStore(lifecycle_dir))
    barrier = Barrier(2)
    result_lock = Lock()
    successes: list[str] = []
    failures: list[BaseException] = []

    def write(store: LifecycleStore, marker: str) -> None:
        try:
            barrier.wait(timeout=5)

            def mutate(record: dict[str, object]) -> None:
                record["memory_context"] = {"writer": marker}

            store.update(run_id, 0, mutate)
            with result_lock:
                successes.append(marker)
        except BaseException as exc:  # the assertion below classifies the losing writer
            with result_lock:
                failures.append(exc)

    workers = tuple(
        Thread(target=write, args=(store, marker), daemon=True)
        for store, marker in zip(stores, ("writer-a", "writer-b"), strict=True)
    )
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert all(not worker.is_alive() for worker in workers)
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], RevisionConflict)

    persisted = LifecycleStore(lifecycle_dir).get(run_id)
    assert persisted is not None
    assert persisted["revision"] == 1
    assert persisted["memory_context"] == {"writer": successes[0]}


def test_failed_mutation_rolls_back_without_incrementing_revision(tmp_path: Path) -> None:
    lifecycle_dir, run_id = _prepared_run(tmp_path)
    store = LifecycleStore(lifecycle_dir)

    def fail_after_mutation(record: dict[str, object]) -> None:
        record["cancel_reason"] = "must-not-persist"
        raise RuntimeError("deliberate mutation failure")

    with pytest.raises(RuntimeError, match="deliberate mutation failure"):
        store.update(run_id, 0, fail_after_mutation)

    persisted = LifecycleStore(lifecycle_dir).get(run_id)
    assert persisted is not None
    assert persisted["revision"] == 0
    assert persisted["cancel_reason"] is None


def test_invalid_cross_field_mutation_rolls_back(tmp_path: Path) -> None:
    lifecycle_dir, run_id = _prepared_run(tmp_path)
    store = LifecycleStore(lifecycle_dir)

    def corrupt(record: dict[str, object]) -> None:
        record["status"] = "completed"
        record["result_run_id"] = None

    with pytest.raises(ValueError, match="lifecycle records require"):
        store.update(run_id, 0, corrupt)

    persisted = store.get(run_id)
    assert persisted is not None
    assert persisted["status"] == "prepared"
    assert persisted["revision"] == 0


def test_prepared_record_rejects_result_run_id_and_rolls_back(tmp_path: Path) -> None:
    lifecycle_dir, run_id = _prepared_run(tmp_path)
    store = LifecycleStore(lifecycle_dir)

    def corrupt(record: dict[str, object]) -> None:
        record["result_run_id"] = "analytics-0123456789ab"

    with pytest.raises(ValueError, match="result_run_id requires completed status"):
        store.update(run_id, 0, corrupt)

    persisted = store.get(run_id)
    assert persisted is not None
    assert persisted["status"] == "prepared"
    assert persisted["result_run_id"] is None
    assert persisted["revision"] == 0


def test_get_rejects_corrupt_persisted_lifecycle_record(tmp_path: Path) -> None:
    lifecycle_dir, run_id = _prepared_run(tmp_path)
    store = LifecycleStore(lifecycle_dir)
    database_path = store.database_path
    assert database_path is not None
    with closing(sqlite3.connect(database_path)) as connection:
        row = connection.execute("SELECT record_json FROM lifecycle_runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        record = json.loads(row[0])
        record["events"][0]["sequence"] = 2
        connection.execute(
            "UPDATE lifecycle_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), run_id),
        )
        connection.commit()

    with pytest.raises(ValueError, match="contiguous sequence"):
        store.get(run_id)


def test_completed_record_rejects_a_different_valid_submission_binding(tmp_path: Path) -> None:
    lifecycle_dir, run_id, _ = _completed_run(tmp_path)
    record = LifecycleStore(lifecycle_dir).get(run_id)
    assert record is not None
    meta_submission = complete_analytics_submission("META")
    record["final_submission"] = meta_submission
    record["result_run_id"] = analytics_run_id(meta_submission)

    with pytest.raises(ValueError, match="final_submission request must exactly match"):
        LifecycleRecordV1.from_mapping(record, expected_run_id=run_id)


def test_reload_rejects_a_different_valid_submission_and_matching_result_id(tmp_path: Path) -> None:
    lifecycle_dir, run_id, _ = _completed_run(tmp_path)
    store = LifecycleStore(lifecycle_dir)
    database_path = store.database_path
    assert database_path is not None
    meta_submission = complete_analytics_submission("META")
    with closing(sqlite3.connect(database_path)) as connection:
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

    with pytest.raises(ValueError, match="final_submission request must exactly match"):
        store.get(run_id)


@pytest.mark.parametrize("field", ("envelope_digest", "receipt_digest"))
def test_completed_record_rederives_stage_commitment_digests(tmp_path: Path, field: str) -> None:
    lifecycle_dir, run_id, _ = _completed_run(tmp_path)
    record = LifecycleStore(lifecycle_dir).get(run_id)
    assert record is not None
    _coherently_tamper_commitment(record, field)

    with pytest.raises(ValueError, match=rf"stage_commitments {field} does not match"):
        LifecycleRecordV1.from_mapping(record, expected_run_id=run_id)


@pytest.mark.parametrize("field", ("envelope_digest", "receipt_digest"))
def test_reload_rejects_coherently_tampered_stage_commitment_digest(tmp_path: Path, field: str) -> None:
    lifecycle_dir, run_id, _ = _completed_run(tmp_path)
    store = LifecycleStore(lifecycle_dir)
    database_path = store.database_path
    assert database_path is not None
    with closing(sqlite3.connect(database_path)) as connection:
        row = connection.execute("SELECT record_json FROM lifecycle_runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        record = json.loads(row[0])
        _coherently_tamper_commitment(record, field)
        connection.execute(
            "UPDATE lifecycle_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), run_id),
        )
        connection.commit()

    with pytest.raises(ValueError, match=rf"stage_commitments {field} does not match"):
        store.get(run_id)


def test_completed_record_requires_an_attempt_for_every_completed_stage(tmp_path: Path) -> None:
    lifecycle_dir, run_id, _ = _completed_run(tmp_path)
    record = LifecycleStore(lifecycle_dir).get(run_id)
    assert record is not None
    attempts = record["attempts"]
    completed_stage_ids = record["completed_stage_ids"]
    assert isinstance(attempts, dict) and isinstance(completed_stage_ids, list)
    attempts.pop(completed_stage_ids[0])

    with pytest.raises(ValueError, match="attempts must include every completed stage"):
        LifecycleRecordV1.from_mapping(record, expected_run_id=run_id)


def test_reload_rejects_a_missing_completed_stage_attempt(tmp_path: Path) -> None:
    lifecycle_dir, run_id, _ = _completed_run(tmp_path)
    store = LifecycleStore(lifecycle_dir)
    database_path = store.database_path
    assert database_path is not None
    with closing(sqlite3.connect(database_path)) as connection:
        row = connection.execute("SELECT record_json FROM lifecycle_runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        record = json.loads(row[0])
        record["attempts"].pop(record["completed_stage_ids"][0])
        connection.execute(
            "UPDATE lifecycle_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), run_id),
        )
        connection.commit()

    with pytest.raises(ValueError, match="attempts must include every completed stage"):
        store.get(run_id)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("cancel_reason", "", "cancel_reason must contain"),
        ("cancel_ack_receipt_id", "unsafe receipt id", "cancel_ack_receipt_id must be a safe identifier"),
        ("cancel_reason", "Valid but premature reason.", "cancel_reason requires cancel_requested or cancelled"),
        ("cancel_ack_receipt_id", "receipt.safe-1", "cancel_ack_receipt_id requires cancelled status"),
    ),
)
def test_prepared_record_rejects_invalid_cancellation_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    lifecycle_dir, run_id = _prepared_run(tmp_path)
    record = LifecycleStore(lifecycle_dir).get(run_id)
    assert record is not None
    record[field] = value

    with pytest.raises(ValueError, match=message):
        LifecycleRecordV1.from_mapping(record, expected_run_id=run_id)


def test_valid_cancellation_transition_round_trips_from_sqlite(tmp_path: Path) -> None:
    lifecycle_dir, run_id = _prepared_run(tmp_path)
    coordinator = CompanyAnalyticsCoordinator(
        LifecycleStore(lifecycle_dir),
        RunStore(tmp_path / "runs-reloaded"),
        profile=CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / "quality-reloaded")),
    )
    requested = coordinator.request_cancel(run_id, 0, "Operator requested a bounded stop.")
    cancelled = coordinator.acknowledge_cancel(run_id, requested["revision"], "execution-receipt.1")

    assert cancelled["status"] == "cancelled"
    reloaded = LifecycleStore(lifecycle_dir).get(run_id)
    assert reloaded is not None
    assert reloaded["cancel_reason"] == "Operator requested a bounded stop."
    assert reloaded["cancel_ack_receipt_id"] == "execution-receipt.1"


@pytest.mark.parametrize(
    ("field", "corrupt_value", "message"),
    (
        ("attempts", "corrupt", "attempts must map"),
        ("request", {"schema_version": "company-research.v1"}, "request is invalid"),
        ("receipts", "corrupt", "receipts and receipt_ids must be arrays"),
        (
            "receipts",
            [{"receipt_id": "bad-receipt", "kind": "warning", "duration_ms": "not-an-integer"}],
            "receipt duration_ms is invalid",
        ),
        ("stage_outputs", "corrupt", "stage_outputs must align"),
        ("memory_recall", "corrupt", "memory_recall has invalid fields"),
        ("memory_stage_receipt", {}, "not a DecisionMemoryReceipt"),
        ("memory_write_receipt", {}, "not a DecisionMemoryReceipt"),
        ("final_submission", {}, "final_submission is invalid"),
        ("failure", {}, "failure must be null"),
    ),
)
def test_get_rejects_corrupt_nested_lifecycle_fields(
    tmp_path: Path,
    field: str,
    corrupt_value: object,
    message: str,
) -> None:
    lifecycle_dir, run_id = _prepared_run(tmp_path)
    store = LifecycleStore(lifecycle_dir)
    database_path = store.database_path
    assert database_path is not None
    with closing(sqlite3.connect(database_path)) as connection:
        row = connection.execute("SELECT record_json FROM lifecycle_runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        record = json.loads(row[0])
        record[field] = corrupt_value
        connection.execute(
            "UPDATE lifecycle_runs SET record_json = ? WHERE run_id = ?",
            (json.dumps(record), run_id),
        )
        connection.commit()

    with pytest.raises(ValueError, match=message):
        store.get(run_id)
