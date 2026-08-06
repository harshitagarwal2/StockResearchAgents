from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Barrier, Lock, Thread

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_lifecycle import CompanyAnalyticsCoordinator
from stock_research_agents.lifecycle import LifecycleStore, RevisionConflict
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
                record["cancel_reason"] = marker

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
    assert persisted["cancel_reason"] == successes[0]


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
