"""Fail-closed social-source provider strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from stock_research_agents_host.adapters.providers._base import ProviderSupport
from stock_research_agents_host.adapters.providers.catalog import provider_specs
from stock_research_agents_host.contracts import SourceBatch, SourceQuery, validate_source_response
from stock_research_agents_host.ports import SourcePort


@dataclass(frozen=True, slots=True)
class DeniedSocialProvider:
    reddit_source: SourcePort | None
    support: ProviderSupport

    provider_id: ClassVar[str] = "social"
    specs: ClassVar = provider_specs(provider_id)

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if capability == "stocktwits":
            return self.support.terminal(
                capability, query, "denied", "Approved StockTwits API access is not configured."
            )
        if self.reddit_source is None:
            return self.support.terminal(capability, query, "denied", "Host Reddit OAuth access is required.")
        return validate_source_response(capability, query, self.reddit_source.fetch(capability, query))
