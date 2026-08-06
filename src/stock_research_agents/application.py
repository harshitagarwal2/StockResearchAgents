"""Application services shared by CLI, MCP, and other inbound adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict, cast

from .application_ports import (
    CompletedPresenter,
    CompletedPublicationCoordinator,
    CompletedResultReader,
    CompletedViewBuilder,
    QualitySidecarPort,
    ResultPublicationPort,
)
from .company_analytics_v1 import CompanyAnalyticsResultV1
from .company_lifecycle import CompanyAnalyticsCoordinator, require_completed_publication
from .contracts import RunEvent
from .research_quality_v1 import evaluate_binary_calibration_payload
from .state import StateLayout


class PublicationGate(Protocol):
    def __call__(
        self,
        run_id: str,
        result_store: CompletedResultReader,
        coordinator: CompletedPublicationCoordinator | None,
    ) -> str: ...


class CompletedPublicationResponse(TypedDict):
    ok: bool
    result: dict[str, object]
    view: dict[str, object]
    events: list[dict[str, object]]
    presentation: dict[str, object]


@dataclass(frozen=True, slots=True)
class CompletedRun:
    """Typed completed result resolved through the publication-read gate."""

    run_id: str
    result: CompanyAnalyticsResultV1
    events: tuple[RunEvent, ...]


@dataclass(frozen=True, slots=True)
class CompletedPublicationService:
    """Build the common completed-publication response for inbound adapters."""

    result_store: CompletedResultReader
    presenter: CompletedPresenter
    view_builder: CompletedViewBuilder
    coordinator: CompletedPublicationCoordinator | None = None

    def response(
        self,
        result: CompanyAnalyticsResultV1,
        events: tuple[RunEvent, ...],
        *,
        presentation_mode: Literal["auto", "path_only"] | None = None,
    ) -> CompletedPublicationResponse:
        presentation = self.presenter(
            result.run_id,
            self.result_store,
            coordinator=self.coordinator,
            mode=presentation_mode,
        )
        serialized_events = [event.to_dict() for event in events]
        serialized_view = self.view_builder(result, events).to_dict()
        return {
            "ok": True,
            "result": result.to_dict(),
            "view": serialized_view,
            "events": serialized_events,
            "presentation": presentation,
        }


@dataclass(frozen=True, slots=True)
class CompletedRunQueryService:
    """Apply the completed-publication gate before serving durable results."""

    result_store: CompletedResultReader
    coordinator: CompletedPublicationCoordinator | None = None
    publication_gate: PublicationGate = require_completed_publication

    def resolve(self, run_id: str) -> str:
        return self.publication_gate(run_id, self.result_store, self.coordinator)

    def get(self, run_id: str) -> CompletedRun:
        resolved = self.resolve(run_id)
        result = self.result_store.get_result(resolved)
        events = self.result_store.get_events(resolved)
        if result is None or events is None:
            raise ValueError(f"completed run not found: {resolved}")
        return CompletedRun(resolved, cast(CompanyAnalyticsResultV1, result), events)

    def require(self, run_id: str) -> tuple[str, CompanyAnalyticsResultV1, tuple[RunEvent, ...]]:
        """Compatibility tuple for existing inbound adapters; prefer :meth:`get`."""
        completed = self.get(run_id)
        return completed.run_id, completed.result, completed.events


@dataclass(frozen=True, slots=True)
class StockResearchApplication:
    """Injected application facade shared by CLI, MCP, and viewer adapters."""

    coordinator: CompanyAnalyticsCoordinator
    result_store: ResultPublicationPort
    quality_store: QualitySidecarPort
    presenter: CompletedPresenter
    view_builder: CompletedViewBuilder
    publication_gate: PublicationGate = require_completed_publication
    state_layout: StateLayout | None = None

    def completed_runs(self) -> CompletedRunQueryService:
        return CompletedRunQueryService(self.result_store, self.coordinator, self.publication_gate)

    def completed_response(
        self,
        result: CompanyAnalyticsResultV1,
        events: tuple[RunEvent, ...],
        *,
        presentation_mode: Literal["auto", "path_only"] | None = None,
    ) -> CompletedPublicationResponse:
        return CompletedPublicationService(
            result_store=self.result_store,
            presenter=self.presenter,
            view_builder=self.view_builder,
            coordinator=self.coordinator,
        ).response(result, events, presentation_mode=presentation_mode)

    def evaluate_quality_cohort(self, payload: object) -> dict[str, object]:
        """Evaluate one strict, leakage-controlled binary calibration cohort."""
        return evaluate_binary_calibration_payload(payload)

    def operational_diagnostics(self) -> dict[str, object]:
        """Return a redacted, read-only report for this application's state layout."""
        if self.state_layout is None:
            raise RuntimeError("operational diagnostics require an explicit state layout")
        from .diagnostics import run_state_diagnostics

        return run_state_diagnostics(self.state_layout).to_dict()
