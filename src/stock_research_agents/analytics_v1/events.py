"""Catalyst and event-cluster contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from stock_research_agents.research_contracts import StrictModel, _bounded_text, _utc_timestamp, _validate_id


@dataclass(frozen=True, slots=True)
class MaterialityAssessment(StrictModel):
    assessment_id: str
    impact: Literal["very_negative", "negative", "mixed", "positive", "very_positive", "unknown"]
    magnitude: Literal["immaterial", "low", "medium", "high", "transformational", "unknown"]
    confidence: float
    rationale: str
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.assessment_id, "assessment_id")
        if not 0 <= self.confidence <= 1:
            raise ValueError("materiality confidence must be between zero and one")
        _bounded_text(self.rationale, "rationale", 2_000)
        for claim_id in self.claim_ids:
            _validate_id(claim_id, "claim_ids")


@dataclass(frozen=True, slots=True)
class Catalyst(StrictModel):
    catalyst_id: str
    title: str
    catalyst_type: Literal["earnings", "product", "regulatory", "capital_allocation", "macro", "legal", "other"]
    expected_at: str | None
    window_start_at: str | None
    window_end_at: str | None
    condition: str | None
    source_ids: tuple[str, ...]
    hypothesis_ids: tuple[str, ...]
    materiality: MaterialityAssessment

    def __post_init__(self) -> None:
        _validate_id(self.catalyst_id, "catalyst_id")
        _bounded_text(self.title, "title", 256)
        if self.expected_at is not None:
            _utc_timestamp(self.expected_at, "expected_at")
        if (self.window_start_at is None) != (self.window_end_at is None):
            raise ValueError("catalyst windows require both start and end")
        if self.window_start_at is not None and self.window_end_at is not None:
            if _utc_timestamp(self.window_end_at, "window_end_at") < _utc_timestamp(
                self.window_start_at, "window_start_at"
            ):
                raise ValueError("catalyst window end must not precede start")
        if self.condition is not None:
            _bounded_text(self.condition, "condition", 1_000)
        for identifier in (*self.source_ids, *self.hypothesis_ids):
            _validate_id(identifier, "catalyst reference")


@dataclass(frozen=True, slots=True)
class EventCluster(StrictModel):
    cluster_id: str
    title: str
    catalyst_ids: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        _validate_id(self.cluster_id, "cluster_id")
        _bounded_text(self.title, "title", 256)
        _bounded_text(self.summary, "summary", 2_000)
        if not self.catalyst_ids:
            raise ValueError("event cluster requires catalysts")
        for identifier in (*self.catalyst_ids, *self.dependency_ids):
            _validate_id(identifier, "event cluster reference")
