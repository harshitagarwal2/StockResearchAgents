from __future__ import annotations

import json

from company_analytics_fixtures import complete_v4_submission

from tradingagents_portable import cli, mcp_server
from tradingagents_portable.company_analytics import submit_company_analytics
from tradingagents_portable.research_quality_v1 import QualityStore
from tradingagents_portable.store import RunStore


def test_analytics_cli_plan_and_import_round_trip(tmp_path, monkeypatch) -> None:
    quality_store = QualityStore(tmp_path / "quality")
    run_store = RunStore(tmp_path / "runs")
    monkeypatch.setattr(
        cli,
        "submit_company_analytics",
        lambda payload: submit_company_analytics(payload, store=run_store, quality_store=quality_store),
    )
    payload = complete_v4_submission("META")
    request_path = tmp_path / "request.json"
    submission_path = tmp_path / "submission.json"
    plan_path = tmp_path / "plan.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(json.dumps(payload["company_research"]["request"]), encoding="utf-8")  # type: ignore[index]
    submission_path.write_text(json.dumps(payload), encoding="utf-8")

    assert cli.main(["analytics-plan", "--input", str(request_path), "--output", str(plan_path)]) == 0
    assert cli.main(["analytics-import", "--input", str(submission_path), "--output", str(result_path)]) == 0

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    imported = json.loads(result_path.read_text(encoding="utf-8"))
    assert plan["workflow_profile"] == "company-analytics.v1"
    assert len(plan["stages"]) == 26
    assert imported["view"]["research_lab"]["analytics"]["coverage_decision"] == "supported"


def test_mcp_analytics_tools_prepare_and_publish_completed_view(tmp_path, monkeypatch) -> None:
    quality_store = QualityStore(tmp_path / "quality")
    run_store = RunStore(tmp_path / "runs")
    monkeypatch.setattr(
        mcp_server,
        "execute_company_analytics_import",
        lambda payload: submit_company_analytics(payload, store=run_store, quality_store=quality_store),
    )
    payload = complete_v4_submission("ORCL")
    request = payload["company_research"]["request"]  # type: ignore[index]

    plan = mcp_server.prepare_company_analytics(request)
    imported = mcp_server.import_company_analytics(payload)

    assert plan["terminal_artifact_kinds"][-1] == "forecast_set.v1"
    assert imported["view"]["research_lab"]["quality"]["schema_version"] == "research-quality.v1"
    assert imported["dashboard_path"].startswith("/?run=analytics-")
