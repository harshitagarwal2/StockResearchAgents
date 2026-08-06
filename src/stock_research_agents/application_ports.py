"""Focused application ports for caller-selected persistence adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from .contracts import RunEvent
from .research_quality_v1.contracts import Forecast, OutcomeObservation, ResearchQualityReceipt
from .research_quality_v1.scoring import QualityScorecard
from .serialization import StoredResult

if TYPE_CHECKING:
    from .company_analytics_v1.contracts import CompanyAnalyticsResultV1
    from .view import RunView


class WireReceipt(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


class CompletedPublicationCoordinator(Protocol):
    """Minimum lifecycle seam needed to authorize completed publication reads."""

    def control(self, run_id: str) -> dict[str, Any]: ...


class CompletedPresenter(Protocol):
    def __call__(
        self,
        run_id: str,
        store: CompletedResultReader,
        *,
        coordinator: CompletedPublicationCoordinator | None = None,
        mode: Literal["auto", "path_only"] | None = None,
    ) -> dict[str, object]: ...


class CompletedViewBuilder(Protocol):
    def __call__(
        self,
        result: CompanyAnalyticsResultV1,
        events: tuple[RunEvent, ...],
    ) -> RunView: ...


class LifecycleReader(Protocol):
    @property
    def state_dir(self) -> Path | None: ...

    def get(self, run_id: str) -> dict[str, Any] | None: ...


class LifecycleWriter(Protocol):
    def create(self, record: Mapping[str, Any]) -> dict[str, Any]: ...

    def update(
        self,
        run_id: str,
        expected_revision: int,
        mutate: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]: ...


class LifecycleRepository(LifecycleReader, LifecycleWriter, Protocol):
    """Read and mutate optimistic-revision lifecycle records."""


class CompletedResultReader(Protocol):
    def get_result(self, run_id: str) -> StoredResult | None: ...

    def get_events(self, run_id: str) -> tuple[RunEvent, ...] | None: ...


class CompletedResultPublisher(Protocol):
    def get_staged(self, run_id: str) -> tuple[StoredResult, tuple[RunEvent, ...]] | None: ...

    def stage(self, result: StoredResult, events: tuple[RunEvent, ...]) -> None: ...

    def publish_staged(self, run_id: str) -> tuple[StoredResult, tuple[RunEvent, ...]]: ...


class ResultPublicationPort(CompletedResultReader, CompletedResultPublisher, Protocol):
    """Compatibility port for callers that both query and publish results."""


class ResearchHistoryReader(Protocol):
    def close(self) -> None: ...

    def recall(
        self,
        symbol: str,
        *,
        same_symbol_limit: int = 5,
        cross_symbol_limit: int = 3,
        cutoff_at: str | None = None,
    ) -> WireReceipt: ...

    def is_published(self, run_id: str) -> bool: ...


class ResearchHistoryWriter(Protocol):
    def close(self) -> None: ...

    def stage_final_decision(
        self,
        result: CompanyAnalyticsResultV1,
        *,
        context: Mapping[str, object] | None = None,
    ) -> WireReceipt: ...

    def publish_decision(self, run_id: str) -> WireReceipt: ...

    def append_outcome(
        self,
        *,
        outcome: object,
        reflection: str,
        memory_id: str | None = None,
        run_id: str | None = None,
        observed_at: str | None = None,
    ) -> WireReceipt: ...


class ResearchHistoryPort(ResearchHistoryReader, ResearchHistoryWriter, Protocol):
    """Read/write boundary for durable research decisions and outcomes."""


# Compatibility type name retained for existing integrations.
DecisionMemoryPort = ResearchHistoryPort


class QualityRegistrationWriter(Protocol):
    def stage_registration(
        self,
        receipt: ResearchQualityReceipt,
        forecasts: tuple[Forecast, ...],
    ) -> None: ...

    def publish_registration(self, run_id: str) -> None: ...

    def is_published(self, run_id: str) -> bool: ...


class ForecastOutcomeRecorder(Protocol):
    def append_outcome(self, observation: OutcomeObservation) -> QualityScorecard: ...


class QualityProjectionReader(Protocol):
    def projection(self, run_id: str) -> dict[str, object] | None: ...


class QualityIndexPort(QualityRegistrationWriter, Protocol):
    """Write-only publication boundary used by lifecycle profiles."""


class QualitySidecarPort(
    QualityRegistrationWriter,
    ForecastOutcomeRecorder,
    QualityProjectionReader,
    Protocol,
):
    """Compatibility port for the complete research-quality sidecar."""
