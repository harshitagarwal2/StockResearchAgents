"""Polymarket prediction-market capability strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from stock_research_agents_host.adapters.providers._types import PolymarketFetch
from stock_research_agents_host.contracts import PredictionMarketsQuery, SourceBatch, SourceQuery


@dataclass(frozen=True, slots=True)
class PolymarketProvider:
    fetch_markets: PolymarketFetch

    capabilities = frozenset({"prediction_markets"})

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        return self.fetch_markets(cast(PredictionMarketsQuery, query))
