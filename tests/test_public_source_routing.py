from __future__ import annotations

import pytest

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


class RecordingSource:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        self._calls.append(capability)
        return _empty_batch(capability, query)


class RecordingAdapter(PublicResearchDataAdapter):
    def __init__(self, calls: list[str]) -> None:
        super().__init__(
            NoNetworkTransport(),
            licensed_source=RecordingSource(calls),
            reddit_oauth_source=RecordingSource(calls),
            clock=lambda: NOW,
        )
        self._calls = calls

    def _sec_filings(self, query: RegulatoryFilingsQuery) -> SourceBatch:
        self._calls.append("sec_filings")
        return _empty_batch("regulatory_filings", query)

    def _sec_facts(self, query: FundamentalsQuery | FinancialStatementsQuery, *, statements: bool) -> SourceBatch:
        self._calls.append("sec_statements" if statements else "sec_fundamentals")
        return _empty_batch("financial_statements" if statements else "fundamentals", query)

    def _gdelt(self, capability: str, query: CompanyNewsQuery | GlobalNewsQuery) -> SourceBatch:
        self._calls.append("gdelt")
        return _empty_batch(capability, query)

    def _polymarket(self, query: PredictionMarketsQuery) -> SourceBatch:
        self._calls.append("polymarket")
        return _empty_batch("prediction_markets", query)

    def _world_bank(self, query: MacroQuery) -> SourceBatch:
        self._calls.append("world_bank")
        return _empty_batch("macro", query)


def _queries() -> tuple[tuple[str, SourceQuery, str], ...]:
    return (
        (
            "prices",
            PricesQuery("prices", "ORCL", "2026-07-01T00:00:00+00:00", NOW, "1d"),
            "prices",
        ),
        (
            "indicators",
            IndicatorsQuery("indicators", "ORCL", "rsi", "2026-07-01T00:00:00+00:00", NOW, {}),
            "indicators",
        ),
        (
            "regulatory_filings",
            RegulatoryFilingsQuery("filings", "ORCL", "US", ("10-Q",), "2026-07-01T00:00:00+00:00", NOW),
            "sec_filings",
        ),
        (
            "fundamentals",
            FundamentalsQuery("fundamentals", "ORCL", ("Assets",), NOW),
            "sec_fundamentals",
        ),
        (
            "financial_statements",
            FinancialStatementsQuery("statements", "ORCL", ("balance_sheet",), ("2025",), NOW),
            "sec_statements",
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
            "reddit",
        ),
    )


@pytest.mark.parametrize(("capability", "query", "expected_call"), _queries())
def test_capabilities_route_to_their_existing_provider_boundary(
    capability: str, query: SourceQuery, expected_call: str
) -> None:
    calls: list[str] = []

    result = RecordingAdapter(calls).fetch(capability, query)

    assert result.capability == capability
    assert calls == [expected_call]


def test_stocktwits_remains_fail_closed_without_invoking_a_host_source() -> None:
    calls: list[str] = []
    query = StockTwitsQuery("stocktwits", "ORCL", "2026-07-28T00:00:00+00:00", NOW, 10)

    result = RecordingAdapter(calls).fetch("stocktwits", query)

    assert result.status == "denied"
    assert calls == []


def test_capability_still_requires_its_matching_typed_query() -> None:
    query = PricesQuery("prices", "ORCL", "2026-07-01T00:00:00+00:00", NOW, "1d")

    with pytest.raises(ValueError, match="company_news requires its matching typed query"):
        RecordingAdapter([]).fetch("company_news", query)
