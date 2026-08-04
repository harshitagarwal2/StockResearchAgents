"""Leakage-aware dataset, split, factor, and experiment receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from tradingagents_portable.research_contracts import StrictModel, _bounded_text, _utc_timestamp, _validate_id

from .common import CalculationReceipt, validate_decimal, validate_digest


@dataclass(frozen=True, slots=True)
class DatasetManifest(StrictModel):
    dataset_id: str
    symbol: str
    content_sha256: str
    start_at: str
    cutoff_at: str
    feature_available_through: str
    target_starts_at: str
    target_ends_at: str
    fields: tuple[str, ...]
    source_ids: tuple[str, ...]
    point_in_time: bool
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.dataset_id, "dataset_id")
        _bounded_text(self.symbol, "symbol", 32)
        validate_digest(self.content_sha256, "content_sha256")
        start = _utc_timestamp(self.start_at, "start_at")
        cutoff = _utc_timestamp(self.cutoff_at, "cutoff_at")
        feature_end = _utc_timestamp(self.feature_available_through, "feature_available_through")
        target_start = _utc_timestamp(self.target_starts_at, "target_starts_at")
        target_end = _utc_timestamp(self.target_ends_at, "target_ends_at")
        if not start <= feature_end <= cutoff < target_start <= target_end:
            raise ValueError("dataset times must separate feature availability, cutoff, and target horizon")
        if not self.fields or len(set(self.fields)) != len(self.fields):
            raise ValueError("dataset fields must be a non-empty unique sequence")
        if not self.source_ids:
            raise ValueError("dataset requires source IDs")
        if not self.point_in_time and not self.limitations:
            raise ValueError("non-point-in-time datasets require limitations")


@dataclass(frozen=True, slots=True)
class SplitManifest(StrictModel):
    split_id: str
    strategy: Literal["walk_forward", "purged_walk_forward", "anchored_walk_forward"]
    train_start_at: str
    train_end_at: str
    test_start_at: str
    test_end_at: str
    purge_days: int
    embargo_days: int
    shuffled: Literal[False]
    content_sha256: str

    def __post_init__(self) -> None:
        _validate_id(self.split_id, "split_id")
        train_start = _utc_timestamp(self.train_start_at, "train_start_at")
        train_end = _utc_timestamp(self.train_end_at, "train_end_at")
        test_start = _utc_timestamp(self.test_start_at, "test_start_at")
        test_end = _utc_timestamp(self.test_end_at, "test_end_at")
        if not train_start < train_end < test_start <= test_end:
            raise ValueError("experiment splits must preserve chronological train/test order")
        if not 0 <= self.purge_days <= 365 or not 0 <= self.embargo_days <= 365:
            raise ValueError("purge_days and embargo_days must be between zero and 365")
        gap_days = (test_start - train_end).total_seconds() / 86_400
        if gap_days < self.purge_days:
            raise ValueError("train/test gap is smaller than the declared purge")
        if self.strategy == "purged_walk_forward" and self.purge_days == 0:
            raise ValueError("purged walk-forward splits require a positive purge")
        if self.shuffled is not False:
            raise ValueError("financial time-series splits cannot be shuffled")
        validate_digest(self.content_sha256, "content_sha256")


@dataclass(frozen=True, slots=True)
class FactorObservation(StrictModel):
    observation_id: str
    factor_id: str
    as_of_at: str
    available_at: str
    value: str
    expected_direction: Literal["positive", "negative", "nonlinear", "unknown"]
    source_ids: tuple[str, ...]
    receipt: CalculationReceipt

    def __post_init__(self) -> None:
        _validate_id(self.observation_id, "observation_id")
        _validate_id(self.factor_id, "factor_id")
        as_of = _utc_timestamp(self.as_of_at, "as_of_at")
        if _utc_timestamp(self.available_at, "available_at") < as_of:
            raise ValueError("factor availability must not precede its as-of time")
        validate_decimal(self.value, "value")
        if not self.source_ids:
            raise ValueError("factor observation requires source IDs")
        if self.receipt.output_value != self.value:
            raise ValueError("factor receipt must reproduce the observed value")


@dataclass(frozen=True, slots=True)
class ExperimentSpec(StrictModel):
    experiment_id: str
    dataset_id: str
    dataset_sha256: str
    split_ids: tuple[str, ...]
    factor_ids: tuple[str, ...]
    target: str
    target_horizon_days: int
    benchmark_symbol: str | None
    metric_names: tuple[str, ...]
    runner_id: str
    implementation_sha256: str

    def __post_init__(self) -> None:
        _validate_id(self.experiment_id, "experiment_id")
        _validate_id(self.dataset_id, "dataset_id")
        validate_digest(self.dataset_sha256, "dataset_sha256")
        if not self.split_ids or not self.factor_ids or not self.metric_names:
            raise ValueError("experiment spec requires splits, factors, and metrics")
        for identifier in (*self.split_ids, *self.factor_ids, *self.metric_names):
            _validate_id(identifier, "experiment reference")
        _validate_id(self.target, "target")
        if not 1 <= self.target_horizon_days <= 3_650:
            raise ValueError("target_horizon_days must be between one and 3650")
        if self.benchmark_symbol is not None:
            _bounded_text(self.benchmark_symbol, "benchmark_symbol", 32)
        _validate_id(self.runner_id, "runner_id")
        validate_digest(self.implementation_sha256, "implementation_sha256")


@dataclass(frozen=True, slots=True)
class ExperimentMetric(StrictModel):
    name: str
    value: str
    unit: str
    sample_count: int

    def __post_init__(self) -> None:
        _validate_id(self.name, "name")
        validate_decimal(self.value, "value")
        _bounded_text(self.unit, "unit", 64)
        if self.sample_count < 1:
            raise ValueError("experiment metric sample_count must be positive")


@dataclass(frozen=True, slots=True)
class ExperimentReceipt(StrictModel):
    receipt_id: str
    experiment_id: str
    status: Literal["completed", "failed", "blocked"]
    started_at: str
    completed_at: str
    dataset_sha256: str
    split_sha256s: tuple[str, ...]
    metrics: tuple[ExperimentMetric, ...]
    artifact_ids: tuple[str, ...]
    logs_sha256: str | None
    limitation: str | None

    def __post_init__(self) -> None:
        _validate_id(self.receipt_id, "receipt_id")
        _validate_id(self.experiment_id, "experiment_id")
        started = _utc_timestamp(self.started_at, "started_at")
        completed = _utc_timestamp(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("experiment completed_at must not precede started_at")
        validate_digest(self.dataset_sha256, "dataset_sha256")
        for digest in self.split_sha256s:
            validate_digest(digest, "split_sha256s")
        if self.logs_sha256 is not None:
            validate_digest(self.logs_sha256, "logs_sha256")
        if self.status == "completed" and not self.metrics:
            raise ValueError("completed experiment receipts require metrics")
        if self.status != "completed" and not self.limitation:
            raise ValueError("failed or blocked experiments require a limitation")
        if self.limitation is not None:
            _bounded_text(self.limitation, "limitation", 1_000)


def split_gap_days(split: SplitManifest) -> float:
    """Expose the deterministic split-gap calculation for conformance tools."""
    train_end = datetime.fromisoformat(split.train_end_at.replace("Z", "+00:00"))
    test_start = datetime.fromisoformat(split.test_start_at.replace("Z", "+00:00"))
    return (test_start - train_end).total_seconds() / 86_400
