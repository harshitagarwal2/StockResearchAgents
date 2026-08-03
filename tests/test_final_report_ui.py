from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "src" / "tradingagents_portable" / "web"


def test_ui_is_a_final_report_projection_not_a_run_harness() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8").lower()
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8").lower()

    assert "<form" not in html
    assert "<input" not in html
    assert "<select" not in html
    assert 'role="tab"' not in html
    assert "setup-view" not in html
    assert "live-view" not in html
    assert "setup-tab" not in javascript
    assert "live-tab" not in javascript
    assert "data-demo-action" not in html
    assert "run-controls" not in html
    assert "run_fixture" not in javascript
    assert "run_legacy" not in javascript
    assert "execute_trade" not in javascript


def test_ui_exposes_every_merged_final_report_section() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    required_section_ids = {
        "executive",
        "analysts",
        "research-debate",
        "trader",
        "risk",
        "evidence",
        "warnings",
        "transparency",
        "artifacts-section",
        "methodology",
    }
    required_data_ids = {
        "analyst-grid",
        "research-debate-list",
        "research-manager",
        "trader-stance",
        "trader-plan",
        "trader-executable",
        "risk-perspectives",
        "risk-manager-judgment",
        "portfolio-decision",
        "processed-signal",
        "evidence-provenance",
        "capability-grid",
        "persistence-grid",
        "execution-grid",
        "artifacts",
        "topology-list",
        "event-summary",
    }
    for element_id in required_section_ids | required_data_ids:
        assert f'id="{element_id}"' in html


def test_ui_loads_only_the_canonical_final_view_without_fabricated_fallback() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    combined = f"{html}\n{javascript}"

    assert 'fetch("/api/runs/current/view"' in javascript
    assert "/api/runs/current/events" not in javascript
    assert "/api/runs/current/result" not in javascript
    assert "ORCL" not in combined
    assert "AAPL" not in combined
    assert "BTC-USD" not in combined
    assert "fixture://" not in combined
    assert "portable-fixture" not in combined
    assert "197.42" not in combined
    assert "No report loaded" in combined


def test_ui_has_no_order_execution_surface() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8").lower()
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8").lower()

    assert "buy button" not in html
    assert "sell button" not in html
    assert "submit order" not in html
    assert 'method: "post"' not in javascript
    assert 'method: "put"' not in javascript
    assert 'method: "delete"' not in javascript
    assert "/api/orders" not in javascript
    assert "/api/broker" not in javascript
    assert "non-executable" in html


def _run_debate_projection(script: str) -> dict[str, object]:
    completed = subprocess.run(  # noqa: S603 - fixed local Node executable and test-owned source
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_ui_falls_back_to_legacy_research_role_histories_without_duplication() -> None:
    result = _run_debate_projection(
        """
        const ui = require('./src/tradingagents_portable/web/app.js');
        const snapshot = {role_histories: {bull: 'BULL HISTORY', bear: 'BEAR HISTORY'}};
        const fallback = ui.resolveDebateEntries([], snapshot, ui.RESEARCH_SNAPSHOT_ROLES);
        const normalized = [{speaker: 'Bull Researcher', position: 'NORMALIZED TURN'}];
        const primary = ui.resolveDebateEntries(normalized, snapshot, ui.RESEARCH_SNAPSHOT_ROLES);
        process.stdout.write(JSON.stringify({fallback, primary}));
        """
    )

    assert result["fallback"] == [
        {"speaker": "Bull Researcher", "position": "BULL HISTORY", "snapshot": True},
        {"speaker": "Bear Researcher", "position": "BEAR HISTORY", "snapshot": True},
    ]
    assert result["primary"] == [{"speaker": "Bull Researcher", "position": "NORMALIZED TURN"}]


def test_ui_falls_back_to_all_three_legacy_risk_role_histories_without_duplication() -> None:
    result = _run_debate_projection(
        """
        const ui = require('./src/tradingagents_portable/web/app.js');
        const snapshot = {role_histories: {
          aggressive: 'AGGRESSIVE HISTORY',
          conservative: 'CONSERVATIVE HISTORY',
          neutral: 'NEUTRAL HISTORY'
        }};
        const fallback = ui.resolveDebateEntries([], snapshot, ui.RISK_SNAPSHOT_ROLES);
        const normalized = [{speaker: 'Neutral Analyst', position: 'NORMALIZED TURN'}];
        const primary = ui.resolveDebateEntries(normalized, snapshot, ui.RISK_SNAPSHOT_ROLES);
        process.stdout.write(JSON.stringify({fallback, primary}));
        """
    )

    assert result["fallback"] == [
        {"speaker": "Aggressive Analyst", "position": "AGGRESSIVE HISTORY", "snapshot": True},
        {"speaker": "Conservative Analyst", "position": "CONSERVATIVE HISTORY", "snapshot": True},
        {"speaker": "Neutral Analyst", "position": "NEUTRAL HISTORY", "snapshot": True},
    ]
    assert result["primary"] == [{"speaker": "Neutral Analyst", "position": "NORMALIZED TURN"}]
