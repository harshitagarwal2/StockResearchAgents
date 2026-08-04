from __future__ import annotations

from hashlib import sha256

from test_research_quality_v1_contracts import _forecast

from tradingagents_portable.research_quality_v1 import (
    OutcomeLedger,
    OutcomeObservation,
    QualityPolicy,
    QualityRuleResult,
    ResearchQualityReceipt,
    validate_quality_bundle,
)


def _sha(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _receipt() -> ResearchQualityReceipt:
    return ResearchQualityReceipt(
        "research-quality.v1",
        "receipt-1",
        "run-1",
        "2026-08-03T01:00:00Z",
        QualityPolicy("policy-1", "1", _sha("policy")),
        _sha("workflow"),
        _sha("request"),
        _sha("dossier"),
        "tradingagents-portable",
        "0.1.0",
        (),
        (QualityRuleResult("rule-1", "pass", "ok"),),
        (),
    )


def test_conformance_accepts_timed_resolved_outcome() -> None:
    forecast = _forecast()
    outcome = OutcomeObservation(
        "research-quality.v1",
        "outcome-1",
        forecast.forecast_id,
        forecast.resolve_after,
        forecast.resolve_after,
        forecast.resolve_after,
        "resolved",
        True,
        None,
        None,
        None,
        ("doc-2",),
        "evaluator",
        None,
    )
    report = validate_quality_bundle(
        _receipt(), (forecast,), (OutcomeLedger("research-quality.v1", forecast.forecast_id).append(outcome),)
    )
    assert report.passed


def test_conformance_rejects_forecast_from_another_run() -> None:
    report = validate_quality_bundle(
        _receipt(),
        (_forecast(run_id="other-run", forecast_id="other-run.forecast-1"),),
        (),
    )
    assert not report.passed
    assert report.issues[0].check == "run_binding"


def test_conformance_rejects_pre_issuance_availability() -> None:
    forecast = _forecast()
    outcome = OutcomeObservation(
        "research-quality.v1",
        "outcome-1",
        forecast.forecast_id,
        "2026-08-02T00:00:00Z",
        "2026-08-02T00:00:00Z",
        "2026-08-04T00:00:00Z",
        "resolved",
        True,
        None,
        None,
        None,
        ("doc-2",),
        "evaluator",
        None,
    )
    report = validate_quality_bundle(
        _receipt(), (forecast,), (OutcomeLedger("research-quality.v1", forecast.forecast_id).append(outcome),)
    )
    assert any(item.check == "temporal" for item in report.issues)
