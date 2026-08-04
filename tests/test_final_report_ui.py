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
        "decision-trace",
        "intelligence",
        "complete-research",
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
        "decision-trace-chain",
        "decision-trace-change",
        "coverage-grid",
        "source-mix",
        "freshness-grid",
        "source-analysis",
        "source-analysis-summary",
        "source-analysis-verdict",
        "source-coverage-matrix",
        "source-analysis-totals",
        "source-independence-note",
        "source-analysis-gap-list",
        "evidence-metrics",
        "news-intelligence",
        "catalyst-ledger",
        "risk-register",
        "conflict-ledger",
        "unknown-ledger",
        "monitoring-ledger",
        "research-change",
        "research-coverage",
        "source-explorer",
        "claim-graph",
        "filings-ledger",
        "earnings-ledger",
        "factor-history",
        "peer-matrix",
        "valuation-cases",
        "event-timeline",
        "stress-scenarios",
        "invalidation-rules",
        "prior-outcomes",
        "evaluation-receipts",
        "portfolio-context-impact",
        "research-mode",
        "analyst-grid",
        "research-debate-list",
        "research-manager",
        "research-recommendation",
        "research-rationale",
        "research-strategic-actions",
        "trader-action",
        "trader-reasoning",
        "trader-entry-price",
        "trader-stop-loss",
        "trader-position-sizing",
        "trader-executable",
        "risk-perspectives",
        "risk-manager-judgment",
        "portfolio-rating",
        "portfolio-summary",
        "portfolio-thesis",
        "portfolio-price-target",
        "portfolio-time-horizon",
        "portfolio-disclaimer",
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
    for obsolete_id in ("research-decision", "trader-stance", "trader-plan", "portfolio-decision"):
        assert f'id="{obsolete_id}"' not in html


def test_ui_renders_the_intelligence_projection_with_safe_dom_helpers() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "renderDecisionTrace" in javascript
    assert "analysis.decision_consistency" in javascript
    assert "renderIntelligence" in javascript
    assert "renderSourceAnalysis" in javascript
    assert "view.intelligence" in javascript
    assert "publicSourceLink" in javascript
    assert 'role="region" aria-label="Structured evidence metrics table" tabindex="0"' in html
    assert 'header.scope = "col"' in javascript
    assert "parsed.username ||" in javascript
    assert 'endsWith(".invalid")' in javascript
    assert "innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript


def test_ui_renders_completed_dossier_sections_and_keeps_legacy_results_absent() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="complete-research"' in html
    assert 'id="complete-research" aria-labelledby="complete-research-title" hidden' in html
    assert "renderCompletedResearch" in javascript
    assert 'if (!Object.keys(dossier).length || dossier.status !== "completed")' in javascript
    assert "section.hidden = true" in javascript
    assert "navigation.hidden = true" in javascript
    for field in (
        "research_delta",
        "documents",
        "source_documents",
        "claims",
        "arguments",
        "filings",
        "filing_changes",
        "transcripts",
        "guidance",
        "factor_snapshots",
        "peer_set",
        "valuation_cases",
        "calculations",
        "stress_scenarios",
        "monitoring_rules",
        "prior_outcomes",
        "portfolio_context",
        "portfolio_impact",
        "entities",
        "evaluation",
        "evaluation_receipts",
    ):
        assert f'"{field}"' in javascript


def test_completed_dossier_renderer_uses_text_nodes_for_untrusted_nested_values() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function researchValue" in javascript
    assert 'return node("span", "", text(value, "Not declared"))' in javascript
    assert "element.textContent = String(content)" in javascript
    assert ".innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript

    result = _run_debate_projection(
        r"""
        class Element {
          constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; this.className = ''; }
          append(...children) { this.children.push(...children); }
        }
        global.document = {createElement: (tag) => new Element(tag), querySelector: () => null};
        const ui = require('./src/tradingagents_portable/web/app.js');
        const hostile = '<img src=x onerror=alert(1)><script>alert(2)</script>';
        const rendered = ui.researchValue({title: hostile, locator: {section: hostile}});
        const scalarNodes = rendered.children.flatMap((row) => row.children[1].children).flatMap((value) =>
          value.tag === 'dl' ? value.children.flatMap((row) => row.children[1].children) : [value]
        );
        process.stdout.write(JSON.stringify({
          text: scalarNodes.map((item) => item.textContent).filter(Boolean),
          tags: scalarNodes.map((item) => item.tag)
        }));
        """
    )

    assert result["text"] == [
        "<img src=x onerror=alert(1)><script>alert(2)</script>",
        "<img src=x onerror=alert(1)><script>alert(2)</script>",
    ]
    assert result["tags"] == ["span", "span"]


def test_ui_loads_only_the_canonical_final_view_without_fabricated_fallback() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    combined = f"{html}\n{javascript}"

    assert 'return "/api/runs/current/view"' in javascript
    assert "resolveViewEndpoint(window.location.search)" in javascript
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


def test_ui_resolves_saved_run_urls_without_falling_forward_to_current() -> None:
    result = _run_debate_projection(
        """
        const ui = require('./src/tradingagents_portable/web/app.js');
        process.stdout.write(JSON.stringify({
          current: ui.resolveViewEndpoint(''),
          saved: ui.resolveViewEndpoint('?run=host-dc2616f0e2c2'),
          invalid: ui.resolveViewEndpoint('?run=../../current')
        }));
        """
    )

    assert result == {
        "current": "/api/runs/current/view",
        "saved": "/api/runs/host-dc2616f0e2c2/view",
        "invalid": None,
    }


def test_ui_uses_authoritative_research_mode_and_explicit_utc_timestamps() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "researchRequest.research_mode" in javascript
    assert 'set("#research-mode", fixtureMode ?' not in javascript
    result = _run_debate_projection(
        """
        const ui = require('./src/tradingagents_portable/web/app.js');
        process.stdout.write(JSON.stringify({
          instant: ui.timestamp('2026-08-01T00:30:00Z'),
          invalid: ui.timestamp('not-a-date')
        }));
        """
    )

    assert result["instant"].endswith(" UTC")
    assert result["invalid"] == "not-a-date"


def test_ui_guards_final_product_and_hides_legacy_complete_research_navigation() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    result = _run_debate_projection(
        """
        const ui = require('./src/tradingagents_portable/web/app.js');
        process.stdout.write(JSON.stringify({
          completed: ui.isCompletedView({overview: {status: 'completed'}}),
          running: ui.isCompletedView({overview: {status: 'running'}}),
          absent: ui.isCompletedView({})
        }));
        """
    )

    assert result == {"completed": True, "running": False, "absent": False}
    assert 'id="complete-research-nav" href="#complete-research" hidden' in html
    assert "Final research remains hidden until completion." in javascript


def test_completed_research_is_summary_first_with_progressive_raw_disclosures() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    stylesheet = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for renderer in (
        "renderResearchDelta",
        "renderCoverageStatusMatrix",
        "renderSources",
        "renderArgumentsAndClaims",
        "renderFilingChanges",
        "renderTranscriptsAndGuidance",
        "renderFactors",
        "renderPeers",
        "renderValuationAndCalculations",
        "renderEventsAndEntities",
        "renderRisks",
        "renderMonitoring",
        "renderPriorOutcomes",
        "renderPortfolioContextAndImpact",
        "renderEvaluationStatusMatrix",
    ):
        assert f"function {renderer}" in javascript
    assert 'node("details", "research-raw")' in javascript
    assert 'node("summary", "", "Full structured record")' in javascript
    assert 'if (key === "as_of_at") return "Information vintage";' in javascript
    assert '"Forecast / model period"' in javascript
    assert '"Reported / measurement period"' in javascript
    assert "summaryLabel: metricSummaryLabel" in javascript
    assert "#source-explorer" in stylesheet
    assert "white-space: nowrap" in stylesheet
    assert "grid-template-columns: 1fr" in stylesheet
    assert "var(--paper-warm)" not in stylesheet
    assert "var(--serif)" not in stylesheet
