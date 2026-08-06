from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stock_research_agents.research_quality_v1 import (
    BinaryCalibrationPolicy,
    Forecast,
    OutcomeLedger,
    OutcomeObservation,
    evaluate_binary_calibration,
    evaluate_binary_calibration_payload,
)


def _pair(index: int, *, probability: float = 0.8, outcome: bool = True) -> tuple[Forecast, OutcomeLedger]:
    run_id = f"run-{index:03d}"
    forecast_id = f"{run_id}.forecast"
    forecast = Forecast(
        "research-quality.v1",
        forecast_id,
        run_id,
        f"instrument-{index:03d}",
        f"claim-{index:03d}",
        "binary_event",
        "Event resolves true",
        "2025-01-01T12:00:00+00:00",
        "2025-01-01T11:00:00+00:00",
        "2025-01-02T00:00:00+00:00",
        "one-day-close",
        "Resolved from the named primary source at the first close after the horizon.",
        probability,
        None,
        None,
        None,
        None,
        None,
        None,
        (f"evidence-{index:03d}",),
        "fixture cohort",
    )
    observation = OutcomeObservation(
        "research-quality.v1",
        f"observation-{index:03d}",
        forecast_id,
        "2025-01-03T00:00:00+00:00",
        "2025-01-03T00:00:00+00:00",
        "2025-01-03T00:00:00+00:00",
        "resolved",
        outcome,
        None,
        None,
        None,
        (f"outcome-source-{index:03d}",),
        "independent fixture evaluator",
        None,
    )
    return forecast, OutcomeLedger("research-quality.v1", forecast_id).append(observation)


def _policy() -> BinaryCalibrationPolicy:
    return BinaryCalibrationPolicy(
        schema_version="research-quality-cohort.v1",
        cohort_id="fixture-independent-binary-v1",
        evaluation_cutoff_at="2025-02-01T00:00:00+00:00",
        horizon="one-day-close",
        resolution_rule="Resolved from the named primary source at the first close after the horizon.",
        minimum_sample_size=30,
        probability_bin_edges=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        require_distinct_instruments=True,
    )


def test_binary_calibration_cohort_reports_deterministic_metrics() -> None:
    pairs = tuple(_pair(index, outcome=index < 24) for index in range(30))

    report = evaluate_binary_calibration(_policy(), pairs)

    assert report.status == "evaluated"
    assert report.sample_size == 30
    assert report.mean_brier_score == pytest.approx(0.16)
    assert report.mean_log_loss == pytest.approx(-(0.8 * math.log(0.8) + 0.2 * math.log(0.2)))
    assert report.expected_calibration_error == pytest.approx(0.0)
    populated = [bucket for bucket in report.bins if bucket.count]
    assert len(populated) == 1
    assert populated[0].mean_probability == pytest.approx(0.8)
    assert populated[0].observed_frequency == pytest.approx(0.8)
    assert report.limitations == (
        "This report evaluates an approved historical cohort; it does not fit or deploy a calibration model.",
    )


def test_binary_calibration_cohort_reports_insufficient_sample() -> None:
    report = evaluate_binary_calibration(_policy(), tuple(_pair(index) for index in range(3)))

    assert report.status == "insufficient_sample"
    assert report.sample_size == 3
    assert report.mean_brier_score is None
    assert "requires at least 30" in report.limitations[0]


def test_binary_calibration_cohort_rejects_instrument_leakage() -> None:
    pairs = list(_pair(index) for index in range(30))
    forecast, ledger = pairs[-1]
    pairs[-1] = (
        Forecast.from_dict({**forecast.to_dict(), "instrument_id": pairs[0][0].instrument_id}),
        ledger,
    )

    report = evaluate_binary_calibration(_policy(), tuple(pairs))

    assert report.status == "policy_blocked"
    assert "distinct instrument_id" in report.limitations[0]


def test_binary_calibration_cohort_rejects_late_outcome_and_convention_drift() -> None:
    pairs = list(_pair(index) for index in range(30))
    forecast, ledger = pairs[0]
    late = OutcomeObservation.from_dict(
        {
            **ledger.active_observation.to_dict(),  # type: ignore[union-attr]
            "observed_at": "2025-02-02T00:00:00+00:00",
            "available_at": "2025-02-02T00:00:00+00:00",
            "resolved_at": "2025-02-02T00:00:00+00:00",
        }
    )
    pairs[0] = (forecast, OutcomeLedger("research-quality.v1", forecast.forecast_id).append(late))

    late_report = evaluate_binary_calibration(_policy(), tuple(pairs))
    assert late_report.status == "policy_blocked"
    assert "evaluation cutoff" in late_report.limitations[0]

    mismatched, ledger = _pair(0)
    mismatched = Forecast.from_dict({**mismatched.to_dict(), "horizon": "one-week-close"})
    convention_report = evaluate_binary_calibration(_policy(), ((mismatched, ledger),))
    assert convention_report.status == "policy_blocked"
    assert "approved horizon" in convention_report.limitations[0]


def test_binary_calibration_wire_adapter_is_strict_and_equivalent() -> None:
    pairs = tuple(_pair(index, outcome=index < 24) for index in range(30))
    payload = {
        "policy": _policy().to_dict(),
        "cohort": [{"forecast": forecast.to_dict(), "outcome_ledger": ledger.to_dict()} for forecast, ledger in pairs],
    }

    assert evaluate_binary_calibration_payload(payload) == evaluate_binary_calibration(_policy(), pairs).to_dict()
    with pytest.raises(ValueError, match="exactly policy and cohort"):
        evaluate_binary_calibration_payload({**payload, "extra": True})


@settings(max_examples=25, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False, width=32),
            st.booleans(),
        ),
        min_size=30,
        max_size=30,
    )
)
def test_binary_cohort_metrics_remain_bounded_for_all_probabilities(
    observations: list[tuple[float, bool]],
) -> None:
    cohort = tuple(
        _pair(index, probability=float(probability), outcome=outcome)
        for index, (probability, outcome) in enumerate(observations)
    )

    report = evaluate_binary_calibration(_policy(), cohort)

    assert report.status == "evaluated"
    assert report.mean_brier_score is not None and 0 <= report.mean_brier_score <= 1
    assert report.mean_log_loss is not None and report.mean_log_loss >= 0
    assert report.expected_calibration_error is not None and 0 <= report.expected_calibration_error <= 1
