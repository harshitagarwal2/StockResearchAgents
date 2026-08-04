"""Host-owned adapters for acquiring evidence and running experiments.

This package may integrate with harness tools, browsers, and provider SDKs.  It
normalizes their outputs before anything crosses into ``tradingagents_portable``.
"""

from .contracts import (
    CompanyNewsQuery,
    FilingQuery,
    FinancialStatementsQuery,
    FundamentalQuery,
    FundamentalsQuery,
    GlobalNewsQuery,
    IndicatorsQuery,
    MacroQuery,
    MarketSeriesQuery,
    NormalizedFact,
    PricesQuery,
    RedditQuery,
    RegulatoryFilingsQuery,
    ResearchQuery,
    SourceBatch,
    SourceObservation,
    SourceQuery,
    StockTwitsQuery,
)
from .ports import (
    ExperimentRunnerPort,
    NotificationPort,
    OutcomeResolverPort,
    SourcePort,
)
from .source_router import SourceRouter

__all__ = [
    "ExperimentRunnerPort",
    "CompanyNewsQuery",
    "FinancialStatementsQuery",
    "FilingQuery",
    "FundamentalQuery",
    "FundamentalsQuery",
    "GlobalNewsQuery",
    "IndicatorsQuery",
    "MacroQuery",
    "MarketSeriesQuery",
    "NormalizedFact",
    "NotificationPort",
    "OutcomeResolverPort",
    "PricesQuery",
    "RedditQuery",
    "RegulatoryFilingsQuery",
    "ResearchQuery",
    "SourceBatch",
    "SourceObservation",
    "SourcePort",
    "SourceQuery",
    "SourceRouter",
    "StockTwitsQuery",
]
