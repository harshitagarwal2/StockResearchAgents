"""Attributable analyst opinions and estimate-consensus snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from stock_research_agents.research_contracts import StrictModel, _bounded_text, _utc_timestamp, _validate_id

from .common import validate_decimal


@dataclass(frozen=True, slots=True)
class RatingScale(StrictModel):
    scale_id: str
    provider: str
    strong_buy_labels: tuple[str, ...]
    buy_labels: tuple[str, ...]
    hold_labels: tuple[str, ...]
    sell_labels: tuple[str, ...]
    strong_sell_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.scale_id, "scale_id")
        _bounded_text(self.provider, "provider", 128)
        labels = (
            *self.strong_buy_labels,
            *self.buy_labels,
            *self.hold_labels,
            *self.sell_labels,
            *self.strong_sell_labels,
        )
        if not labels or len(set(label.casefold() for label in labels)) != len(labels):
            raise ValueError("rating scale labels must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class AnalystOpinion(StrictModel):
    opinion_id: str
    institution: str
    analyst_name: str | None
    published_at: str
    available_at: str
    source_id: str
    original_rating: str
    normalized_rating: Literal["strong_buy", "buy", "hold", "sell", "strong_sell", "not_rated"]
    price_target: str | None
    currency: str | None
    horizon_at: str | None
    thesis_extract: str | None

    def __post_init__(self) -> None:
        _validate_id(self.opinion_id, "opinion_id")
        _bounded_text(self.institution, "institution", 256)
        if self.analyst_name is not None:
            _bounded_text(self.analyst_name, "analyst_name", 128)
        published = _utc_timestamp(self.published_at, "published_at")
        available = _utc_timestamp(self.available_at, "available_at")
        if available < published:
            raise ValueError("analyst opinion available_at must not precede published_at")
        _validate_id(self.source_id, "source_id")
        _bounded_text(self.original_rating, "original_rating", 128)
        if self.price_target is not None:
            validate_decimal(self.price_target, "price_target")
            if self.currency is None:
                raise ValueError("price targets require currency")
        if self.horizon_at is not None and _utc_timestamp(self.horizon_at, "horizon_at") <= published:
            raise ValueError("analyst opinion horizon must be after publication")
        if self.thesis_extract is not None:
            _bounded_text(self.thesis_extract, "thesis_extract", 2_000)


@dataclass(frozen=True, slots=True)
class EstimateObservation(StrictModel):
    estimate_id: str
    metric: str
    fiscal_period_id: str
    value: str
    unit: str
    institution: str | None
    contributor_count: int | None
    observed_at: str
    available_at: str
    source_id: str

    def __post_init__(self) -> None:
        _validate_id(self.estimate_id, "estimate_id")
        _validate_id(self.metric, "metric")
        _validate_id(self.fiscal_period_id, "fiscal_period_id")
        validate_decimal(self.value, "value")
        _bounded_text(self.unit, "unit", 64)
        if self.institution is not None:
            _bounded_text(self.institution, "institution", 256)
        if self.contributor_count is not None and self.contributor_count < 1:
            raise ValueError("contributor_count must be positive")
        observed = _utc_timestamp(self.observed_at, "observed_at")
        available = _utc_timestamp(self.available_at, "available_at")
        if available < observed:
            raise ValueError("estimate available_at must not precede observed_at")
        _validate_id(self.source_id, "source_id")


@dataclass(frozen=True, slots=True)
class ConsensusSnapshot(StrictModel):
    snapshot_id: str
    metric: str
    fiscal_period_id: str
    as_of_at: str
    mean: str
    median: str
    low: str
    high: str
    standard_deviation: str | None
    contributor_count: int
    estimate_ids: tuple[str, ...]
    prior_snapshot_id: str | None
    revision_percent: str | None

    def __post_init__(self) -> None:
        _validate_id(self.snapshot_id, "snapshot_id")
        _validate_id(self.metric, "metric")
        _validate_id(self.fiscal_period_id, "fiscal_period_id")
        _utc_timestamp(self.as_of_at, "as_of_at")
        for name in ("mean", "median", "low", "high"):
            validate_decimal(getattr(self, name), name)
        if self.standard_deviation is not None:
            validate_decimal(self.standard_deviation, "standard_deviation")
        if self.contributor_count < 1 or self.contributor_count < len(self.estimate_ids):
            raise ValueError("contributor_count must cover the retained estimate IDs")
        if not self.estimate_ids:
            raise ValueError("consensus snapshot requires estimate IDs")
        for estimate_id in self.estimate_ids:
            _validate_id(estimate_id, "estimate_ids")
        if self.prior_snapshot_id is not None:
            _validate_id(self.prior_snapshot_id, "prior_snapshot_id")
            if self.revision_percent is None:
                raise ValueError("consensus revisions require revision_percent")
        if self.revision_percent is not None:
            validate_decimal(self.revision_percent, "revision_percent")
