"""Profile strategies for the durable host-executed research lifecycle.

The coordinator owns state transitions and publication recovery.  A profile
strategy owns only workflow-specific contracts, terminal parsing, and sidecar
registration.  This keeps the lifecycle open for new profiles without copying
its optimistic-locking state machine.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .application_ports import QualityIndexPort
from .company_analytics import build_company_analytics_draft, prepare_company_analytics
from .company_analytics_v1 import HostSubmissionV4, parse_host_submission_v4
from .company_research import build_company_research_draft, prepare_company_research
from .publication import PublicationDraft
from .research_conformance import assert_research_dossier_conformant
from .research_contracts import CompanyResearchRequest, HostSubmissionV3, parse_host_submission_v3
from .research_quality_v1 import QUALITY_STORE


class LifecycleProfileStrategy(Protocol):
    """Strategy interface consumed by the profile-neutral coordinator."""

    workflow_profile: str
    workflow_id: str
    terminal_stage_id: str
    terminal_output_ref: str
    terminal_kind: str
    persistence_outputs: tuple[str, ...]

    def prepare(
        self,
        request: CompanyResearchRequest,
        *,
        research_pack_id: str | None,
        execution_mode: str | None,
    ) -> Mapping[str, object]: ...

    def parse_terminal(self, payload: object) -> HostSubmissionV3 | HostSubmissionV4: ...

    def request_from_submission(
        self,
        submission: HostSubmissionV3 | HostSubmissionV4,
    ) -> CompanyResearchRequest: ...

    def build_publication(self, payload: object) -> PublicationDraft: ...

    def stage_sidecars(self, payload: object) -> None: ...

    def publish_sidecars(self, payload: object) -> None: ...

    def sidecars_ready(self, payload: object | None) -> bool: ...


class CompanyResearchLifecycleProfile:
    """Frozen v3 dossier strategy retained for backward compatibility."""

    workflow_profile = "company-research.v2"
    workflow_id = "tradingagents.company-research.v2"
    terminal_stage_id = "publish.dossier"
    terminal_output_ref = "host-submission.v3.schema.json#/$defs/hostSubmission"
    terminal_kind = "host_submission_v3"
    persistence_outputs: tuple[str, ...] = (
        "durable_company_lifecycle",
        "research_dossier.v3",
        "portable_report_bundle",
    )

    def prepare(
        self,
        request: CompanyResearchRequest,
        *,
        research_pack_id: str | None,
        execution_mode: str | None,
    ) -> Mapping[str, object]:
        if research_pack_id is not None:
            raise ValueError("company-research.v2 does not accept a research pack")
        if execution_mode is not None:
            raise ValueError("company-research.v2 does not accept an analytics execution mode")
        return prepare_company_research(request)

    def parse_terminal(self, payload: object) -> HostSubmissionV3:
        submission = parse_host_submission_v3(payload)
        assert_research_dossier_conformant(submission.dossier.to_dict())
        return submission

    def request_from_submission(self, submission: HostSubmissionV3 | HostSubmissionV4) -> CompanyResearchRequest:
        if not isinstance(submission, HostSubmissionV3):
            raise TypeError("company-research.v2 requires HostSubmissionV3")
        return submission.request

    def build_publication(self, payload: object) -> PublicationDraft:
        return build_company_research_draft(self.parse_terminal(payload))

    def stage_sidecars(self, payload: object) -> None:
        self.parse_terminal(payload)

    def publish_sidecars(self, payload: object) -> None:
        self.parse_terminal(payload)

    def sidecars_ready(self, payload: object | None) -> bool:
        return payload is not None


class CompanyAnalyticsLifecycleProfile:
    """V4 analytics strategy with an injectable immutable quality store."""

    workflow_profile = "company-analytics.v1"
    workflow_id = "tradingagents.company-analytics.v1"
    terminal_stage_id = "publish.completed"
    terminal_output_ref = "host-submission.v4.schema.json"
    terminal_kind = "host_submission_v4"
    persistence_outputs: tuple[str, ...] = (
        "durable_company_analytics_lifecycle",
        "research_dossier.v3",
        "analytics_bundle.v1",
        "run_card.v1",
        "hypothesis_ledger.v1",
        "research_iterations.v1",
        "research_quality.v1",
        "forecast_set.v1",
        "portable_report_bundle",
    )

    def __init__(self, quality_store: QualityIndexPort = QUALITY_STORE) -> None:
        self.quality_store = quality_store

    def prepare(
        self,
        request: CompanyResearchRequest,
        *,
        research_pack_id: str | None,
        execution_mode: str | None,
    ) -> Mapping[str, object]:
        return prepare_company_analytics(
            request,
            research_pack_id=research_pack_id or "initiating-coverage.v1",
            execution_mode=execution_mode or "compatible",
        )

    def parse_terminal(self, payload: object) -> HostSubmissionV4:
        return parse_host_submission_v4(payload)

    def request_from_submission(self, submission: HostSubmissionV3 | HostSubmissionV4) -> CompanyResearchRequest:
        if not isinstance(submission, HostSubmissionV4):
            raise TypeError("company-analytics.v1 requires HostSubmissionV4")
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


COMPANY_RESEARCH_LIFECYCLE_PROFILE = CompanyResearchLifecycleProfile()
