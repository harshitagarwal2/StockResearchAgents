"""Internal callable contracts shared by provider strategies."""

from __future__ import annotations

from typing import Protocol

from stock_research_agents_host.contracts import (
    CompanyNewsQuery,
    FinancialStatementsQuery,
    FundamentalsQuery,
    GlobalNewsQuery,
    MacroQuery,
    PredictionMarketsQuery,
    RegulatoryFilingsQuery,
    SourceBatch,
    SourceQuery,
)


class TerminalBatch(Protocol):
    def __call__(self, capability: str, query: SourceQuery, status: str, limitation: str) -> SourceBatch: ...


class SecFilingsFetch(Protocol):
    def __call__(self, query: RegulatoryFilingsQuery) -> SourceBatch: ...


class SecFactsFetch(Protocol):
    def __call__(self, query: FundamentalsQuery | FinancialStatementsQuery, *, statements: bool) -> SourceBatch: ...


class GdeltFetch(Protocol):
    def __call__(self, capability: str, query: CompanyNewsQuery | GlobalNewsQuery) -> SourceBatch: ...


class PolymarketFetch(Protocol):
    def __call__(self, query: PredictionMarketsQuery) -> SourceBatch: ...


class WorldBankFetch(Protocol):
    def __call__(self, query: MacroQuery) -> SourceBatch: ...
