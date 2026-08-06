"""GDELT news provider, including query validation and normalization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, cast
from urllib.parse import urlsplit, urlunsplit

from stock_research_agents_host.adapters.providers._base import (
    ProviderPayloadError,
    ProviderSupport,
    digest,
    instant,
    iso,
    query_instant,
)
from stock_research_agents_host.adapters.providers.catalog import provider_specs
from stock_research_agents_host.contracts import (
    CompanyNewsQuery,
    GlobalNewsQuery,
    NormalizedFact,
    SourceBatch,
    SourceObservation,
    SourceQuery,
)


def _safe_uri(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        return fallback
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


@dataclass(frozen=True, slots=True)
class GdeltProvider:
    support: ProviderSupport

    provider_id: ClassVar[str] = "gdelt"
    specs: ClassVar = provider_specs(provider_id)

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if not isinstance(query, CompanyNewsQuery | GlobalNewsQuery):
            raise ValueError(f"{capability} requires its matching typed query")
        terms = query.symbol if isinstance(query, CompanyNewsQuery) else " OR ".join(query.topics)
        published_after = query_instant(query.published_after)
        published_before = query_instant(query.published_before)
        response = self.support.request(
            capability,
            query,
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": terms,
                "mode": "artlist",
                "format": "json",
                "maxrecords": query.max_items,
                "startdatetime": published_after.strftime("%Y%m%d%H%M%S"),
                "enddatetime": published_before.strftime("%Y%m%d%H%M%S"),
            },
            headers=self.support.headers,
        )
        if isinstance(response, SourceBatch):
            return response
        if not isinstance(response.payload, Mapping) or not isinstance(response.payload.get("articles"), list):
            raise ProviderPayloadError("GDELT response must contain an articles array")
        articles = cast(list[object], response.payload["articles"])
        rows: list[SourceObservation] = []
        seen_uris: set[str] = set()
        for article in articles:
            if not isinstance(article, Mapping):
                continue
            published = iso(article.get("seendate"))
            published_instant = instant(published)
            if (
                published is None
                or published_instant is None
                or not published_after <= published_instant <= published_before
            ):
                continue
            uri = _safe_uri(article.get("url"), f"https://api.gdeltproject.org/article/{digest(article)}")
            if uri in seen_uris:
                continue
            seen_uris.add(uri)
            facts = tuple(
                NormalizedFact(name, str(value))
                for name, value in (
                    ("title", article.get("title")),
                    ("domain", article.get("domain")),
                    ("language", article.get("language")),
                )
                if value
            )
            rows.append(
                self.support.observation(
                    source_id=f"gdelt-{digest(uri)[:24]}",
                    source_kind="news",
                    uri=uri,
                    observed=published,
                    published=published,
                    available=published,
                    provider="GDELT",
                    provider_version="DOC-2.0",
                    license_id="gdelt-metadata-links-v1",
                    facts=facts,
                    digest_value=article,
                )
            )
        saturated = len(articles) >= query.max_items
        gap = (
            ("GDELT returned the requested max_items limit; additional matching articles may exist.",)
            if saturated
            else ()
        )
        limitations = (
            "GDELT seendate is a seen/discovery timestamp, not a publisher publication timestamp; "
            "published_at uses it as an availability proxy.",
            *gap,
        )
        return self.support.batch(
            capability,
            query,
            tuple(rows[: query.max_items]),
            "GDELT",
            "DOC-2.0",
            "gdelt-metadata-links-v1",
            "https://www.gdeltproject.org/about.html",
            status="partial" if saturated else "complete",
            limitations=limitations,
            gaps=gap,
            redistributable="unknown",
            entitlement_limitation=(
                "Only GDELT metadata and publisher links are returned; no article body is redistributed."
            ),
        )
