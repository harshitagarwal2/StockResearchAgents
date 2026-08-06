"""Leakage-aware deterministic cohort evaluation for resolved binary forecasts."""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from .contracts import Forecast, OutcomeLedger
from .scoring import score_forecast

COHORT_SCHEMA_VERSION: Literal["research-quality-cohort.v1"] = "research-quality-cohort.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _instant(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class BinaryCalibrationPolicy:
    """Caller-approved conventions for one independently resolved binary cohort."""

    schema_version: Literal["research-quality-cohort.v1"]
    cohort_id: str
    evaluation_cutoff_at: str
    horizon: str
    resolution_rule: str
    minimum_sample_size: int
    probability_bin_edges: tuple[float, ...]
    require_distinct_instruments: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != COHORT_SCHEMA_VERSION:
            raise ValueError("unsupported binary calibration policy schema version")
        if _SAFE_ID.fullmatch(self.cohort_id) is None:
            raise ValueError("cohort_id must be a safe identifier")
        _instant(self.evaluation_cutoff_at, "evaluation_cutoff_at")
        if not self.horizon.strip() or len(self.horizon) > 256:
            raise ValueError("horizon must be a non-empty string no longer than 256 characters")
        if not self.resolution_rule.strip() or len(self.resolution_rule) > 2_000:
            raise ValueError("resolution_rule must be a non-empty string no longer than 2000 characters")
        if self.minimum_sample_size < 30:
            raise ValueError("minimum_sample_size must be at least 30")
        edges = self.probability_bin_edges
        if not 2 <= len(edges) <= 21 or edges[0] != 0.0 or edges[-1] != 1.0:
            raise ValueError("probability_bin_edges must contain 2-21 values spanning exactly 0.0 to 1.0")
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in edges):
            raise ValueError("probability_bin_edges must contain finite probabilities")
        if any(left >= right for left, right in zip(edges, edges[1:], strict=False)):
            raise ValueError("probability_bin_edges must be strictly increasing")
        if not self.require_distinct_instruments:
            raise ValueError("binary calibration cohorts must require distinct instruments")

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"probability_bin_edges": list(self.probability_bin_edges)}

    @classmethod
    def from_dict(cls, value: object) -> BinaryCalibrationPolicy:
        fields = {
            "schema_version",
            "cohort_id",
            "evaluation_cutoff_at",
            "horizon",
            "resolution_rule",
            "minimum_sample_size",
            "probability_bin_edges",
            "require_distinct_instruments",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("binary calibration policy must contain exactly the v1 fields")
        edges = value["probability_bin_edges"]
        if not isinstance(edges, list | tuple) or any(
            not isinstance(item, int | float) or isinstance(item, bool) for item in edges
        ):
            raise ValueError("probability_bin_edges must be an array of numbers")
        minimum = value["minimum_sample_size"]
        distinct = value["require_distinct_instruments"]
        if not isinstance(minimum, int) or isinstance(minimum, bool):
            raise ValueError("minimum_sample_size must be an integer")
        if not isinstance(distinct, bool):
            raise ValueError("require_distinct_instruments must be boolean")
        for field in ("schema_version", "cohort_id", "evaluation_cutoff_at", "horizon", "resolution_rule"):
            if not isinstance(value[field], str):
                raise ValueError(f"{field} must be a string")
        return cls(
            value["schema_version"],  # type: ignore[arg-type]
            value["cohort_id"],
            value["evaluation_cutoff_at"],
            value["horizon"],
            value["resolution_rule"],
            minimum,
            tuple(float(item) for item in edges),
            distinct,
        )


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower_bound: float
    upper_bound: float
    count: int
    mean_probability: float | None
    observed_frequency: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BinaryCalibrationReport:
    schema_version: Literal["research-quality-cohort.v1"]
    cohort_id: str
    status: Literal["evaluated", "insufficient_sample", "policy_blocked"]
    evaluation_cutoff_at: str
    sample_size: int
    mean_brier_score: float | None
    mean_log_loss: float | None
    expected_calibration_error: float | None
    bins: tuple[CalibrationBin, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "bins": [bucket.to_dict() for bucket in self.bins],
            "limitations": list(self.limitations),
        }


def _blocked(policy: BinaryCalibrationPolicy, sample_size: int, reason: str) -> BinaryCalibrationReport:
    return BinaryCalibrationReport(
        COHORT_SCHEMA_VERSION,
        policy.cohort_id,
        "policy_blocked",
        policy.evaluation_cutoff_at,
        sample_size,
        None,
        None,
        None,
        (),
        (reason,),
    )


def evaluate_binary_calibration(
    policy: BinaryCalibrationPolicy,
    cohort: tuple[tuple[Forecast, OutcomeLedger], ...],
) -> BinaryCalibrationReport:
    """Evaluate a fixed historical cohort without fitting or deploying a model."""
    sample_size = len(cohort)
    forecast_ids = [forecast.forecast_id for forecast, _ in cohort]
    if len(set(forecast_ids)) != sample_size:
        return _blocked(policy, sample_size, "Cohort forecast_id values must be unique.")
    instrument_ids = [forecast.instrument_id for forecast, _ in cohort]
    if len(set(instrument_ids)) != sample_size:
        return _blocked(policy, sample_size, "Each cohort member must use a distinct instrument_id.")

    cutoff = _instant(policy.evaluation_cutoff_at, "evaluation_cutoff_at")
    resolved: list[tuple[float, float]] = []
    for forecast, ledger in cohort:
        if forecast.forecast_kind != "binary_event":
            return _blocked(policy, sample_size, "Binary calibration cohorts may contain only binary_event forecasts.")
        if forecast.horizon != policy.horizon:
            return _blocked(policy, sample_size, "Every forecast must use the approved horizon.")
        if forecast.resolution_rule != policy.resolution_rule:
            return _blocked(policy, sample_size, "Every forecast must use the approved resolution rule.")
        if ledger.forecast_id != forecast.forecast_id:
            return _blocked(policy, sample_size, "Outcome ledger forecast_id does not match its forecast.")
        observation = ledger.active_observation
        if observation is None or observation.resolution_status != "resolved" or observation.binary_outcome is None:
            return _blocked(policy, sample_size, "Every cohort forecast requires an active resolved binary outcome.")
        if (
            _instant(observation.available_at, "outcome.available_at") > cutoff
            or _instant(observation.resolved_at, "outcome.resolved_at") > cutoff
        ):
            return _blocked(
                policy,
                sample_size,
                "Outcome availability and resolution must not exceed the evaluation cutoff.",
            )
        scorecard = score_forecast(forecast, ledger)
        if scorecard.status != "scored":
            return _blocked(
                policy,
                sample_size,
                "Every cohort member must pass per-forecast timing and scoring policy.",
            )
        probability = forecast.probability
        assert probability is not None
        resolved.append((probability, 1.0 if observation.binary_outcome else 0.0))

    if sample_size < policy.minimum_sample_size:
        return BinaryCalibrationReport(
            COHORT_SCHEMA_VERSION,
            policy.cohort_id,
            "insufficient_sample",
            policy.evaluation_cutoff_at,
            sample_size,
            None,
            None,
            None,
            (),
            (f"Cohort requires at least {policy.minimum_sample_size} independently resolved forecasts.",),
        )

    edges = policy.probability_bin_edges
    bin_values: list[list[tuple[float, float]]] = [[] for _ in range(len(edges) - 1)]
    for probability, outcome in resolved:
        index = min(bisect_right(edges, probability) - 1, len(bin_values) - 1)
        bin_values[index].append((probability, outcome))

    bins: list[CalibrationBin] = []
    weighted_error = 0.0
    for index, values in enumerate(bin_values):
        if values:
            mean_probability = sum(probability for probability, _ in values) / len(values)
            observed_frequency = sum(outcome for _, outcome in values) / len(values)
            weighted_error += len(values) * abs(mean_probability - observed_frequency)
        else:
            mean_probability = None
            observed_frequency = None
        bins.append(
            CalibrationBin(
                edges[index],
                edges[index + 1],
                len(values),
                mean_probability,
                observed_frequency,
            )
        )

    mean_brier = sum((probability - outcome) ** 2 for probability, outcome in resolved) / sample_size
    mean_log_loss = (
        sum(
            -(
                outcome * math.log(min(max(probability, 1e-15), 1 - 1e-15))
                + (1 - outcome) * math.log(1 - min(max(probability, 1e-15), 1 - 1e-15))
            )
            for probability, outcome in resolved
        )
        / sample_size
    )
    return BinaryCalibrationReport(
        COHORT_SCHEMA_VERSION,
        policy.cohort_id,
        "evaluated",
        policy.evaluation_cutoff_at,
        sample_size,
        mean_brier,
        mean_log_loss,
        weighted_error / sample_size,
        tuple(bins),
        ("This report evaluates an approved historical cohort; it does not fit or deploy a calibration model.",),
    )


def evaluate_binary_calibration_payload(payload: object) -> dict[str, object]:
    """Strict wire adapter for hosts that do not share Python contract objects."""
    if not isinstance(payload, dict) or set(payload) != {"policy", "cohort"}:
        raise ValueError("binary calibration payload must contain exactly policy and cohort")
    raw_cohort = payload["cohort"]
    if not isinstance(raw_cohort, list | tuple):
        raise ValueError("binary calibration cohort must be an array")
    cohort: list[tuple[Forecast, OutcomeLedger]] = []
    for index, item in enumerate(raw_cohort):
        if not isinstance(item, dict) or set(item) != {"forecast", "outcome_ledger"}:
            raise ValueError(f"cohort[{index}] must contain exactly forecast and outcome_ledger")
        cohort.append((Forecast.from_dict(item["forecast"]), OutcomeLedger.from_dict(item["outcome_ledger"])))
    return evaluate_binary_calibration(BinaryCalibrationPolicy.from_dict(payload["policy"]), tuple(cohort)).to_dict()


__all__ = [
    "BinaryCalibrationPolicy",
    "BinaryCalibrationReport",
    "COHORT_SCHEMA_VERSION",
    "CalibrationBin",
    "evaluate_binary_calibration",
    "evaluate_binary_calibration_payload",
]
