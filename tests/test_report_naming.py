from __future__ import annotations

from pathlib import Path

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents import cli
from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.report_server import create_report_server, report_summary
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore

ROOT = Path(__file__).resolve().parents[1]


def test_report_is_the_only_viewer_cli_command() -> None:
    parser = cli._parser()
    report = parser.parse_args(["report", "--port", "0"])
    analytics_import = parser.parse_args(["analytics-import", "--input", "submission.json", "--report"])

    assert report.command == "report"
    assert report.port == 0
    assert analytics_import.report is True
    with pytest.raises(SystemExit):
        parser.parse_args(["dashboard"])
    with pytest.raises(SystemExit):
        parser.parse_args(["research", "AAPL"])
    with pytest.raises(SystemExit):
        parser.parse_args(["host-import", "--input", "submission.json"])
    with pytest.raises(SystemExit):
        parser.parse_args(["company-import", "--input", "submission.json"])


def test_report_facade_uses_completed_run_projection(tmp_path: Path) -> None:
    store = RunStore(state_dir=tmp_path / "runs")
    result, _events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=store,
        quality_store=QualityStore(),
    )

    summary = report_summary(result.run_id, store)
    server = create_report_server("127.0.0.1", 0, store=store)
    try:
        assert summary["ok"] is True
        assert summary["run_id"] == result.run_id
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_viewer_uses_canonical_human_facing_names() -> None:
    markup = (ROOT / "src" / "stock_research_agents" / "web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "src" / "stock_research_agents" / "web" / "app.js").read_text(encoding="utf-8")

    assert "StockResearchAgents · Company Analytics Viewer" in markup
    assert "Company analytics viewer" in markup
    assert "Completed company analytics" in markup
    assert "Completed company-analytics projection" in script
    assert "canonical completed result" in script
