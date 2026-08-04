from __future__ import annotations

from pathlib import Path

from tradingagents_portable import cli
from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.fixture import run_fixture
from tradingagents_portable.report_server import create_report_server, report_summary
from tradingagents_portable.store import RunStore

ROOT = Path(__file__).resolve().parents[1]


def test_report_is_preferred_cli_alias_with_compatibility_dashboard() -> None:
    parser = cli._parser()
    report = parser.parse_args(["report", "--fixture", "--port", "0"])
    dashboard = parser.parse_args(["dashboard", "--fixture", "--port", "0"])
    upstream = parser.parse_args(["research", "AAPL", "--report"])
    host_import = parser.parse_args(["host-import", "--input", "submission.json", "--report"])
    company_import = parser.parse_args(["company-import", "--input", "submission.json", "--report"])

    assert report.command == "report"
    assert dashboard.command == "dashboard"
    assert report.fixture is True
    assert dashboard.fixture is True
    assert upstream.dashboard is True
    assert host_import.dashboard is True
    assert company_import.dashboard is True


def test_report_facade_uses_completed_dashboard_projection(tmp_path: Path) -> None:
    store = RunStore(state_dir=tmp_path / "runs")
    result, events = run_fixture(RunRequest())
    store.put(result, events)

    summary = report_summary(result.run_id, store)
    server = create_report_server("127.0.0.1", 0, store=store)
    try:
        assert summary["ok"] is True
        assert summary["run_id"] == result.run_id
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_viewer_uses_canonical_human_facing_names() -> None:
    markup = (ROOT / "src" / "tradingagents_portable" / "web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "src" / "tradingagents_portable" / "web" / "app.js").read_text(encoding="utf-8")

    assert "StockResearchAgents · Research Dossier Viewer" in markup
    assert "Research conclusion" in markup
    assert "Completed Research Dossier" in markup
    assert "Completed Research Dossier" in script
    assert "Completed read model" in script
