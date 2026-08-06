from __future__ import annotations

from hashlib import sha256

import pytest

from stock_research_agents.research_quality_v1 import (
    Forecast,
    OutcomeLedger,
    OutcomeObservation,
    QualityPolicy,
    QualityRuleResult,
    ResearchQualityReceipt,
    canonical_digest,
)


def _sha(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _forecast(kind: str = "binary_event", **changes: object) -> Forecast:
    values: dict[str, object] = {
        "schema_version": "research-quality.v1",
        "forecast_id": "run-1.forecast-1",
        "run_id": "run-1",
        "instrument_id": "equity-1",
        "claim_id": "claim-1",
        "forecast_kind": kind,
        "target": "Revenue outcome",
        "forecast_at": "2026-08-03T00:00:00Z",
        "information_cutoff_at": "2026-08-02T00:00:00Z",
        "resolve_after": "2026-09-03T00:00:00Z",
        "horizon": "30d",
        "resolution_rule": "Use the retained primary-source outcome.",
        "probability": 0.7 if kind == "binary_event" else None,
        "point_estimate": 10.0 if kind == "numeric_metric" else None,
        "interval_lower": 8.0 if kind == "interval" else None,
        "interval_upper": 12.0 if kind == "interval" else None,
        "direction": "up" if kind in {"directional_return", "benchmark_relative_return"} else None,
        "unit": "USD" if kind in {"numeric_metric", "interval"} else None,
        "benchmark_id": "SPY" if kind == "benchmark_relative_return" else None,
        "evidence_document_ids": ("doc-1",),
        "producer_provenance": "host-owned research harness",
    }
    values.update(changes)
    return Forecast(**values)  # type: ignore[arg-type]


def test_receipt_is_canonical_and_immutable() -> None:
    receipt = ResearchQualityReceipt(
        "research-quality.v1",
        "receipt-1",
        "run-1",
        "2026-08-03T01:00:00Z",
        QualityPolicy("policy-1", "1", _sha("policy")),
        _sha("workflow"),
        _sha("request"),
        _sha("dossier"),
        "stock-research-agents",
        "0.1.0",
        (("evaluate.final", _sha("stage")),),
        (QualityRuleResult("rule-1", "pass", "validated"),),
        (),
    )
    assert receipt.digest() == canonical_digest(receipt)
    assert receipt.to_dict()["stage_digests"] == [{"stage_id": "evaluate.final", "sha256": _sha("stage")}]


@pytest.mark.parametrize(
    "kind", ["binary_event", "numeric_metric", "interval", "directional_return", "benchmark_relative_return"]
)
def test_all_forecast_kinds_have_strict_valid_shape(kind: str) -> None:
    assert _forecast(kind).forecast_kind == kind


def test_forecast_rejects_mixed_kind_fields() -> None:
    with pytest.raises(ValueError, match="binary events"):
        _forecast(point_estimate=2.0)


def test_forecast_round_trip_rejects_unknown_fields() -> None:
    forecast = _forecast("numeric_metric")
    assert Forecast.from_dict(forecast.to_dict()) == forecast
    malformed = forecast.to_dict() | {"provider_api_key": "forbidden"}
    with pytest.raises(ValueError, match="credential-shaped"):
        Forecast.from_dict(malformed)


def test_outcomes_append_and_never_overwrite() -> None:
    forecast = _forecast()
    first = OutcomeObservation(
        "research-quality.v1",
        "outcome-1",
        forecast.forecast_id,
        "2026-08-04T00:00:00Z",
        "2026-08-04T00:00:00Z",
        "2026-08-04T00:00:00Z",
        "resolved",
        True,
        None,
        None,
        None,
        ("doc-2",),
        "independent evaluator",
        None,
    )
    corrected = OutcomeObservation(
        "research-quality.v1",
        "outcome-2",
        forecast.forecast_id,
        "2026-08-05T00:00:00Z",
        "2026-08-05T00:00:00Z",
        "2026-08-05T00:00:00Z",
        "resolved",
        False,
        None,
        None,
        None,
        ("doc-3",),
        "independent evaluator",
        "outcome-1",
    )
    ledger = OutcomeLedger("research-quality.v1", forecast.forecast_id).append(first).append(corrected)
    assert ledger.active_observation == corrected
    assert len(ledger.observations) == 2


def test_outcome_cannot_skip_active_supersession() -> None:
    with pytest.raises(ValueError, match="supersede"):
        OutcomeLedger("research-quality.v1", "forecast-1").append(
            OutcomeObservation(
                "research-quality.v1",
                "outcome-1",
                "forecast-1",
                "2026-08-04T00:00:00Z",
                "2026-08-04T00:00:00Z",
                "2026-08-04T00:00:00Z",
                "resolved",
                True,
                None,
                None,
                None,
                ("doc-2",),
                "evaluator",
                "missing",
            )
        )
