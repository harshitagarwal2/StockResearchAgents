from __future__ import annotations

from test_research_quality_v1_contracts import _forecast

from tradingagents_portable.research_quality_v1 import OutcomeLedger, OutcomeObservation, score_forecast


def _ledger(forecast, **changes):
    values = {
        "schema_version": "research-quality.v1",
        "observation_id": "outcome-1",
        "forecast_id": forecast.forecast_id,
        "observed_at": forecast.resolve_after,
        "available_at": forecast.resolve_after,
        "resolved_at": forecast.resolve_after,
        "resolution_status": "resolved",
        "binary_outcome": None,
        "numeric_outcome": None,
        "realized_return": None,
        "benchmark_return": None,
        "outcome_document_ids": ("doc-2",),
        "evaluator": "independent evaluator",
        "supersedes_observation_id": None,
    }
    values.update(changes)
    return OutcomeLedger("research-quality.v1", forecast.forecast_id).append(OutcomeObservation(**values))


def test_binary_scores_brier_and_log_loss() -> None:
    score = score_forecast(_forecast(), _ledger(_forecast(), binary_outcome=True))
    assert score.status == "scored"
    assert {item.name for item in score.metrics} == {"brier_score", "log_loss"}


def test_numeric_interval_directional_and_relative_scores() -> None:
    numeric = _forecast("numeric_metric")
    assert {item.name for item in score_forecast(numeric, _ledger(numeric, numeric_outcome=12.0)).metrics} == {
        "mae",
        "rmse",
        "signed_bias",
    }
    interval = _forecast("interval")
    assert (
        dict(
            (item.name, item.value)
            for item in score_forecast(interval, _ledger(interval, numeric_outcome=10.0)).metrics
        )["coverage"]
        == 1.0
    )
    directional = _forecast("directional_return")
    assert (
        dict(
            (item.name, item.value)
            for item in score_forecast(directional, _ledger(directional, realized_return=0.02)).metrics
        )["directional_accuracy"]
        == 1.0
    )
    relative = _forecast("benchmark_relative_return")
    assert (
        dict(
            (item.name, item.value)
            for item in score_forecast(relative, _ledger(relative, realized_return=0.03, benchmark_return=0.01)).metrics
        )["relative_return"]
        == 0.019999999999999997
    )


def test_missing_outcome_is_not_scored() -> None:
    forecast = _forecast("numeric_metric")
    score = score_forecast(forecast, _ledger(forecast))
    assert score.status == "insufficient_evidence"


def test_outcome_before_resolution_boundary_is_policy_blocked() -> None:
    forecast = _forecast()

    resolved_early = score_forecast(
        forecast,
        _ledger(
            forecast,
            observed_at="2026-09-02T00:00:00Z",
            available_at="2026-09-02T00:00:00Z",
            resolved_at="2026-09-02T00:00:00Z",
            binary_outcome=True,
        ),
    )
    available_early = score_forecast(
        forecast,
        _ledger(
            forecast,
            observed_at="2026-09-02T00:00:00Z",
            available_at="2026-09-02T00:00:00Z",
            resolved_at=forecast.resolve_after,
            binary_outcome=True,
        ),
    )

    assert resolved_early.status == "policy_blocked"
    assert available_early.status == "policy_blocked"
    assert not resolved_early.metrics
    assert not available_early.metrics


def test_outcome_at_resolution_boundary_is_scored() -> None:
    forecast = _forecast()

    score = score_forecast(forecast, _ledger(forecast, binary_outcome=True))

    assert score.status == "scored"
