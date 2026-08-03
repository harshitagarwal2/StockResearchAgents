from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType

import pytest

from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.fixture import run_fixture
from tradingagents_portable.projection import LegacyStateProjector


def _legacy_state() -> dict[str, object]:
    return {
        "market_report": "MARKET FULL REPORT",
        "sentiment_report": "SENTIMENT FULL REPORT",
        "news_report": "NEWS FULL REPORT",
        "fundamentals_report": "FUNDAMENTALS FULL REPORT",
        "investment_debate_state": {
            "history": "Bull: upside\nBear: downside",
            "bull_history": "Bull: upside",
            "bear_history": "Bear: downside",
            "current_response": "Bear: downside",
            "judge_decision": "RESEARCH MANAGER PLAN",
            "count": 2,
        },
        "investment_plan": "INVESTMENT PLAN EXACT",
        "trader_investment_plan": "TRADER PLAN EXACT",
        "risk_debate_state": {
            "history": "Aggressive: buy\nConservative: wait\nNeutral: hold",
            "aggressive_history": "Aggressive: buy",
            "conservative_history": "Conservative: wait",
            "neutral_history": "Neutral: hold",
            "current_aggressive_response": "Aggressive: buy",
            "current_conservative_response": "Conservative: wait",
            "current_neutral_response": "Neutral: hold",
            "judge_decision": "PORTFOLIO MANAGER DECISION EXACT",
            "count": 3,
        },
        "final_trade_decision": "FINAL TRADE DECISION EXACT",
    }


def test_projector_is_lossless_for_reports_and_distinct_decision_fields() -> None:
    state = _legacy_state()
    before = deepcopy(state)
    result = LegacyStateProjector().project(
        run_id="legacy-test",
        request=RunRequest(executor="legacy"),
        final_state=MappingProxyType(state),
        processed_signal="BUY",
        config={
            "llm_provider": "openai",
            "deep_think_llm": "deep",
            "quick_think_llm": "quick",
            "backend_url": "https://api.example.test/v1",
            "output_language": "English",
            "temperature": 0.2,
            "llm_max_retries": 4,
            "google_thinking_level": "high",
            "openai_reasoning_effort": "medium",
            "anthropic_effort": "high",
            "data_vendors": {"market": "yfinance", "news": "alpha_vantage"},
            "api_key": "MUST_NOT_LEAK",
        },
        started_at="2026-07-03T12:00:00+00:00",
        completed_at="2026-07-03T12:01:00+00:00",
    )

    assert state == before
    assert result.report_sections.market_report == "MARKET FULL REPORT"
    assert result.report_sections.fundamentals_report == "FUNDAMENTALS FULL REPORT"
    assert result.investment_plan == "INVESTMENT PLAN EXACT"
    assert result.trader_investment_plan == "TRADER PLAN EXACT"
    assert result.portfolio_manager_decision == "PORTFOLIO MANAGER DECISION EXACT"
    assert result.final_trade_decision == "FINAL TRADE DECISION EXACT"
    assert result.processed_signal == "BUY"
    assert result.trader_decision.stance == "buy"
    assert result.trader_decision.executable is False
    assert result.execution_config.backend_url == "https://api.example.test/v1"
    assert result.execution_config.output_language == "English"
    assert result.execution_config.temperature == 0.2
    assert result.execution_config.max_retries == 4
    assert result.execution_config.google_thinking_level == "high"
    assert result.execution_config.openai_reasoning_effort == "medium"
    assert result.execution_config.anthropic_effort == "high"
    assert "MUST_NOT_LEAK" not in str(result.to_dict())


def test_projector_preserves_snapshots_without_inventing_turns() -> None:
    result = LegacyStateProjector().project(
        run_id="legacy-test",
        request=RunRequest(executor="legacy"),
        final_state=_legacy_state(),
        processed_signal="HOLD",
        config={},
        started_at="start",
        completed_at="end",
    )

    assert result.research_debate == ()
    assert result.risk_debate == ()
    assert result.research_debate_snapshot.history == "Bull: upside\nBear: downside"
    assert result.research_debate_snapshot.current_response == "Bear: downside"
    assert result.research_debate_snapshot.role_histories == {
        "bull": "Bull: upside",
        "bear": "Bear: downside",
    }
    assert result.risk_debate_snapshot.current_responses["neutral"] == "Neutral: hold"
    assert result.capability.observation_mode == "legacy_post_run"
    assert result.persistence.run_logging_enabled is True
    assert result.persistence.writes_expected is True
    assert result.persistence.outputs == ("upstream_decision_memory", "upstream_state_log")


@pytest.mark.parametrize("signal", ["BUY", "OVERWEIGHT", "HOLD", "UNDERWEIGHT", "SELL"])
def test_projector_preserves_every_upstream_signal_tier(signal: str) -> None:
    result = LegacyStateProjector().project(
        run_id="legacy-test",
        request=RunRequest(executor="legacy"),
        final_state=_legacy_state(),
        processed_signal=signal,
        config={},
        started_at="start",
        completed_at="end",
    )

    expected = signal.lower()
    assert result.processed_signal == signal
    assert result.trader_decision.stance == expected
    assert result.portfolio_decision.action == expected


def test_fixture_populates_the_full_parity_surface() -> None:
    result, _ = run_fixture(RunRequest())

    assert all(
        result.report_sections.to_dict()[key]
        for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report")
    )
    assert result.research_debate_snapshot.count == 2
    assert result.risk_debate_snapshot.count == 3
    assert result.investment_plan
    assert result.trader_investment_plan
    assert result.portfolio_manager_decision
    assert result.final_trade_decision
    assert result.processed_signal == "NO_ACTION"
    assert result.capability.observation_mode == "fixture"
    assert result.persistence.writes_expected is False
