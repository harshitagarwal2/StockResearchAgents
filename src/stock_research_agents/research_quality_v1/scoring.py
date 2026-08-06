"""Deterministic forecast-kind-specific scoring for Research Quality v1."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from .contracts import Forecast, OutcomeLedger, OutcomeObservation


@dataclass(frozen=True, slots=True)
class ScoreMetric:
    name: str
    value: float
    unit: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QualityScorecard:
    forecast_id: str
    forecast_kind: str
    status: Literal["scored", "insufficient_evidence", "policy_blocked"]
    scored_at: str | None
    observation_id: str | None
    metrics: tuple[ScoreMetric, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "metrics": [item.to_dict() for item in self.metrics],
            "limitations": list(self.limitations),
        }


def _direction(value: float) -> str:
    return "up" if value > 0 else "down" if value < 0 else "flat"


def _insufficient(forecast: Forecast, observation: OutcomeObservation | None, reason: str) -> QualityScorecard:
    return QualityScorecard(
        forecast.forecast_id,
        forecast.forecast_kind,
        "insufficient_evidence",
        observation.resolved_at if observation else None,
        observation.observation_id if observation else None,
        (),
        (reason,),
    )


def score_forecast(forecast: Forecast, ledger: OutcomeLedger) -> QualityScorecard:
    """Score the active resolved observation without fitting or calibration."""
    if ledger.forecast_id != forecast.forecast_id:
        raise ValueError("ledger forecast_id does not match forecast")
    observation = ledger.active_observation
    if observation is None:
        return _insufficient(forecast, None, "No outcome observation has been recorded.")
    if observation.resolution_status != "resolved":
        return _insufficient(forecast, observation, "The active observation is not resolved.")
    if datetime.fromisoformat(observation.available_at.replace("Z", "+00:00")).astimezone(UTC) < datetime.fromisoformat(
        forecast.forecast_at.replace("Z", "+00:00")
    ).astimezone(UTC):
        return QualityScorecard(
            forecast.forecast_id,
            forecast.forecast_kind,
            "policy_blocked",
            observation.resolved_at,
            observation.observation_id,
            (),
            ("Outcome availability predates forecast issuance.",),
        )
    resolve_after = datetime.fromisoformat(forecast.resolve_after.replace("Z", "+00:00")).astimezone(UTC)
    if any(
        datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(UTC) < resolve_after
        for timestamp in (observation.available_at, observation.resolved_at)
    ):
        return QualityScorecard(
            forecast.forecast_id,
            forecast.forecast_kind,
            "policy_blocked",
            observation.resolved_at,
            observation.observation_id,
            (),
            ("Outcome availability and resolution must not predate the forecast resolution boundary.",),
        )

    metrics: tuple[ScoreMetric, ...]
    if forecast.forecast_kind == "binary_event":
        if observation.binary_outcome is None:
            return _insufficient(forecast, observation, "Resolved binary outcome is missing.")
        actual = 1.0 if observation.binary_outcome else 0.0
        probability = forecast.probability
        assert probability is not None
        clipped = min(max(probability, 1e-15), 1 - 1e-15)
        metrics = (
            ScoreMetric("brier_score", (probability - actual) ** 2, "squared_probability_error"),
            ScoreMetric("log_loss", -(actual * math.log(clipped) + (1 - actual) * math.log(1 - clipped)), "nats"),
        )
    elif forecast.forecast_kind == "numeric_metric":
        if observation.numeric_outcome is None:
            return _insufficient(forecast, observation, "Resolved numeric outcome is missing.")
        estimate = forecast.point_estimate
        assert estimate is not None and forecast.unit is not None
        error = estimate - observation.numeric_outcome
        metrics = (
            ScoreMetric("mae", abs(error), forecast.unit),
            ScoreMetric("rmse", abs(error), forecast.unit),
            ScoreMetric("signed_bias", error, forecast.unit),
        )
    elif forecast.forecast_kind == "interval":
        if observation.numeric_outcome is None:
            return _insufficient(forecast, observation, "Resolved numeric outcome is missing.")
        lower, upper = forecast.interval_lower, forecast.interval_upper
        assert lower is not None and upper is not None and forecast.unit is not None
        metrics = (
            ScoreMetric("coverage", 1.0 if lower <= observation.numeric_outcome <= upper else 0.0, "fraction"),
            ScoreMetric("interval_width", upper - lower, forecast.unit),
        )
    elif forecast.forecast_kind == "directional_return":
        if observation.realized_return is None:
            return _insufficient(forecast, observation, "Resolved return outcome is missing.")
        assert forecast.direction is not None
        metrics = (
            ScoreMetric(
                "directional_accuracy",
                1.0 if forecast.direction == _direction(observation.realized_return) else 0.0,
                "fraction",
            ),
            ScoreMetric("realized_return", observation.realized_return, "return"),
        )
    else:
        if observation.realized_return is None or observation.benchmark_return is None:
            return _insufficient(forecast, observation, "Resolved portfolio and benchmark returns are required.")
        relative = observation.realized_return - observation.benchmark_return
        assert forecast.direction is not None
        metrics = (
            ScoreMetric("directional_accuracy", 1.0 if forecast.direction == _direction(relative) else 0.0, "fraction"),
            ScoreMetric("relative_return", relative, "return"),
            ScoreMetric("benchmark_return", observation.benchmark_return, "return"),
        )
    return QualityScorecard(
        forecast.forecast_id,
        forecast.forecast_kind,
        "scored",
        observation.resolved_at,
        observation.observation_id,
        metrics,
        (),
    )
