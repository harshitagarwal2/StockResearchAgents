from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from tradingagents_portable import dashboard
from tradingagents_portable.contracts import RunRequest, StageKind
from tradingagents_portable.dashboard import create_dashboard_server, dashboard_report, launch_dashboard
from tradingagents_portable.lifecycle import (
    HostRunCoordinator,
    LifecycleStatus,
    LifecycleStore,
    RevisionConflict,
)
from tradingagents_portable.memory import DecisionMemoryStore
from tradingagents_portable.presentation import ViewerDaemonPresenter
from tradingagents_portable.store import RunStore
from tradingagents_portable.view import build_run_view

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "src" / "tradingagents_portable" / "web"


def _request(symbol: str = "ORCL") -> RunRequest:
    return RunRequest(
        symbol=symbol,
        as_of_date="2026-08-01",
        analysts=("market",),
        debate_rounds=1,
        risk_rounds=1,
        executor="host_native",
    )


def _output(stage: dict[str, Any]) -> dict[str, Any]:
    kind = StageKind(stage["kind"])
    if kind is StageKind.ANALYST:
        return {
            "company_of_interest": "Oracle Corporation",
            "instrument_context": "Public common stock.",
            "evidence": [
                {
                    "id": "ev-market",
                    "category": "market",
                    "title": "Verified market evidence",
                    "summary": "Bounded lifecycle conformance evidence.",
                    "values": {"sample": 1},
                    "provenance": {
                        "provider": "public-test-source",
                        "source_type": "primary_document",
                        "source_uri": "https://example.com/ORCL/market",
                        "retrieved_at": "2026-08-02T12:00:00+00:00",
                        "source_date": "2026-08-01",
                    },
                    "limitations": ["Conformance fixture."],
                }
            ],
            "report": {
                "thesis": "Market evidence is balanced.",
                "evidence_ids": ["ev-market"],
                "confidence": 0.6,
                "content": "Complete market conformance report.",
            },
        }
    if kind in {StageKind.RESEARCH_DEBATE, StageKind.RISK_DEBATE}:
        return {"position": f"{stage['role']} bounded view.", "evidence_ids": ["ev-market"]}
    if kind is StageKind.RESEARCH_MANAGER:
        return {
            "recommendation": "Hold",
            "rationale": "The retained evidence is balanced.",
            "strategic_actions": "Wait for a verified catalyst.",
            "confidence": 0.6,
        }
    if kind is StageKind.TRADER:
        return {
            "action": "Hold",
            "reasoning": "Research-only lifecycle conclusion.",
            "entry_price": 175.0,
            "stop_loss": 160.0,
            "position_sizing": "At most 1% as a hypothetical scenario.",
            "executable": False,
            "execution_authority": "none",
            "submitted": False,
        }
    return {
        "risk_decision": {
            "risk_level": "moderate",
            "constraints": ["No order execution."],
            "unresolved": ["Future results."],
        },
        "portfolio_decision": {
            "rating": "Hold",
            "executive_summary": "Hold is a research rating only.",
            "investment_thesis": "Evidence is balanced at the cutoff.",
            "price_target": 190.0,
            "time_horizon": "12 months",
            "executable": False,
            "execution_authority": "none",
            "submitted": False,
        },
        "final_trade_decision": "Rating: Hold\nResearch conclusion only; no order is authorized.",
        "warnings": ["Lifecycle conformance fixture."],
    }


def _rating_output(stage: dict[str, Any], rating: str) -> dict[str, Any]:
    output = _output(stage)
    kind = StageKind(stage["kind"])
    if kind is StageKind.RESEARCH_MANAGER:
        output["recommendation"] = rating
    elif kind is StageKind.TRADER:
        output["action"] = (
            "Buy" if rating in {"Buy", "Overweight"} else "Sell" if rating in {"Sell", "Underweight"} else "Hold"
        )
    elif kind is StageKind.PORTFOLIO:
        output["portfolio_decision"]["rating"] = rating
        output["final_trade_decision"] = f"Rating: {rating}\nResearch conclusion only; no order is authorized."
    return output


def _coordinator(root: Path, memory: DecisionMemoryStore | None = None) -> HostRunCoordinator:
    return HostRunCoordinator(LifecycleStore(root), RunStore(root), memory_store=memory)


def test_host_coordinator_uses_explicit_composed_repository_ports() -> None:
    lifecycle_store = LifecycleStore()
    result_store = RunStore()
    coordinator = HostRunCoordinator(lifecycle_store, result_store)

    assert coordinator.lifecycle_store is lifecycle_store
    assert coordinator.result_store is result_store


def _complete(coordinator: HostRunCoordinator, run_id: str, revision: int, *, rating: str = "Hold") -> int:
    while True:
        next_stage = coordinator.next_stage(run_id)
        stage = next_stage["stage"]
        if stage is None:
            return int(next_stage["control"]["revision"])
        attempt = int(next_stage["attempt"])
        receipt = {
            "receipt_id": f"start:{stage['id']}:{attempt}",
            "kind": "stage_started",
            "stage_id": stage["id"],
            "attempt": attempt,
            "safe_summary": f"Started {stage['role']}.",
        }
        output = _rating_output(stage, rating)
        kind = StageKind(stage["kind"])
        if kind in {StageKind.RESEARCH_DEBATE, StageKind.RISK_DEBATE}:
            context_key = "research_debate_so_far" if kind is StageKind.RESEARCH_DEBATE else "risk_debate_so_far"
            prior_turns = next_stage["context"][context_key]
            if prior_turns:
                output["responds_to"] = prior_turns[-1]["speaker"]
            elif kind is StageKind.RISK_DEBATE:
                output["responds_to"] = "Trader"
        output_digest = hashlib.sha256(
            json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        completed_receipt = {
            "receipt_id": f"complete:{stage['id']}:{attempt}",
            "kind": "stage_completed",
            "stage_id": stage["id"],
            "attempt": attempt,
            "output_digest": output_digest,
            "safe_summary": f"Completed {stage['role']}.",
        }
        accepted = coordinator.append_receipts(run_id, [receipt, completed_receipt], revision)
        revision = int(accepted["control"]["revision"])
        committed = coordinator.commit_stage(
            run_id,
            stage["id"],
            output,
            revision,
            attempt=attempt,
        )
        revision = int(committed["control"]["revision"])


def _dashboard_visibility(
    coordinator: HostRunCoordinator,
    run_id: str,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    server = create_dashboard_server(
        "127.0.0.1",
        0,
        WEB_ROOT,
        coordinator.result_store,
        coordinator=coordinator,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/api/runs", timeout=5) as response:  # noqa: S310
            runs = json.load(response)["runs"]
        statuses: dict[str, int] = {}
        for suffix in ("", "/result", "/view", "/events"):
            try:
                with urlopen(f"{base}/api/runs/{run_id}{suffix}", timeout=5) as response:  # noqa: S310
                    statuses[suffix] = response.status
            except HTTPError as exc:
                statuses[suffix] = exc.code
        return runs, statuses
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_durable_lifecycle_completes_all_stages_and_publishes_only_at_finalization(tmp_path: Path) -> None:
    memory = DecisionMemoryStore(tmp_path / "memory.sqlite3")
    coordinator = _coordinator(tmp_path, memory)
    control = coordinator.create(_request())
    run_id = control["run_id"]

    assert control["status"] == LifecycleStatus.PREPARED
    assert coordinator.result_store.get_result(run_id) is None
    next_stage = coordinator.start(run_id, control["revision"])
    revision = _complete(coordinator, run_id, next_stage["control"]["revision"])
    assert coordinator.result_store.get_result(run_id) is None

    result, events = coordinator.finalize(run_id, revision)

    assert result.run_id == run_id
    assert result.processed_signal == "HOLD"
    assert result.persistence.checkpoint_enabled is True
    assert result.persistence.decision_memory_enabled is True
    assert coordinator.result_store.get_result(run_id) == result
    assert coordinator.control(run_id)["status"] == LifecycleStatus.COMPLETED
    assert len([event for event in events if event.data.get("host_completion_attested") is True]) == 9
    assert not any(event.data.get("execution_observed") is True for event in events)
    assert events[-2].kind.value == "artifact"
    assert events[-1].status == "completed"
    recall = memory.recall("ORCL")
    assert recall.same_symbol[0].run_id == run_id


def test_running_lifecycle_resumes_after_restart_and_replays_only_incomplete_stage(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    run_id = control["run_id"]
    started = coordinator.start(run_id, control["revision"])
    first = started["stage"]
    first_receipt = coordinator.append_receipts(
        run_id,
        [
            {
                "receipt_id": "attempt-one",
                "kind": "stage_started",
                "stage_id": first["id"],
                "attempt": 1,
            }
        ],
        started["control"]["revision"],
    )

    restarted = _coordinator(tmp_path)
    resumed = restarted.resume(run_id, first_receipt["control"]["revision"])

    assert resumed["stage"]["id"] == first["id"]
    assert resumed["attempt"] == 2
    committed = restarted.commit_stage(
        run_id,
        first["id"],
        _output(first),
        resumed["control"]["revision"],
    )
    assert committed["stage"]["id"] != first["id"]
    assert restarted.control(run_id)["completed_stage_ids"] == [first["id"]]
    events = restarted.result_store.get_events(run_id)
    assert events is not None
    assert events[-1].data["attempt"] == 2


def test_revision_conflicts_and_cooperative_cancellation_are_enforced(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    run_id = control["run_id"]
    started = coordinator.start(run_id, control["revision"])

    with pytest.raises(RevisionConflict, match="revision conflict"):
        coordinator.request_cancel(run_id, control["revision"], "Stop this research run.")

    cancelled = coordinator.request_cancel(
        run_id,
        started["control"]["revision"],
        "User requested cancellation.",
    )
    with pytest.raises(ValueError, match="cannot start another stage|cannot be appended"):
        coordinator.append_receipts(
            run_id,
            [
                {
                    "receipt_id": "late-stage",
                    "kind": "stage_started",
                    "stage_id": started["stage"]["id"],
                    "attempt": 1,
                }
            ],
            cancelled["revision"],
        )
    acknowledged = coordinator.acknowledge_cancel(run_id, cancelled["revision"], "host-cancelled-1")
    assert acknowledged["status"] == LifecycleStatus.CANCELLED


def test_receipts_are_cursor_readable_and_reject_credentials(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    run_id = control["run_id"]
    started = coordinator.start(run_id, control["revision"])
    revision = started["control"]["revision"]
    stage = started["stage"]

    with pytest.raises(ValueError, match="credential-shaped"):
        coordinator.append_receipts(
            run_id,
            [
                {
                    "receipt_id": "unsafe",
                    "kind": "stage_progress",
                    "stage_id": stage["id"],
                    "api_key": "forbidden",
                }
            ],
            revision,
        )

    accepted = coordinator.append_receipts(
        run_id,
        [
            {
                "receipt_id": "safe-start",
                "kind": "stage_started",
                "stage_id": stage["id"],
                "attempt": 1,
                "capability_id": "market.price_history",
                "input_digest": "a" * 64,
                "output_digest": "b" * 64,
                "safe_summary": "Verified public price history through the cutoff.",
            }
        ],
        revision,
    )
    page = coordinator.poll_events(run_id, after_sequence=2, limit=1)
    assert accepted["accepted"] == 1
    assert len(page["events"]) == 1
    assert page["events"][0]["data"]["capability_id"] == "market.price_history"


def test_stage_commit_validates_nested_schema_and_does_not_fabricate_execution(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    stage = started["stage"]
    invalid = _output(stage)
    invalid["report"]["confidence"] = 2

    with pytest.raises(ValueError, match="confidence.*less than or equal"):
        coordinator.commit_stage(
            control["run_id"],
            stage["id"],
            invalid,
            started["control"]["revision"],
        )

    committed = coordinator.commit_stage(
        control["run_id"],
        stage["id"],
        _output(stage),
        started["control"]["revision"],
    )
    events = coordinator.result_store.get_events(control["run_id"])
    assert committed["control"]["completed_stage_ids"] == [stage["id"]]
    assert events is not None
    assert events[-1].status == "committed"
    assert events[-1].data["envelope_observed"] is True
    assert events[-1].data["output_observed"] is True
    assert events[-1].data["output_content_verified"] is True
    assert events[-1].data["host_completion_attested"] is False
    assert events[-1].data["execution_observed"] is False
    assert events[-1].data["execution_receipt_ids"] == []


def test_lifecycle_requires_ordered_debate_response_links(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    revision = coordinator.start(control["run_id"], control["revision"])["control"]["revision"]

    while True:
        next_stage = coordinator.next_stage(control["run_id"])
        stage = next_stage["stage"]
        assert stage is not None
        if StageKind(stage["kind"]) is StageKind.RESEARCH_DEBATE:
            break
        committed = coordinator.commit_stage(control["run_id"], stage["id"], _output(stage), revision)
        revision = committed["control"]["revision"]

    with pytest.raises(ValueError, match="opening research turn"):
        coordinator.commit_stage(
            control["run_id"],
            stage["id"],
            {**_output(stage), "responds_to": "Bear Researcher"},
            revision,
        )

    committed = coordinator.commit_stage(control["run_id"], stage["id"], _output(stage), revision)
    next_stage = coordinator.next_stage(control["run_id"])
    response_stage = next_stage["stage"]
    assert response_stage is not None
    with pytest.raises(ValueError, match="immediately preceding Bull Researcher"):
        coordinator.commit_stage(
            control["run_id"],
            response_stage["id"],
            _output(response_stage),
            committed["control"]["revision"],
        )


def test_tool_receipts_are_stage_scoped_and_receipt_batches_are_bounded(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    stage = started["stage"]
    started_receipt = coordinator.append_receipts(
        control["run_id"],
        [
            {
                "receipt_id": "scoped-start",
                "kind": "stage_started",
                "stage_id": stage["id"],
                "attempt": 1,
            }
        ],
        started["control"]["revision"],
    )

    with pytest.raises(ValueError, match="not allowed for stage"):
        coordinator.append_receipts(
            control["run_id"],
            [
                {
                    "receipt_id": "wrong-tool",
                    "kind": "tool_completed",
                    "stage_id": stage["id"],
                    "attempt": 1,
                    "capability_id": "news.company",
                }
            ],
            started_receipt["control"]["revision"],
        )

    with pytest.raises(ValueError, match="at most 100"):
        coordinator.append_receipts(
            control["run_id"],
            [{"receipt_id": f"progress-{index}", "kind": "stage_progress"} for index in range(101)],
            started_receipt["control"]["revision"],
        )


def test_finalization_hides_staged_memory_and_recovers_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = DecisionMemoryStore(tmp_path / "memory.sqlite3")
    coordinator = _coordinator(tmp_path, memory)
    control = coordinator.create(_request())
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete(coordinator, control["run_id"], started["control"]["revision"])
    original_update = coordinator.lifecycle_store.update
    calls = 0

    def fail_before_completion(run_id: str, expected_revision: int, mutation: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected lifecycle completion failure")
        return original_update(run_id, expected_revision, mutation)

    monkeypatch.setattr(coordinator.lifecycle_store, "update", fail_before_completion)
    with pytest.raises(OSError, match="injected"):
        coordinator.finalize(control["run_id"], revision)

    assert coordinator.control(control["run_id"])["status"] == LifecycleStatus.FINALIZING
    assert memory.recall("ORCL").same_symbol == ()

    monkeypatch.setattr(coordinator.lifecycle_store, "update", original_update)
    current_revision = coordinator.control(control["run_id"])["revision"]
    result, _events = coordinator.finalize(control["run_id"], current_revision)
    assert result.processed_signal == "HOLD"
    assert len(memory.recall("ORCL").same_symbol) == 1


def test_finalization_recovers_hidden_result_after_publish_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = DecisionMemoryStore(tmp_path / "memory.sqlite3")
    coordinator = _coordinator(tmp_path, memory)
    control = coordinator.create(_request())
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete(coordinator, control["run_id"], started["control"]["revision"])
    original_publish = coordinator.result_store.publish_staged

    def fail_publish(run_id: str) -> Any:
        raise OSError(f"injected publication failure for {run_id}")

    monkeypatch.setattr(coordinator.result_store, "publish_staged", fail_publish)
    with pytest.raises(OSError, match="injected"):
        coordinator.finalize(control["run_id"], revision)

    failed_control = coordinator.control(control["run_id"])
    assert failed_control["status"] == LifecycleStatus.FINALIZING
    assert failed_control["storage_status"] == LifecycleStatus.COMPLETED
    assert failed_control["publication_pending"] is True
    assert coordinator.result_store.get_result(control["run_id"]) is None
    assert memory.recall("ORCL").same_symbol == ()
    pending_events = coordinator.poll_events(control["run_id"])
    assert pending_events["status"] == LifecycleStatus.FINALIZING
    assert pending_events["publication_pending"] is True
    assert not any(event["kind"] == "run" and event["status"] == "completed" for event in pending_events["events"])

    monkeypatch.setattr(coordinator.result_store, "publish_staged", original_publish)
    current_revision = coordinator.control(control["run_id"])["revision"]
    result, _events = coordinator.finalize(control["run_id"], current_revision)
    assert result.run_id == control["run_id"]
    assert coordinator.control(control["run_id"])["status"] == LifecycleStatus.COMPLETED
    completed_events = coordinator.poll_events(control["run_id"])
    assert completed_events["status"] == LifecycleStatus.COMPLETED
    assert completed_events["publication_pending"] is False
    assert completed_events["events"][-1]["status"] == "completed"
    assert len(memory.recall("ORCL").same_symbol) == 1


def test_control_remains_publication_pending_until_memory_visibility_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = DecisionMemoryStore(tmp_path / "memory.sqlite3")
    coordinator = _coordinator(tmp_path, memory)
    control = coordinator.create(_request())
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete(coordinator, control["run_id"], started["control"]["revision"])
    original_publish = memory.publish_decision

    def fail_memory_publish(run_id: str) -> Any:
        raise OSError(f"injected memory publication failure for {run_id}")

    monkeypatch.setattr(memory, "publish_decision", fail_memory_publish)
    with pytest.raises(OSError, match="injected"):
        coordinator.finalize(control["run_id"], revision)

    pending = coordinator.control(control["run_id"])
    assert pending["status"] == LifecycleStatus.FINALIZING
    assert pending["storage_status"] == LifecycleStatus.COMPLETED
    assert pending["publication_pending"] is True
    assert coordinator.result_store.get_result(control["run_id"]) is not None
    assert memory.recall("ORCL").same_symbol == ()
    assert dashboard_report(control["run_id"], coordinator.result_store, coordinator=coordinator)["ok"] is False
    pending_runs, pending_statuses = _dashboard_visibility(coordinator, control["run_id"])
    assert pending_runs == []
    assert pending_statuses == {"": 404, "/result": 404, "/view": 404, "/events": 404}
    with pytest.raises(ValueError, match="completed run not found"):
        launch_dashboard(
            "127.0.0.1",
            0,
            WEB_ROOT,
            run_id=control["run_id"],
            store=coordinator.result_store,
            coordinator=coordinator,
        )

    presenter = ViewerDaemonPresenter(coordinator.result_store, startup_timeout=1)
    try:
        pending_link = presenter.present(control["run_id"])
        assert pending_link.status == "unavailable"
        assert pending_link.error is not None
        assert pending_link.error["code"] == "viewer_run_not_ready"

        monkeypatch.setattr(memory, "publish_decision", original_publish)
        result, _events = coordinator.finalize(control["run_id"], pending["revision"])
        assert result.run_id == control["run_id"]
        assert coordinator.control(control["run_id"])["status"] == LifecycleStatus.COMPLETED
        assert len(memory.recall("ORCL").same_symbol) == 1
        assert dashboard_report(control["run_id"], coordinator.result_store, coordinator=coordinator)["ok"] is True

        completed_runs, completed_statuses = _dashboard_visibility(coordinator, control["run_id"])
        assert [item["run_id"] for item in completed_runs] == [control["run_id"]]
        assert completed_statuses == {"": 200, "/result": 200, "/view": 200, "/events": 200}
        launched = launch_dashboard(
            "127.0.0.1",
            0,
            WEB_ROOT,
            run_id=control["run_id"],
            store=coordinator.result_store,
            coordinator=coordinator,
        )
        launched_server = dashboard._SERVERS.pop()
        try:
            assert launched["run_id"] == control["run_id"]
        finally:
            launched_server.shutdown()
            launched_server.server_close()
    finally:
        presenter.stop(timeout=5)


@pytest.mark.parametrize(
    ("rating", "signal"),
    [
        ("Buy", "BUY"),
        ("Overweight", "OVERWEIGHT"),
        ("Hold", "HOLD"),
        ("Underweight", "UNDERWEIGHT"),
        ("Sell", "SELL"),
    ],
)
def test_all_five_portfolio_ratings_survive_lifecycle_restart_and_ui_projection(
    tmp_path: Path,
    rating: str,
    signal: str,
) -> None:
    state_dir = tmp_path / rating.lower()
    coordinator = _coordinator(state_dir)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete(
        coordinator,
        control["run_id"],
        started["control"]["revision"],
        rating=rating,
    )

    restarted = _coordinator(state_dir)
    result, events = restarted.finalize(control["run_id"], revision)
    view = build_run_view(result, events).to_dict()
    assert result.portfolio_decision.rating == rating.lower()
    assert result.processed_signal == signal
    assert view["decisions"]["portfolio"]["rating"] == rating.lower()
    assert view["signal"]["processed_signal"] == signal
    assert view["signal"]["executable"] is False


def test_lifecycle_database_and_directory_are_private(tmp_path: Path) -> None:
    state_dir = tmp_path / "private-state"
    coordinator = _coordinator(state_dir)
    coordinator.create(_request(), decision_memory_enabled=False)

    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((state_dir / "lifecycle.sqlite3").stat().st_mode) == 0o600
