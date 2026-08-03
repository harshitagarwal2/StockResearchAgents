from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import tradingrearchagents.store as store_module
from tradingrearchagents.contracts import EventKind, RunEvent, RunRequest, RunResult
from tradingrearchagents.fixture import run_fixture
from tradingrearchagents.serialization import (
    deserialize_run_event,
    deserialize_run_result,
    serialize_run_event,
    serialize_run_result,
)
from tradingrearchagents.store import RunStore


def _completed_run() -> tuple[RunResult, tuple[RunEvent, ...]]:
    return run_fixture(RunRequest(), RunStore())


def _event(run_id: str, sequence: int = 1) -> RunEvent:
    return RunEvent(
        id=f"{run_id}-event-{sequence}",
        run_id=run_id,
        sequence=sequence,
        timestamp="2026-08-03T12:00:00+00:00",
        kind=EventKind.RUN,
        status="running",
        message="Partial run event.",
        data={"safe": True},
    )


def test_run_result_and_event_round_trip_through_strict_json() -> None:
    result, events = _completed_run()

    restored_result = deserialize_run_result(serialize_run_result(result))
    restored_event = deserialize_run_event(serialize_run_event(events[0]))

    assert restored_result == result
    assert restored_event == events[0]
    assert restored_result.request.legacy_config == result.request.legacy_config


def test_deserialization_rejects_unknown_fields_and_wrong_schema() -> None:
    result, events = _completed_run()
    result_payload = json.loads(serialize_run_result(result))
    event_payload = json.loads(serialize_run_event(events[0]))
    result_payload["unexpected"] = "field"
    event_payload["schema_version"] = "1900-01-01"

    with pytest.raises(ValueError, match="unsupported fields"):
        deserialize_run_result(json.dumps(result_payload))
    with pytest.raises(ValueError, match="schema_version"):
        deserialize_run_event(json.dumps(event_payload))


def test_durable_store_rehydrates_completed_run_after_restart(tmp_path: Path) -> None:
    result, events = _completed_run()
    first = RunStore(state_dir=tmp_path / "state")

    first.put(result, events)
    restarted = RunStore(state_dir=tmp_path / "state")

    assert restarted.current_run_id() == result.run_id
    assert restarted.get_result(result.run_id) == result
    assert restarted.get_events(result.run_id) == events
    assert restarted.list_results() == (result,)


def test_event_only_partial_run_rehydrates_and_can_be_appended(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    first = RunStore(state_dir=state_dir)
    first.put_events("partial-safe", (_event("partial-safe"),))

    restarted = RunStore(state_dir=state_dir)
    assert restarted.get_result("partial-safe") is None
    assert restarted.get_events("partial-safe") == (_event("partial-safe"),)
    assert restarted.resolve_run_id("current") == "partial-safe"

    restarted.append_event(_event("partial-safe", sequence=2))
    final = RunStore(state_dir=state_dir)
    assert final.get_events("partial-safe") == (_event("partial-safe"), _event("partial-safe", sequence=2))


def test_event_cursor_is_exclusive_bounded_and_validated() -> None:
    store = RunStore()
    store.put_events("partial-safe", tuple(_event("partial-safe", sequence=index) for index in range(1, 5)))

    assert store.get_events_after("partial-safe", after_sequence=2, limit=1) == (_event("partial-safe", sequence=3),)
    assert store.get_events_after("unknown-safe") is None
    with pytest.raises(ValueError, match="non-negative integer"):
        store.get_events_after("partial-safe", after_sequence=-1)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        store.get_events_after("partial-safe", limit=0)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        store.get_events_after("partial-safe", limit=1001)


def test_in_memory_store_does_not_create_default_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configured = tmp_path / "must-not-exist"
    monkeypatch.setenv("TRADINGREARCHAGENTS_STATE_DIR", str(configured))

    store = RunStore()
    assert store.state_dir is None
    assert store.current_run_id() is None
    assert not configured.exists()


@pytest.mark.parametrize("run_id", ["../escape", "nested/run", "/absolute", "", "space id"])
def test_durable_store_rejects_unsafe_run_ids_before_path_access(tmp_path: Path, run_id: str) -> None:
    state_dir = tmp_path / "state"
    store = RunStore(state_dir=state_dir)

    with pytest.raises(ValueError, match="safe identifier"):
        store.put_events(run_id, ())
    with pytest.raises(ValueError, match="safe identifier"):
        store.get_result(run_id)
    assert not state_dir.exists()


def test_durable_store_rejects_events_for_another_run(tmp_path: Path) -> None:
    store = RunStore(state_dir=tmp_path / "state")

    with pytest.raises(ValueError, match="must all match run_id"):
        store.put_events("expected", (_event("different"),))


def test_durable_store_files_are_json_and_atomic_temporary_files_are_removed(tmp_path: Path) -> None:
    result, events = _completed_run()
    state_dir = tmp_path / "state"
    RunStore(state_dir=state_dir).put(result, events)

    result_path = state_dir / "results" / f"{result.run_id}.json"
    events_path = state_dir / "events" / f"{result.run_id}.json"
    assert json.loads(result_path.read_text(encoding="utf-8"))["run_id"] == result.run_id
    assert isinstance(json.loads(events_path.read_text(encoding="utf-8")), list)
    assert json.loads((state_dir / "current.json").read_text(encoding="utf-8")) == {"run_id": result.run_id}
    assert not list(state_dir.rglob("*.tmp"))
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in state_dir.rglob("*.json"))


@pytest.mark.parametrize(
    "failed_path",
    [
        "direct-put.json",
        "bundles/{run_id}.json",
        "results/{run_id}.json",
        "events/{run_id}.json",
        "current.json",
    ],
)
def test_direct_put_recovers_atomically_after_each_durable_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failed_path: str,
) -> None:
    result, events = _completed_run()
    state_dir = tmp_path / "state"
    expected_failure_path = failed_path.format(run_id=result.run_id)
    original_atomic_write = store_module._atomic_write

    def fail_after_write(path: Path, content: str) -> None:
        original_atomic_write(path, content)
        if path.relative_to(state_dir).as_posix() == expected_failure_path:
            raise OSError(f"simulated crash after {expected_failure_path}")

    monkeypatch.setattr(store_module, "_atomic_write", fail_after_write)
    interrupted = RunStore(state_dir=state_dir)
    with pytest.raises(OSError, match="simulated crash"):
        interrupted.put(result, events)

    assert interrupted.get_result(result.run_id) is None
    assert interrupted.get_events(result.run_id) is None

    monkeypatch.setattr(store_module, "_atomic_write", original_atomic_write)
    restarted = RunStore(state_dir=state_dir)
    assert restarted.get_result(result.run_id) == result
    assert restarted.get_events(result.run_id) == events
    assert restarted.current_run_id() == result.run_id
    assert not (state_dir / "direct-put.json").exists()
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in state_dir.rglob("*.json"))


def test_lifecycle_stage_stays_hidden_across_restart_until_explicit_publish(tmp_path: Path) -> None:
    result, events = _completed_run()
    state_dir = tmp_path / "state"
    RunStore(state_dir=state_dir).stage(result, events)

    restarted = RunStore(state_dir=state_dir)
    assert restarted.get_result(result.run_id) is None
    assert restarted.get_events(result.run_id) is None
    assert restarted.current_run_id() is None
    assert restarted.get_staged(result.run_id) == (result, events)
    assert not (state_dir / "bundles" / f"{result.run_id}.json").exists()

    restarted.publish_staged(result.run_id)
    published = RunStore(state_dir=state_dir)
    assert published.get_result(result.run_id) == result
    assert published.get_events(result.run_id) == events


def test_legacy_result_without_events_is_not_exposed(tmp_path: Path) -> None:
    result, _events = _completed_run()
    state_dir = tmp_path / "state"
    result_path = state_dir / "results" / f"{result.run_id}.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(serialize_run_result(result), encoding="utf-8")

    restarted = RunStore(state_dir=state_dir)
    assert restarted.get_result(result.run_id) is None
    assert restarted.list_results() == ()


def test_durable_store_detects_filename_payload_mismatch(tmp_path: Path) -> None:
    result, _events = _completed_run()
    state_dir = tmp_path / "state"
    results_dir = state_dir / "results"
    results_dir.mkdir(parents=True)
    mismatched = replace(result, run_id="different-safe-id")
    (results_dir / "expected-safe-id.json").write_text(serialize_run_result(mismatched), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match filename"):
        RunStore(state_dir=state_dir).list_results()
