from __future__ import annotations

from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore
from stock_research_agents.view import build_run_view


def test_view_preserves_declared_documents_and_source_lineage_without_proxy_counts() -> None:
    result, events = submit_company_analytics(
        complete_analytics_submission("META"),
        store=RunStore(),
        quality_store=QualityStore(),
    )
    view = build_run_view(result, events).to_dict()

    assert view["research_dossier"]["documents"] == tuple(
        item.to_dict() for item in result.submission.company_research.dossier.documents
    )
    assert view["source_lineage"] == result.submission.source_lineage.to_dict()
    assert "source_analysis" not in view
    assert "intelligence" not in view


def test_view_keeps_blocked_entitlement_explicit() -> None:
    result, events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=RunStore(),
        quality_store=QualityStore(),
    )
    documents = build_run_view(result, events).to_dict()["research_dossier"]["documents"]
    blocked = [item for item in documents if item["entitlement"]["access"] == "entitlement_blocked"]

    assert blocked
    assert all(item["entitlement"]["redistributable"] is False for item in blocked)
