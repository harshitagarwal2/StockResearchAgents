"""Fail-closed social-source provider strategies."""

from __future__ import annotations

from dataclasses import dataclass

from stock_research_agents_host.adapters.providers._types import TerminalBatch
from stock_research_agents_host.contracts import SourceBatch, SourceQuery, validate_source_response
from stock_research_agents_host.ports import SourcePort


@dataclass(frozen=True, slots=True)
class DeniedSocialProvider:
    reddit_source: SourcePort | None
    terminal: TerminalBatch

    capabilities = frozenset({"stocktwits", "reddit"})

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if capability == "stocktwits":
            return self.terminal(capability, query, "denied", "Approved StockTwits API access is not configured.")
        if self.reddit_source is None:
            return self.terminal(capability, query, "denied", "Host Reddit OAuth access is required.")
        return validate_source_response(capability, query, self.reddit_source.fetch(capability, query))
