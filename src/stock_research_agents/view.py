"""Projection-only completed view for first-party company analytics results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .company_analytics_v1 import CompanyAnalyticsResultV1
from .contracts import RunEvent
from .reporting import build_report_artifacts, report_groups
from .semantics import build_completed_run_semantics


@dataclass(frozen=True, slots=True)
class RunView:
    """JSON-safe, UI-ready projection with no analytical business logic."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload


def build_run_view(
    result: CompanyAnalyticsResultV1,
    events: tuple[RunEvent, ...],
    *,
    quality_projection: Mapping[str, object] | None = None,
) -> RunView:
    """Expose a completed analytics result without executor-specific fields."""
    if not isinstance(result, CompanyAnalyticsResultV1):
        raise TypeError("result must be a CompanyAnalyticsResultV1")
    if any(not isinstance(event, RunEvent) or event.run_id != result.run_id for event in events):
        raise ValueError("events must be RunEvent values for result.run_id")

    submission = result.submission
    research = submission.company_research
    request = research.request
    dossier = research.dossier
    identity = dossier.identity
    artifacts = (*result.artifacts, *build_report_artifacts(result))
    artifact_ids = {artifact.id for artifact in artifacts}

    payload: dict[str, Any] = {
        "schema_version": "company-analytics-view.v1",
        "ok": True,
        "run_id": result.run_id,
        "overview": {
            "symbol": identity.symbol,
            "issuer_name": identity.issuer_name,
            "company_name": identity.issuer_name,
            "asset_type": identity.asset_type,
            "exchange": identity.exchange,
            "currency": identity.currency,
            "country": identity.country,
            "as_of_at": dossier.as_of_at,
            "as_of_date": dossier.as_of_at[:10],
            "status": result.status.value,
            "profile": result.profile,
            "recommendation": dossier.recommendation,
            "coverage_decision": submission.analytics_bundle.coverage_decision,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "prototype_notice": result.prototype_notice,
            "warnings": list(result.warnings),
            "non_executable": result.non_executable,
        },
        "semantics": build_completed_run_semantics(result, events).to_dict(),
        "research_request": request.to_dict(),
        "research_dossier": dossier.to_dict(),
        "analytics": submission.analytics_bundle.to_dict(),
        "source_lineage": submission.source_lineage.to_dict(),
        "research_lab": {
            "run_card": submission.run_card.to_dict(),
            "hypotheses": [item.to_dict() for item in submission.hypothesis_ledgers],
            "iterations": [item.to_dict() for item in submission.research_iterations],
            "quality": submission.quality_receipt.to_dict(),
            "forecasts": [item.to_dict() for item in submission.forecasts],
            "quality_history": dict(quality_projection) if quality_projection is not None else None,
        },
        "reports": {
            "groups": report_groups(artifacts),
            "complete_artifact_id": "report.complete",
        },
        "events": [event.to_dict() for event in events],
        "artifacts": [artifact.to_dict() for artifact in artifacts],
        "actions": [
            {
                "id": "view_complete_report",
                "available": "report.complete" in artifact_ids,
                "reason": "Available from the deterministic completed-report projection.",
            }
        ],
    }
    return RunView(payload)
