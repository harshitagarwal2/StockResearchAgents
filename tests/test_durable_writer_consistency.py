from __future__ import annotations

import multiprocessing
import threading
from pathlib import Path

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.company_analytics_v1 import CompanyAnalyticsSubmissionV1
from stock_research_agents.contracts import EventKind, RunEvent
from stock_research_agents.research_quality_v1 import OutcomeObservation, QualityStore
from stock_research_agents.serialization import deserialize_run_event, serialize_run_event
from stock_research_agents.state_write_lock import state_write_lock, writer_lock_path
from stock_research_agents.store import RunStore


def _event(run_id: str, sequence: int) -> RunEvent:
    return RunEvent(
        id=f"{run_id}-event-{sequence}",
        run_id=run_id,
        sequence=sequence,
        timestamp="2026-08-06T12:00:00+00:00",
        kind=EventKind.RUN,
        status="running",
        message=f"Partial event {sequence}.",
        data={},
    )


def _append_event_worker(
    state_dir: str,
    event_json: str,
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    store = RunStore(state_dir)
    start.wait(timeout=10)
    try:
        store.append_event(deserialize_run_event(event_json))
    except BaseException as exc:
        results.put(f"{type(exc).__name__}: {exc}")
    else:
        results.put(None)


def _append_stale_quality_correction_worker(
    quality_dir: str,
    run_id: str,
    observation_payload: dict[str, object],
    ready: multiprocessing.synchronize.Event,
    proceed: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    store = QualityStore(quality_dir)
    store.projection(run_id)
    ready.set()
    proceed.wait(timeout=10)
    try:
        store.append_outcome(OutcomeObservation.from_dict(observation_payload))
    except BaseException as exc:
        results.put(f"{type(exc).__name__}: {exc}")
    else:
        results.put(None)


def _outcome(
    forecast_id: str,
    observation_id: str,
    supersedes_observation_id: str | None,
) -> OutcomeObservation:
    return OutcomeObservation(
        "research-quality.v1",
        observation_id,
        forecast_id,
        "2027-08-02T00:00:00Z",
        "2027-08-02T00:05:00Z",
        "2027-08-02T00:10:00Z",
        "resolved",
        observation_id == "outcome.initial",
        None,
        None,
        None,
        ("outcome.document",),
        "host-owned primary-source resolver",
        supersedes_observation_id,
    )


def test_multiprocess_partial_event_appends_do_not_lose_updates(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    run_id = "concurrent-partial"
    RunStore(state_dir).put_events(run_id, (_event(run_id, 1),))
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = tuple(
        context.Process(
            target=_append_event_worker,
            args=(str(state_dir), serialize_run_event(_event(run_id, sequence)), start, results),
        )
        for sequence in (2, 3)
    )

    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=15)

    assert all(worker.exitcode == 0 for worker in workers)
    assert [results.get(timeout=5) for _ in workers] == [None, None]
    events = RunStore(state_dir).get_events(run_id)
    assert events is not None
    assert {event.id for event in events} == {f"{run_id}-event-{sequence}" for sequence in (1, 2, 3)}


def test_long_lived_run_store_observes_new_completed_current_publication(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    reader = RunStore(state_dir)
    assert reader.current_run_id() is None

    first_result, first_events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=RunStore(),
        quality_store=QualityStore(),
    )
    second_result, second_events = submit_company_analytics(
        complete_analytics_submission("META"),
        store=RunStore(),
        quality_store=QualityStore(),
    )
    RunStore(state_dir).put(first_result, first_events)
    assert reader.current_run_id() == first_result.run_id
    assert reader.get_result(first_result.run_id) == first_result

    RunStore(state_dir).put(second_result, second_events)
    assert reader.current_run_id() == second_result.run_id
    assert reader.get_result(second_result.run_id) == second_result


def test_stale_quality_writer_refreshes_before_cross_process_append(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    quality_dir = state_dir / "quality"
    submission = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("ORCL"))
    quality_store = QualityStore(quality_dir)
    quality_store.register(submission.quality_receipt, submission.forecasts)
    forecast_id = submission.forecasts[0].forecast_id
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    proceed = context.Event()
    results = context.Queue()
    correction = _outcome(forecast_id, "outcome.corrected", "outcome.initial")
    worker = context.Process(
        target=_append_stale_quality_correction_worker,
        args=(
            str(quality_dir),
            submission.run_card.run_id,
            correction.to_dict(),
            ready,
            proceed,
            results,
        ),
    )
    worker.start()
    assert ready.wait(timeout=10)

    quality_store.append_outcome(_outcome(forecast_id, "outcome.initial", None))
    proceed.set()
    worker.join(timeout=15)

    assert worker.exitcode == 0
    assert results.get(timeout=5) is None
    projection = quality_store.projection(submission.run_card.run_id)
    assert projection is not None
    assert [
        item["observation_id"]
        for item in projection["outcome_ledgers"][0]["observations"]  # type: ignore[index]
    ] == ["outcome.initial", "outcome.corrected"]


def test_durable_quality_reader_waits_through_staged_registration_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    quality_dir = state_dir / "quality"
    submission = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("ORCL"))
    writer = QualityStore(quality_dir)
    writer.stage_registration(submission.quality_receipt, submission.forecasts)
    run_id = submission.run_card.run_id
    staged_path = quality_dir / "staged-registrations" / f"{run_id}.json"
    original_unlink = Path.unlink
    writer_at_unlink = threading.Event()
    release_writer = threading.Event()
    reader_refresh_entered = threading.Event()
    reader_finished = threading.Event()
    failures: list[BaseException] = []
    projections: list[dict[str, object] | None] = []

    def paused_staged_unlink(path: Path, missing_ok: bool = False) -> None:
        if path == staged_path:
            writer_at_unlink.set()
            if not release_writer.wait(timeout=5):
                raise TimeoutError("reader test did not release staged-registration publisher")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", paused_staged_unlink)

    def publish() -> None:
        try:
            writer.publish_registration(run_id)
        except BaseException as exc:
            failures.append(exc)

    reader = QualityStore(quality_dir)
    original_refresh = reader._refresh_durable_snapshot

    def tracked_refresh() -> None:
        reader_refresh_entered.set()
        original_refresh()

    monkeypatch.setattr(reader, "_refresh_durable_snapshot", tracked_refresh)

    def read_projection() -> None:
        try:
            projections.append(reader.projection(run_id))
        except BaseException as exc:
            failures.append(exc)
        finally:
            reader_finished.set()

    publisher = threading.Thread(target=publish)
    publisher.start()
    assert writer_at_unlink.wait(timeout=5)

    quality_reader = threading.Thread(target=read_projection)
    quality_reader.start()
    assert not reader_refresh_entered.wait(timeout=0.2)
    assert not reader_finished.is_set()

    release_writer.set()
    publisher.join(timeout=5)
    quality_reader.join(timeout=5)

    assert not publisher.is_alive()
    assert not quality_reader.is_alive()
    assert failures == []
    assert reader_refresh_entered.is_set()
    assert projections == [reader.projection(run_id)]
    assert projections[0] is not None


def test_state_writer_lock_is_reentrant_and_releases_after_failure(tmp_path: Path) -> None:
    state_root = tmp_path / "state"

    with pytest.raises(RuntimeError, match="deliberate failure"):
        with state_write_lock(state_root):
            with state_write_lock(state_root):
                raise RuntimeError("deliberate failure")

    with state_write_lock(state_root):
        assert writer_lock_path(state_root).is_file()
        RunStore(state_root).put_events("nested-publication", (_event("nested-publication", 1),))

    assert RunStore(state_root).get_events("nested-publication") == (_event("nested-publication", 1),)
