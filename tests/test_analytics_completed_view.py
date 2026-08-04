from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from company_analytics_fixtures import complete_v4_submission

from tradingagents_portable.company_analytics import build_company_analytics_draft
from tradingagents_portable.contracts import RunStatus
from tradingagents_portable.view import build_run_view

WEB = Path(__file__).resolve().parents[1] / "src" / "tradingagents_portable" / "web"


def test_completed_view_projects_sidecars_without_recalculating_them() -> None:
    draft = build_company_analytics_draft(complete_v4_submission("META"))
    view = build_run_view(draft.result, draft.events).to_dict()

    lab = view["research_lab"]
    assert lab["analytics"]["coverage_decision"] == "supported"
    assert lab["run_card"]["profile"] == "company-analytics.v1"
    assert lab["hypotheses"][0]["final_status"] == "proposed"
    assert lab["quality"]["schema_version"] == "research-quality.v1"
    assert lab["forecasts"][0]["forecast_kind"] == "binary_event"


def test_nonterminal_view_never_projects_completed_sidecars() -> None:
    draft = build_company_analytics_draft(complete_v4_submission("ORCL"))
    partial = replace(draft.result, status=RunStatus.RUNNING)
    lab = build_run_view(partial, draft.events[:-1]).to_dict()["research_lab"]

    assert all(value is None for value in lab.values())


def test_completed_v4_view_renders_representative_visible_values() -> None:
    draft = build_company_analytics_draft(complete_v4_submission("META"))
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
        get childElementCount() { return this.children.length; }
        set textContent(value) { this._text = String(value); this.children = []; }
        get textContent() {
          return this._text + this.children.map((child) =>
            child && typeof child === 'object' ? child.textContent : String(child)
          ).join('');
        }
      }

      const html = fs.readFileSync('./src/tradingagents_portable/web/index.html', 'utf8');
      const elements = new Map();
      for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set(match[1], new Element());
      global.document = {
        body: new Element('body'),
        createElement: (tag) => new Element(tag),
        querySelector: (selector) => selector.startsWith('#') ? elements.get(selector.slice(1)) || null : null
      };

      const view = JSON.parse(fs.readFileSync(0, 'utf8'));
      const ui = require('./src/tradingagents_portable/web/app.js');
      ui.render(view);
      const ids = [
        'portfolio-summary', 'evidence-provenance', 'analytics-summary', 'hypothesis-lab',
        'risk-unresolved', 'artifacts', 'source-explorer', 'source-analysis-summary',
        'source-analysis-verdict', 'source-analysis-totals', 'source-coverage-matrix',
        'source-analysis-gap-list', 'complete-research', 'research-lab'
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

    assert "Synthetic, point-in-time-safe research dossier for META." in rendered["portfolio-summary"]["text"]
    assert "META synthetic filing evidence" in rendered["evidence-provenance"]["text"]
    assert "supported" in rendered["analytics-summary"]["text"]
    assert "META has a supported constructive scenario." in rendered["hypothesis-lab"]["text"]
    assert "Licensed consensus unavailable" in rendered["risk-unresolved"]["text"]
    assert "Complete company research: META" in rendered["artifacts"]["text"]
    assert "Host entitlement was unavailable at the research cutoff." in rendered["source-explorer"]["text"]
    assert "retained documents include 5 canonical" in rendered["source-analysis-summary"]["text"]
    assert "Insufficient" in rendered["source-analysis-verdict"]["text"]
    assert "Declared publishers" in rendered["source-analysis-totals"]["text"]
    assert "Held / required" in rendered["source-coverage-matrix"]["text"]
    assert "cannot prove independence" in rendered["source-analysis-gap-list"]["text"]
    assert rendered["complete-research"]["hidden"] is False
    assert rendered["research-lab"]["hidden"] is False


def test_packaged_viewer_has_a_read_only_research_lab() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    javascript = (WEB / "app.js").read_text(encoding="utf-8")

    for element_id in (
        "research-lab",
        "run-card-ledger",
        "hypothesis-lab",
        "model-lab",
        "experiment-lab",
        "forecast-lab",
        "quality-lab",
        "policy-lab",
    ):
        assert f'id="{element_id}"' in html
    assert "function renderResearchLab(view)" in javascript
    assert "This page displays receipts; it does not recalculate them." in html
    assert "broker" not in html.lower().split('id="research-lab"', 1)[1].split("</section>", 1)[0]
