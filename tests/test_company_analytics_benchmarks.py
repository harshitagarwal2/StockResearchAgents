from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pytest

from tradingagents_portable.analytics_v1 import (
    CapitalBridge,
    DcfModelSpec,
    FinancialFact,
    FiscalPeriod,
    RatioDefinition,
    RestatementLink,
    SplitManifest,
)
from tradingagents_portable.analytics_v1.calculators import calculate_dcf, standard_ratio_calculator
from tradingagents_portable.research_quality_v1 import Forecast, OutcomeLedger, OutcomeObservation, score_forecast

BENCHMARKS = Path(__file__).parents[1] / "benchmarks"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((BENCHMARKS / name).read_text())


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _decimal_text(value: object, field: str) -> str:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return "0" if parsed == 0 else format(parsed.normalize(), "f")


def _normalize_ohlcv_rows(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    timestamps: set[datetime] = set()
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    for row in rows:
        if set(row) != required:
            raise ValueError("OHLCV rows require exactly timestamp, open, high, low, close, and volume")
        timestamp = _instant(str(row["timestamp"]))
        if timestamp in timestamps:
            raise ValueError("timestamps must be unique")
        timestamps.add(timestamp)
        values = {field: Decimal(_decimal_text(row[field], field)) for field in required - {"timestamp"}}
        if values["volume"] < 0:
            raise ValueError("volume must be non-negative")
        if values["high"] < max(values["open"], values["close"]):
            raise ValueError("high must cover open and close")
        if values["low"] > min(values["open"], values["close"]):
            raise ValueError("low must cover open and close")
        normalized.append(
            {
                "timestamp": timestamp.isoformat(),
                **{field: _decimal_text(values[field], field) for field in ("open", "high", "low", "close", "volume")},
            }
        )
    return sorted(normalized, key=lambda row: row["timestamp"])


def _point_in_time_fact(facts: tuple[FinancialFact, ...], cutoff_at: str) -> FinancialFact:
    visible = [fact for fact in facts if _instant(fact.available_at) <= _instant(cutoff_at)]
    if not visible:
        raise ValueError("no fact was available at the cutoff")
    return max(visible, key=lambda fact: _instant(fact.available_at))


@pytest.mark.parametrize(
    "case",
    _fixture("ohlcv_dirty.v1.json")["accepted_cases"],
    ids=lambda case: case["case_id"],
)
def test_ohlcv_oracle_normalizes_accepted_rows(case: dict[str, object]) -> None:
    assert _normalize_ohlcv_rows(case["rows"]) == case["expected"]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "case",
    _fixture("ohlcv_dirty.v1.json")["rejected_cases"],
    ids=lambda case: case["case_id"],
)
def test_ohlcv_oracle_rejects_dirty_rows(case: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=str(case["error"])):
        _normalize_ohlcv_rows(case["rows"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "case",
    _fixture("point_in_time_restatement.v1.json")["cutoff_cases"],
    ids=lambda case: case["cutoff_at"],
)
def test_point_in_time_oracle_uses_only_facts_available_at_cutoff(case: dict[str, str]) -> None:
    fixture = _fixture("point_in_time_restatement.v1.json")
    period = FiscalPeriod(**fixture["period"])
    facts = tuple(FinancialFact(period=period, **fact) for fact in fixture["facts"])
    RestatementLink(**fixture["restatement"])

    selected = _point_in_time_fact(facts, case["cutoff_at"])

    assert selected.fact_id == case["expected_fact_id"]
    assert selected.value == case["expected_value"]


def test_ratio_oracle_recomputes_declared_value_and_lineage_digest() -> None:
    fixture = _fixture("ratio_valuation.v1.json")
    case = fixture["ratio"]
    observation = standard_ratio_calculator().calculate(
        observation_id=case["observation_id"],
        definition=RatioDefinition(**case["definition"]),
        period=FiscalPeriod(**fixture["period"]),
        numerator=case["numerator"],
        denominator=case["denominator"],
        numerator_fact_ids=tuple(case["numerator_fact_ids"]),
        denominator_fact_ids=tuple(case["denominator_fact_ids"]),
        calculated_at=fixture["calculated_at"],
    )

    assert observation.value == case["expected_value"]
    assert observation.receipt.calculation_sha256 == case["expected_receipt_sha256"]


def test_dcf_oracle_recomputes_declared_values_and_lineage_digest() -> None:
    fixture = _fixture("ratio_valuation.v1.json")
    case = fixture["dcf"]
    model = dict(case["model"])
    model["forecast_period_ids"] = tuple(model["forecast_period_ids"])
    model["free_cash_flows"] = tuple(model["free_cash_flows"])
    model["capital_bridge"] = CapitalBridge(**model["capital_bridge"])
    valuation = calculate_dcf(
        DcfModelSpec(**model),
        valuation_id=case["valuation_id"],
        calculated_at=fixture["calculated_at"],
    )

    assert valuation.enterprise_value == case["expected_enterprise_value"]
    assert valuation.equity_value == case["expected_equity_value"]
    assert valuation.fair_value_per_share == case["expected_fair_value_per_share"]
    assert valuation.receipt.calculation_sha256 == case["expected_receipt_sha256"]


@pytest.mark.parametrize(
    "case",
    _fixture("time_split.v1.json")["accepted_cases"],
    ids=lambda case: case["split_id"],
)
def test_time_split_oracle_accepts_chronological_unshuffled_split(case: dict[str, object]) -> None:
    split = SplitManifest(**case)  # type: ignore[arg-type]

    assert split.shuffled is False
    assert split.purge_days > 0
    assert split.embargo_days >= 0


@pytest.mark.parametrize(
    "case",
    _fixture("time_split.v1.json")["rejected_cases"],
    ids=lambda case: case["case_id"],
)
def test_time_split_oracle_rejects_leakage_or_shuffle(case: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=str(case["error"])):
        SplitManifest(**case["split"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "case",
    _fixture("forecast_scoring.v1.json")["cases"],
    ids=lambda case: case["case_id"],
)
def test_forecast_oracle_resolves_to_declared_scorecard(case: dict[str, object]) -> None:
    forecast = Forecast.from_dict(case["forecast"])
    outcome = OutcomeObservation.from_dict(case["outcome"])
    ledger = OutcomeLedger("research-quality.v1", forecast.forecast_id).append(outcome)

    scorecard = score_forecast(forecast, ledger)

    assert scorecard.status == "scored"
    actual = {metric.name: metric.value for metric in scorecard.metrics}
    assert actual == pytest.approx(case["expected_metrics"])  # type: ignore[arg-type]
