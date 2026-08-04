"""Cross-record conformance for the Research Quality v1 sidecar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import Forecast, OutcomeLedger, ResearchQualityReceipt
from .scoring import score_forecast


@dataclass(frozen=True, slots=True)
class QualityConformanceIssue:
    check: str
    path: str
    detail: str


@dataclass(frozen=True, slots=True)
class QualityConformanceReport:
    issues: tuple[QualityConformanceIssue, ...]
    schema_version: str = "research-quality.v1"

    @property
    def passed(self) -> bool:
        return not self.issues


def validate_quality_bundle(
    receipt: ResearchQualityReceipt,
    forecasts: tuple[Forecast, ...],
    ledgers: tuple[OutcomeLedger, ...],
) -> QualityConformanceReport:
    """Validate safe provenance, forecast identity, append-only outcomes, and scoring readiness."""
    issues: list[QualityConformanceIssue] = []
    forecast_ids = [item.forecast_id for item in forecasts]
    if len(forecast_ids) != len(set(forecast_ids)):
        issues.append(QualityConformanceIssue("identity", "$.forecasts", "forecast IDs must be unique"))
    by_forecast = {item.forecast_id: item for item in forecasts}
    ledger_ids = [item.forecast_id for item in ledgers]
    if len(ledger_ids) != len(set(ledger_ids)):
        issues.append(QualityConformanceIssue("identity", "$.ledgers", "ledger forecast IDs must be unique"))
    for index, forecast in enumerate(forecasts):
        if forecast.run_id != receipt.run_id:
            issues.append(
                QualityConformanceIssue(
                    "run_binding", f"$.forecasts[{index}].run_id", "forecast must belong to receipt run_id"
                )
            )
        if datetime.fromisoformat(forecast.information_cutoff_at.replace("Z", "+00:00")) > datetime.fromisoformat(
            forecast.forecast_at.replace("Z", "+00:00")
        ):
            issues.append(
                QualityConformanceIssue(
                    "temporal", f"$.forecasts[{index}]", "information cutoff follows forecast issuance"
                )
            )
    for index, ledger in enumerate(ledgers):
        ledger_forecast = by_forecast.get(ledger.forecast_id)
        if ledger_forecast is None:
            issues.append(
                QualityConformanceIssue(
                    "references", f"$.ledgers[{index}].forecast_id", "ledger references an unknown forecast"
                )
            )
            continue
        observation = ledger.active_observation
        if observation is not None and datetime.fromisoformat(
            observation.available_at.replace("Z", "+00:00")
        ) < datetime.fromisoformat(ledger_forecast.forecast_at.replace("Z", "+00:00")):
            issues.append(
                QualityConformanceIssue(
                    "temporal", f"$.ledgers[{index}]", "outcome availability predates forecast issuance"
                )
            )
        scorecard = score_forecast(ledger_forecast, ledger)
        if scorecard.status == "policy_blocked":
            issues.append(QualityConformanceIssue("evaluation_policy", f"$.ledgers[{index}]", scorecard.limitations[0]))
    return QualityConformanceReport(tuple(issues))
