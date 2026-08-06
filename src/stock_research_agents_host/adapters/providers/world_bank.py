"""World Bank macroeconomic capability strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from stock_research_agents_host.adapters.providers._types import WorldBankFetch
from stock_research_agents_host.contracts import MacroQuery, SourceBatch, SourceQuery


@dataclass(frozen=True, slots=True)
class WorldBankProvider:
    fetch_macro: WorldBankFetch

    capabilities = frozenset({"macro"})

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        return self.fetch_macro(cast(MacroQuery, query))
