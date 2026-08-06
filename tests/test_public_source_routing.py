from __future__ import annotations

from dataclasses import dataclass

import pytest

from stock_research_agents_host.adapters.providers.catalog import CapabilitySpec, provider_specs
from stock_research_agents_host.adapters.public import HTTPResponse, PublicResearchDataAdapter
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
    SourceBatch,
    SourceCompleteness,
    SourceEntitlement,
    SourcePagination,
    SourceProvenance,
    SourceQuery,
    StockTwitsQuery,
)
from stock_research_agents_host.source_router import ProviderSourceRouter

NOW = "2026-08-03T12:00:00+00:00"


class NoNetworkTransport:
    def get_json(self, url: str, *, params: object = None, headers: object = None) -> HTTPResponse:
        raise AssertionError(f"routing characterization unexpectedly used the network: {url}")


def _empty_batch(capability: str, query: SourceQuery) -> SourceBatch:
    return SourceBatch(
        capability=capability,
        query=query,
        cutoff=query.cutoff_at,
        status="complete",
        items=(),
        provenance=SourceProvenance("characterization", "1", "test", "1", NOW),
        entitlement=SourceEntitlement("allowed", True, "https://example.com/terms", "test-v1", None),
        completeness=SourceCompleteness(True),
        pagination=SourcePagination(False, None, 0, 1),
    )


@dataclass(frozen=True, slots=True)
class RecordingProvider:
    provider_id: str
    specs: tuple[CapabilitySpec, ...]
    calls: list[str]

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        self.calls.append(self.provider_id)
        return _empty_batch(capability, query)


def _queries() -> tuple[tuple[str, SourceQuery, str], ...]:
    return (
        (
            "prices",
            PricesQuery("prices", "ORCL", "2026-07-01T00:00:00+00:00", NOW, "1d"),
            "licensed_market_data",
        ),
        (
            "indicators",
            IndicatorsQuery("indicators", "ORCL", "rsi", "2026-07-01T00:00:00+00:00", NOW, {}),
            "licensed_market_data",
        ),
        (
            "regulatory_filings",
            RegulatoryFilingsQuery("filings", "ORCL", "US", ("10-Q",), "2026-07-01T00:00:00+00:00", NOW),
            "sec",
        ),
        (
            "fundamentals",
            FundamentalsQuery("fundamentals", "ORCL", ("Assets",), NOW),
            "sec",
        ),
        (
            "financial_statements",
            FinancialStatementsQuery("statements", "ORCL", ("balance_sheet",), ("2025",), NOW),
            "sec",
        ),
        (
            "company_news",
            CompanyNewsQuery("company-news", "ORCL", "2026-07-01T00:00:00+00:00", NOW, 10),
            "gdelt",
        ),
        (
            "global_news",
            GlobalNewsQuery("global-news", ("inflation",), "2026-07-01T00:00:00+00:00", NOW, 10),
            "gdelt",
        ),
        (
            "prediction_markets",
            PredictionMarketsQuery("markets", ("Oracle earnings",), NOW, 10),
            "polymarket",
        ),
        (
            "macro",
            MacroQuery(
                "macro",
                ("NY.GDP.MKTP.CD",),
                ("US",),
                "2024-01-01T00:00:00+00:00",
                "2025-12-31T00:00:00+00:00",
                NOW,
            ),
            "world_bank",
        ),
        (
            "reddit",
            RedditQuery("reddit", "ORCL", "2026-07-28T00:00:00+00:00", NOW, 10),
            "social",
        ),
    )


@pytest.mark.parametrize(("capability", "query", "expected_call"), _queries())
def test_capabilities_route_to_their_existing_provider_boundary(
    capability: str, query: SourceQuery, expected_call: str
) -> None:
    calls: list[str] = []

    providers = tuple(
        RecordingProvider(provider_id, provider_specs(provider_id), calls)
        for provider_id in ("licensed_market_data", "sec", "gdelt", "polymarket", "world_bank", "social")
    )

    result = ProviderSourceRouter(providers).fetch(capability, query)

    assert result.capability == capability
    assert calls == [expected_call]


def test_stocktwits_remains_fail_closed_without_invoking_a_host_source() -> None:
    query = StockTwitsQuery("stocktwits", "ORCL", "2026-07-28T00:00:00+00:00", NOW, 10)

    result = PublicResearchDataAdapter(NoNetworkTransport(), clock=lambda: NOW).fetch("stocktwits", query)

    assert result.status == "denied"


def test_capability_still_requires_its_matching_typed_query() -> None:
    query = PricesQuery("prices", "ORCL", "2026-07-01T00:00:00+00:00", NOW, "1d")

    with pytest.raises(ValueError, match="company_news requires its matching typed query"):
        PublicResearchDataAdapter(NoNetworkTransport(), clock=lambda: NOW).fetch("company_news", query)


def test_public_adapter_exposes_every_cataloged_capability_once() -> None:
    adapter = PublicResearchDataAdapter(NoNetworkTransport(), clock=lambda: NOW)

    assert adapter.capabilities == frozenset(
        {
            "prices",
            "indicators",
            "regulatory_filings",
            "fundamentals",
            "financial_statements",
            "company_news",
            "global_news",
            "macro",
            "prediction_markets",
            "stocktwits",
            "reddit",
        }
    )


def test_provider_router_rejects_catalog_ownership_mismatch() -> None:
    provider = RecordingProvider("wrong-owner", provider_specs("sec"), [])

    with pytest.raises(ValueError, match="catalog ownership mismatch"):
        ProviderSourceRouter((provider,))
