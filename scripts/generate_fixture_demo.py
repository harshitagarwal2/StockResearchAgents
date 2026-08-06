#!/usr/bin/env python3
# ruff: noqa: E501 - embedded SVG lines intentionally mirror the generated artifact
"""Generate the committed, visibly fixture-labeled ORCL product demonstration."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from company_analytics_fixtures import complete_analytics_submission  # noqa: E402

from stock_research_agents.company_analytics import build_company_analytics_draft  # noqa: E402
from stock_research_agents.view import build_run_view  # noqa: E402

_FILES = ("events.json", "preview.svg", "result.json", "view.json")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _svg(view: dict[str, object]) -> bytes:
    overview = view["overview"]
    dossier = view["research_dossier"]
    lab = view["research_lab"]
    events = view["events"]
    assert isinstance(overview, dict)
    assert isinstance(dossier, dict)
    assert isinstance(lab, dict)
    assert isinstance(events, list)
    documents = dossier["documents"]
    forecasts = lab["forecasts"]
    run_card = lab["run_card"]
    assert isinstance(documents, list | tuple)
    assert isinstance(forecasts, list | tuple)
    assert isinstance(run_card, dict)
    stages = run_card["stages"]
    assert isinstance(stages, list | tuple)
    recommendation = str(overview["recommendation"])
    recommendation_lines = textwrap.wrap(recommendation, width=74)[:2] or ["No recommendation supplied."]
    recommendation_svg = "".join(
        f'<text x="84" y="{356 + index * 28}" class="body">{escape(line)}</text>'
        for index, line in enumerate(recommendation_lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675" role="img" aria-labelledby="title description">
  <title id="title">Fixture Research Dossier Viewer preview for {escape(str(overview["symbol"]))}</title>
  <desc id="description">A deterministic, non-executable fixture preview generated from the typed completed view.</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#08111f"/><stop offset="1" stop-color="#14233a"/></linearGradient>
    <style>
      .label {{ font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: 1px; fill: #8dd5ff; }}
      .title {{ font: 700 40px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #f6f9ff; }}
      .subtitle {{ font: 500 18px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #b8c6dc; }}
      .metric {{ font: 700 30px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #f6f9ff; }}
      .caption {{ font: 500 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #92a5c2; }}
      .body {{ font: 500 18px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #dce6f7; }}
    </style>
  </defs>
  <rect width="1200" height="675" rx="28" fill="url(#background)"/>
  <rect x="52" y="46" width="1096" height="583" rx="22" fill="#0d192a" stroke="#294363"/>
  <text x="84" y="91" class="label">STOCKRESEARCHAGENTS · RESEARCH DOSSIER VIEWER</text>
  <rect x="84" y="116" width="128" height="34" rx="17" fill="#173f55"/><text x="105" y="139" class="label">FIXTURE DATA</text>
  <rect x="226" y="116" width="330" height="34" rx="17" fill="#4d2e2a"/><text x="246" y="139" class="label">NON-EXECUTABLE ANALYTICAL SCENARIO</text>
  <text x="84" y="213" class="title">{escape(str(overview["symbol"]))} · {escape(str(overview["issuer_name"]))}</text>
  <text x="84" y="250" class="subtitle">Completed at {escape(str(overview["as_of_at"]))} · Coverage {escape(str(overview["coverage_decision"]))}</text>
  <g transform="translate(84 282)">
    <rect width="226" height="92" rx="14" fill="#13243a"/><text x="22" y="42" class="metric">{len(stages)}</text><text x="22" y="69" class="caption">validated lifecycle stages</text>
    <rect x="244" width="226" height="92" rx="14" fill="#13243a"/><text x="266" y="42" class="metric">{len(documents)}</text><text x="266" y="69" class="caption">attributed source documents</text>
    <rect x="488" width="226" height="92" rx="14" fill="#13243a"/><text x="510" y="42" class="metric">{len(forecasts)}</text><text x="510" y="69" class="caption">typed forecasts</text>
    <rect x="732" width="226" height="92" rx="14" fill="#13243a"/><text x="754" y="42" class="metric">{len(events)}</text><text x="754" y="69" class="caption">ordered lifecycle events</text>
  </g>
  <text x="84" y="427" class="label">FIXTURE RECOMMENDATION</text>
  {recommendation_svg}
  <line x1="84" y1="512" x2="1116" y2="512" stroke="#294363"/>
  <text x="84" y="553" class="caption">Generated from company-analytics-view.v1 · browser code performs projection only</text>
  <text x="84" y="584" class="caption">Synthetic fixture values are not current market research, investment advice, or an executable trade.</text>
</svg>
"""
    return svg.encode()


def generate(output_dir: Path) -> None:
    draft = build_company_analytics_draft(complete_analytics_submission("ORCL"))
    view = build_run_view(draft.result, draft.events).to_dict()
    payloads = {
        "events.json": _json_bytes([event.to_dict() for event in draft.events]),
        "preview.svg": _svg(view),
        "result.json": _json_bytes(draft.result.to_dict()),
        "view.json": _json_bytes(view),
    }
    output_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    for name, content in payloads.items():
        (output_dir / name).write_bytes(content)
    manifest = {
        "schema_version": "stockresearchagents-fixture-demo.v1",
        "fixture": True,
        "non_executable": True,
        "run_id": draft.result.run_id,
        "files": sorted(_FILES),
        "sha256": {name: hashlib.sha256(payloads[name]).hexdigest() for name in sorted(payloads)},
    }
    (output_dir / "manifest.json").write_bytes(_json_bytes(manifest))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "examples" / "generated" / "orcl-fixture",
    )
    arguments = parser.parse_args()
    generate(arguments.output_dir)
    print(f"Generated deterministic fixture demo at {arguments.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
