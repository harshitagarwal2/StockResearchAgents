from __future__ import annotations

import json
from threading import Thread
from urllib.request import urlopen

from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.reporting import build_report_artifacts
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore
from stock_research_agents.view import build_run_view
from stock_research_agents.viewer_server import create_viewer_server


def _completed(symbol: str = "ORCL"):
    return submit_company_analytics(
        complete_analytics_submission(symbol),
        store=RunStore(),
        quality_store=QualityStore(),
    )


def test_analytics_report_bundle_has_five_first_party_groups() -> None:
    result, _events = _completed()
    artifacts = build_report_artifacts(result)
    groups = [item for item in artifacts if item.kind == "report_group"]

    assert [item.id for item in groups] == [
        "report.1.executive-summary",
        "report.2.evidence-and-claims",
        "report.3.analytics-and-valuation",
        "report.4.risks-and-counterevidence",
        "report.5.monitoring-and-quality",
    ]
    assert {item.id for item in artifacts} >= {
        "report.provenance",
        "report.complete",
        "data.company-analytics-result.v1",
        "data.run-events.v1",
    }


def test_run_view_projects_only_canonical_analytics_fields() -> None:
    result, events = _completed("META")
    view = build_run_view(result, events).to_dict()

    assert view["run_id"] == result.run_id
    assert view["overview"]["symbol"] == "META"
    assert view["research_dossier"] == result.submission.company_research.dossier.to_dict()
    assert view["analytics"] == result.submission.analytics_bundle.to_dict()
    assert view["research_lab"]["run_card"] == result.submission.run_card.to_dict()
    assert {"analyst_reports", "research_debate", "trader", "portfolio", "topology"}.isdisjoint(view)


def test_report_provenance_is_a_lossless_typed_projection() -> None:
    result, _events = _completed("QQQ")
    provenance = next(item for item in build_report_artifacts(result) if item.id == "report.provenance")

    assert provenance.content["documents"] == [
        document.to_dict() for document in result.submission.company_research.dossier.documents
    ]
    assert provenance.content["source_lineage"] == result.submission.source_lineage.to_dict()


def test_viewer_serves_analytics_view_and_current_alias() -> None:
    store = RunStore()
    result, _events = submit_company_analytics(
        complete_analytics_submission("ORCL"), store=store, quality_store=QualityStore()
    )
    server = create_viewer_server("127.0.0.1", 0, store=store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        for run_id in (result.run_id, "current"):
            with urlopen(f"http://{host}:{port}/api/runs/{run_id}/view", timeout=5) as response:  # noqa: S310
                payload = json.load(response)
            assert payload["view"]["run_id"] == result.run_id
            assert payload["view"]["overview"]["symbol"] == "ORCL"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
