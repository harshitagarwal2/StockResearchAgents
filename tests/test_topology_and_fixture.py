from __future__ import annotations

from dataclasses import asdict

import pytest

from tradingagents_portable.contracts import EventKind, RunRequest, RunResult, RunStatus, StageKind
from tradingagents_portable.fixture import prepare_fixture, run_fixture
from tradingagents_portable.store import RunStore
from tradingagents_portable.topology import build_legacy_topology


@pytest.mark.parametrize("rounds", [1, 3, 5])
def test_legacy_topology_has_exact_turn_counts_and_terminal_portfolio(rounds: int) -> None:
    requested = ("market", "social", "news", "fundamentals")
    topology = build_legacy_topology(requested, debate_rounds=rounds, risk_rounds=rounds)

    analysts = [stage for stage in topology.stages if stage.kind is StageKind.ANALYST]
    research = [stage for stage in topology.stages if stage.kind is StageKind.RESEARCH_DEBATE]
    risk = [stage for stage in topology.stages if stage.kind is StageKind.RISK_DEBATE]
    stage_ids = [stage.id for stage in topology.stages]

    assert topology.analysts == requested
    assert [stage.id for stage in analysts] == [f"analyst.{name}" for name in requested]
    assert len(research) == 2 * rounds
    assert [stage.role for stage in research] == ["Bull Researcher", "Bear Researcher"] * rounds
    assert stage_ids.index("research.manager") + 1 == stage_ids.index("trader")
    assert len(risk) == 3 * rounds
    assert [stage.role for stage in risk] == [
        role for _ in range(rounds) for role in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst")
    ]
    assert topology.terminal_stage == "portfolio"
    assert topology.stages[-1].id == "portfolio"
    assert topology.stages[-1].kind is StageKind.PORTFOLIO

    for previous, current in zip(topology.stages, topology.stages[1:], strict=False):
        assert current.ordinal == previous.ordinal + 1
        assert current.depends_on == (previous.id,)


def test_requested_and_effective_analysts_are_explicit_in_preflight() -> None:
    requested = ("market", "news")
    request = RunRequest(analysts=requested)
    prepared = prepare_fixture(request)

    assert tuple(prepared["request"]["analysts"]) == requested
    assert tuple(prepared["topology"]["analysts"]) == requested


def test_preflight_preserves_always_on_memory_and_opt_in_checkpoint_defaults() -> None:
    request = RunRequest()
    prepared = prepare_fixture(request)

    assert request.checkpoint_enabled is False
    assert prepared["request"]["checkpoint_enabled"] is False
    assert prepared["persistence"]["decision_memory_enabled"] is True
    assert prepared["persistence"]["run_logging_enabled"] is True
    assert prepared["persistence"]["checkpoint_enabled"] is False


def test_orcl_fixture_is_deterministic_complete_and_typed() -> None:
    request = RunRequest(debate_rounds=3, risk_rounds=3)
    first_result, first_events = run_fixture(request, RunStore())
    second_result, second_events = run_fixture(request, RunStore())

    assert isinstance(first_result, RunResult)
    assert first_result.status is RunStatus.COMPLETED
    assert asdict(first_result) == asdict(second_result)
    assert tuple(asdict(event) for event in first_events) == tuple(asdict(event) for event in second_events)
    assert len(first_result.analyst_reports) == len(request.analysts)
    assert len(first_result.research_debate) == 2 * request.debate_rounds
    assert len(first_result.risk_debate) == 3 * request.risk_rounds
    assert first_result.research_decision.rationale
    assert first_result.trader_decision.plan
    assert first_result.risk_decision.constraints
    assert first_result.portfolio_decision.summary
    assert first_result.trader_decision.executable is False
    assert first_result.portfolio_decision.executable is False
    assert {artifact.media_type for artifact in first_result.artifacts} >= {
        "text/markdown",
        "application/json",
    }
    assert {item.category for item in first_result.evidence} == set(request.analysts)
    assert all(item.provenance.fixture for item in first_result.evidence)

    assert [event.sequence for event in first_events] == list(range(1, len(first_events) + 1))
    assert first_events[0].kind is EventKind.RUN
    assert first_events[0].status == RunStatus.RUNNING.value
    assert first_events[-1].kind is EventKind.RUN
    assert first_events[-1].status == RunStatus.COMPLETED.value
    for stage in first_result.topology.stages:
        stage_events = [event for event in first_events if event.stage_id == stage.id]
        assert stage_events[0].status == "started"
        assert stage_events[-1].status == "completed"


def test_fixture_rejects_non_orcl_symbol_without_network_fallback() -> None:
    with pytest.raises(ValueError, match="ORCL"):
        RunRequest(symbol="AAPL", executor="fixture")
