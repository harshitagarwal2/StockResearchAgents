"""World Bank macroeconomic provider, including pagination and normalization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from stock_research_agents_host.adapters.providers._base import (
    ProviderPayloadError,
    ProviderSupport,
    instant,
    iso,
    query_instant,
)
from stock_research_agents_host.adapters.providers.catalog import provider_specs
from stock_research_agents_host.contracts import MacroQuery, NormalizedFact, SourceBatch, SourceObservation, SourceQuery

MAX_WORLD_BANK_PAGES = 100


@dataclass(frozen=True, slots=True)
class WorldBankProvider:
    support: ProviderSupport

    provider_id: ClassVar[str] = "world_bank"
    specs: ClassVar = provider_specs(provider_id)

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if not isinstance(query, MacroQuery):
            raise ValueError(f"{capability} requires its matching typed query")
        retrieved_at = iso(self.support.clock())
        retrieved_instant = instant(retrieved_at)
        vintage = query_instant(query.vintage_as_of)
        start = query_instant(query.start_time)
        end = query_instant(query.end_time)
        if retrieved_instant is None or retrieved_instant > vintage:
            return self.support.terminal(
                capability,
                query,
                "unavailable",
                "The World Bank current-data API cannot reconstruct a historical vintage after its cutoff.",
            )
        rows: list[SourceObservation] = []
        for region in query.regions:
            for series in query.series:
                total_pages = 1
                for page in range(1, MAX_WORLD_BANK_PAGES + 1):
                    response = self.support.request(
                        capability,
                        query,
                        f"https://api.worldbank.org/v2/country/{region}/indicator/{series}",
                        params={
                            "format": "json",
                            "date": f"{start.year}:{end.year}",
                            "page": page,
                            "per_page": 1000,
                        },
                        headers=self.support.headers,
                    )
                    if isinstance(response, SourceBatch):
                        return response
                    response_retrieved_at = iso(self.support.clock())
                    response_retrieved_instant = instant(response_retrieved_at)
                    if (
                        response_retrieved_at is None
                        or response_retrieved_instant is None
                        or response_retrieved_instant > vintage
                    ):
                        return self.support.terminal(
                            capability,
                            query,
                            "unavailable",
                            "The World Bank current-data API cannot reconstruct a historical vintage after its cutoff.",
                        )
                    if not isinstance(response.payload, list) or len(response.payload) < 2:
                        raise ProviderPayloadError("World Bank response must contain metadata and observations")
                    metadata, observations = response.payload[0], response.payload[1]
                    if page == 1:
                        total_pages = int(metadata.get("pages", 1)) if isinstance(metadata, Mapping) else 1
                        if not 1 <= total_pages <= MAX_WORLD_BANK_PAGES:
                            return self.support.terminal(
                                capability,
                                query,
                                "unavailable",
                                "World Bank pagination exceeds the bounded "
                                f"{MAX_WORLD_BANK_PAGES}-page retrieval limit.",
                            )
                    for index, row in enumerate(observations if isinstance(observations, list) else []):
                        if not isinstance(row, Mapping) or row.get("value") is None:
                            continue
                        year = str(row.get("date", ""))
                        observed = f"{year}-01-01T00:00:00+00:00"
                        observed_instant = instant(observed)
                        if observed_instant is None or not start <= observed_instant <= end:
                            continue
                        uri = f"https://api.worldbank.org/v2/country/{region}/indicator/{series}"
                        rows.append(
                            self.support.observation(
                                source_id=f"world-bank-{region}-{series}-{year}-{page}-{index}",
                                source_kind="other",
                                uri=uri,
                                observed=observed,
                                published=response_retrieved_at,
                                available=response_retrieved_at,
                                retrieved=response_retrieved_at,
                                provider="World Bank",
                                provider_version="api-v2",
                                license_id="world-bank-cc-by-4.0",
                                facts=(
                                    NormalizedFact("series", series),
                                    NormalizedFact("value", str(row["value"]), period=year),
                                    NormalizedFact("region", region),
                                    NormalizedFact("vintage_as_of", query.vintage_as_of),
                                ),
                                digest_value=row,
                            )
                        )
                    if page >= total_pages:
                        break
        return self.support.batch(
            capability,
            query,
            tuple(rows),
            "World Bank",
            "api-v2",
            "world-bank-cc-by-4.0",
            "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets",
            limitations=("World Bank API values are the current vintage; historical revision lineage is not exposed.",),
        )
