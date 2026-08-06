"""SEC capability strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from stock_research_agents_host.adapters.providers._types import SecFactsFetch, SecFilingsFetch
from stock_research_agents_host.contracts import (
    FinancialStatementsQuery,
    FundamentalsQuery,
    RegulatoryFilingsQuery,
    SourceBatch,
    SourceQuery,
)


@dataclass(frozen=True, slots=True)
class SecProvider:
    fetch_filings: SecFilingsFetch
    fetch_facts: SecFactsFetch

    capabilities = frozenset({"regulatory_filings", "fundamentals", "financial_statements"})

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if capability == "regulatory_filings":
            return self.fetch_filings(cast(RegulatoryFilingsQuery, query))
        statements = capability == "financial_statements"
        return self.fetch_facts(
            cast(FundamentalsQuery | FinancialStatementsQuery, query),
            statements=statements,
        )
