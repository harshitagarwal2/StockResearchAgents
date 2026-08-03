from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.request import urlopen

from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.dashboard import create_dashboard_server
from tradingagents_portable.fixture import run_fixture
from tradingagents_portable.legacy import LegacyTradingAgentsAdapter
from tradingagents_portable.projection import LegacyStateProjector
from tradingagents_portable.store import RunStore
from tradingagents_portable.view import build_run_view

EXPECTED_FIXTURE_ARTIFACTS = {
    "report.group.1.analysts",
    "report.group.2.research",
    "report.group.3.trading",
    "report.group.4.risk",
    "report.group.5.portfolio",
    "report.complete",
    "data.run_result",
    "data.run_events",
}


class _ReportAwareGraph:
    saved_to: object = None

    def __init__(self, **_: Any) -> None:
        pass

    def propagate(self, *_: object, **__: object) -> tuple[dict[str, object], str]:
        return {"final_trade_decision": "FINAL"}, "HOLD"

    def save_reports(self, _state: object, _symbol: str, *, save_path: object) -> None:
        type(self).saved_to = save_path


class _ReportAwareAdapter(LegacyTradingAgentsAdapter):
    def _load(self) -> tuple[type[Any], dict[str, Any]]:
        return _ReportAwareGraph, {}


def test_fixture_report_bundle_matches_all_five_cli_groups() -> None:
    result, _ = run_fixture(RunRequest(), RunStore())
    assert {artifact.id for artifact in result.artifacts} == EXPECTED_FIXTURE_ARTIFACTS

    groups = [artifact for artifact in result.artifacts if artifact.kind == "report_group"]
    assert [artifact.title for artifact in groups] == [
        "I. Analyst Team Reports",
        "II. Research Team Decision",
        "III. Trading Team Plan",
        "IV. Risk Management Team Decision",
        "V. Portfolio Manager Decision",
    ]
    assert [section["title"] for section in groups[0].content["sections"]] == [
        "Market Analyst",
        "Sentiment Analyst",
        "News Analyst",
        "Fundamentals Analyst",
    ]
    assert [section["title"] for section in groups[1].content["sections"]] == [
        "Bull Researcher",
        "Bear Researcher",
        "Research Manager",
    ]
    assert [section["title"] for section in groups[3].content["sections"]] == [
        "Aggressive Analyst",
        "Conservative Analyst",
        "Neutral Analyst",
    ]
    complete = next(artifact for artifact in result.artifacts if artifact.id == "report.complete")
    assert all(artifact.title in complete.content for artifact in groups)
    assert all(
        artifact.content["disk_write_declared"] is False
        for artifact in result.artifacts
        if artifact.id in {"data.run_result", "data.run_events"}
    )


def test_run_view_is_lossless_and_keeps_decision_and_signal_separate() -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    view = build_run_view(result, events).to_dict()

    assert view["request"]["symbol"] == result.request.symbol
    assert view["topology"] == result.topology.to_dict()
    assert view["evidence"] == [item.to_dict() for item in result.evidence]
    assert view["analyst_reports"] == [report.to_dict() for report in result.analyst_reports]
    assert view["report_sections"] == result.report_sections.to_dict()
    assert view["debates"]["research"]["snapshot"] == result.research_debate_snapshot.to_dict()
    assert view["debates"]["risk"]["snapshot"] == result.risk_debate_snapshot.to_dict()
    assert view["decisions"]["portfolio"] == result.portfolio_decision.to_dict()
    assert view["decisions"]["research"]["recommendation"] == "hold"
    assert view["decisions"]["trader"]["action"] == "hold"
    assert view["decisions"]["portfolio"]["rating"] == "hold"
    assert view["outputs"]["final_trade_decision"] == result.final_trade_decision
    assert view["signal"]["processed_signal"] == result.processed_signal
    assert view["signal"]["source"] == "portfolio_rating"
    assert view["signal"]["processed_signal"] != view["outputs"]["final_trade_decision"]
    assert view["events"] == [event.to_dict() for event in events]
    assert view["artifacts"] == [artifact.to_dict() for artifact in result.artifacts]
    assert {action["id"] for action in view["actions"]} == {"view_complete_report", "resume", "cancel"}
    assert all(action["id"] != "execute_trade" for action in view["actions"])


def test_run_view_projects_full_fixture_intelligence_without_inventing_sources() -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    view = build_run_view(result, events).to_dict()
    intelligence = view["intelligence"]

    assert set(intelligence) == {
        "coverage",
        "source_mix",
        "freshness",
        "evidence_metrics",
        "news",
        "catalysts",
        "risk_register",
        "conflicts",
        "unknowns",
        "monitoring_conditions",
    }
    assert intelligence["coverage"] == {
        "evidence_count": 4,
        "analyst_count": 4,
        "limitation_count": 4,
        "source_url_count": 2,
        "dated_source_count": 4,
        "source_quality_buckets": {"synthetic": 4},
    }
    assert intelligence["source_mix"]["categories"] == {
        "fundamentals": 1,
        "market": 1,
        "news": 1,
        "social": 1,
    }
    assert intelligence["source_mix"]["providers"] == {"portable-fixture": 4}
    assert intelligence["freshness"] == {
        "cutoff": result.request.as_of_date,
        "oldest_source_date": result.request.as_of_date,
        "latest_source_date": result.request.as_of_date,
        "oldest_retrieved_at": f"{result.request.as_of_date}T12:00:00+00:00",
        "latest_retrieved_at": f"{result.request.as_of_date}T12:00:00+00:00",
    }
    assert len(intelligence["evidence_metrics"]) == 11
    assert len(intelligence["news"]) == 3
    assert sum("url" in article for article in intelligence["news"]) == 2
    assert all(
        article.get("url", "https://filtered.invalid").startswith(("http://", "https://"))
        for article in intelligence["news"]
    )
    assert len(intelligence["catalysts"]) == 3
    assert len(intelligence["risk_register"]) == 6
    assert len(intelligence["conflicts"]) == 2
    assert len(intelligence["unknowns"]) == 5
    assert len(intelligence["monitoring_conditions"]) == 4
    for section in ("evidence_metrics", "news", "catalysts", "conflicts"):
        assert all(record["evidence_id"] and record["category"] for record in intelligence[section])
    assert all(article["synthetic"] is True for article in intelligence["news"])
    assert any(item.get("source") == "risk_decision.constraints" for item in intelligence["risk_register"])
    assert any(item.get("source") == "risk_decision.unresolved" for item in intelligence["unknowns"])
    assert intelligence["monitoring_conditions"][-1]["source"] == "research_decision.strategic_actions"


def test_run_view_intelligence_is_backward_compatible_and_quality_fallback_is_safe() -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    explicit = replace(
        result.evidence[0],
        values={"close_usd": 162.4, "source_quality": "primary"},
        provenance=replace(
            result.evidence[0].provenance,
            source_uri="https://source.example/market",
            source_date=None,
            fixture=False,
        ),
    )
    unknown = replace(
        result.evidence[1],
        values={"positive": 7},
        provenance=replace(
            result.evidence[1].provenance,
            source_uri="javascript:alert(1)",
            fixture=False,
        ),
    )
    projected_result = replace(result, evidence=(explicit, unknown))
    view = build_run_view(projected_result, events).to_dict()

    assert view["evidence"] == [explicit.to_dict(), unknown.to_dict()]
    assert view["evidence"][0]["values"]["close_usd"] == 162.4
    assert view["evidence"][1]["values"]["positive"] == 7
    assert view["intelligence"]["coverage"] == {
        "evidence_count": 2,
        "analyst_count": 4,
        "limitation_count": 2,
        "source_url_count": 1,
        "dated_source_count": 1,
        "source_quality_buckets": {"primary": 1, "unknown": 1},
    }
    assert view["intelligence"]["evidence_metrics"] == []
    assert view["intelligence"]["news"] == []


def test_legacy_projection_preserves_source_report_contents_in_memory() -> None:
    final_state = {
        "market_report": "MARKET",
        "sentiment_report": "SENTIMENT",
        "news_report": "NEWS",
        "fundamentals_report": "FUNDAMENTALS",
        "investment_debate_state": {
            "bull_history": "BULL",
            "bear_history": "BEAR",
            "judge_decision": "MANAGER",
        },
        "investment_plan": "MANAGER",
        "trader_investment_plan": "TRADER",
        "risk_debate_state": {
            "aggressive_history": "AGGRESSIVE",
            "conservative_history": "CONSERVATIVE",
            "neutral_history": "NEUTRAL",
            "judge_decision": "PORTFOLIO",
        },
        "final_trade_decision": "FINAL",
    }
    result = LegacyStateProjector().project(
        run_id="legacy-report-test",
        request=RunRequest(executor="legacy"),
        final_state=final_state,
        processed_signal="HOLD",
        config={},
        started_at="start",
        completed_at="end",
    )
    groups = [artifact.content for artifact in result.artifacts if artifact.kind == "report_group"]
    projected_text = str(groups)
    for text in (
        "MARKET",
        "SENTIMENT",
        "NEWS",
        "FUNDAMENTALS",
        "BULL",
        "BEAR",
        "MANAGER",
        "TRADER",
        "AGGRESSIVE",
        "CONSERVATIVE",
        "NEUTRAL",
        "PORTFOLIO",
    ):
        assert text in projected_text
    assert {artifact.id for artifact in result.artifacts} == EXPECTED_FIXTURE_ARTIFACTS | {
        "data.legacy_state",
        "data.legacy_signal",
    }


def test_dashboard_serves_run_view_and_current_alias() -> None:
    store = RunStore()
    result, events = run_fixture(RunRequest(), store)
    server = create_dashboard_server("127.0.0.1", 0, store=store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    host_text = host.decode() if isinstance(host, bytes) else host
    try:
        for run_id in (result.run_id, "current"):
            with urlopen(f"http://{host_text}:{port}/api/runs/{run_id}/view", timeout=5) as response:  # noqa: S310
                payload = json.load(response)
            assert payload["ok"] is True
            assert payload["view"]["run_id"] == result.run_id
            assert len(payload["view"]["events"]) == len(events)
            assert payload["view"]["decisions"]["portfolio"] == result.portfolio_decision.to_dict()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_view_does_not_expose_legacy_config_values() -> None:
    private_value = "https://must-not-leak.example"
    result = LegacyStateProjector().project(
        run_id="legacy-secret-test",
        request=RunRequest(executor="legacy", legacy_config={"backend_url": private_value}),
        final_state={},
        processed_signal="",
        config={"backend_url": private_value},
        started_at="start",
        completed_at="end",
    )
    view = build_run_view(result, ()).to_dict()
    assert private_value not in str(view["request"])
    assert view["request"]["legacy_config"]["values_redacted"] is True


def test_legacy_report_tree_is_an_explicit_additional_output(tmp_path: Path) -> None:
    _ReportAwareGraph.saved_to = None
    adapter = _ReportAwareAdapter(store=RunStore())
    adapter.run(RunRequest(executor="legacy", analysts=("market",)))
    assert _ReportAwareGraph.saved_to is None

    output = str(tmp_path) + "/report-tree"
    result, _ = adapter.run(
        RunRequest(
            executor="legacy",
            analysts=("market",),
            legacy_config={"report_output_path": output},
        )
    )
    assert _ReportAwareGraph.saved_to == output
    assert result.persistence.writes_expected is True
    assert result.persistence.outputs == (
        "upstream_decision_memory",
        "upstream_state_log",
        f"explicit_report_tree:{output}",
    )
