"""Host-owned source adapters for acquiring evidence.

This package may integrate with browser tools and provider SDKs. It
normalizes their outputs before anything crosses into ``stock_research_agents``.
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
    PredictionMarketsQuery,
    PricesQuery,
    RedditQuery,
    RegulatoryFilingsQuery,
    ResearchQuery,
    SourceBatch,
    SourceObservation,
    SourceQuery,
    StockTwitsQuery,
)
from .ports import SourcePort
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
    "PredictionMarketsQuery",
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
