from __future__ import annotations

import json
from pathlib import Path

from tradingagents_portable import cli
from tradingagents_portable.contracts import InstrumentIdentity, RunRequest, RunResult
from tradingagents_portable.legacy import LegacyTradingAgentsAdapter
from tradingagents_portable.store import RunStore


class FakeUpstreamAdapter:
    last_request: RunRequest | None = None
    cleared = False

    def __init__(self, legacy_path: str | None = None) -> None:
        self.legacy_path = legacy_path

    def defaults(self) -> dict[str, object]:
        return {
            "max_debate_rounds": 3,
            "max_risk_discuss_rounds": 4,
            "checkpoint_enabled": True,
        }

    def resolve_subject(self, subject: str, asset_type: str) -> tuple[str, str]:
        normalized = "BTC-USD" if subject.upper() == "BTCUSD" else subject.upper()
        resolved = "crypto" if asset_type == "auto" and normalized.endswith("-USD") else asset_type
        return normalized, "stock" if resolved == "auto" else resolved

    def clear_checkpoints(self) -> int:
        type(self).cleared = True
        return 2

    def run(self, request: RunRequest) -> tuple[RunResult, tuple[object, ...]]:
        type(self).last_request = request
        return (
            RunResult(
                run_id="legacy-fake",
                request=request,
                instrument=InstrumentIdentity(
                    requested_symbol=request.symbol,
                    company_of_interest=request.symbol,
                    trade_date=request.as_of_date,
                    asset_type=request.asset_type,
                    instrument_context=f"Resolved instrument: {request.symbol}",
                ),
            ),
            (),
        )


def test_research_maps_arbitrary_symbol_and_full_public_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "LegacyTradingAgentsAdapter", FakeUpstreamAdapter)
    output = tmp_path / "normalized.json"
    report_dir = tmp_path / "report"

    exit_code = cli.main(
        [
            "research",
            "0700.hk",
            "--date",
            "2026-07-03",
            "--analyst",
            "market",
            "--analyst",
            "news",
            "--debate-rounds",
            "2",
            "--risk-rounds",
            "5",
            "--provider",
            "openai",
            "--quick-model",
            "quick",
            "--deep-model",
            "deep",
            "--backend-url",
            "https://api.example.test/v1",
            "--output-language",
            "Japanese",
            "--temperature",
            "0.2",
            "--max-retries",
            "6",
            "--reasoning-effort",
            "high",
            "--no-checkpoint",
            "--report-output",
            str(report_dir),
            "--legacy-path",
            "/fake/upstream",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    request = FakeUpstreamAdapter.last_request
    assert request is not None
    assert request.symbol == "0700.HK"
    assert request.asset_type == "stock"
    assert request.analysts == ("market", "news")
    assert (request.debate_rounds, request.risk_rounds) == (2, 5)
    assert request.checkpoint_enabled is False
    assert request.legacy_config == {
        "llm_provider": "openai",
        "quick_think_llm": "quick",
        "deep_think_llm": "deep",
        "backend_url": "https://api.example.test/v1",
        "output_language": "Japanese",
        "temperature": 0.2,
        "llm_max_retries": 6,
        "openai_reasoning_effort": "high",
        "report_output_path": str(report_dir),
    }
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["view"]["overview"]["company_of_interest"] == "0700.HK"
    assert "api_key" not in str(payload).lower()


def test_research_auto_detects_crypto_and_preserves_upstream_env_defaults(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "LegacyTradingAgentsAdapter", FakeUpstreamAdapter)

    assert cli.main(["research", "btcusd", "--date", "2026-07-03"]) == 0

    request = FakeUpstreamAdapter.last_request
    assert request is not None
    assert request.symbol == "BTC-USD"
    assert request.asset_type == "crypto"
    assert request.analysts == ("market", "social", "news")
    assert (request.debate_rounds, request.risk_rounds) == (3, 4)
    assert request.checkpoint_enabled is True
    assert request.legacy_config == {}
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_research_dashboard_uses_same_process_stored_run(monkeypatch) -> None:
    monkeypatch.setattr(cli, "LegacyTradingAgentsAdapter", FakeUpstreamAdapter)
    served: list[tuple[str, int, str | None]] = []
    monkeypatch.setattr(cli, "_serve_dashboard", lambda host, port, run_id=None: served.append((host, port, run_id)))

    assert cli.main(["research", "AAPL", "--date", "2026-07-03", "--dashboard", "--port", "0"]) == 0
    assert served == [("127.0.0.1", 0, "legacy-fake")]


def test_research_clear_checkpoints_delegates_and_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "LegacyTradingAgentsAdapter", FakeUpstreamAdapter)
    FakeUpstreamAdapter.cleared = False

    assert cli.main(["research", "AAPL", "--clear-checkpoints"]) == 0
    assert FakeUpstreamAdapter.cleared is True
    assert json.loads(capsys.readouterr().out) == {"ok": True, "cleared_checkpoints": 2}


class FakeGraph:
    init: dict[str, object] = {}
    propagate_args: tuple[object, ...] = ()

    def __init__(self, **kwargs: object) -> None:
        type(self).init = kwargs

    def propagate(self, *args: object, **kwargs: object) -> tuple[dict[str, object], str]:
        type(self).propagate_args = (*args, kwargs)
        return (
            {
                "company_of_interest": args[0],
                "trade_date": args[1],
                "instrument_context": f"Resolved company identity for {args[0]}",
                "market_report": "market",
                "investment_plan": "plan",
                "trader_investment_plan": "trader",
                "final_trade_decision": "hold",
            },
            "HOLD",
        )


class FakeLoadedUpstream(LegacyTradingAgentsAdapter):
    def _load(self) -> tuple[type[FakeGraph], dict[str, object]]:
        return FakeGraph, {"llm_provider": "env-provider", "checkpoint_enabled": False}


def test_adapter_maps_arbitrary_request_to_upstream_graph_without_credentials() -> None:
    adapter = FakeLoadedUpstream(store=RunStore())
    request = RunRequest(
        symbol="MSFT",
        as_of_date="2026-07-03",
        executor="legacy",
        analysts=("market", "news"),
        debate_rounds=2,
        risk_rounds=3,
        checkpoint_enabled=True,
        legacy_config={"llm_provider": "test-provider", "quick_think_llm": "quick"},
    )

    result, _ = adapter.run(request)

    assert FakeGraph.init["selected_analysts"] == ("market", "news")
    config = FakeGraph.init["config"]
    assert isinstance(config, dict)
    assert config["llm_provider"] == "test-provider"
    assert config["quick_think_llm"] == "quick"
    assert config["max_debate_rounds"] == 2
    assert config["max_risk_discuss_rounds"] == 3
    assert config["checkpoint_enabled"] is True
    assert FakeGraph.propagate_args == ("MSFT", "2026-07-03", {"asset_type": "stock"})
    assert result.instrument.company_of_interest == "MSFT"
    assert result.instrument.instrument_context == "Resolved company identity for MSFT"
