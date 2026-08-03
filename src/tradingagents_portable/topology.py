"""Versioned contract for the complete legacy TradingAgents workflow shape."""

from __future__ import annotations

from .contracts import StageKind, StageSpec, WorkflowTopology

ANALYST_ROLES = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}


def build_legacy_topology(
    analysts: tuple[str, ...] = ("market", "social", "news", "fundamentals"),
    debate_rounds: int = 1,
    risk_rounds: int = 1,
) -> WorkflowTopology:
    """Expand the graph into its exact logical stage sequence.

    Analyst tool-call loops are internal to each analyst stage. Research emits
    Bull then Bear for every configured round (2N turns). Risk emits Aggressive,
    Conservative, then Neutral for every configured round (3N turns).
    """
    stages: list[StageSpec] = []
    previous: tuple[str, ...] = ()
    ordinal = 1
    for analyst in analysts:
        stage_id = f"analyst.{analyst}"
        stages.append(StageSpec(stage_id, StageKind.ANALYST, ANALYST_ROLES[analyst], ordinal, previous))
        previous = (stage_id,)
        ordinal += 1

    for round_number in range(1, debate_rounds + 1):
        for slug, role in (("bull", "Bull Researcher"), ("bear", "Bear Researcher")):
            stage_id = f"research.{round_number}.{slug}"
            stages.append(StageSpec(stage_id, StageKind.RESEARCH_DEBATE, role, ordinal, previous))
            previous = (stage_id,)
            ordinal += 1

    stages.append(StageSpec("research.manager", StageKind.RESEARCH_MANAGER, "Research Manager", ordinal, previous))
    previous = ("research.manager",)
    ordinal += 1
    stages.append(StageSpec("trader", StageKind.TRADER, "Trader", ordinal, previous))
    previous = ("trader",)
    ordinal += 1

    risk_roles = (
        ("aggressive", "Aggressive Analyst"),
        ("conservative", "Conservative Analyst"),
        ("neutral", "Neutral Analyst"),
    )
    for round_number in range(1, risk_rounds + 1):
        for slug, role in risk_roles:
            stage_id = f"risk.{round_number}.{slug}"
            stages.append(StageSpec(stage_id, StageKind.RISK_DEBATE, role, ordinal, previous))
            previous = (stage_id,)
            ordinal += 1

    stages.append(StageSpec("portfolio", StageKind.PORTFOLIO, "Portfolio Manager", ordinal, previous))
    return WorkflowTopology(
        analysts=analysts,
        debate_rounds=debate_rounds,
        risk_rounds=risk_rounds,
        stages=tuple(stages),
    )
