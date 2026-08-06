from __future__ import annotations

from dataclasses import replace

from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.conformance import evaluate_validation, validation_digest
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore


def _completed_analytics():
    return submit_company_analytics(
        complete_analytics_submission("META"),
        store=RunStore(),
        quality_store=QualityStore(),
    )


def test_completed_analytics_passes_repository_owned_validation() -> None:
    result, events = _completed_analytics()

    report = evaluate_validation(result, events)

    assert report.passed is True
    assert report.verified is True
    assert report.schema_version == "1.0.0"
    assert report.overall_status == "validation_passed"
    assert len(validation_digest(report)) == 64
    assert {check.name for check in report.checks} == {
        "profile_and_submission_identity",
        "canonical_stage_receipts",
        "stage_event_receipt_integrity",
        "research_dossier_semantics",
        "artifact_projection_integrity",
        "non_execution_boundary",
        "quality_receipt_integrity",
        "five_analytics_report_groups",
    }
    assert len(result.submission.run_card.stages) == 26


def test_validation_rejects_a_stage_event_that_does_not_match_its_run_card_receipt() -> None:
    result, events = _completed_analytics()
    first = replace(events[0], data={**events[0].data, "output_digest": "0" * 64})

    report = evaluate_validation(result, (first, *events[1:]))

    assert report.passed is False
    check = next(item for item in report.checks if item.name == "stage_event_receipt_integrity")
    assert check.status == "failed"


def test_validation_rejects_terminal_artifacts_that_are_not_exact_submission_projections() -> None:
    result, events = _completed_analytics()
    dossier_artifact = result.artifacts[0]
    tampered = replace(
        result,
        artifacts=(replace(dossier_artifact, content={"tampered": True}), *result.artifacts[1:]),
    )

    report = evaluate_validation(tampered, events)

    assert report.passed is False
    check = next(item for item in report.checks if item.name == "artifact_projection_integrity")
    assert check.status == "failed"


def test_validation_rejects_duplicate_artifact_kinds_without_collapsing_them() -> None:
    result, events = _completed_analytics()
    artifacts = list(result.artifacts)
    artifacts[-1] = replace(artifacts[-1], kind=artifacts[0].kind)
    object.__setattr__(result, "artifacts", tuple(artifacts))

    report = evaluate_validation(result, events)

    assert report.passed is False
    check = next(item for item in report.checks if item.name == "artifact_projection_integrity")
    assert check.status == "failed"
