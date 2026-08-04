"""Focused application ports for host-selected persistence adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol

from .contracts import RunEvent, RunResult
from .research_quality_v1.contracts import Forecast, OutcomeObservation, ResearchQualityReceipt
from .research_quality_v1.scoring import QualityScorecard


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


class EventRepository(Protocol):
    def put_events(self, run_id: str, events: Iterable[RunEvent]) -> None: ...


class ResultPublicationPort(Protocol):
    @property
    def state_dir(self) -> Path | None: ...

    def get_result(self, run_id: str) -> RunResult | None: ...

    def get_events(self, run_id: str) -> tuple[RunEvent, ...] | None: ...

    def get_staged(self, run_id: str) -> tuple[RunResult, tuple[RunEvent, ...]] | None: ...

    def stage(self, result: RunResult, events: tuple[RunEvent, ...]) -> None: ...

    def publish_staged(self, run_id: str) -> tuple[RunResult, tuple[RunEvent, ...]]: ...


class HostRunRepository(ResultPublicationPort, EventRepository, Protocol):
    """Combined result and event operations required by host-run coordination."""


class DecisionMemoryPort(Protocol):
    def recall(
        self,
        symbol: str,
        *,
        same_symbol_limit: int = 5,
        cross_symbol_limit: int = 3,
        cutoff: str | None = None,
        cutoff_at: str | None = None,
    ) -> WireReceipt: ...

    def stage_final_decision(
        self,
        result: RunResult,
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
