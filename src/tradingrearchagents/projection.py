"""Pure projection of an upstream completed AgentState into portable contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .contracts import (
    AnalystReport,
    Artifact,
    CapabilityMetadata,
    DebateSnapshot,
    ExecutionConfig,
    InstrumentIdentity,
    PersistenceMetadata,
    PortfolioDecision,
    ReportSections,
    ResearchDecision,
    RiskDecision,
    RunRequest,
    RunResult,
    TraderDecision,
)
from .reporting import build_report_artifacts
from .topology import build_legacy_topology


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _markdown_field(markdown: str, label: str) -> str:
    pattern = re.compile(
        rf"(?ims)^\s*\*\*{re.escape(label)}\*\*\s*:\s*(.+?)"
        r"(?=^\s*\*\*[^*\n]+\*\*\s*:|^\s*FINAL TRANSACTION PROPOSAL:|\Z)"
    )
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def _rating(markdown: str, label: str, allowed: set[str]) -> str:
    candidate = _markdown_field(markdown, label).strip().lower()
    if candidate in allowed:
        return candidate
    if label == "Action":
        fallback = re.search(
            r"(?i)FINAL TRANSACTION PROPOSAL:\s*\*\*(BUY|HOLD|SELL)\*\*",
            markdown,
        )
        if fallback and fallback.group(1).lower() in allowed:
            return fallback.group(1).lower()
    return "unknown"


def _optional_float(markdown: str, label: str) -> float | None:
    raw = _markdown_field(markdown, label)
    if not raw:
        return None
    try:
        value = float(raw.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _snapshot(value: object, *, risk: bool) -> DebateSnapshot:
    state = _mapping(value)
    roles: tuple[str, ...]
    if risk:
        roles = ("aggressive", "conservative", "neutral")
    else:
        roles = ("bull", "bear")
    return DebateSnapshot(
        history=_text(state.get("history")),
        role_histories={role: _text(state.get(f"{role}_history")) for role in roles},
        current_response=_text(state.get("current_response")),
        current_responses={role: _text(state.get(f"current_{role}_response")) for role in roles},
        judge_decision=_text(state.get("judge_decision")),
        count=int(state.get("count") or 0),
    )


def public_execution_config(request: RunRequest, config: Mapping[str, Any]) -> ExecutionConfig:
    """Select known non-secret settings; arbitrary provider config is never persisted."""
    vendor_config = _mapping(config.get("data_vendors"))
    vendors = tuple(sorted({_text(value) for value in vendor_config.values() if value}))
    return ExecutionConfig(
        executor=request.executor,
        llm_provider=_text(config.get("llm_provider")) or None,
        deep_model=_text(config.get("deep_think_llm")) or None,
        quick_model=_text(config.get("quick_think_llm")) or None,
        backend_url=_text(config.get("backend_url")) or None,
        output_language=_text(config.get("output_language")) or None,
        temperature=config.get("temperature") if isinstance(config.get("temperature"), int | float) else None,
        max_retries=config.get("llm_max_retries") if isinstance(config.get("llm_max_retries"), int) else None,
        google_thinking_level=_text(config.get("google_thinking_level")) or None,
        openai_reasoning_effort=_text(config.get("openai_reasoning_effort")) or None,
        anthropic_effort=_text(config.get("anthropic_effort")) or None,
        data_vendors=vendors,
        checkpoint_enabled=request.checkpoint_enabled,
        max_debate_rounds=request.debate_rounds,
        max_risk_discuss_rounds=request.risk_rounds,
    )


class LegacyStateProjector:
    """Map a frozen completed upstream state without parsing synthetic debate turns."""

    def project(
        self,
        *,
        run_id: str,
        request: RunRequest,
        final_state: Mapping[str, Any],
        processed_signal: object,
        config: Mapping[str, Any],
        started_at: str,
        completed_at: str,
        report_output_path: str | None = None,
    ) -> RunResult:
        reports = ReportSections(
            market_report=_text(final_state.get("market_report")),
            sentiment_report=_text(final_state.get("sentiment_report")),
            news_report=_text(final_state.get("news_report")),
            fundamentals_report=_text(final_state.get("fundamentals_report")),
        )
        analyst_reports = tuple(
            AnalystReport(analyst=name, thesis=content, content=content)
            for name, content in (
                ("market", reports.market_report),
                ("social", reports.sentiment_report),
                ("news", reports.news_report),
                ("fundamentals", reports.fundamentals_report),
            )
            if name in request.analysts and content
        )
        research_snapshot = _snapshot(final_state.get("investment_debate_state"), risk=False)
        risk_snapshot = _snapshot(final_state.get("risk_debate_state"), risk=True)
        investment_plan = _text(final_state.get("investment_plan"))
        trader_plan = _text(final_state.get("trader_investment_plan"))
        final_decision = _text(final_state.get("final_trade_decision"))
        signal = _text(processed_signal)
        research_recommendation = _rating(
            investment_plan,
            "Recommendation",
            {"buy", "overweight", "hold", "underweight", "sell"},
        )
        research_rationale = _markdown_field(investment_plan, "Rationale")
        research_actions = _markdown_field(investment_plan, "Strategic Actions")
        trader_action = _rating(trader_plan, "Action", {"buy", "hold", "sell"})
        trader_reasoning = _markdown_field(trader_plan, "Reasoning")
        normalized_signal = signal.strip().lower()
        supported_signals = {"buy", "overweight", "hold", "underweight", "sell"}
        portfolio_rating = _rating(final_decision, "Rating", supported_signals)
        if portfolio_rating == "unknown" and normalized_signal in supported_signals:
            portfolio_rating = normalized_signal

        # The upstream graph always persists its decision memory and final-state
        # log during a successful run.  An explicitly requested report tree is
        # an additional output, not the only write performed by the adapter.
        outputs = ["upstream_decision_memory", "upstream_state_log"]
        if report_output_path:
            outputs.append(f"explicit_report_tree:{report_output_path}")
        base_result = RunResult(
            run_id=run_id,
            request=request,
            instrument=InstrumentIdentity(
                requested_symbol=request.symbol,
                company_of_interest=_text(final_state.get("company_of_interest")) or request.symbol,
                trade_date=_text(final_state.get("trade_date")) or request.as_of_date,
                asset_type=request.asset_type,
                instrument_context=_text(final_state.get("instrument_context")),
            ),
            topology=build_legacy_topology(request.analysts, request.debate_rounds, request.risk_rounds),
            analyst_reports=analyst_reports,
            report_sections=reports,
            # Upstream exposes aggregate histories in its completed state, not a
            # turn ledger. Leave turn arrays empty rather than inventing turns.
            research_debate=(),
            research_debate_snapshot=research_snapshot,
            research_decision=ResearchDecision(
                recommendation=research_recommendation,  # type: ignore[arg-type]
                rationale=research_rationale or investment_plan,
                strategic_actions=research_actions,
                raw_markdown=investment_plan,
                projection_quality="parsed" if research_recommendation != "unknown" else "raw_markdown_only",
            ),
            trader_decision=TraderDecision(
                action=trader_action,  # type: ignore[arg-type]
                reasoning=trader_reasoning or trader_plan,
                entry_price=_optional_float(trader_plan, "Entry Price"),
                stop_loss=_optional_float(trader_plan, "Stop Loss"),
                position_sizing=_markdown_field(trader_plan, "Position Sizing") or None,
                raw_markdown=trader_plan,
                executable=False,
                execution_authority="none",
                submitted=False,
                caveats=("Projected research output is not an executable order.",),
                projection_quality="parsed" if trader_action != "unknown" else "raw_markdown_only",
            ),
            risk_debate=(),
            risk_debate_snapshot=risk_snapshot,
            risk_decision=RiskDecision(
                risk_level="unknown",
                constraints=("No broker or order execution is exposed by this adapter.",),
            ),
            portfolio_decision=PortfolioDecision(
                rating=portfolio_rating,  # type: ignore[arg-type]
                executive_summary=_markdown_field(final_decision, "Executive Summary") or final_decision,
                investment_thesis=_markdown_field(final_decision, "Investment Thesis"),
                price_target=_optional_float(final_decision, "Price Target"),
                time_horizon=_markdown_field(final_decision, "Time Horizon") or None,
                raw_markdown=final_decision,
                executable=False,
                execution_authority="none",
                submitted=False,
                projection_quality="parsed" if portfolio_rating != "unknown" else "raw_markdown_only",
            ),
            investment_plan=investment_plan,
            trader_investment_plan=trader_plan,
            portfolio_manager_decision=risk_snapshot.judge_decision,
            final_trade_decision=final_decision,
            processed_signal=signal,
            execution_config=public_execution_config(request, config),
            persistence=PersistenceMetadata(
                decision_memory_enabled=True,
                run_logging_enabled=True,
                checkpoint_enabled=request.checkpoint_enabled,
                writes_expected=True,
                outputs=tuple(outputs),
            ),
            capability=CapabilityMetadata(
                executor="legacy",
                observation_mode="legacy_post_run",
                deterministic=False,
                live_data=True,
                external_credentials_required=True,
                portable_boundary_credentials_required=False,
                host_tool_auth="environment_owned",
                upstream_business_logic=True,
            ),
            artifacts=(),
            warnings=(
                "Executed by upstream TradingAgentsGraph; provider and point-in-time guarantees "
                "are inherited from its configuration.",
                "Legacy events are a post-run projection and are not native per-stage telemetry.",
            ),
            started_at=started_at,
            completed_at=completed_at,
        )
        safe_legacy_state = {key: value for key, value in final_state.items() if key != "past_context"}
        legacy_artifacts = (
            Artifact(
                "data.legacy_state",
                "legacy_state",
                "Legacy final state",
                "application/json",
                safe_legacy_state,
            ),
            Artifact("data.legacy_signal", "legacy_signal", "Legacy processed signal", "text/plain", signal),
        )
        return replace(
            base_result,
            artifacts=(*build_report_artifacts(base_result), *legacy_artifacts),
        )
