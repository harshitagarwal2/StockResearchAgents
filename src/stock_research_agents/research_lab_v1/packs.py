"""Curated, versioned research-pack definitions."""

from __future__ import annotations

from .contracts import ResearchPackDefinition

_COMMON_STAGES = (
    "resolve.identity",
    "acquire.sources",
    "normalize.evidence",
    "analyze.fundamentals",
    "analyze.market",
    "synthesize.thesis",
    "challenge.thesis",
    "evaluate.quality",
    "publish.completed",
)
_COMMON_OUTPUTS = ("research_dossier.v1", "run_card.v1", "hypothesis_ledger.v1", "research_quality.v1")


def _pack(
    pack_id: str,
    title: str,
    purpose: str,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    history_policy: str,
) -> ResearchPackDefinition:
    return ResearchPackDefinition(
        pack_id=pack_id,
        title=title,
        purpose=purpose,
        required_capabilities=required,
        optional_capabilities=optional,
        stage_ids=_COMMON_STAGES,
        output_artifact_kinds=_COMMON_OUTPUTS,
        history_policy=history_policy,  # type: ignore[arg-type]
    )


RESEARCH_PACKS = (
    _pack(
        "initiating-coverage.v1",
        "Initiating coverage",
        "Build a full point-in-time company model, thesis, risks, catalysts, and monitoring plan.",
        ("official_filings", "fundamental_history", "market_history", "company_news"),
        ("earnings_transcripts", "licensed_analyst_research", "ownership_positioning"),
        "structural",
    ),
    _pack(
        "earnings-preview.v1",
        "Earnings preview",
        "Frame expectations, estimate ranges, key performance indicators, and scenario reactions before earnings.",
        ("official_filings", "fundamental_history", "market_history", "company_news"),
        ("estimate_consensus", "licensed_analyst_research", "options_positioning"),
        "event_driven",
    ),
    _pack(
        "earnings-update.v1",
        "Earnings update",
        "Reconcile reported results, guidance, revisions, and thesis changes after an earnings event.",
        ("earnings_release", "official_filings", "market_history", "company_news"),
        ("earnings_transcripts", "estimate_consensus", "licensed_analyst_research"),
        "event_driven",
    ),
    _pack(
        "model-update.v1",
        "Model update",
        "Refresh historical facts, assumptions, valuation, and sensitivity analysis with full calculation lineage.",
        ("official_filings", "fundamental_history", "market_history"),
        ("estimate_consensus", "peer_fundamentals"),
        "cycle_aware",
    ),
    _pack(
        "thesis-tracker.v1",
        "Thesis tracker",
        "Test prior hypotheses against new evidence and preserve supported, weakened, or refuted transitions.",
        ("company_news", "official_filings", "market_history"),
        ("earnings_transcripts", "licensed_analyst_research"),
        "cycle_aware",
    ),
    _pack(
        "catalyst-calendar.v1",
        "Catalyst calendar",
        "Map dated and conditional catalysts, dependencies, expected observations, and monitoring triggers.",
        ("company_news", "official_filings"),
        ("regulatory_events", "industry_events", "prediction_markets"),
        "event_driven",
    ),
    _pack(
        "sector-overview.v1",
        "Sector overview",
        "Compare structural drivers, peers, valuation regimes, and cross-company risks across a sector.",
        ("peer_fundamentals", "market_history", "industry_news"),
        ("licensed_analyst_research", "ownership_positioning"),
        "structural",
    ),
    _pack(
        "idea-screen.v1",
        "Idea screen",
        "Apply declared filters, rank candidates, and surface evidence gaps before deeper coverage.",
        ("fundamental_snapshot", "market_history"),
        ("estimate_consensus", "company_news", "ownership_positioning"),
        "user_bounded",
    ),
)

_BY_ID = {pack.pack_id: pack for pack in RESEARCH_PACKS}


def get_research_pack(pack_id: str) -> ResearchPackDefinition:
    try:
        return _BY_ID[pack_id]
    except KeyError as exc:
        raise KeyError(f"unknown research pack: {pack_id}") from exc


def research_pack_catalog() -> tuple[dict[str, object], ...]:
    return tuple(pack.to_dict() for pack in RESEARCH_PACKS)
