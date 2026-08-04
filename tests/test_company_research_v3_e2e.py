from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
from research_v3_fixtures import complete_v3_submission

from tradingagents_portable.contracts import Artifact, RunRequest
from tradingagents_portable.fixture import run_fixture
from tradingagents_portable.research_conformance import validate_research_dossier as audit_research_dossier
from tradingagents_portable.research_contracts import (
    ResearchDossierV3,
    parse_host_submission_v3,
    parse_research_dossier,
    serialize_research_dossier,
)
from tradingagents_portable.store import RunStore
from tradingagents_portable.view import build_run_view


@pytest.mark.parametrize("symbol", ["ORCL", "META", "QQQ"])
def test_complete_submission_parses_for_each_supported_identity(symbol: str) -> None:
    submission = complete_v3_submission(symbol)

    parsed = parse_host_submission_v3(submission)

    assert parsed.request.identity.symbol == symbol
    assert parsed.dossier.identity == parsed.request.identity
    assert parsed.dossier.status == "completed"


@pytest.mark.parametrize("symbol", ["ORCL", "META", "QQQ"])
def test_dossier_roundtrip_preserves_canonical_payload(symbol: str) -> None:
    dossier = parse_research_dossier(complete_v3_submission(symbol)["dossier"])

    reparsed = ResearchDossierV3.from_json(serialize_research_dossier(dossier))

    assert reparsed == dossier
    assert reparsed.digest() == dossier.digest()


def test_fixture_document_hashes_cover_the_retained_synthetic_content() -> None:
    dossier = complete_v3_submission("ORCL")["dossier"]
    for document in dossier["documents"]:
        retained = json.dumps(
            {
                "extract": document["extract"],
                "kind": document["kind"],
                "publisher": document["publisher"],
                "title": document["title"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert document["locator"]["content_sha256"] == sha256(retained.encode()).hexdigest()


@pytest.mark.parametrize("symbol", ["ORCL", "META", "QQQ"])
def test_complete_submission_passes_semantic_research_audit(symbol: str) -> None:
    dossier = complete_v3_submission(symbol)["dossier"]

    report = audit_research_dossier(dossier)

    assert report.passed, report.to_dict()


def test_document_unavailable_at_cutoff_is_rejected() -> None:
    submission = complete_v3_submission("ORCL")
    submission["dossier"]["documents"][0]["temporal"]["available_at"] = "2026-08-01T00:00:00Z"

    with pytest.raises(ValueError, match="available by cutoff"):
        parse_host_submission_v3(submission)


def test_filing_after_cutoff_is_rejected() -> None:
    submission = complete_v3_submission("META")
    submission["dossier"]["filings"][0]["filed_at"] = "2026-08-01T00:00:00Z"

    with pytest.raises(ValueError, match="filing .* unavailable at the research cutoff"):
        parse_host_submission_v3(submission)


def test_broken_claim_source_link_is_rejected() -> None:
    submission = complete_v3_submission("ORCL")
    submission["dossier"]["claims"][0]["evidence_document_ids"] = ["missing-document"]

    with pytest.raises(ValueError, match="references unknown documents"):
        parse_host_submission_v3(submission)


def test_tampered_calculation_result_fails_deterministic_recomputation() -> None:
    dossier = complete_v3_submission("META")["dossier"]
    dossier["calculations"][0]["result"] += 1.0

    report = audit_research_dossier(dossier)

    assert any(issue.check == "reproducibility" and issue.path.endswith(".result") for issue in report.issues)


def test_tampered_valuation_fails_calculation_link_recomputation() -> None:
    dossier = complete_v3_submission("ORCL")["dossier"]
    dossier["valuations"][0]["fair_value"] += 10.0

    report = audit_research_dossier(dossier)

    assert any(issue.check == "reproducibility" and issue.path.endswith(".fair_value") for issue in report.issues)


def test_debate_turn_with_unknown_claim_is_rejected() -> None:
    submission = complete_v3_submission("META")
    submission["dossier"]["arguments"][1]["claim_ids"] = ["missing-claim"]

    with pytest.raises(ValueError, match="argument .* references unknown claims"):
        parse_host_submission_v3(submission)


def test_semantic_audit_rejects_ungrounded_canonical_argument() -> None:
    dossier = complete_v3_submission("ORCL")["dossier"]
    dossier["arguments"][0]["claim_ids"] = []

    report = audit_research_dossier(dossier)

    assert any(issue.check == "debate_grounding" for issue in report.issues)


def test_research_delta_links_to_current_artifacts_and_prior_digest() -> None:
    dossier = parse_research_dossier(complete_v3_submission("ORCL")["dossier"])

    assert dossier.research_delta is not None
    assert dossier.research_delta.previous_dossier_sha256 == "a" * 64
    assert dossier.research_delta.added_document_ids[0] in {item.id for item in dossier.documents}
    assert dossier.research_delta.changed_claim_ids[0] in {item.id for item in dossier.claims}
    assert dossier.research_delta.changed_valuation_ids[0] in {item.id for item in dossier.valuations}


def test_research_delta_with_unknown_valuation_is_rejected() -> None:
    submission = complete_v3_submission("META")
    submission["dossier"]["research_delta"]["changed_valuation_ids"] = ["missing-valuation"]

    with pytest.raises(ValueError, match="research_delta references unknown valuations"):
        parse_host_submission_v3(submission)


def test_entitlement_gap_is_retained_without_licensed_extract_or_false_completeness() -> None:
    dossier = parse_research_dossier(complete_v3_submission("QQQ")["dossier"])
    blocked_coverage = next(item for item in dossier.coverage if item.area == "licensed_consensus")
    blocked_document = next(item for item in dossier.documents if item.id in blocked_coverage.source_document_ids)

    assert blocked_coverage.status == "entitlement_blocked"
    assert blocked_coverage.limitation
    assert blocked_document.entitlement.access == "entitlement_blocked"
    assert blocked_document.extract is None


def test_incomplete_coverage_without_limitation_is_rejected() -> None:
    submission = complete_v3_submission("ORCL")
    submission["dossier"]["coverage"][-1]["limitation"] = None

    with pytest.raises(ValueError, match="non-complete coverage requires an explicit limitation"):
        parse_host_submission_v3(submission)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("api_key", "fixture-secret", "credential material is forbidden"),
        ("raw_transcript", "bulk source payload", "raw source content is forbidden"),
        ("order", {"side": "buy", "quantity": 100}, "execution material is forbidden"),
    ],
)
def test_forbidden_boundary_material_is_rejected(field: str, value: object, message: str) -> None:
    submission = complete_v3_submission("META")
    submission["dossier"][field] = value

    with pytest.raises(ValueError, match=message):
        parse_host_submission_v3(submission)


def test_completed_dossier_is_projected_losslessly_into_run_view() -> None:
    result, events = run_fixture(RunRequest(symbol="ORCL"), RunStore())
    dossier = complete_v3_submission("ORCL")["dossier"]
    completed = replace(
        result,
        artifacts=result.artifacts
        + (
            Artifact(
                id="research_dossier.v3",
                kind="research_dossier.v3",
                title="Completed research dossier",
                content=deepcopy(dossier),
            ),
        ),
    )

    view = build_run_view(completed, events).to_dict()

    assert view["research_dossier"] == dossier


def test_cross_symbol_submissions_do_not_share_identity_or_research_ids() -> None:
    submissions = [complete_v3_submission(symbol) for symbol in ("ORCL", "META", "QQQ")]
    dossiers = [parse_host_submission_v3(item).dossier for item in submissions]

    assert {item.identity.instrument_id for item in dossiers} == {
        "equity:US68389X1054",
        "equity:US30303M1027",
        "fund:US46090E1038",
    }
    assert len({item.digest() for item in dossiers}) == 3
    assert all(
        left.documents[0].id != right.documents[0].id for left, right in zip(dossiers, dossiers[1:], strict=False)
    )


def test_fund_identity_can_report_transcripts_as_not_applicable_by_omission() -> None:
    dossier = parse_host_submission_v3(complete_v3_submission("QQQ")).dossier

    assert dossier.identity.asset_type == "fund"
    assert dossier.transcripts == ()
    assert dossier.filings
    assert dossier.peers[0].peer_instrument_id.startswith("fund:")
