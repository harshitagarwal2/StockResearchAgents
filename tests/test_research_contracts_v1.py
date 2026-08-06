from __future__ import annotations

import json
from copy import deepcopy

import pytest

from stock_research_agents.research_contracts import (
    COMPANY_RESEARCH_SUBMISSION_V1_SCHEMA_PATH,
    CompanyResearchSubmissionV1,
    parse_company_research_submission_v1,
    serialize_research_dossier,
    validate_research_dossier,
)


def _identity() -> dict[str, object]:
    return {
        "instrument_id": "instrument.acme",
        "symbol": "ACME",
        "issuer_name": "Acme Corporation",
        "asset_type": "equity",
        "exchange": "XNYS",
        "currency": "USD",
        "country": "US",
        "cik": "0000000001",
    }


def _document(document_id: str, kind: str, available_at: str = "2026-07-31T14:00:00Z") -> dict[str, object]:
    return {
        "id": document_id,
        "kind": kind,
        "title": f"Source {document_id}",
        "publisher": "Acme Corporation",
        "locator": {
            "canonical_uri": f"https://example.com/{document_id}",
            "document_id": document_id,
            "accession_number": "0000000001-26-000001" if kind == "filing" else None,
            "content_sha256": "a" * 64,
        },
        "entitlement": {"access": "public", "redistributable": True, "terms_uri": None, "limitation": None},
        "temporal": {
            "observed_at": "2026-06-30T20:00:00Z",
            "published_at": "2026-07-31T13:00:00Z",
            "available_at": available_at,
            "retrieved_at": "2026-08-03T17:00:00Z",
            "cutoff_at": "2026-08-01T00:00:00Z",
        },
        "extract": "A bounded retained extract.",
    }


def valid_submission() -> dict[str, object]:
    identity = _identity()
    portfolio = {
        "objective": "Long-term capital appreciation",
        "horizon": "five years",
        "risk_tolerance": "moderate",
        "sector_exposure_percent": 12.0,
        "issuer_exposure_percent": 2.0,
        "constraints": ["research only"],
        "non_executable": True,
    }
    plan = {
        "objectives": [
            {
                "id": "objective.quality",
                "question": "Is operating quality durable?",
                "decision_relevance": "Determines the rating and valuation range.",
                "required_claim_kinds": ["fact", "thesis"],
            }
        ],
        "coverage_dimensions": [
            {
                "area": "fundamentals",
                "required": True,
                "minimum_source_count": 1,
                "preferred_source_kinds": ["filing", "transcript"],
                "entitlement_policy": "public_only",
            }
        ],
        "history_windows": [
            {
                "area": "fundamentals",
                "start_at": "2021-08-01T00:00:00Z",
                "end_at": "2026-08-01T00:00:00Z",
                "minimum_periods": 5,
                "expansion_reasons": ["Cover a meaningful operating cycle."],
                "latest_data_checks": ["Check the latest filing available by cutoff."],
                "stop_conditions": ["Older evidence no longer changes a material conclusion."],
            }
        ],
        "latest_data_checks": ["Verify current guidance and amendments."],
        "stop_conditions": ["All required coverage has an explicit terminal status."],
    }
    dossier = {
        "schema_version": "company-research.v1",
        "dossier_id": "dossier.acme.20260801",
        "status": "completed",
        "as_of_at": "2026-08-01T00:00:00Z",
        "completed_at": "2026-08-03T18:00:00Z",
        "identity": identity,
        "documents": [_document("doc.filing", "filing"), _document("doc.transcript", "transcript")],
        "calculations": [
            {
                "id": "calc.revenue.copy",
                "formula": "reported revenue",
                "operation": "identity",
                "input_metric_ids": ["metric.revenue"],
                "constants": [],
                "result": 10.0,
                "unit": "USDm",
                "engine": "portable-arithmetic-v1",
                "rounding_digits": 2,
                "tolerance": 0.0001,
                "deterministic": True,
            }
        ],
        "metrics": [
            {
                "id": "metric.revenue",
                "label": "Revenue",
                "value": 10.0,
                "unit": "USDm",
                "period_start": "2026-04-01T00:00:00Z",
                "period_end": "2026-06-30T23:59:59Z",
                "as_of_at": "2026-07-31T14:00:00Z",
                "basis": "reported",
                "source_document_ids": ["doc.filing"],
                "calculation_id": None,
            },
            {
                "id": "metric.revenue.verified",
                "label": "Verified revenue",
                "value": 10.0,
                "unit": "USDm",
                "period_start": "2026-04-01T00:00:00Z",
                "period_end": "2026-06-30T23:59:59Z",
                "as_of_at": "2026-07-31T14:00:00Z",
                "basis": "calculated",
                "source_document_ids": ["doc.filing"],
                "calculation_id": "calc.revenue.copy",
            },
        ],
        "claims": [
            {
                "id": "claim.quality",
                "statement": "Reported revenue supports the operating-quality thesis.",
                "kind": "thesis",
                "stance": "bull",
                "evidence_document_ids": ["doc.filing"],
                "metric_ids": ["metric.revenue"],
                "counterevidence_document_ids": ["doc.transcript"],
                "counterclaim_ids": ["claim.caution"],
                "confidence": 0.7,
            },
            {
                "id": "claim.caution",
                "statement": "Management commentary identifies execution uncertainty.",
                "kind": "guidance",
                "stance": "bear",
                "evidence_document_ids": ["doc.transcript"],
                "metric_ids": [],
                "counterevidence_document_ids": ["doc.filing"],
                "counterclaim_ids": ["claim.quality"],
                "confidence": 0.6,
            },
        ],
        "arguments": [
            {
                "argument_id": "argument.bull.1",
                "debate": "research",
                "round": 1,
                "turn": 1,
                "role": "bull",
                "claim_ids": ["claim.quality"],
                "assumption_ids": ["claim.quality"],
                "rebuttal_of": None,
                "concessions": ["Execution remains uncertain."],
                "unresolved": ["Durability requires another period."],
            },
            {
                "argument_id": "argument.bear.1",
                "debate": "research",
                "round": 1,
                "turn": 2,
                "role": "bear",
                "claim_ids": ["claim.caution"],
                "assumption_ids": [],
                "rebuttal_of": "argument.bull.1",
                "concessions": [],
                "unresolved": ["Magnitude is unknown."],
            },
        ],
        "filings": [
            {
                "id": "filing.10q",
                "form": "10-Q",
                "accession_number": "0000000001-26-000001",
                "filed_at": "2026-07-31T13:00:00Z",
                "period_end": "2026-06-30T23:59:59Z",
                "document_id": "doc.filing",
                "amendment": False,
            }
        ],
        "filing_changes": [
            {
                "id": "filing_change.current",
                "prior_document_id": None,
                "current_document_id": "doc.filing",
                "change_kind": "mda",
                "summary": "Current-period MD&A emphasizes operating durability.",
                "metric_ids": ["metric.revenue"],
                "claim_ids": ["claim.quality"],
            }
        ],
        "transcripts": [
            {
                "id": "transcript.q2",
                "event_at": "2026-07-31T13:00:00Z",
                "document_id": "doc.transcript",
                "speaker_summary": "Management and analysts discussed execution.",
                "guidance_claim_ids": ["claim.caution"],
                "segments": [
                    {
                        "id": "segment.qa.1",
                        "section": "qa",
                        "speaker": "CEO",
                        "extract": "Execution remains a focus.",
                        "claim_ids": ["claim.caution"],
                    }
                ],
                "themes": [
                    {
                        "id": "theme.execution",
                        "title": "Execution",
                        "segment_ids": ["segment.qa.1"],
                        "claim_ids": ["claim.caution"],
                    }
                ],
            }
        ],
        "guidance": [
            {
                "id": "guidance.revenue",
                "metric": "Revenue",
                "period": "FY2027",
                "low": 40.0,
                "high": 44.0,
                "unit": "USDm",
                "status": "introduced",
                "claim_id": "claim.caution",
            }
        ],
        "peers": [
            {
                "id": "peer.example",
                "peer_instrument_id": "instrument.peer",
                "rationale": "Comparable model",
                "methodology": "Same industry and revenue model.",
                "metric_ids": ["metric.revenue"],
                "evidence_document_ids": ["doc.filing"],
            }
        ],
        "factors": [
            {
                "id": "factor.quality",
                "factor": "quality",
                "direction": "positive",
                "magnitude": "moderate",
                "value": 0.6,
                "unit": "score",
                "methodology": "Reported-metric factor mapping.",
                "methodology_version": "1.0",
                "as_of_at": "2026-08-01T00:00:00Z",
                "prior_snapshot_id": None,
                "delta": None,
                "history_document_ids": ["doc.filing"],
                "evidence_document_ids": ["doc.filing"],
            }
        ],
        "valuations": [
            {
                "id": "valuation.base",
                "name": "base",
                "methodology": "Verified revenue anchor",
                "currency": "USD",
                "fair_value": 10.0,
                "horizon": "12 months",
                "input_metric_ids": ["metric.revenue"],
                "calculation_ids": ["calc.revenue.copy"],
                "assumption_claim_ids": ["claim.quality"],
                "assumptions": [
                    {
                        "id": "assumption.revenue",
                        "label": "Revenue",
                        "value": 10.0,
                        "unit": "USDm",
                        "metric_ids": ["metric.revenue"],
                        "claim_ids": [],
                    }
                ],
                "sensitivity_cells": [
                    {
                        "id": "sensitivity.base",
                        "row_assumption_id": "assumption.revenue",
                        "column_assumption_id": "assumption.revenue",
                        "fair_value": 10.0,
                        "calculation_ids": ["calc.revenue.copy"],
                    }
                ],
            }
        ],
        "entities": [{"id": "entity.acme", "name": "Acme Corporation", "kind": "issuer"}],
        "events": [
            {
                "id": "event.earnings",
                "occurred_at": "2026-07-31T13:00:00Z",
                "title": "Quarterly results",
                "status": "historical",
                "evidence_document_ids": ["doc.filing"],
                "claim_ids": ["claim.quality"],
                "entity_ids": ["entity.acme"],
                "ripple_event_ids": [],
            }
        ],
        "risks": [
            {
                "id": "risk.execution",
                "name": "Execution",
                "probability": None,
                "impact": "unknown",
                "thesis": "Execution could weaken the thesis.",
                "evidence_document_ids": ["doc.transcript"],
                "claim_ids": ["claim.caution"],
                "trigger_metric_ids": ["metric.revenue"],
            }
        ],
        "monitoring": [
            {
                "id": "monitor.revenue",
                "description": "Monitor revenue",
                "cadence": "quarterly",
                "trigger": "Revenue declines",
                "consequence": "Revisit rating",
                "related_ids": ["metric.revenue", "claim.quality"],
            }
        ],
        "prior_outcomes": [
            {
                "id": "outcome.prior",
                "forecast_claim_id": "claim.quality",
                "forecast_at": "2026-01-01T00:00:00Z",
                "evaluated_at": "2026-07-31T14:00:00Z",
                "result": "partially_confirmed",
                "outcome_document_ids": ["doc.filing"],
                "calibration_score": 0.7,
                "notes": "Revenue matched the directional forecast.",
            }
        ],
        "evaluation": {
            "evaluator": "portable deterministic validator",
            "evaluator_provenance": "Local schema and invariant checks; no model arithmetic.",
            "rubric_version": "company-research.v1",
            "checks": [
                {
                    "id": "check.evidence",
                    "status": "pass",
                    "rubric": "Every decision claim resolves to retained evidence.",
                    "evaluator": "portable-validator",
                    "evaluated_at": "2026-08-03T17:00:00Z",
                    "document_ids": ["doc.filing", "doc.transcript"],
                    "claim_ids": ["claim.quality", "claim.caution"],
                    "calculation_ids": [],
                    "notes": "All references resolved.",
                },
                {
                    "id": "check.numerical",
                    "status": "pass",
                    "rubric": "Recomputed result is within declared tolerance.",
                    "evaluator": "portable-arithmetic-v1",
                    "evaluated_at": "2026-08-03T17:00:00Z",
                    "document_ids": [],
                    "claim_ids": [],
                    "calculation_ids": ["calc.revenue.copy"],
                    "notes": "Identity operation reproduced 10.0.",
                },
            ],
            "limitations": [],
        },
        "research_delta": {
            "previous_dossier_sha256": None,
            "added_document_ids": ["doc.filing", "doc.transcript"],
            "changed_claim_ids": ["claim.quality"],
            "changed_valuation_ids": ["valuation.base"],
            "summary": "Initial dossier.",
        },
        "portfolio_context": portfolio,
        "portfolio_impact": {
            "thesis": "A research-only hypothetical allocation would increase issuer exposure.",
            "issuer_exposure_delta_percent": 1.0,
            "sector_exposure_delta_percent": 1.0,
            "diversification_effect": "neutral",
            "risk_contribution": "similar",
            "metric_ids": ["metric.revenue"],
            "claim_ids": ["claim.quality"],
            "non_executable": True,
        },
        "coverage": [
            {
                "area": "fundamentals",
                "status": "complete",
                "source_document_ids": ["doc.filing", "doc.transcript"],
                "limitation": None,
            }
        ],
        "recommendation": "hold",
        "executive_summary": "Evidence supports a balanced research-only Hold rating.",
        "limitations": ["Synthetic test fixture."],
    }
    return {
        "schema_version": "company-research.v1",
        "workflow_id": "stockresearchagents.company-research.v1",
        "request": {
            "schema_version": "company-research.v1",
            "request_id": "request.acme.20260801",
            "requested_at": "2026-08-03T16:00:00Z",
            "cutoff_at": "2026-08-01T00:00:00Z",
            "research_mode": "fixture",
            "identity": identity,
            "research_plan": plan,
            "output_language": "English",
            "portfolio_context": portfolio,
            "non_executable": True,
        },
        "dossier": dossier,
    }


def test_research_submission_strict_round_trip_and_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    payload = valid_submission()
    schema = json.loads(COMPANY_RESEARCH_SUBMISSION_V1_SCHEMA_PATH.read_text())
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(payload)
    submission = parse_company_research_submission_v1(payload)
    assert isinstance(submission, CompanyResearchSubmissionV1)
    assert json.loads(serialize_research_dossier(submission.dossier)) == payload["dossier"]
    validate_research_dossier(submission.dossier, "2026-08-01T00:00:00Z")
    assert submission.dossier.arguments[1].rebuttal_of == "argument.bull.1"
    assert len(submission.dossier.digest()) == 64


def _research_schema_errors(payload: object) -> list[object]:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(COMPANY_RESEARCH_SUBMISSION_V1_SCHEMA_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    return list(validator.iter_errors(payload))


def test_research_rejects_blocked_redistributable_entitlement_in_parser_and_schema() -> None:
    payload = valid_submission()
    entitlement = payload["dossier"]["documents"][1]["entitlement"]  # type: ignore[index]
    entitlement.update(access="entitlement_blocked", redistributable=True, limitation="Access unavailable.")

    assert _research_schema_errors(payload)
    with pytest.raises(ValueError, match="blocked sources cannot be redistributable"):
        parse_company_research_submission_v1(payload)


def test_research_rejects_non_redistributable_document_extract_in_parser_and_schema() -> None:
    payload = valid_submission()
    entitlement = payload["dossier"]["documents"][1]["entitlement"]  # type: ignore[index]
    entitlement.update(access="licensed", redistributable=False, limitation="Reference only.")

    assert _research_schema_errors(payload)
    with pytest.raises(ValueError, match="non-redistributable documents cannot include extracts"):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize("access", ["licensed", "entitlement_blocked"])
def test_research_rejects_segment_extracts_from_restricted_transcript(access: str) -> None:
    payload = valid_submission()
    transcript_document = payload["dossier"]["documents"][1]  # type: ignore[index]
    transcript_document["entitlement"].update(  # type: ignore[union-attr]
        access=access, redistributable=False, limitation="Reference only."
    )
    transcript_document["extract"] = None  # type: ignore[index]
    payload["request"]["research_plan"]["coverage_dimensions"][0]["entitlement_policy"] = (  # type: ignore[index]
        "caller_entitled_allowed"
    )

    # Draft 2020-12 cannot resolve transcript.document_id into the separate documents array.
    assert not _research_schema_errors(payload)
    with pytest.raises(ValueError, match="cannot include segment extracts.*non-redistributable"):
        parse_company_research_submission_v1(payload)


def test_research_retains_restricted_transcript_provenance_without_body_text() -> None:
    payload = valid_submission()
    transcript_document = payload["dossier"]["documents"][1]  # type: ignore[index]
    transcript_document["entitlement"].update(  # type: ignore[union-attr]
        access="licensed", redistributable=False, limitation="Reference only."
    )
    transcript_document["extract"] = None  # type: ignore[index]
    transcript = payload["dossier"]["transcripts"][0]  # type: ignore[index]
    transcript["segments"] = []  # type: ignore[index]
    transcript["themes"] = []  # type: ignore[index]
    payload["request"]["research_plan"]["coverage_dimensions"][0]["entitlement_policy"] = (  # type: ignore[index]
        "caller_entitled_allowed"
    )

    parsed = parse_company_research_submission_v1(payload)

    assert parsed.dossier.documents[1].locator.canonical_uri == "https://example.com/doc.transcript"
    assert parsed.dossier.documents[1].extract is None
    assert parsed.dossier.transcripts[0].document_id == "doc.transcript"
    assert parsed.dossier.transcripts[0].segments == ()


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("api_key", "credential material"),
        ("order_payload", "execution material"),
        ("raw_transcript", "raw source content"),
    ],
)
def test_research_rejects_forbidden_material_recursively(field: str, message: str) -> None:
    payload = valid_submission()
    payload["dossier"]["documents"][0][field] = "forbidden"  # type: ignore[index]
    with pytest.raises(ValueError, match=message):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/source?access_token=sensitive123",
        "https://example.com/source?client-secret=sensitive123",
        "https://example.com/source#refresh_token=sensitive123",
        "https://example.com/source?X-Amz-Credential=temporary",
        "https://example.com/source?X-Amz-Signature=sensitive123",
        "https://example.com/source?X-Goog-Credential=temporary",
        "https://example.com/source?sig=sensitive123",
        "https://example.com/source?AWSAccessKeyId=sensitive123",
    ],
)
def test_research_rejects_credential_shaped_uri_parameters(uri: str) -> None:
    payload = valid_submission()
    payload["dossier"]["documents"][0]["locator"]["canonical_uri"] = uri

    with pytest.raises(ValueError, match="credential-shaped query parameters"):
        parse_company_research_submission_v1(payload)


def test_runtime_enforces_research_plan_collection_bounds_advertised_by_schema() -> None:
    payload = valid_submission()
    objective = payload["request"]["research_plan"]["objectives"][0]
    payload["request"]["research_plan"]["objectives"] = [
        {**objective, "id": f"objective-{index}"} for index in range(65)
    ]

    with pytest.raises(ValueError, match="research_plan.objectives exceeds the 64-item bound"):
        parse_company_research_submission_v1(payload)


def test_completed_coverage_must_satisfy_planned_minimum_source_count() -> None:
    payload = valid_submission()
    payload["request"]["research_plan"]["coverage_dimensions"][0]["minimum_source_count"] = 3

    with pytest.raises(ValueError, match="requires at least 3 sources"):
        parse_company_research_submission_v1(payload)


def test_required_coverage_cannot_be_declared_not_applicable() -> None:
    payload = valid_submission()
    payload["dossier"]["coverage"][0].update(
        status="not_applicable",
        source_document_ids=[],
        limitation="Host declared the required area inapplicable.",
    )

    with pytest.raises(ValueError, match="required coverage dimension.*cannot be not_applicable"):
        parse_company_research_submission_v1(payload)


def test_complete_coverage_honors_preferred_source_kind_and_public_only_policy() -> None:
    payload = valid_submission()
    dimension = payload["request"]["research_plan"]["coverage_dimensions"][0]
    dimension["preferred_source_kinds"] = ["news"]

    with pytest.raises(ValueError, match="lacks its planned preferred source kinds"):
        parse_company_research_submission_v1(payload)

    payload = valid_submission()
    payload["dossier"]["documents"][0]["entitlement"]["access"] = "licensed"
    with pytest.raises(ValueError, match="permits only public sources"):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize("field", ["retrieved_at", "evaluated_at"])
def test_research_rejects_operations_after_dossier_completion(field: str) -> None:
    payload = valid_submission()
    if field == "retrieved_at":
        payload["dossier"]["documents"][0]["temporal"][field] = "2026-08-03T19:00:00Z"
    else:
        payload["dossier"]["evaluation"]["checks"][0][field] = "2026-08-03T19:00:00Z"

    with pytest.raises(ValueError, match="after dossier completion"):
        parse_company_research_submission_v1(payload)


def test_research_rejects_broken_argument_and_evidence_references() -> None:
    payload = valid_submission()
    payload["dossier"]["arguments"][1]["rebuttal_of"] = "argument.missing"  # type: ignore[index]
    with pytest.raises(ValueError, match="unknown arguments"):
        parse_company_research_submission_v1(payload)
    payload = valid_submission()
    payload["dossier"]["claims"][0]["evidence_document_ids"] = ["doc.missing"]  # type: ignore[index]
    with pytest.raises(ValueError, match="unknown documents"):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize("field", ["documents", "claims", "arguments"])
def test_completed_research_requires_core_records(field: str) -> None:
    payload = valid_submission()
    payload["dossier"][field] = []  # type: ignore[index]
    with pytest.raises(ValueError, match="completed dossiers require"):
        parse_company_research_submission_v1(payload)


def test_research_requires_completion_after_request_start() -> None:
    payload = valid_submission()
    payload["dossier"]["completed_at"] = "2026-08-03T15:00:00Z"  # type: ignore[index]
    with pytest.raises(ValueError, match="cannot precede request.requested_at"):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["dossier"]["documents"][0]["temporal"].update(available_at="2026-08-02T00:00:00Z"),
            "available by cutoff",
        ),
        (
            lambda payload: payload["dossier"]["metrics"][0].update(period_end="2026-08-02T00:00:00Z"),
            "reported metric.period_end cannot follow metric.as_of_at",
        ),
        (
            lambda payload: payload["dossier"]["prior_outcomes"][0].update(evaluated_at="2026-08-02T00:00:00Z"),
            "unavailable at",
        ),
    ],
)
def test_research_rejects_point_in_time_leakage(mutate: object, message: str) -> None:
    payload = deepcopy(valid_submission())
    mutate(payload)  # type: ignore[operator]
    with pytest.raises(ValueError, match=message):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize(
    ("as_of_at", "message"),
    [
        ("2026-07-31T14:00:00", "exact timezone-aware"),
        ("not-a-timestamp", "exact timezone-aware"),
        ("2026-08-02T00:00:00Z", "unavailable at the research cutoff"),
    ],
)
def test_metric_information_vintage_must_be_exact_and_cutoff_safe(as_of_at: str, message: str) -> None:
    payload = valid_submission()
    payload["dossier"]["metrics"][0]["as_of_at"] = as_of_at

    with pytest.raises(ValueError, match=message):
        parse_company_research_submission_v1(payload)


def test_metric_information_vintage_is_required() -> None:
    payload = valid_submission()
    del payload["dossier"]["metrics"][0]["as_of_at"]

    with pytest.raises(ValueError, match=r"metrics\[0\]\.as_of_at is required"):
        parse_company_research_submission_v1(payload)


def test_reported_metric_cannot_describe_a_period_later_than_its_information_vintage() -> None:
    payload = valid_submission()
    payload["dossier"]["metrics"][0]["period_end"] = "2026-07-31T23:00:00Z"

    with pytest.raises(ValueError, match="reported metric.period_end cannot follow metric.as_of_at"):
        parse_company_research_submission_v1(payload)


def test_cutoff_safe_estimate_can_describe_a_future_period() -> None:
    payload = valid_submission()
    payload["dossier"]["metrics"][0].update(
        basis="estimated",
        period_end="2026-12-31T23:59:59Z",
    )

    submission = parse_company_research_submission_v1(payload)

    assert submission.dossier.metrics[0].basis == "estimated"
    assert submission.dossier.metrics[0].period_end == "2026-12-31T23:59:59Z"


def test_cutoff_safe_assumption_can_describe_a_future_period_without_documents() -> None:
    payload = valid_submission()
    payload["dossier"]["metrics"][0].update(
        basis="assumption",
        period_end="2026-12-31T23:59:59Z",
        source_document_ids=[],
    )

    submission = parse_company_research_submission_v1(payload)

    assert submission.dossier.metrics[0].source_document_ids == ()


def test_cutoff_safe_calculation_can_describe_a_future_period() -> None:
    payload = valid_submission()
    payload["dossier"]["metrics"][1].update(
        period_start="2026-10-01T00:00:00Z",
        period_end="2026-12-31T23:59:59Z",
    )

    submission = parse_company_research_submission_v1(payload)

    assert submission.dossier.metrics[1].basis == "calculated"
    assert submission.dossier.metrics[1].period_end == "2026-12-31T23:59:59Z"


def test_calculated_metric_cannot_predate_an_input_metric() -> None:
    payload = valid_submission()
    payload["dossier"]["documents"][0]["temporal"].update(
        published_at="2026-07-31T12:00:00Z",
        available_at="2026-07-31T13:00:00Z",
    )
    payload["dossier"]["metrics"][1]["as_of_at"] = "2026-07-31T13:00:00Z"

    with pytest.raises(ValueError, match="predates input metric"):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize(("field", "value"), [("value", 10.5), ("unit", "USD")])
def test_calculated_metric_must_match_its_calculation_result_and_unit(field: str, value: object) -> None:
    payload = valid_submission()
    payload["dossier"]["metrics"][1][field] = value

    with pytest.raises(ValueError, match="must match calculation result and unit"):
        parse_company_research_submission_v1(payload)


def test_metric_cannot_predate_its_supporting_document() -> None:
    payload = valid_submission()
    payload["dossier"]["documents"][0]["temporal"]["available_at"] = "2026-07-31T15:00:00Z"

    with pytest.raises(ValueError, match="predates the availability of source document"):
        parse_company_research_submission_v1(payload)


def test_company_research_v1_manifest_is_ordered_and_completed_only() -> None:
    manifest_path = COMPANY_RESEARCH_SUBMISSION_V1_SCHEMA_PATH.parent / "company-research.v1.json"
    manifest = json.loads(manifest_path.read_text())
    stages = manifest["stages"]
    assert [stage["ordinal"] for stage in stages] == list(range(1, len(stages) + 1))
    assert stages[-1]["id"] == "publish.dossier"
    assert manifest["terminal_artifact_kind"] == "research_dossier.v1"
    assert manifest["contracts"]["terminal"].endswith("#/$defs/companyResearchSubmission")
