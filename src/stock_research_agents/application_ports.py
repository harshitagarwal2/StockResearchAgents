"""Focused application ports for caller-selected persistence adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .contracts import RunEvent
from .research_quality_v1.contracts import Forecast, OutcomeObservation, ResearchQualityReceipt
from .research_quality_v1.scoring import QualityScorecard
from .serialization import StoredResult

if TYPE_CHECKING:
    from .company_analytics_v1.contracts import CompanyAnalyticsResultV1


class WireReceipt(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


class LifecycleRepository(Protocol):
    @property
    def state_dir(self) -> Path | None: ...

    def create(self, record: Mapping[str, Any]) -> dict[str, Any]: ...

    def get(self, run_id: str) -> dict[str, Any] | None: ...

    def update(
        self,
        run_id: str,
        expected_revision: int,
        mutate: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]: ...


class ResultPublicationPort(Protocol):
    @property
    def state_dir(self) -> Path | None: ...

    def get_result(self, run_id: str) -> StoredResult | None: ...

    def get_events(self, run_id: str) -> tuple[RunEvent, ...] | None: ...

    def get_staged(self, run_id: str) -> tuple[StoredResult, tuple[RunEvent, ...]] | None: ...

    def stage(self, result: StoredResult, events: tuple[RunEvent, ...]) -> None: ...

    def publish_staged(self, run_id: str) -> tuple[StoredResult, tuple[RunEvent, ...]]: ...


class DecisionMemoryPort(Protocol):
    def close(self) -> None: ...

    def recall(
        self,
        symbol: str,
        *,
        same_symbol_limit: int = 5,
        cross_symbol_limit: int = 3,
        cutoff_at: str | None = None,
    ) -> WireReceipt: ...

    def stage_final_decision(
        self,
        result: CompanyAnalyticsResultV1,
        *,
        context: Mapping[str, object] | None = None,
    ) -> WireReceipt: ...

    def publish_decision(self, run_id: str) -> WireReceipt: ...

    def is_published(self, run_id: str) -> bool: ...

    def append_outcome(
        self,
        *,
        outcome: object,
        reflection: str,
        memory_id: str | None = None,
        run_id: str | None = None,
        observed_at: str | None = None,
    ) -> WireReceipt: ...


class QualityIndexPort(Protocol):
    def stage_registration(
        self,
        receipt: ResearchQualityReceipt,
        forecasts: tuple[Forecast, ...],
    ) -> None: ...

    def publish_registration(self, run_id: str) -> None: ...

    def is_published(self, run_id: str) -> bool: ...


class QualitySidecarPort(QualityIndexPort, Protocol):
    def append_outcome(self, observation: OutcomeObservation) -> QualityScorecard: ...

    def projection(self, run_id: str) -> dict[str, object] | None: ...
