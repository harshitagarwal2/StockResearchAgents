"""Licensed host market-data provider strategy."""

from __future__ import annotations

from dataclasses import dataclass

from stock_research_agents_host.adapters.providers._types import TerminalBatch
from stock_research_agents_host.contracts import SourceBatch, SourceQuery, validate_source_response
from stock_research_agents_host.ports import SourcePort


@dataclass(frozen=True, slots=True)
class LicensedMarketDataProvider:
    source: SourcePort | None
    terminal: TerminalBatch

    capabilities = frozenset({"prices", "indicators"})

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if self.source is None:
            return self.terminal(capability, query, "unavailable", "A licensed host SourcePort is required.")
        return validate_source_response(capability, query, self.source.fetch(capability, query))
