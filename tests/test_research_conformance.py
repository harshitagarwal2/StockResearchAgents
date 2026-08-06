from __future__ import annotations

from copy import deepcopy

import pytest
from research_submission_fixtures import complete_research_submission

from stock_research_agents.research_conformance import (
    assert_research_dossier_conformant,
    validate_research_dossier,
)


def _valid_dossier() -> dict[str, object]:
    return {
        "schema_version": "3.0.0",
        "cutoff": "2026-08-01T20:00:00Z",
        "completed_at": "2026-08-02T03:00:00Z",
        "sources": [{"id": "src-1", "published_at": "2026-08-01T19:00:00Z"}],
        "evidence": [{"id": "ev-1", "source_ids": ["src-1"], "available_at": "2026-08-01T19:05:00Z"}],
        "claims": [{"id": "claim-1", "evidence_ids": ["ev-1"]}],
        "metrics": [{"id": "metric-1", "value": 12.0, "unit": "USD/share", "period": "FY2026", "evidence_id": "ev-1"}],
        "calculations": [
            {
                "id": "calc-1",
                "formula": "metric-1 * multiple",
                "inputs": {"metric-1": 12.0, "multiple": 10.0},
                "input_metric_ids": ["metric-1"],
                "result": 120.0,
                "unit": "USD/share",
                "deterministic": True,
            }
        ],
        "valuations": [
            {
                "id": "valuation-1",
                "methodology": "Forward multiple",
                "currency": "USD",
                "input_metric_ids": ["metric-1"],
                "calculation_ids": ["calc-1"],
                "fair_value": 120.0,
            }
        ],
        "peers": [
            {
                "id": "peer-1",
                "symbol": "PEER",
                "rationale": "Comparable recurring-revenue model.",
                "normalization": {"currency": "USD", "period": "NTM"},
            }
        ],
        "debate": [{"id": "turn-1", "claim_ids": ["claim-1"], "evidence_ids": ["ev-1"]}],
        "portfolio_context": {"sanitized": True, "non_executable": True},
        "coverage": {"status": "complete", "gaps": []},
    }


def test_valid_research_dossier_passes_all_semantic_checks() -> None:
    dossier = _valid_dossier()

    report = validate_research_dossier(dossier)

    assert report.passed
    assert report.issues == ()
    assert report.to_dict()["passed"] is True
    assert_research_dossier_conformant(dossier)


def test_calculation_constants_participate_in_deterministic_recomputation() -> None:
    dossier = _valid_dossier()
    calculation = dossier["calculations"][0]
    calculation["formula"] = "metric-1 * scale"
    calculation["inputs"] = {"metric-1": 12.0}
    calculation["constants"] = [{"name": "scale", "value": 10.0}]

    report = validate_research_dossier(dossier)

    assert report.passed, report.to_dict()


def test_calculation_operation_cannot_contradict_formula_semantics() -> None:
    dossier = complete_research_submission("ORCL")["dossier"]
    dossier["calculations"][0]["operation"] = "discounted_cash_flow"

    report = validate_research_dossier(dossier)

    assert any(issue.check == "reproducibility" and issue.path.endswith(".result") for issue in report.issues)


def test_canonical_research_fixture_passes_generic_validation() -> None:
    submission = complete_research_submission("ORCL")
    dossier = submission["dossier"]
    assert isinstance(dossier, dict)

    report = validate_research_dossier(dossier)

    assert report.passed, report.to_dict()


def test_generic_conformance_accepts_future_period_with_cutoff_safe_information_vintage() -> None:
    dossier = complete_research_submission("ORCL")["dossier"]
    dossier["metrics"][1]["period_end"] = "2027-07-31T00:00:00Z"

    report = validate_research_dossier(dossier)

    assert report.passed, report.to_dict()


def test_generic_conformance_rejects_post_cutoff_metric_information_vintage() -> None:
    dossier = complete_research_submission("ORCL")["dossier"]
    dossier["metrics"][1]["period_end"] = "2027-07-31T00:00:00Z"
    dossier["metrics"][1]["as_of_at"] = "2026-08-02T00:00:00Z"

    report = validate_research_dossier(dossier)

    assert any(issue.check == "temporal_safety" and issue.path.endswith(".as_of_at") for issue in report.issues)


def test_contract_shaped_research_dossier_allows_post_cutoff_processing_but_not_evidence_leakage() -> None:
    dossier = _valid_dossier()
    dossier["as_of_at"] = dossier.pop("cutoff")
    dossier["completed_at"] = "2026-08-02T03:00:00Z"
    dossier["documents"] = [
        {
            "id": "doc-1",
            "temporal": {
                "observed_at": "2026-08-01T18:00:00Z",
                "published_at": "2026-08-01T19:00:00Z",
                "available_at": "2026-08-01T19:05:00Z",
                "retrieved_at": "2026-08-02T01:00:00Z",
                "cutoff_at": "2026-08-01T20:00:00Z",
            },
        }
    ]
    dossier.pop("sources")
    dossier.pop("evidence")
    dossier["claims"] = [{"id": "claim-1", "evidence_document_ids": ["doc-1"], "metric_ids": []}]
    dossier.pop("debate")
    dossier["arguments"] = [
        {
            "argument_id": "turn-1",
            "debate": "research",
            "claim_ids": ["claim-1"],
            "assumption_ids": [],
            "rebuttal_of": None,
            "concessions": [],
            "unresolved": ["Long-term durability remains uncertain."],
        }
    ]
    dossier["metrics"] = [
        {
            "id": "metric-1",
            "value": 12.0,
            "unit": "USD/share",
            "period_end": "2026-07-31T00:00:00Z",
            "source_document_ids": ["doc-1"],
        }
    ]
    dossier["calculations"] = [
        {
            "id": "calc-1",
            "formula": "metric-1 * 10",
            "input_metric_ids": ["metric-1"],
            "result": 120.0,
            "unit": "USD/share",
            "deterministic": True,
        }
    ]
    dossier["portfolio_context"] = {"non_executable": True}
    dossier["coverage"] = [{"area": "fundamentals", "status": "complete", "source_document_ids": ["doc-1"]}]
    dossier["evaluation"] = {
        "evaluated_at": "2026-08-02T02:00:00Z",
        "checked_claim_ids": ["claim-1"],
        "checked_calculation_ids": ["calc-1"],
    }

    report = validate_research_dossier(dossier)

    assert report.passed, report.to_dict()


def test_calculation_and_valuation_results_are_recomputed() -> None:
    dossier = _valid_dossier()
    calculations = dossier["calculations"]
    valuations = dossier["valuations"]
    assert isinstance(calculations, list)
    assert isinstance(valuations, list)
    calculations[0]["result"] = 119.0
    valuations[0]["fair_value"] = 121.0
    valuations[0]["sensitivity_outputs"] = [{"calculation_id": "calc-1", "value": 122.0}]

    report = validate_research_dossier(dossier)
    reproducibility_issues = [issue for issue in report.issues if issue.check == "reproducibility"]

    assert any(issue.path == "$.calculations[0].result" for issue in reproducibility_issues)
    assert any(issue.path == "$.valuations[0].fair_value" for issue in reproducibility_issues)
    assert any("sensitivity_outputs" in issue.path for issue in reproducibility_issues)


def test_argument_links_and_resolution_semantics_are_validated() -> None:
    dossier = _valid_dossier()
    dossier.pop("debate")
    dossier["arguments"] = [
        {
            "argument_id": "arg-1",
            "debate": "research",
            "claim_ids": ["claim-1"],
            "assumption_ids": [],
            "rebuttal_of": "arg-2",
            "concessions": ["Margin risk", "Margin risk"],
            "unresolved": ["Margin risk"],
        },
        {
            "argument_id": "arg-2",
            "debate": "risk",
            "claim_ids": ["claim-1"],
            "assumption_ids": [],
            "rebuttal_of": None,
            "concessions": [],
            "unresolved": [],
        },
    ]

    report = validate_research_dossier(dossier)
    debate_issues = [issue for issue in report.issues if issue.check == "debate_grounding"]

    assert any(issue.path.endswith("rebuttal_of") for issue in debate_issues)
    assert any(issue.path.endswith("concessions") for issue in debate_issues)
    assert any("both conceded and unresolved" in issue.detail for issue in debate_issues)


def test_research_conformance_reports_all_deterministic_safety_failures() -> None:
    dossier = deepcopy(_valid_dossier())
    dossier["api_key"] = "forbidden"
    dossier["sources"] = [{"id": "src-1", "published_at": "2026-08-02T00:00:00Z"}]
    dossier["evidence"] = [{"id": "ev-1", "source_ids": ["missing"]}]
    dossier["claims"] = [{"id": "claim-1", "evidence_ids": ["ev-1"], "supersedes": "missing-claim"}]
    dossier["metrics"] = [{"id": "metric-1", "value": "12", "unit": "", "evidence_id": "ev-1"}]
    dossier["calculations"] = [{"id": "calc-1", "inputs": {"metric-1": 12.0}, "result": 120.0}]
    dossier["valuations"] = [{"id": "valuation-1", "inputs": {}, "value": 120.0}]
    dossier["peers"] = [{"id": "peer-1", "rationale": "", "normalization": {}}]
    dossier["debate"] = [{"id": "turn-1", "claim_ids": []}]
    dossier["portfolio_context"] = {"account_number": "raw", "executable": True, "submitted": False}
    dossier["coverage"] = {"status": "complete", "gaps": ["missing transcript"]}

    report = validate_research_dossier(dossier)
    checks = {issue.check for issue in report.issues}

    assert not report.passed
    assert checks == {
        "completeness_honesty",
        "credential_safety",
        "debate_grounding",
        "metric_semantics",
        "peer_methodology",
        "portfolio_safety",
        "reference_integrity",
        "reproducibility",
        "supersession_integrity",
        "temporal_safety",
    }
    with pytest.raises(ValueError, match="research dossier conformance failed"):
        assert_research_dossier_conformant(dossier)


def test_supersession_cycles_are_rejected() -> None:
    dossier = _valid_dossier()
    dossier["claims"] = [
        {"id": "claim-1", "evidence_ids": ["ev-1"], "supersedes": "claim-2"},
        {"id": "claim-2", "evidence_ids": ["ev-1"], "supersedes": "claim-1"},
    ]

    report = validate_research_dossier(dossier)

    assert any(issue.check == "supersession_integrity" and "cycle" in issue.detail for issue in report.issues)
