"""GDELT news capability strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from stock_research_agents_host.adapters.providers._types import GdeltFetch
from stock_research_agents_host.contracts import CompanyNewsQuery, GlobalNewsQuery, SourceBatch, SourceQuery


@dataclass(frozen=True, slots=True)
class GdeltProvider:
    fetch_news: GdeltFetch

    capabilities = frozenset({"company_news", "global_news"})

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        return self.fetch_news(capability, cast(CompanyNewsQuery | GlobalNewsQuery, query))
