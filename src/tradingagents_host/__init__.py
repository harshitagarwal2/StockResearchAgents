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
from .source_portfolio import (
    MAX_SOURCE_PORTFOLIO_OBSERVATIONS,
    MAX_SOURCE_PORTFOLIO_PROVIDERS,
    SOURCE_PORTFOLIO_RECEIPT_VERSION,
    ExactDuplicateCluster,
    SourceObservationRef,
    SourcePortfolioCollector,
    SourcePortfolioReceipt,
    SourceProviderAttempt,
)
from .source_router import SourceRouter

__all__ = [
    "ExperimentRunnerPort",
    "ExactDuplicateCluster",
    "CompanyNewsQuery",
    "FinancialStatementsQuery",
    "FilingQuery",
    "FundamentalQuery",
    "FundamentalsQuery",
    "GlobalNewsQuery",
    "IndicatorsQuery",
    "MacroQuery",
    "MarketSeriesQuery",
    "MAX_SOURCE_PORTFOLIO_OBSERVATIONS",
    "MAX_SOURCE_PORTFOLIO_PROVIDERS",
    "NormalizedFact",
    "NotificationPort",
    "OutcomeResolverPort",
    "PricesQuery",
    "RedditQuery",
    "RegulatoryFilingsQuery",
    "ResearchQuery",
    "SOURCE_PORTFOLIO_RECEIPT_VERSION",
    "SourceBatch",
    "SourceObservation",
    "SourceObservationRef",
    "SourcePortfolioCollector",
    "SourcePortfolioReceipt",
    "SourcePort",
    "SourceProviderAttempt",
    "SourceQuery",
    "SourceRouter",
    "StockTwitsQuery",
]
