"""Workflow strategy for the durable company analytics lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .application_ports import QualityIndexPort
from .company_analytics import COMPANY_ANALYTICS_WORKFLOW, prepare_company_analytics
from .company_analytics_v1 import CompanyAnalyticsSubmissionV1
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
    """Compatibility facade combining the workflow and its quality sidecar."""

    workflow_profile = COMPANY_ANALYTICS_WORKFLOW.descriptor.profile
    workflow_id = COMPANY_ANALYTICS_WORKFLOW.descriptor.workflow_id
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

    def __init__(self, quality_store: QualityIndexPort | None = None) -> None:
        if quality_store is None:
            from .research_quality_v1 import QualityStore

            quality_store = QualityStore()
        self.workflow = COMPANY_ANALYTICS_WORKFLOW
        self.sidecar_publisher = CompanyAnalyticsQualitySidecarPublisher(quality_store)

    @property
    def quality_store(self) -> QualityIndexPort:
        """Deprecated compatibility access; use ``sidecar_publisher``."""
        return self.sidecar_publisher.quality_store

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
        return self.workflow.parse_submission(payload)

    def request_from_submission(self, submission: CompanyAnalyticsSubmissionV1) -> CompanyResearchRequest:
        return submission.company_research.request

    def build_publication(self, payload: object) -> PublicationDraft:
        return self.workflow.build_publication(payload)

    def stage_sidecars(self, payload: object) -> None:
        self.sidecar_publisher.stage_sidecars(payload)

    def publish_sidecars(self, payload: object) -> None:
        self.sidecar_publisher.publish_sidecars(payload)

    def sidecars_ready(self, payload: object | None) -> bool:
        return self.sidecar_publisher.sidecars_ready(payload)


class CompanyAnalyticsQualitySidecarPublisher:
    """Publish research-quality state independently of workflow definition."""

    def __init__(self, quality_store: QualityIndexPort) -> None:
        self.quality_store = quality_store

    def stage_sidecars(self, payload: object) -> None:
        submission = COMPANY_ANALYTICS_WORKFLOW.parse_submission(payload)
        self.quality_store.stage_registration(submission.quality_receipt, submission.forecasts)

    def publish_sidecars(self, payload: object) -> None:
        submission = COMPANY_ANALYTICS_WORKFLOW.parse_submission(payload)
        self.quality_store.publish_registration(submission.quality_receipt.run_id)

    def sidecars_ready(self, payload: object | None) -> bool:
        if payload is None:
            return False
        submission = COMPANY_ANALYTICS_WORKFLOW.parse_submission(payload)
        return self.quality_store.is_published(submission.quality_receipt.run_id)


COMPANY_ANALYTICS_LIFECYCLE_PROFILE: CompanyAnalyticsLifecycleProfile


def __getattr__(name: str) -> object:
    """Keep the former default profile import without composing it here."""
    if name == "COMPANY_ANALYTICS_LIFECYCLE_PROFILE":
        from .bootstrap import DEFAULT_RUNTIME

        return DEFAULT_RUNTIME.coordinator.profile
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
