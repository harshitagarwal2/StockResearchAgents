from __future__ import annotations

import json
import subprocess
from pathlib import Path

from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import build_company_analytics_draft
from stock_research_agents.view import build_run_view

WEB = Path(__file__).resolve().parents[1] / "src" / "stock_research_agents" / "web"


def test_completed_view_projects_first_party_analytics_sections_without_recalculation() -> None:
    draft = build_company_analytics_draft(complete_analytics_submission("META"))
    view = build_run_view(draft.result, draft.events).to_dict()

    assert view["analytics"]["coverage_decision"] == "supported"
    assert view["source_lineage"]["schema_version"] == "source-lineage-crosswalk.v1"
    assert view["research_lab"]["run_card"]["profile"] == "company-analytics.v1"
    assert view["research_lab"]["hypotheses"][0]["final_status"] == "proposed"
    assert view["research_lab"]["quality"]["schema_version"] == "research-quality.v1"
    assert view["research_lab"]["forecasts"][0]["forecast_kind"] == "binary_event"

    for obsolete in ("analyst_reports", "debates", "decisions", "execution_config", "topology"):
        assert obsolete not in view


def test_completed_analytics_view_renders_representative_visible_values() -> None:
    draft = build_company_analytics_draft(complete_analytics_submission("META"))
    view = build_run_view(draft.result, draft.events).to_dict()
    script = r"""
      const fs = require('fs');

      class ClassList {
        constructor(element) { this.element = element; }
        add(...names) {
          const current = new Set(this.element.className.split(/\s+/).filter(Boolean));
          names.forEach((name) => current.add(name));
          this.element.className = Array.from(current).join(' ');
        }
      }

      class Element {
        constructor(tag = 'div') {
          this.tagName = tag.toUpperCase();
          this.children = [];
          this.className = '';
          this.dataset = {};
          this.hidden = false;
          this._text = '';
          this.classList = new ClassList(this);
        }
        append(...children) { this.children.push(...children); }
        replaceChildren(...children) { this.children = children; this._text = ''; }
        set textContent(value) { this._text = String(value); this.children = []; }
        get textContent() {
          return this._text + this.children.map((child) =>
            child && typeof child === 'object' ? child.textContent : String(child)
          ).join('');
        }
      }

      const html = fs.readFileSync('./src/stock_research_agents/web/index.html', 'utf8');
      const elements = new Map();
      for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set(match[1], new Element());
      global.document = {
        body: new Element('body'),
        createElement: (tag) => new Element(tag),
        querySelector: (selector) => selector.startsWith('#') ? elements.get(selector.slice(1)) || null : null
      };

      const view = JSON.parse(fs.readFileSync(0, 'utf8'));
      const ui = require('./src/stock_research_agents/web/app.js');
      ui.render(view);
      const ids = [
        'executive-summary', 'documents', 'claims', 'source-lineage', 'analytics-bundle',
        'risk-register', 'monitoring-rules', 'hypotheses', 'quality', 'forecasts',
        'run-card-stages', 'artifacts', 'report-shell'
      ];
      const rendered = Object.fromEntries(ids.map((id) => [id, {
        text: elements.get(id).textContent,
        hidden: elements.get(id).hidden
      }]));
      process.stdout.write(JSON.stringify(rendered));
    """

    completed = subprocess.run(  # noqa: S603 - fixed local Node executable and test-owned renderer
        ["node", "-e", script],
        cwd=WEB.parents[2],
        input=json.dumps(view),
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = json.loads(completed.stdout)

    assert "Synthetic, point-in-time-safe research dossier for META." in rendered["executive-summary"]["text"]
    assert "META synthetic filing evidence" in rendered["documents"]["text"]
    assert "META has a supported constructive scenario." in rendered["claims"]["text"]
    assert "meta-doc-filing" in rendered["source-lineage"]["text"]
    assert "supported" in rendered["analytics-bundle"]["text"]
    assert "Valuation compression" in rendered["risk-register"]["text"]
    assert "Monitor the selected valuation multiple." in rendered["monitoring-rules"]["text"]
    assert "META has a supported constructive scenario." in rendered["hypotheses"]["text"]
    assert "Analytics sidecars reproduced." in rendered["quality"]["text"]
    assert "binary_event" in rendered["forecasts"]["text"]
    assert "Research Plan" in rendered["run-card-stages"]["text"]
    assert "Completed research dossier: META" in rendered["artifacts"]["text"]
    assert rendered["report-shell"]["hidden"] is False


def test_packaged_viewer_has_a_read_only_analytics_lab() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    javascript = (WEB / "app.js").read_text(encoding="utf-8")

    for element_id in (
        "analytics",
        "analytics-bundle",
        "run-card",
        "run-card-stages",
        "hypotheses",
        "iterations",
        "forecasts",
        "quality",
    ):
        assert f'id="{element_id}"' in html
    assert "function renderAnalyticsBundle(analytics)" in javascript
    assert "function renderRunCard(runCard)" in javascript
    assert "This page displays them; it does not recompute them." in html
    assert "<form" not in html
