from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "src" / "stock_research_agents" / "web"


def _run_js(script: str) -> dict[str, object]:
    completed = subprocess.run(  # noqa: S603 - fixed local Node executable and test-owned source
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_ui_is_a_completed_company_analytics_projection() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    combined = f"{html}\n{javascript}".lower()

    for top_level in (
        "overview",
        "research_request",
        "research_dossier",
        "analytics",
        "source_lineage",
        "research_lab",
        "reports",
        "events",
        "artifacts",
        "actions",
    ):
        assert f"view.{top_level}" in javascript

    assert "<form" not in combined
    assert "<input" not in combined
    assert "<select" not in combined
    assert "run_fixture" not in combined
    assert "execute_trade" not in combined
    assert 'method: "post"' not in javascript.lower()
    assert "/api/orders" not in combined
    assert "non-executable" in combined


def test_ui_replaces_legacy_team_and_trade_viewer_concepts() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8").lower()
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8").lower()

    for obsolete_id in (
        "analyst-grid",
        "research-debate-list",
        "trader-action",
        "risk-perspectives",
        "portfolio-rating",
        "execution-grid",
    ):
        assert f'id="{obsolete_id}"' not in html
    for obsolete_projection in (
        "view.analyst_reports",
        "view.debates",
        "view.decisions",
        "view.execution_config",
    ):
        assert obsolete_projection not in javascript


def test_ui_exposes_each_first_party_result_section() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    required_section_ids = {
        "executive",
        "evidence",
        "analytics",
        "risks",
        "monitoring",
        "run-card",
        "records",
    }
    required_data_ids = {
        "recommendation",
        "executive-summary",
        "overview-metadata",
        "request-metadata",
        "request-objectives",
        "request-coverage",
        "documents",
        "claims",
        "arguments",
        "source-lineage",
        "metrics",
        "calculations",
        "valuations",
        "analytics-bundle",
        "risk-register",
        "counterevidence",
        "limitations",
        "monitoring-rules",
        "research-delta",
        "hypotheses",
        "iterations",
        "quality",
        "forecasts",
        "run-card-meta",
        "run-card-stages",
        "reports",
        "artifacts",
        "events",
        "actions",
    }

    for element_id in required_section_ids | required_data_ids:
        assert f'id="{element_id}"' in html


def test_ui_uses_safe_text_nodes_for_untrusted_nested_values() -> None:
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "element.textContent = String(content)" in javascript
    assert "innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript

    result = _run_js(
        r"""
        class Element {
          constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; this.className = ''; }
          append(...children) { this.children.push(...children); }
        }
        global.document = {createElement: (tag) => new Element(tag), querySelector: () => null};
        const ui = require('./src/stock_research_agents/web/app.js');
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


def test_public_source_links_fail_closed_for_nonpublic_or_credentialed_hosts() -> None:
    result = _run_js(
        r"""
        class Element {
          constructor(tag) { this.tag = tag; this.textContent = ''; this.className = ''; }
        }
        global.document = {createElement: (tag) => new Element(tag), querySelector: () => null};
        const ui = require('./src/stock_research_agents/web/app.js');
        const publicLink = ui.publicSourceLink('https://www.sec.gov/Archives/example');
        const privateLink = ui.publicSourceLink('http://127.0.0.1/private');
        const credentialed = ui.publicSourceLink('https://user:secret@example.com/private');
        process.stdout.write(JSON.stringify({
          publicText: publicLink.textContent,
          publicHref: publicLink.href,
          privateText: privateLink.textContent,
          credentialedText: credentialed.textContent
        }));
        """
    )

    assert result["publicText"] == "www.sec.gov"
    assert result["publicHref"] == "https://www.sec.gov/Archives/example"
    assert "withheld" in str(result["privateText"]).lower()
    assert "withheld" in str(result["credentialedText"]).lower()


def test_ui_loads_only_the_canonical_completed_view() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    combined = f"{html}\n{javascript}"

    assert 'return "/api/runs/current/view"' in javascript
    assert "resolveViewEndpoint(window.location.search)" in javascript
    assert "/api/runs/current/events" not in javascript
    assert "/api/runs/current/result" not in javascript
    assert "ORCL" not in combined
    assert "AAPL" not in combined
    assert "fixture://" not in combined
    assert "No report loaded" in combined


def test_ui_resolves_saved_run_urls_without_falling_forward_to_current() -> None:
    result = _run_js(
        """
        const ui = require('./src/stock_research_agents/web/app.js');
        process.stdout.write(JSON.stringify({
          current: ui.resolveViewEndpoint(''),
          saved: ui.resolveViewEndpoint('?run=analytics-dc2616f0e2c2'),
          invalid: ui.resolveViewEndpoint('?run=../../current')
        }));
        """
    )

    assert result == {
        "current": "/api/runs/current/view",
        "saved": "/api/runs/analytics-dc2616f0e2c2/view",
        "invalid": None,
    }


def test_ui_guards_completed_results_and_formats_utc_timestamps() -> None:
    result = _run_js(
        """
        const ui = require('./src/stock_research_agents/web/app.js');
        process.stdout.write(JSON.stringify({
          completed: ui.isCompletedView({overview: {status: 'completed'}}),
          running: ui.isCompletedView({overview: {status: 'running'}}),
          absent: ui.isCompletedView({}),
          instant: ui.timestamp('2026-08-01T00:30:00Z'),
          invalid: ui.timestamp('not-a-date')
        }));
        """
    )

    assert result["completed"] is True
    assert result["running"] is False
    assert result["absent"] is False
    assert str(result["instant"]).endswith(" UTC")
    assert result["invalid"] == "not-a-date"


def test_ui_has_responsive_accessible_motion_and_focus_treatment() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    stylesheet = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'class="skip-link"' in html
    assert 'role="status" aria-live="polite"' in html
    assert "@media (max-width: 820px)" in stylesheet
    assert "@media (max-width: 540px)" in stylesheet
    assert "@media (prefers-reduced-motion: reduce)" in stylesheet
    assert ":focus-visible" in stylesheet
    assert "var(--paper-warm)" not in stylesheet
    assert "var(--serif)" not in stylesheet
