from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from research_v3_fixtures import complete_v3_submission

from tradingagents_portable.company_research import submit_company_research
from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.fixture import run_fixture
from tradingagents_portable.store import RunStore
from tradingagents_portable.view import build_run_view


def _source_analysis(submission: dict[str, object]) -> dict[str, Any]:
    result, events = submit_company_research(submission, store=RunStore())
    return build_run_view(result, events).to_dict()["intelligence"]["source_analysis"]


def test_source_analysis_does_not_mistake_document_count_for_source_diversity() -> None:
    analysis = _source_analysis(complete_v3_submission("ORCL"))

    totals = analysis["totals"]
    concentration = analysis["concentration"]
    independence = analysis["independence"]

    assert totals["retained_document_record_count"] == 5
    assert totals["canonical_document_count"] == 5
    assert totals["accessible_document_count"] == 4
    assert totals["blocked_document_count"] == 1
    assert totals["access_unknown_document_count"] == 0
    assert totals["declared_publisher_count"] == 1
    assert totals["origin_host_count"] == 1
    assert totals["retrieval_provider_count"] == 0
    assert totals["undeclared_retrieval_provider_record_count"] == 5
    assert totals["unique_canonical_uri_count"] == 5
    assert concentration["status"] == "single_publisher"
    assert concentration["top_publisher_share"] == 1.0
    assert analysis["verdict"] == "insufficient"
    assert independence == {
        "status": "unsupported_by_v3_contract",
        "contract_support": False,
        "required_receipt": "versioned_source_portfolio_ownership_receipt",
        "declared_group_count": 0,
        "declared_group_counts": {},
        "undeclared_record_count": 5,
    }
    assert any("cannot prove independence" in gap["finding"] for gap in analysis["gaps"])


def test_strict_v3_source_mix_does_not_substitute_publisher_for_retrieval_provider() -> None:
    result, events = submit_company_research(complete_v3_submission("META"), store=RunStore())
    intelligence = build_run_view(result, events).to_dict()["intelligence"]

    assert intelligence["source_mix"]["providers"] == {"undeclared": 5}
    assert intelligence["source_mix"]["provider_basis"] == "undeclared_by_strict_v3_dossier"
    assert intelligence["source_analysis"]["publisher_counts"] == {"Deterministic fixture publisher": 5}
    assert intelligence["source_analysis"]["retrieval_provider_counts"] == {}


def test_source_analysis_compares_accessible_documents_with_each_planned_dimension() -> None:
    analysis = _source_analysis(complete_v3_submission("META"))
    rows = {row["area"]: row for row in analysis["coverage_rows"]}

    assert rows["financials"] == {
        "area": "financials",
        "required": True,
        "retained_document_count": 1,
        "accessible_document_count": 1,
        "unique_accessible_source_count": 1,
        "planned_minimum": 1,
        "minimum_met": True,
        "publisher_diversity_count": 1,
        "origin_host_count": 1,
        "preferred_source_kinds": ["filing"],
        "present_source_kinds": ["filing"],
        "preferred_kind_met": True,
        "latest_usable_at": "2026-07-29T13:05:00Z",
        "reported_status": "complete",
        "verdict": "complete",
        "source_document_ids": ["meta-doc-filing"],
        "limitation": None,
    }
    assert rows["licensed_consensus"]["retained_document_count"] == 1
    assert rows["licensed_consensus"]["accessible_document_count"] == 0
    assert rows["licensed_consensus"]["unique_accessible_source_count"] == 0
    assert rows["licensed_consensus"]["minimum_met"] is False
    assert rows["licensed_consensus"]["reported_status"] == "entitlement_blocked"
    assert rows["licensed_consensus"]["verdict"] == "insufficient"


def test_source_analysis_calls_publisher_and_host_counts_proxies_not_independence() -> None:
    submission = complete_v3_submission("ORCL")
    dossier = submission["dossier"]
    assert isinstance(dossier, dict)
    documents = dossier["documents"]
    assert isinstance(documents, list)
    for ordinal, document in enumerate(documents, start=1):
        assert isinstance(document, dict)
        document["publisher"] = f"Declared publisher {ordinal}"

    analysis = _source_analysis(submission)

    assert analysis["totals"]["declared_publisher_count"] == 5
    assert analysis["totals"]["origin_host_count"] == 1
    assert analysis["concentration"]["status"] == "distributed"
    assert analysis["independence"]["status"] == "unsupported_by_v3_contract"
    assert analysis["claim_support"]["multiple_publisher_claim_count"] >= 1
    assert "not independence evidence" in analysis["claim_support"]["independence_note"]


def test_source_analysis_keeps_linked_reporting_separate_from_canonical_documents() -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    analysis = build_run_view(result, events).to_dict()["intelligence"]["source_analysis"]

    assert analysis["basis"]["documents"] == "run_evidence"
    assert analysis["totals"]["retained_document_record_count"] == 4
    assert analysis["totals"]["canonical_document_count"] == 0
    assert analysis["totals"]["unattributable_document_count"] == 4
    assert analysis["totals"]["accessible_document_count"] == 0
    assert analysis["totals"]["access_unknown_document_count"] == 4
    assert analysis["totals"]["linked_source_item_count"] == 3
    assert analysis["totals"]["opened_attributable_link_count"] == 0
    assert analysis["totals"]["discovery_only_link_count"] == 0
    assert analysis["totals"]["unverified_link_count"] == 3
    assert analysis["totals"]["linked_access_unknown_count"] == 3
    assert any(gap["area"] == "linked_reporting" for gap in analysis["gaps"])


def test_source_analysis_separates_one_discovery_provider_from_linked_publisher_origins() -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    evidence = list(result.evidence)
    news_index = next(index for index, item in enumerate(evidence) if item.category == "news")
    news = evidence[news_index]
    articles = [
        {
            "headline": "Publisher A report",
            "publisher": "Publisher A",
            "url": "https://news-a.example/report",
            "published_at": result.request.as_of_date,
            "source_quality": "reputable_journalism",
            "verification_status": "single_source_reported",
            "access": "public",
        },
        {
            "headline": "Publisher B report",
            "publisher": "Publisher B",
            "url": "https://news-b.example/report",
            "published_at": result.request.as_of_date,
            "source_quality": "reputable_journalism",
            "verification_status": "primary_confirmed",
            "access": "public",
        },
        {
            "headline": "Duplicate Publisher B link",
            "publisher": "Publisher B",
            "url": "https://news-b.example/report",
            "published_at": result.request.as_of_date,
            "source_quality": "aggregator_discovery",
            "verification_status": "discovery_only",
            "access": "public",
        },
    ]
    evidence[news_index] = replace(news, values={**news.values, "articles": articles})
    result = replace(result, evidence=tuple(evidence))

    analysis = build_run_view(result, events).to_dict()["intelligence"]["source_analysis"]

    assert analysis["totals"]["retrieval_provider_count"] == 1
    assert analysis["retrieval_provider_counts"] == {"portable-fixture": 4}
    assert analysis["totals"]["linked_source_item_count"] == 3
    assert analysis["totals"]["opened_attributable_link_count"] == 2
    assert analysis["totals"]["primary_confirmed_link_count"] == 1
    assert analysis["totals"]["single_source_reported_link_count"] == 1
    assert analysis["totals"]["discovery_only_link_count"] == 1
    assert analysis["totals"]["unverified_link_count"] == 0
    assert analysis["totals"]["duplicate_uri_count"] == 1
    assert analysis["totals"]["origin_host_count"] == 2
    assert analysis["publisher_counts"]["Publisher A"] == 1
    assert analysis["publisher_counts"]["Publisher B"] == 1
    assert "portable-fixture" not in analysis["publisher_counts"]


def test_source_analysis_deduplicates_hash_uri_bridge_chains_regardless_of_order() -> None:
    submission = complete_v3_submission("META")
    request = submission["request"]
    dossier = submission["dossier"]
    assert isinstance(request, dict)
    assert isinstance(dossier, dict)
    documents = dossier["documents"]
    claims = dossier["claims"]
    coverage = dossier["coverage"]
    research_plan = request["research_plan"]
    assert isinstance(documents, list)
    assert isinstance(claims, list)
    assert isinstance(coverage, list)
    assert isinstance(research_plan, dict)
    dimensions = research_plan["coverage_dimensions"]
    assert isinstance(dimensions, list)

    original = documents[0]
    assert isinstance(original, dict)
    original_locator = original["locator"]
    assert isinstance(original_locator, dict)
    bridge_uri = "https://fixtures.example.test/meta/filing-mirror"

    uri_match = deepcopy(original)
    assert isinstance(uri_match, dict)
    uri_match["id"] = "meta-doc-filing-uri-match"
    uri_match_locator = uri_match["locator"]
    assert isinstance(uri_match_locator, dict)
    uri_match_locator["document_id"] = uri_match["id"]
    uri_match_locator["canonical_uri"] = bridge_uri
    uri_match_locator["content_sha256"] = "b" * 64

    bridge = deepcopy(original)
    assert isinstance(bridge, dict)
    bridge["id"] = "meta-doc-filing-bridge"
    bridge_locator = bridge["locator"]
    assert isinstance(bridge_locator, dict)
    bridge_locator["document_id"] = bridge["id"]
    bridge_locator["canonical_uri"] = bridge_uri
    bridge_locator["content_sha256"] = original_locator["content_sha256"]

    # The bridge is deliberately appended last: A=(H,U1), C=(G,U2), B=(H,U2).
    documents.extend((uri_match, bridge))
    financial_dimension = next(item for item in dimensions if item["area"] == "financials")
    financial_dimension["minimum_source_count"] = 2
    financial_coverage = next(item for item in coverage if item["area"] == "financials")
    financial_coverage["source_document_ids"].extend((uri_match["id"], bridge["id"]))
    claims[0]["evidence_document_ids"].extend((uri_match["id"], bridge["id"]))

    analysis = _source_analysis(submission)
    financials = next(row for row in analysis["coverage_rows"] if row["area"] == "financials")

    assert financials["retained_document_count"] == 3
    assert financials["accessible_document_count"] == 3
    assert financials["unique_accessible_source_count"] == 1
    assert financials["minimum_met"] is False
    assert financials["verdict"] == "insufficient"
    assert analysis["coverage_verdict"] == "insufficient"
    assert analysis["claim_support"]["claims_with_duplicate_support_references"] >= 1
    assert {item["field"] for item in analysis["source_metadata_conflicts"]} >= {
        "canonical_uri",
        "content_sha256",
    }


def test_duplicate_url_merges_later_publisher_and_counts_all_retrieval_providers() -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    evidence = list(result.evidence)
    news_index = next(index for index, item in enumerate(evidence) if item.category == "news")
    news = evidence[news_index]
    shared_url = "https://publisher.example/report"
    evidence[news_index] = replace(
        news,
        values={
            **news.values,
            "articles": [
                {
                    "headline": "Discovery record",
                    "url": shared_url,
                    "published_at": result.request.as_of_date,
                    "source_quality": "aggregator_discovery",
                    "verification_status": "discovery_only",
                    "access": "public",
                    "discovery_provider": "provider-a",
                },
                {
                    "headline": "Opened publisher record",
                    "publisher": "Publisher",
                    "url": shared_url,
                    "published_at": result.request.as_of_date,
                    "source_quality": "reputable_journalism",
                    "verification_status": "primary_confirmed",
                    "access": "public",
                    "retrieval_provider": "provider-b",
                },
            ],
        },
    )
    result = replace(result, evidence=tuple(evidence))

    analysis = build_run_view(result, events).to_dict()["intelligence"]["source_analysis"]

    assert analysis["totals"]["unique_traceable_source_count"] == 1
    assert analysis["publisher_counts"] == {"Publisher": 1}
    assert analysis["retrieval_provider_counts"] == {
        "portable-fixture": 4,
        "provider-a": 1,
        "provider-b": 1,
    }
    assert analysis["totals"]["retrieval_provider_count"] == 3
    assert analysis["totals"]["opened_attributable_link_count"] == 1
    assert analysis["totals"]["source_metadata_conflict_count"] == 1
    assert analysis["source_metadata_conflicts"][0]["field"] == "title"


def test_merged_source_freshness_and_conflicts_are_input_order_independent() -> None:
    submission = complete_v3_submission("META")
    dossier = submission["dossier"]
    assert isinstance(dossier, dict)
    documents = dossier["documents"]
    coverage = dossier["coverage"]
    assert isinstance(documents, list)
    assert isinstance(coverage, list)
    original = documents[0]
    assert isinstance(original, dict)

    later_observation = deepcopy(original)
    assert isinstance(later_observation, dict)
    later_observation["id"] = "meta-doc-filing-later-observation"
    locator = later_observation["locator"]
    temporal = later_observation["temporal"]
    assert isinstance(locator, dict)
    assert isinstance(temporal, dict)
    locator["document_id"] = later_observation["id"]
    locator["canonical_uri"] = "https://fixtures.example.test/meta/Filing"
    temporal.update(
        {
            "observed_at": "2026-07-30T12:00:00Z",
            "published_at": "2026-07-30T13:00:00Z",
            "available_at": "2026-07-30T13:05:00Z",
            "retrieved_at": "2026-07-31T10:00:00Z",
        }
    )
    documents.append(later_observation)
    financial_coverage = next(item for item in coverage if item["area"] == "financials")
    financial_coverage["source_document_ids"].append(later_observation["id"])

    forward = _source_analysis(submission)
    reversed_submission = deepcopy(submission)
    reversed_dossier = reversed_submission["dossier"]
    assert isinstance(reversed_dossier, dict)
    reversed_documents = reversed_dossier["documents"]
    reversed_coverage = reversed_dossier["coverage"]
    assert isinstance(reversed_documents, list)
    assert isinstance(reversed_coverage, list)
    reversed_documents.reverse()
    reversed_financial_coverage = next(item for item in reversed_coverage if item["area"] == "financials")
    reversed_financial_coverage["source_document_ids"].reverse()
    backward = _source_analysis(reversed_submission)

    forward_financials = next(row for row in forward["coverage_rows"] if row["area"] == "financials")
    backward_financials = next(row for row in backward["coverage_rows"] if row["area"] == "financials")
    assert forward_financials["latest_usable_at"] == "2026-07-30T13:05:00Z"
    assert backward_financials["latest_usable_at"] == forward_financials["latest_usable_at"]
    assert backward["source_metadata_conflicts"] == forward["source_metadata_conflicts"]
    assert {item["field"] for item in forward["source_metadata_conflicts"]} >= {
        "available_at",
        "canonical_uri",
        "published_at",
        "retrieved_at",
    }


def test_blocked_primary_confirmed_link_does_not_become_opened_or_attributable() -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    evidence = list(result.evidence)
    news_index = next(index for index, item in enumerate(evidence) if item.category == "news")
    news = evidence[news_index]
    evidence[news_index] = replace(
        news,
        values={
            **news.values,
            "articles": [
                {
                    "headline": "Blocked publisher report",
                    "publisher": "Publisher A",
                    "url": "https://news-a.example/blocked-report",
                    "published_at": result.request.as_of_date,
                    "source_quality": "reputable_journalism",
                    "verification_status": "primary_confirmed",
                    "access": "entitlement_blocked",
                },
                {
                    "headline": "Public discovery record for the same URL",
                    "publisher": "Publisher A",
                    "url": "https://news-a.example/blocked-report",
                    "published_at": result.request.as_of_date,
                    "source_quality": "aggregator_discovery",
                    "verification_status": "discovery_only",
                    "access": "public",
                },
            ],
        },
    )
    result = replace(result, evidence=tuple(evidence))

    analysis = build_run_view(result, events).to_dict()["intelligence"]["source_analysis"]

    assert analysis["totals"]["primary_confirmed_link_count"] == 1
    assert analysis["totals"]["linked_blocked_count"] == 1
    assert analysis["totals"]["linked_accessible_count"] == 1
    assert analysis["totals"]["opened_attributable_link_count"] == 0
    assert any(item["field"] == "access" for item in analysis["source_metadata_conflicts"])
    assert any(gap["area"] == "linked_reporting" for gap in analysis["gaps"])
