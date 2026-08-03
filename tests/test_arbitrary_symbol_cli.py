from __future__ import annotations

import json
from typing import Any

import pytest

from tradingagents_portable import cli, mcp_server
from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.legacy import LegacyTradingAgentsAdapter
from tradingagents_portable.store import RunStore

FULL_UPSTREAM_STATE: dict[str, object] = {
    "market_report": "MARKET REPORT",
    "sentiment_report": "SENTIMENT REPORT",
    "news_report": "NEWS REPORT",
    "fundamentals_report": "FUNDAMENTALS REPORT",
    "investment_debate_state": {
        "history": "BULL HISTORY\nBEAR HISTORY",
        "bull_history": "BULL HISTORY",
        "bear_history": "BEAR HISTORY",
        "current_response": "BEAR CURRENT",
        "current_bull_response": "BULL CURRENT",
        "current_bear_response": "BEAR CURRENT",
        "judge_decision": "RESEARCH JUDGMENT",
        "count": 4,
    },
    "investment_plan": "RESEARCH MANAGER PLAN",
    "trader_investment_plan": "TRADER PLAN",
    "risk_debate_state": {
        "history": "AGGRESSIVE\nCONSERVATIVE\nNEUTRAL",
        "aggressive_history": "AGGRESSIVE HISTORY",
        "conservative_history": "CONSERVATIVE HISTORY",
        "neutral_history": "NEUTRAL HISTORY",
        "current_aggressive_response": "AGGRESSIVE CURRENT",
        "current_conservative_response": "CONSERVATIVE CURRENT",
        "current_neutral_response": "NEUTRAL CURRENT",
        "judge_decision": "PORTFOLIO JUDGMENT",
        "count": 6,
    },
    "final_trade_decision": "FINAL PORTFOLIO DECISION",
}


class RecordingGraph:
    constructor_calls: list[dict[str, object]] = []
    propagate_calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).constructor_calls.append(kwargs)

    def propagate(self, symbol: str, as_of_date: str, *, asset_type: str) -> tuple[dict[str, object], str]:
        type(self).propagate_calls.append({"symbol": symbol, "as_of_date": as_of_date, "asset_type": asset_type})
        return FULL_UPSTREAM_STATE, "HOLD"


class RecordingAdapter(LegacyTradingAgentsAdapter):
    def _load(self) -> tuple[type[Any], dict[str, Any]]:
        return RecordingGraph, {
            "llm_provider": "default-provider",
            "deep_think_llm": "default-deep",
            "quick_think_llm": "default-quick",
            "checkpoint_enabled": False,
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
        }


@pytest.fixture(autouse=True)
def reset_recording_graph() -> None:
    RecordingGraph.constructor_calls.clear()
    RecordingGraph.propagate_calls.clear()


@pytest.mark.parametrize(
    ("symbol", "asset_type", "requested_analysts", "effective_analysts"),
    [
        ("AAPL", "stock", ("market", "social", "news", "fundamentals"), ("market", "social", "news", "fundamentals")),
        ("ORCL", "stock", ("market", "news"), ("market", "news")),
        ("BTC-USD", "crypto", ("market", "social", "news", "fundamentals"), ("market", "social", "news")),
    ],
)
def test_legacy_adapter_preserves_arbitrary_instrument_and_normalizes_every_cli_output(
    symbol: str,
    asset_type: str,
    requested_analysts: tuple[str, ...],
    effective_analysts: tuple[str, ...],
) -> None:
    request = RunRequest(
        symbol=symbol,
        as_of_date="2026-07-15",
        asset_type=asset_type,  # type: ignore[arg-type]
        analysts=requested_analysts,
        debate_rounds=2,
        risk_rounds=3,
        executor="legacy",
        checkpoint_enabled=True,
        legacy_config={
            "llm_provider": "test-provider",
            "deep_think_llm": "deep-test",
            "quick_think_llm": "quick-test",
            "output_language": "English",
        },
    )

    result, events = RecordingAdapter(store=RunStore()).run(request)

    assert RecordingGraph.propagate_calls == [{"symbol": symbol, "as_of_date": "2026-07-15", "asset_type": asset_type}]
    constructor = RecordingGraph.constructor_calls[0]
    assert constructor["selected_analysts"] == effective_analysts
    assert constructor["debug"] is False
    assert constructor["callbacks"] is None
    config = constructor["config"]
    assert isinstance(config, dict)
    assert config["llm_provider"] == "test-provider"
    assert config["deep_think_llm"] == "deep-test"
    assert config["quick_think_llm"] == "quick-test"
    assert config["output_language"] == "English"
    assert config["checkpoint_enabled"] is True
    assert config["max_debate_rounds"] == 2
    assert config["max_risk_discuss_rounds"] == 3

    assert result.request.symbol == symbol
    assert result.request.as_of_date == "2026-07-15"
    assert result.request.asset_type == asset_type
    assert result.request.analysts == effective_analysts
    assert result.report_sections.market_report == "MARKET REPORT"
    assert result.report_sections.sentiment_report == "SENTIMENT REPORT"
    assert result.report_sections.news_report == "NEWS REPORT"
    if asset_type == "crypto":
        assert result.report_sections.fundamentals_report == "FUNDAMENTALS REPORT"
        assert "fundamentals" not in {report.analyst for report in result.analyst_reports}
    else:
        assert {report.analyst for report in result.analyst_reports} == set(effective_analysts)
    assert result.research_debate_snapshot.judge_decision == "RESEARCH JUDGMENT"
    assert result.investment_plan == "RESEARCH MANAGER PLAN"
    assert result.trader_investment_plan == "TRADER PLAN"
    assert result.risk_debate_snapshot.judge_decision == "PORTFOLIO JUDGMENT"
    assert result.final_trade_decision == "FINAL PORTFOLIO DECISION"
    assert result.processed_signal == "HOLD"
    assert result.trader_decision.executable is False
    assert result.portfolio_decision.executable is False
    assert {artifact.id for artifact in result.artifacts} >= {
        "report.group.1.analysts",
        "report.group.2.research",
        "report.group.3.trading",
        "report.group.4.risk",
        "report.group.5.portfolio",
        "report.complete",
        "data.legacy_state",
        "data.legacy_signal",
    }
    assert events[0].status == "running"
    assert events[-1].status == "completed"


@pytest.mark.parametrize(
    ("input_symbol", "canonical_symbol", "asset_type", "expected_analysts"),
    [
        ("aapl", "AAPL", "stock", ("market", "social", "news", "fundamentals")),
        ("ORCL", "ORCL", "stock", ("market", "news")),
        ("btc-usd", "BTC-USD", "crypto", ("market", "social", "news")),
    ],
)
def test_cli_research_command_canonicalizes_and_auto_detects_any_supported_symbol(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    input_symbol: str,
    canonical_symbol: str,
    asset_type: str,
    expected_analysts: tuple[str, ...],
) -> None:
    monkeypatch.setattr(cli, "LegacyTradingAgentsAdapter", RecordingAdapter, raising=False)
    analysts = ["market", "news"] if canonical_symbol == "ORCL" else ["market", "social", "news", "fundamentals"]
    argv = [
        "research",
        input_symbol,
        "--date",
        "2026-07-15",
        "--debate-rounds",
        "2",
        "--risk-rounds",
        "3",
    ]
    for analyst in analysts:
        argv.extend(("--analyst", analyst))

    assert cli.main(argv) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["result"]["request"]["symbol"] == canonical_symbol
    assert payload["result"]["request"]["asset_type"] == asset_type
    assert tuple(payload["result"]["request"]["analysts"]) == expected_analysts
    assert payload["result"]["final_trade_decision"] == "FINAL PORTFOLIO DECISION"
    assert payload["result"]["processed_signal"] == "HOLD"


@pytest.mark.parametrize(
    ("symbol", "asset_type", "analysts", "effective_analysts"),
    [
        ("AAPL", "stock", ["market", "social", "news", "fundamentals"], ["market", "social", "news", "fundamentals"]),
        ("ORCL", "stock", ["market", "news"], ["market", "news"]),
        ("BTC-USD", "crypto", ["market", "social", "news", "fundamentals"], ["market", "social", "news"]),
    ],
)
def test_mcp_run_legacy_accepts_arbitrary_symbol_and_returns_complete_normalized_result(
    monkeypatch: pytest.MonkeyPatch,
    symbol: str,
    asset_type: str,
    analysts: list[str],
    effective_analysts: list[str],
) -> None:
    monkeypatch.setattr(mcp_server, "LegacyTradingAgentsAdapter", RecordingAdapter)

    payload = mcp_server.run_legacy(
        symbol=symbol,
        as_of_date="2026-07-15",
        asset_type=asset_type,
        analysts=analysts,
        debate_rounds=2,
        risk_rounds=3,
        checkpoint_enabled=True,
        llm_provider="test-provider",
        deep_think_llm="deep-test",
        quick_think_llm="quick-test",
    )

    assert payload["ok"] is True
    result = payload["result"]
    assert result["request"]["symbol"] == symbol
    assert result["request"]["as_of_date"] == "2026-07-15"
    assert result["request"]["asset_type"] == asset_type
    assert tuple(result["request"]["analysts"]) == tuple(effective_analysts)
    assert result["execution_config"]["max_debate_rounds"] == 2
    assert result["execution_config"]["max_risk_discuss_rounds"] == 3
    assert result["execution_config"]["checkpoint_enabled"] is True
    assert result["final_trade_decision"] == "FINAL PORTFOLIO DECISION"
    assert result["processed_signal"] == "HOLD"


def test_mcp_run_legacy_preserves_upstream_environment_defaults_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EnvironmentDefaultsAdapter(RecordingAdapter):
        def _load(self) -> tuple[type[Any], dict[str, Any]]:
            graph, defaults = super()._load()
            return graph, {
                **defaults,
                "max_debate_rounds": 3,
                "max_risk_discuss_rounds": 4,
                "checkpoint_enabled": True,
            }

    monkeypatch.setattr(mcp_server, "LegacyTradingAgentsAdapter", EnvironmentDefaultsAdapter)

    payload = mcp_server.run_legacy(symbol="MSFT", as_of_date="2026-07-15")

    assert payload["ok"] is True
    request = payload["result"]["request"]
    assert request["debate_rounds"] == 3
    assert request["risk_rounds"] == 4
    assert request["checkpoint_enabled"] is True


def test_openai_codex_provider_is_forwarded_without_oauth_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server, "LegacyTradingAgentsAdapter", RecordingAdapter)
    monkeypatch.setenv("TRADINGAGENTS_CODEX_AUTH_PATH", "/private/runtime-owned/codex-auth.json")

    payload = mcp_server.run_legacy(
        symbol="AAPL",
        as_of_date="2026-07-15",
        llm_provider="openai_codex",
        openai_reasoning_effort="high",
    )

    assert payload["ok"] is True
    config = RecordingGraph.constructor_calls[0]["config"]
    assert isinstance(config, dict)
    assert config["llm_provider"] == "openai_codex"
    assert config["openai_reasoning_effort"] == "high"
    serialized = json.dumps(payload)
    assert "codex-auth.json" not in serialized
    assert "private/runtime-owned" not in serialized


def test_fixture_remains_explicitly_orcl_only_while_legacy_is_symbol_agnostic() -> None:
    with pytest.raises(ValueError, match="fixture supports symbol ORCL only"):
        RunRequest(symbol="AAPL", executor="fixture")

    request = RunRequest(symbol="AAPL", executor="legacy")
    assert request.symbol == "AAPL"
