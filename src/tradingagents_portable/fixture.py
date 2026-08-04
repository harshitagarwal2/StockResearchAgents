"""Deterministic, credential-free ORCL workflow executor."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from .contracts import (
    AnalystReport,
    CapabilityMetadata,
    DebateSnapshot,
    DebateTurn,
    EventKind,
    EvidenceItem,
    ExecutionConfig,
    InstrumentIdentity,
    PersistenceMetadata,
    PortfolioDecision,
    Provenance,
    ReportSections,
    ResearchDecision,
    RiskDecision,
    RunEvent,
    RunRequest,
    RunResult,
    RunStatus,
    TraderDecision,
)
from .reporting import build_report_artifacts
from .store import RUN_STORE, RunStore
from .topology import build_legacy_topology


def fixture_run_id(request: RunRequest) -> str:
    material = "|".join(
        (
            request.symbol,
            request.as_of_date,
            request.asset_type,
            ",".join(request.analysts),
            str(request.debate_rounds),
            str(request.risk_rounds),
        )
    )
    return "fixture-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def prepare_fixture(request: RunRequest) -> dict[str, Any]:
    if request.executor != "fixture":
        request = replace(request, executor="fixture")
    topology = build_legacy_topology(request.analysts, request.debate_rounds, request.risk_rounds)
    return {
        "run_id": fixture_run_id(request),
        "request": request.to_dict(),
        "topology": topology.to_dict(),
        "persistence": {
            "decision_memory_enabled": True,
            "run_logging_enabled": True,
            "checkpoint_enabled": request.checkpoint_enabled,
        },
        "deterministic": True,
        "external_credentials_required": False,
    }


def _fixture_evidence(request: RunRequest) -> tuple[EvidenceItem, ...]:
    retrieved = f"{request.as_of_date}T12:00:00+00:00"

    def provenance(source_type: str, source_uri: str) -> Provenance:
        return Provenance(
            provider="portable-fixture",
            source_type=source_type,
            source_uri=source_uri,
            retrieved_at=retrieved,
            source_date=request.as_of_date,
            fixture=True,
            notes=("Synthetic static values for integration testing; not live market data.",),
        )

    return (
        EvidenceItem(
            id="ev-market",
            category="market",
            title="ORCL deterministic market snapshot",
            summary="Fixture price is above its fixture 50-day average with moderate volatility.",
            values={
                "close_usd": 162.4,
                "sma_50_usd": 156.1,
                "rsi_14": 58.2,
                "source_quality": "synthetic_fixture",
                "metrics": [
                    {
                        "name": "close_usd",
                        "value": 162.4,
                        "unit": "USD",
                        "period": request.as_of_date,
                        "basis": "synthetic completed-session snapshot",
                    },
                    {
                        "name": "sma_50_usd",
                        "value": 156.1,
                        "unit": "USD",
                        "period": "synthetic 50-session window",
                        "trend": "fixture close above fixture average",
                    },
                    {
                        "name": "rsi_14",
                        "value": 58.2,
                        "period": "synthetic 14-session window",
                        "context": "constructive but not extended fixture regime",
                    },
                ],
                "catalysts": [
                    {
                        "catalyst": "Synthetic momentum remains above the fixture 50-day average",
                        "rank": 2,
                        "horizon": "next cutoff-valid market snapshot",
                        "trigger": "live close and volume confirm the synthetic regime",
                    }
                ],
                "risks": [
                    {
                        "risk": "Fixture momentum reversal",
                        "rank": 3,
                        "trigger": "cutoff-valid close breaks the live trend support",
                    }
                ],
                "monitoring_conditions": ["Compare the fixture close with cutoff-valid live pricing"],
            },
            provenance=provenance("synthetic_market", "fixture://orcl/market"),
            limitations=("Not suitable for pricing, backtesting, or an investment decision.",),
        ),
        EvidenceItem(
            id="ev-social",
            category="social",
            title="ORCL deterministic sentiment sample",
            summary="Fixture discussion is constructive but includes valuation concern.",
            values={
                "positive": 7,
                "neutral": 2,
                "negative": 3,
                "sample_size": 12,
                "source_quality": "synthetic_fixture",
                "metrics": {
                    "positive_mentions": {"value": 7, "unit": "mentions"},
                    "sample_size": {"value": 12, "unit": "mentions"},
                },
                "conflicts": ["Synthetic positive discussion conflicts with synthetic valuation concern"],
                "unknowns": ["Whether a live, representative sample would reproduce fixture sentiment"],
            },
            provenance=provenance("synthetic_sentiment", "fixture://orcl/social"),
            limitations=("Tiny synthetic sample; no population inference is valid.",),
        ),
        EvidenceItem(
            id="ev-news",
            category="news",
            title="ORCL deterministic news digest",
            summary="Fixture items balance cloud demand momentum against execution risk.",
            values={
                "items": 3,
                "positive": 1,
                "mixed": 1,
                "risk": 1,
                "source_quality": "synthetic_fixture",
                "metrics": {"article_count": 3, "positive_count": 1, "risk_count": 1},
                "articles": [
                    {
                        "headline": "Synthetic cloud demand scenario remains constructive",
                        "publisher": "StockResearchAgents fixture",
                        "published_at": request.as_of_date,
                        "source_quality": "synthetic_fixture",
                        "claim_type": "inference",
                        "verification_status": "unverified",
                        "summary": (
                            "A synthetic scenario models improving cloud demand; it is not a claim about Oracle's "
                            "actual results."
                        ),
                        "why_it_matters": (
                            "It demonstrates how a live demand catalyst should connect to the upside case and "
                            "monitoring ledger."
                        ),
                        "stance": "bull",
                        "url": "https://example.invalid/orcl/synthetic-cloud-demand",
                        "synthetic": True,
                    },
                    {
                        "headline": "Synthetic capacity expansion scenario has mixed execution effects",
                        "publisher": "StockResearchAgents fixture",
                        "published_at": request.as_of_date,
                        "source_quality": "synthetic_fixture",
                        "claim_type": "inference",
                        "verification_status": "unverified",
                        "summary": (
                            "A synthetic capacity build-out creates both revenue opportunity and execution pressure."
                        ),
                        "why_it_matters": (
                            "It tests whether the final thesis preserves a two-sided catalyst instead of flattening "
                            "it into sentiment."
                        ),
                        "stance": "neutral",
                        "url": "https://example.invalid/orcl/synthetic-capacity",
                        "synthetic": True,
                    },
                    {
                        "headline": "Synthetic leverage scenario highlights downside sensitivity",
                        "publisher": "StockResearchAgents fixture",
                        "published_at": request.as_of_date,
                        "source_quality": "synthetic_fixture",
                        "claim_type": "inference",
                        "verification_status": "unverified",
                        "summary": (
                            "A synthetic leverage stress case increases sensitivity to slower growth and valuation "
                            "compression."
                        ),
                        "why_it_matters": (
                            "It demonstrates a downside item that must remain visible even when the operating thesis "
                            "is constructive."
                        ),
                        "stance": "bear",
                        "url": "fixture://orcl/synthetic-leverage",
                        "synthetic": True,
                    },
                ],
                "catalysts": [
                    {
                        "catalyst": "Synthetic cloud demand acceleration",
                        "rank": 1,
                        "horizon": "next live earnings cycle",
                        "trigger": "cutoff-valid official results confirm durable demand acceleration",
                    }
                ],
                "risks": [
                    {
                        "risk": "Synthetic capacity execution shortfall",
                        "rank": 2,
                        "horizon": "next live earnings cycle",
                        "trigger": "official delivery or margin evidence misses the investment-case assumption",
                    }
                ],
                "monitoring_conditions": [
                    {"condition": "Replace every synthetic headline with cutoff-valid reporting"}
                ],
            },
            provenance=provenance("synthetic_news", "fixture://orcl/news"),
            limitations=("Synthetic headlines are not claims about real events.",),
        ),
        EvidenceItem(
            id="ev-fundamentals",
            category="fundamentals",
            title="ORCL deterministic fundamentals snapshot",
            summary="Fixture profile combines recurring revenue strength with leverage and valuation risk.",
            values={
                "revenue_growth_pct": 8.1,
                "operating_margin_pct": 31.4,
                "net_debt_to_ebitda": 3.2,
                "source_quality": "synthetic_fixture",
                "metrics": [
                    {
                        "name": "revenue_growth_pct",
                        "value": 8.1,
                        "unit": "percent",
                        "period": "synthetic trailing year",
                        "basis": "synthetic non-GAAP-neutral fixture value",
                    },
                    {
                        "name": "operating_margin_pct",
                        "value": 31.4,
                        "unit": "percent",
                        "period": "synthetic trailing year",
                        "basis": "synthetic operating-margin fixture value",
                    },
                    {
                        "name": "net_debt_to_ebitda",
                        "value": 3.2,
                        "unit": "ratio",
                        "period": request.as_of_date,
                        "basis": "synthetic leverage fixture value",
                    },
                ],
                "catalysts": [
                    {
                        "catalyst": "Synthetic recurring-revenue durability",
                        "rank": 3,
                        "horizon": "multi-quarter live validation",
                    }
                ],
                "risks": [
                    {
                        "risk": "Synthetic leverage and valuation compression",
                        "rank": 1,
                        "trigger": "live cash conversion or leverage misses the research assumption",
                    }
                ],
                "conflicts": [{"conflict": "Synthetic margin strength coexists with synthetic leverage risk"}],
                "unknowns": ["Cutoff-valid valuation and balance-sheet inputs"],
                "monitoring_conditions": ["Recalculate leverage from live point-in-time filings"],
            },
            provenance=provenance("synthetic_fundamentals", "fixture://orcl/fundamentals"),
            limitations=("Static synthetic values have no point-in-time financial validity.",),
        ),
    )


def _analyst_reports(request: RunRequest) -> tuple[AnalystReport, ...]:
    reports = {
        "market": AnalystReport("market", "Fixture momentum is constructive but not extended.", ("ev-market",), 0.68),
        "social": AnalystReport(
            "social", "Fixture sentiment is mildly positive with valuation disagreement.", ("ev-social",), 0.55
        ),
        "news": AnalystReport("news", "Fixture catalysts and execution risks are balanced.", ("ev-news",), 0.60),
        "fundamentals": AnalystReport(
            "fundamentals",
            "Fixture operating quality is offset by leverage and price sensitivity.",
            ("ev-fundamentals",),
            0.64,
        ),
    }
    return tuple(replace(reports[name], content=reports[name].thesis) for name in request.analysts)


def _research_debate(request: RunRequest) -> tuple[DebateTurn, ...]:
    turns: list[DebateTurn] = []
    prior: str | None = None
    turn_number = 1
    all_evidence = tuple(f"ev-{name}" for name in request.analysts)
    for round_number in range(1, request.debate_rounds + 1):
        bull = DebateTurn(
            debate="research",
            round=round_number,
            turn=turn_number,
            speaker="Bull Researcher",
            position=f"Round {round_number}: the fixture supports a cautious constructive research case.",
            responds_to=prior,
            evidence_ids=all_evidence,
        )
        turns.append(bull)
        prior = bull.speaker
        turn_number += 1
        bear = DebateTurn(
            debate="research",
            round=round_number,
            turn=turn_number,
            speaker="Bear Researcher",
            position=f"Round {round_number}: leverage, valuation, and synthetic-data limits weaken conviction.",
            responds_to=prior,
            evidence_ids=all_evidence,
        )
        turns.append(bear)
        prior = bear.speaker
        turn_number += 1
    return tuple(turns)


def _risk_debate(request: RunRequest) -> tuple[DebateTurn, ...]:
    positions = {
        "Aggressive Analyst": "The fixture upside case could justify further research under a strict loss budget.",
        "Conservative Analyst": "Synthetic evidence cannot justify capital exposure; preserve optionality.",
        "Neutral Analyst": "Record the thesis and risks, but take no executable action from this fixture.",
    }
    turns: list[DebateTurn] = []
    prior: str | None = "Trader"
    turn_number = 1
    for round_number in range(1, request.risk_rounds + 1):
        for speaker in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
            turn = DebateTurn(
                debate="risk",
                round=round_number,
                turn=turn_number,
                speaker=speaker,
                position=f"Round {round_number}: {positions[speaker]}",
                responds_to=prior,
                evidence_ids=("ev-market", "ev-fundamentals"),
            )
            turns.append(turn)
            prior = speaker
            turn_number += 1
    return tuple(turns)


def run_fixture(request: RunRequest, store: RunStore = RUN_STORE) -> tuple[RunResult, tuple[RunEvent, ...]]:
    if request.executor != "fixture":
        request = replace(request, executor="fixture")
    topology = build_legacy_topology(request.analysts, request.debate_rounds, request.risk_rounds)
    run_id = fixture_run_id(request)
    started = datetime.fromisoformat(request.as_of_date).replace(tzinfo=UTC, hour=12)
    evidence = _fixture_evidence(request)
    reports = _analyst_reports(request)
    research_debate = _research_debate(request)
    risk_debate = _risk_debate(request)
    research_decision = ResearchDecision(
        recommendation="hold",
        rationale="The static fixture supports further research, not a live investment conclusion.",
        strategic_actions="Validate the synthetic thesis with live, cutoff-valid evidence before changing the rating.",
        supporting_turns=tuple(turn.turn for turn in research_debate),
        confidence=0.61,
        projection_quality="synthetic",
    )
    research_decision = replace(research_decision, raw_markdown=research_decision.render_markdown())
    trader_decision = TraderDecision(
        action="hold",
        reasoning="Synthetic evidence supports a Hold research scenario until live evidence validates the thesis.",
        position_sizing="No analytical allocation from synthetic evidence.",
        caveats=("Synthetic evidence", "No live price", "No suitability assessment"),
        projection_quality="synthetic",
    )
    trader_decision = replace(trader_decision, raw_markdown=trader_decision.render_markdown())
    risk_decision = RiskDecision(
        risk_level="unknown",
        constraints=("No broker integration", "No order execution", "No position sizing"),
        unresolved=("Live valuation", "Current news", "User-specific risk tolerance"),
    )
    portfolio_decision = PortfolioDecision(
        rating="hold",
        executive_summary="Retain the fixture as a Hold research demonstration only; authorize no transaction.",
        investment_thesis=(
            "The synthetic evidence is adequate to exercise the workflow, not to support a live allocation."
        ),
        time_horizon="Until live evidence is supplied",
        projection_quality="synthetic",
    )
    portfolio_decision = replace(portfolio_decision, raw_markdown=portfolio_decision.render_markdown())
    report_by_name = {report.analyst: report.content for report in reports}
    report_sections = ReportSections(
        market_report=report_by_name.get("market", ""),
        sentiment_report=report_by_name.get("social", ""),
        news_report=report_by_name.get("news", ""),
        fundamentals_report=report_by_name.get("fundamentals", ""),
    )
    investment_plan = research_decision.raw_markdown
    trader_plan = trader_decision.raw_markdown
    portfolio_manager_decision = portfolio_decision.raw_markdown
    final_trade_decision = "Rating: Hold\nSynthetic fixture only; no portfolio transaction is authorized."
    base_result = RunResult(
        run_id=run_id,
        request=request,
        instrument=InstrumentIdentity(
            requested_symbol=request.symbol,
            company_of_interest="Oracle Corporation",
            trade_date=request.as_of_date,
            asset_type=request.asset_type,
            instrument_context="Deterministic synthetic NYSE common-stock fixture.",
        ),
        topology=topology,
        evidence=evidence,
        analyst_reports=reports,
        report_sections=report_sections,
        research_debate=research_debate,
        research_debate_snapshot=DebateSnapshot(
            history="\n".join(turn.position for turn in research_debate),
            role_histories={
                "bull": "\n".join(turn.position for turn in research_debate if turn.speaker.startswith("Bull")),
                "bear": "\n".join(turn.position for turn in research_debate if turn.speaker.startswith("Bear")),
            },
            current_response=research_debate[-1].position if research_debate else "",
            current_responses={
                "bull": next(
                    (turn.position for turn in reversed(research_debate) if turn.speaker.startswith("Bull")), ""
                ),
                "bear": next(
                    (turn.position for turn in reversed(research_debate) if turn.speaker.startswith("Bear")), ""
                ),
            },
            judge_decision=investment_plan,
            count=len(research_debate),
        ),
        research_decision=research_decision,
        trader_decision=trader_decision,
        risk_debate=risk_debate,
        risk_debate_snapshot=DebateSnapshot(
            history="\n".join(turn.position for turn in risk_debate),
            role_histories={
                role: "\n".join(turn.position for turn in risk_debate if turn.speaker.lower().startswith(role))
                for role in ("aggressive", "conservative", "neutral")
            },
            current_responses={
                role: next(
                    (turn.position for turn in reversed(risk_debate) if turn.speaker.lower().startswith(role)),
                    "",
                )
                for role in ("aggressive", "conservative", "neutral")
            },
            judge_decision=portfolio_manager_decision,
            count=len(risk_debate),
        ),
        risk_decision=risk_decision,
        portfolio_decision=portfolio_decision,
        investment_plan=investment_plan,
        trader_investment_plan=trader_plan,
        portfolio_manager_decision=portfolio_manager_decision,
        final_trade_decision=final_trade_decision,
        processed_signal="HOLD",
        execution_config=ExecutionConfig(
            executor="fixture",
            checkpoint_enabled=request.checkpoint_enabled,
            max_debate_rounds=request.debate_rounds,
            max_risk_discuss_rounds=request.risk_rounds,
        ),
        persistence=PersistenceMetadata(
            decision_memory_enabled=True,
            run_logging_enabled=True,
            checkpoint_enabled=request.checkpoint_enabled,
            writes_expected=False,
            outputs=("in_memory_run_store",),
        ),
        capability=CapabilityMetadata(),
        warnings=("All ORCL facts and values in this run are deterministic synthetic fixtures.",),
        started_at=started.isoformat(),
        completed_at=(started + timedelta(seconds=len(topology.stages) + 2)).isoformat(),
    )
    result = replace(base_result, artifacts=build_report_artifacts(base_result))

    events: list[RunEvent] = []
    tick = 0

    def emit(
        kind: EventKind, status: str, message: str, stage_id: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        nonlocal tick
        tick += 1
        events.append(
            RunEvent(
                id=f"{run_id}:{tick:04d}",
                run_id=run_id,
                sequence=tick,
                timestamp=(started + timedelta(seconds=tick)).isoformat(),
                kind=kind,
                stage_id=stage_id,
                status=status,
                message=message,
                data=data or {},
            )
        )

    emit(
        EventKind.RUN,
        RunStatus.RUNNING.value,
        "Deterministic fixture run started.",
        data={"checkpoint_enabled": request.checkpoint_enabled},
    )
    evidence_by_category = {item.category: item for item in evidence}
    report_by_analyst = {item.analyst: item for item in reports}
    research_by_id = {
        f"research.{turn.round}.{'bull' if turn.speaker.startswith('Bull') else 'bear'}": turn
        for turn in research_debate
    }
    risk_slug = {
        "Aggressive Analyst": "aggressive",
        "Conservative Analyst": "conservative",
        "Neutral Analyst": "neutral",
    }
    risk_by_id = {f"risk.{turn.round}.{risk_slug[turn.speaker]}": turn for turn in risk_debate}
    for stage in topology.stages:
        emit(
            EventKind.STAGE,
            "started",
            f"{stage.role} started.",
            stage.id,
            {"role": stage.role, "kind": stage.kind.value},
        )
        if stage.id.startswith("analyst."):
            analyst = stage.id.split(".", 1)[1]
            item = evidence_by_category[analyst]
            emit(EventKind.EVIDENCE, "collected", item.title, stage.id, {"evidence_id": item.id, "fixture": True})
            emit(
                EventKind.ARTIFACT,
                "created",
                f"{stage.role} report created.",
                stage.id,
                report_by_analyst[analyst].to_dict(),
            )
        elif stage.id in research_by_id:
            emit(
                EventKind.DEBATE,
                "turn_completed",
                research_by_id[stage.id].position,
                stage.id,
                research_by_id[stage.id].to_dict(),
            )
        elif stage.id == "research.manager":
            emit(EventKind.DECISION, "completed", research_decision.rationale, stage.id, research_decision.to_dict())
        elif stage.id == "trader":
            emit(EventKind.DECISION, "completed", trader_decision.plan, stage.id, trader_decision.to_dict())
        elif stage.id in risk_by_id:
            emit(
                EventKind.DEBATE,
                "turn_completed",
                risk_by_id[stage.id].position,
                stage.id,
                risk_by_id[stage.id].to_dict(),
            )
        elif stage.id == "portfolio":
            emit(EventKind.DECISION, "completed", portfolio_decision.summary, stage.id, portfolio_decision.to_dict())
        emit(EventKind.STAGE, "completed", f"{stage.role} completed.", stage.id)
    emit(EventKind.WARNING, "recorded", result.warnings[0], data={"prototype": True})
    emit(
        EventKind.RUN,
        RunStatus.COMPLETED.value,
        "Deterministic fixture run completed.",
        data={"artifact_ids": [a.id for a in result.artifacts]},
    )
    frozen_events = tuple(events)
    store.put(result, frozen_events)
    return result, frozen_events
