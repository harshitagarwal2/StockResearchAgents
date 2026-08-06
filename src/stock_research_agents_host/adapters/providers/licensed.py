"""Licensed host market-data provider strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from stock_research_agents_host.adapters.providers._base import ProviderSupport
from stock_research_agents_host.adapters.providers.catalog import provider_specs
from stock_research_agents_host.contracts import SourceBatch, SourceQuery, validate_source_response
from stock_research_agents_host.ports import SourcePort


@dataclass(frozen=True, slots=True)
class LicensedMarketDataProvider:
    source: SourcePort | None
    support: ProviderSupport

    provider_id: ClassVar[str] = "licensed_market_data"
    specs: ClassVar = provider_specs(provider_id)

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if self.source is None:
            return self.support.terminal(capability, query, "unavailable", "A licensed host SourcePort is required.")
        return validate_source_response(capability, query, self.source.fetch(capability, query))
