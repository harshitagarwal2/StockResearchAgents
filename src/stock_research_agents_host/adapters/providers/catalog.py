"""Canonical typed capability ownership for research-data providers."""

from __future__ import annotations

from dataclasses import dataclass

from stock_research_agents_host.contracts import (
    CompanyNewsQuery,
    FinancialStatementsQuery,
    FundamentalsQuery,
    GlobalNewsQuery,
    IndicatorsQuery,
    MacroQuery,
    PredictionMarketsQuery,
    PricesQuery,
    RedditQuery,
    RegulatoryFilingsQuery,
    SourceQuery,
    StockTwitsQuery,
)


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """One source capability, its typed query, and its owning provider."""

    name: str
    query_type: type[SourceQuery]
    provider_id: str
    public_adapter_conformant: bool

    def validate(self, query: SourceQuery) -> None:
        if not isinstance(query, self.query_type):
            raise ValueError(f"{self.name} requires its matching typed query")


CAPABILITY_SPECS = (
    CapabilitySpec("prices", PricesQuery, "licensed_market_data", False),
    CapabilitySpec("indicators", IndicatorsQuery, "licensed_market_data", False),
    CapabilitySpec("regulatory_filings", RegulatoryFilingsQuery, "sec", True),
    CapabilitySpec("fundamentals", FundamentalsQuery, "sec", True),
    CapabilitySpec("financial_statements", FinancialStatementsQuery, "sec", True),
    CapabilitySpec("company_news", CompanyNewsQuery, "gdelt", True),
    CapabilitySpec("global_news", GlobalNewsQuery, "gdelt", True),
    CapabilitySpec("macro", MacroQuery, "world_bank", True),
    CapabilitySpec("prediction_markets", PredictionMarketsQuery, "polymarket", True),
    CapabilitySpec("stocktwits", StockTwitsQuery, "social", False),
    CapabilitySpec("reddit", RedditQuery, "social", False),
)

_SPECS_BY_NAME = {spec.name: spec for spec in CAPABILITY_SPECS}
if len(_SPECS_BY_NAME) != len(CAPABILITY_SPECS):  # pragma: no cover - import-time invariant
    raise RuntimeError("research capability catalog contains duplicate names")


def capability_spec(capability: str) -> CapabilitySpec:
    try:
        return _SPECS_BY_NAME[capability]
    except KeyError as exc:
        raise ValueError(f"no source provider route for capability: {capability}") from exc


def provider_specs(provider_id: str) -> tuple[CapabilitySpec, ...]:
    specs = tuple(spec for spec in CAPABILITY_SPECS if spec.provider_id == provider_id)
    if not specs:
        raise ValueError(f"source provider has no catalog entries: {provider_id}")
    return specs


def public_adapter_capabilities() -> tuple[str, ...]:
    return tuple(spec.name for spec in CAPABILITY_SPECS if spec.public_adapter_conformant)
