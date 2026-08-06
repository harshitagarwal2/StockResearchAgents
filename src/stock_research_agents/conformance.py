"""Credential-free validation of completed company analytics publications."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from .company_analytics_v1 import CompanyAnalyticsResultV1, canonical_stage_ids
from .contracts import RunEvent
from .reporting import build_report_artifacts, report_groups
from .research_conformance import validate_research_dossier as validate_research_dossier_semantics
from .research_quality_v1 import validate_quality_bundle

VALIDATION_SCHEMA_VERSION = "1.0.0"
OPTIONAL_VALIDATION_CHECKS: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    passed: bool
    detail: str
    verified: bool = True

    @property
    def status(self) -> Literal["passed", "failed", "skipped"]:
        if not self.verified:
            return "skipped"
        return "passed" if self.passed else "failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "verified": self.verified,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    run_id: str
    checks: tuple[ValidationCheck, ...]
    schema_version: str = VALIDATION_SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return self.verified and all(check.passed for check in self.checks if check.verified)

    @property
    def verified(self) -> bool:
        return all(check.verified or check.name in OPTIONAL_VALIDATION_CHECKS for check in self.checks)

    @property
    def overall_status(self) -> Literal["validation_unverified", "validation_failed", "validation_passed"]:
        if not self.verified:
            return "validation_unverified"
        return "validation_passed" if self.passed else "validation_failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "passed": self.passed,
            "verified": self.verified,
            "overall_status": self.overall_status,
            "checks": [check.to_dict() for check in self.checks],
        }


def _check(name: str, condition: bool, detail: str) -> ValidationCheck:
    return ValidationCheck(name, bool(condition), detail)


def _json_equivalent(left: object, right: object) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def evaluate_validation(
    result: CompanyAnalyticsResultV1,
    events: tuple[RunEvent, ...],
) -> ValidationReport:
    """Validate exact submission, evidence, quality, and stage receipt integrity."""
    if not isinstance(result, CompanyAnalyticsResultV1):
        raise TypeError("result must be a CompanyAnalyticsResultV1")
    if not isinstance(events, tuple) or not all(isinstance(event, RunEvent) for event in events):
        raise TypeError("events must be a tuple of RunEvent values")
    submission = result.submission
    dossier = submission.company_research.dossier
    expected_stage_ids = canonical_stage_ids()
    run_card_stages = submission.run_card.stages
    actual_stage_ids = tuple(stage.stage_id for stage in run_card_stages)
    stage_events = tuple(event for event in events if event.kind.value == "stage")
    event_stage_ids = tuple(event.stage_id for event in stage_events)
    stage_event_receipts_match = len(stage_events) == len(run_card_stages) and all(
        event.run_id == result.run_id
        and event.status == "completed"
        and event.stage_id == receipt.stage_id
        and event.data.get("workflow_profile") == result.profile
        and event.data.get("input_digest") == receipt.input_digest
        and event.data.get("output_digest") == receipt.output_digest
        and event.data.get("attempts") == receipt.attempts
        for event, receipt in zip(stage_events, run_card_stages, strict=True)
    )

    expected_artifact_contents = {
        "research_dossier.v1": dossier.to_dict(),
        "analytics_bundle.v1": submission.analytics_bundle.to_dict(),
        "run_card.v1": submission.run_card.to_dict(),
        "hypothesis_ledger.v1": [item.to_dict() for item in submission.hypothesis_ledgers],
        "research_iterations.v1": [item.to_dict() for item in submission.research_iterations],
        "research_quality.v1": submission.quality_receipt.to_dict(),
        "forecast_set.v1": [item.to_dict() for item in submission.forecasts],
    }
    artifact_kinds = tuple(artifact.kind for artifact in result.artifacts)
    artifact_projection_matches = (
        len(artifact_kinds) == len(expected_artifact_contents)
        and len(set(artifact_kinds)) == len(artifact_kinds)
        and set(artifact_kinds) == set(expected_artifact_contents)
        and all(
            _json_equivalent(artifact.content, expected_artifact_contents[artifact.kind])
            for artifact in result.artifacts
        )
    )
    dossier_report = validate_research_dossier_semantics(dossier.to_dict())
    quality_report = validate_quality_bundle(submission.quality_receipt, submission.forecasts, ())
    group_ordinals = tuple(group["ordinal"] for group in report_groups(build_report_artifacts(result)))

    checks = (
        _check(
            "profile_and_submission_identity",
            result.profile == "company-analytics.v1"
            and submission.schema_version == "company-analytics.v1"
            and submission.workflow_id == "stockresearchagents.company-analytics.v1"
            and result.run_id == submission.run_card.run_id,
            "The result, submitted contract, workflow, profile, and run ID agree.",
        ),
        _check(
            "canonical_stage_receipts",
            len(run_card_stages) == 26
            and actual_stage_ids == expected_stage_ids
            and all(stage.status == "completed" for stage in run_card_stages),
            "The run card contains the exact ordered 26 completed canonical stages.",
        ),
        _check(
            "stage_event_receipt_integrity",
            event_stage_ids == expected_stage_ids and stage_event_receipts_match,
            "Each run-card stage has one ordered event with matching input, output, attempt, and profile receipts.",
        ),
        _check(
            "research_dossier_semantics",
            dossier_report.passed,
            "Point-in-time evidence, references, calculations, privacy, and completeness are conformant."
            if dossier_report.passed
            else f"Research dossier has {len(dossier_report.issues)} semantic issue(s).",
        ),
        _check(
            "artifact_projection_integrity",
            artifact_projection_matches,
            "Every terminal artifact is an exact projection of the validated analytics submission.",
        ),
        _check(
            "non_execution_boundary",
            result.non_executable is True,
            "The completed result carries no execution authority.",
        ),
        _check(
            "quality_receipt_integrity",
            quality_report.passed,
            "Forecast, workflow, request, dossier, and stage digests reproduce the quality receipt."
            if quality_report.passed
            else f"Research quality sidecar has {len(quality_report.issues)} issue(s).",
        ),
        _check(
            "five_analytics_report_groups",
            group_ordinals == (1, 2, 3, 4, 5),
            "Executive, evidence, analytics, risk, and monitoring groups are present.",
        ),
    )
    return ValidationReport(result.run_id, checks)


def validation_digest(report: ValidationReport) -> str:
    payload = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
