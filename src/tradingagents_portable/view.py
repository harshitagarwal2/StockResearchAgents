"""Lossless dashboard-oriented projection of a portable run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import RunEvent, RunResult
from .reporting import report_groups


@dataclass(frozen=True, slots=True)
class RunView:
    """UI-ready representation that keeps decisions and signal distinct."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload


def _badge(label: str, value: object, tone: str, detail: str) -> dict[str, object]:
    return {"label": label, "value": value, "tone": tone, "detail": detail}


def build_run_view(result: RunResult, events: tuple[RunEvent, ...]) -> RunView:
    """Expose every RunResult section without collapsing its meanings."""
    persistence = result.persistence.to_dict()
    capability = result.capability.to_dict()
    checkpoint = result.persistence.checkpoint_enabled
    completed = result.status.value == "completed"
    artifacts = [artifact.to_dict() for artifact in result.artifacts]
    artifact_ids = {artifact.id for artifact in result.artifacts}
    request = result.request.to_dict()
    # Adapter configuration may contain provider credentials.  The view keeps
    # the field visible while never reflecting its values.
    request["legacy_config"] = {
        "configured": bool(result.request.legacy_config),
        "keys": sorted(result.request.legacy_config),
        "values_redacted": bool(result.request.legacy_config),
    }

    payload: dict[str, Any] = {
        "schema_version": result.schema_version,
        "ok": True,
        "run_id": result.run_id,
        "overview": {
            "symbol": result.request.symbol,
            "company_of_interest": result.instrument.company_of_interest or result.request.symbol,
            "instrument_context": result.instrument.instrument_context,
            "as_of_date": result.request.as_of_date,
            "trade_date": result.instrument.trade_date or result.request.as_of_date,
            "asset_type": result.request.asset_type,
            "status": result.status.value,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "prototype_notice": result.prototype_notice,
            "warnings": list(result.warnings),
        },
        "request": request,
        "execution_config": result.execution_config.to_dict(),
        "topology": result.topology.to_dict(),
        "evidence": [item.to_dict() for item in result.evidence],
        "analyst_reports": [report.to_dict() for report in result.analyst_reports],
        "report_sections": result.report_sections.to_dict(),
        "reports": {
            "groups": report_groups(result.artifacts),
            "complete_artifact_id": "report.complete" if "report.complete" in artifact_ids else None,
        },
        "debates": {
            "research": {
                "turns": [turn.to_dict() for turn in result.research_debate],
                "snapshot": result.research_debate_snapshot.to_dict(),
            },
            "risk": {
                "turns": [turn.to_dict() for turn in result.risk_debate],
                "snapshot": result.risk_debate_snapshot.to_dict(),
            },
        },
        "decisions": {
            "research": result.research_decision.to_dict(),
            "trader": result.trader_decision.to_dict(),
            "risk": result.risk_decision.to_dict(),
            "portfolio": result.portfolio_decision.to_dict(),
        },
        "outputs": {
            "investment_plan": result.investment_plan,
            "trader_investment_plan": result.trader_investment_plan,
            "portfolio_manager_decision": result.portfolio_manager_decision,
            "final_trade_decision": result.final_trade_decision,
        },
        "signal": {
            "processed_signal": result.processed_signal,
            "source": "portfolio_rating",
            "meaning": "Derived from the Portfolio Manager rating; it is research output, never an order.",
            "executable": False,
            "execution_authority": "none",
            "submitted": False,
        },
        "persistence": {
            "metadata": persistence,
            "badges": [
                _badge("Decision memory", result.persistence.decision_memory_enabled, "info", "Executor behavior"),
                _badge("Run logging", result.persistence.run_logging_enabled, "info", "Executor behavior"),
                _badge(
                    "Checkpoint resume",
                    checkpoint,
                    "enabled" if checkpoint else "muted",
                    "Opt-in; disabled by default",
                ),
                _badge(
                    "Writes expected",
                    result.persistence.writes_expected,
                    "warning" if result.persistence.writes_expected else "safe",
                    ", ".join(result.persistence.outputs) or "No declared outputs",
                ),
            ],
        },
        "capability": {
            "metadata": capability,
            "badges": [
                _badge("Executor", result.capability.executor, "info", result.capability.observation_mode),
                _badge("Deterministic", result.capability.deterministic, "safe", "Replay characteristic"),
                _badge("Live data", result.capability.live_data, "warning", "Data-source characteristic"),
                _badge(
                    "Portable boundary credentials",
                    result.capability.portable_boundary_credentials_required,
                    "warning" if result.capability.portable_boundary_credentials_required else "safe",
                    "The portable host-plan/import boundary never accepts credentials",
                ),
                _badge("Host tool auth", result.capability.host_tool_auth, "info", "Owned by the selected harness"),
                _badge("Execution authority", "none", "safe", "No broker or order surface exists"),
            ],
        },
        "events": [event.to_dict() for event in events],
        "artifacts": artifacts,
        "actions": [
            {
                "id": "view_complete_report",
                "available": "report.complete" in artifact_ids,
                "reason": "Available from the canonical in-memory report bundle."
                if "report.complete" in artifact_ids
                else "No complete-report artifact was produced.",
            },
            {
                "id": "resume",
                "available": checkpoint and not completed,
                "reason": "Resume requires an opted-in checkpoint and an incomplete run."
                if not (checkpoint and not completed)
                else "An incomplete checkpoint-enabled run can be resumed by its executor.",
            },
            {
                "id": "cancel",
                "available": not completed,
                "reason": "Completed runs cannot be cancelled." if completed else "Run is still active.",
            },
        ],
    }
    return RunView(payload)
