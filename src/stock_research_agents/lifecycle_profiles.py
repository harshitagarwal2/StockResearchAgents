"""Workflow strategy for the durable company analytics lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .application_ports import QualityIndexPort
from .company_analytics import build_company_analytics_draft, prepare_company_analytics
from .company_analytics_v1 import CompanyAnalyticsSubmissionV1, parse_company_analytics_submission_v1
from .publication import PublicationDraft
from .research_contracts import CompanyResearchRequest


class WorkflowPlanner(Protocol):
    """Prepare the caller-owned execution plan for a workflow."""

    workflow_profile: str
    workflow_id: str

    def prepare(
        self,
        request: CompanyResearchRequest,
        *,
        research_pack_id: str | None,
        execution_mode: str | None,
    ) -> Mapping[str, object]: ...


class TerminalSubmissionCodec(Protocol):
    """Parse a terminal submission and expose its originating request."""

    def parse_terminal(self, payload: object) -> CompanyAnalyticsSubmissionV1: ...

    def request_from_submission(self, submission: CompanyAnalyticsSubmissionV1) -> CompanyResearchRequest: ...

    def build_publication(self, payload: object) -> PublicationDraft: ...


class SidecarPublisher(Protocol):
    """Stage, publish, and query workflow-specific sidecars."""

    def stage_sidecars(self, payload: object) -> None: ...

    def publish_sidecars(self, payload: object) -> None: ...

    def sidecars_ready(self, payload: object | None) -> bool: ...


class WorkflowDefinition(WorkflowPlanner, TerminalSubmissionCodec, SidecarPublisher, Protocol):
    """Complete workflow definition consumed by the lifecycle coordinator."""

    terminal_stage_id: str
    terminal_output_ref: str
    terminal_kind: str
    persistence_outputs: tuple[str, ...]


# Compatibility name for callers that imported the original broad strategy.
LifecycleProfileStrategy = WorkflowDefinition


class CompanyAnalyticsLifecycleProfile:
    """Company analytics workflow definition with an injectable quality index."""

    workflow_profile = "company-analytics.v1"
    workflow_id = "stockresearchagents.company-analytics.v1"
    terminal_stage_id = "publish.completed"
    terminal_output_ref = "company-analytics-submission.v1.schema.json"
    terminal_kind = "company_analytics_submission_v1"
    persistence_outputs: tuple[str, ...] = (
        "durable_company_analytics_lifecycle",
        "research_dossier.v1",
        "analytics_bundle.v1",
        "run_card.v1",
        "hypothesis_ledger.v1",
        "research_iterations.v1",
        "research_quality.v1",
        "forecast_set.v1",
        "completed_report_bundle",
    )

    def __init__(self, quality_store: QualityIndexPort) -> None:
        self.quality_store = quality_store

    def prepare(
        self,
        request: CompanyResearchRequest,
        *,
        research_pack_id: str | None,
        execution_mode: str | None,
    ) -> Mapping[str, object]:
        plan = dict(
            prepare_company_analytics(
                request,
                research_pack_id=research_pack_id or "initiating-coverage.v1",
                execution_mode=execution_mode or "sequential",
            )
        )
        if plan["execution_mode"] == "sequential":
            plan["execution_mode_readiness"] = "executor_required"
            plan["execution_mode_locally_ready"] = False
        return plan

    def parse_terminal(self, payload: object) -> CompanyAnalyticsSubmissionV1:
        return parse_company_analytics_submission_v1(payload)

    def request_from_submission(self, submission: CompanyAnalyticsSubmissionV1) -> CompanyResearchRequest:
        return submission.company_research.request

    def build_publication(self, payload: object) -> PublicationDraft:
        return build_company_analytics_draft(payload)

    def stage_sidecars(self, payload: object) -> None:
        submission = self.parse_terminal(payload)
        self.quality_store.stage_registration(submission.quality_receipt, submission.forecasts)

    def publish_sidecars(self, payload: object) -> None:
        submission = self.parse_terminal(payload)
        self.quality_store.publish_registration(submission.quality_receipt.run_id)

    def sidecars_ready(self, payload: object | None) -> bool:
        if payload is None:
            return False
        submission = self.parse_terminal(payload)
        return self.quality_store.is_published(submission.quality_receipt.run_id)
