"""Polymarket provider, including bounded payload validation and normalization."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import ClassVar, cast
from urllib.parse import quote

from stock_research_agents_host.adapters.providers._base import (
    ProviderPayloadError,
    ProviderSupport,
    digest,
    instant,
    iso,
    query_instant,
)
from stock_research_agents_host.adapters.providers.catalog import provider_specs
from stock_research_agents_host.contracts import NormalizedFact, PredictionMarketsQuery, SourceBatch, SourceQuery

MAX_EVENTS = 25
MAX_MARKETS_PER_EVENT = 100
MAX_TOTAL_MARKETS = MAX_EVENTS * MAX_MARKETS_PER_EVENT
MAX_TOTAL_RESULTS = 1_000_000
MAX_SLUG_CHARS = 256
MAX_QUESTION_CHARS = 2_000
MAX_SCALAR_CHARS = 2_000
MAX_ARRAY_CHARS = 4_096
SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
TERMS_URL = "https://polymarket.com/tos"


def _array(value: object, field: str, *, strings_only: bool) -> list[str]:
    if isinstance(value, str):
        if len(value) > MAX_ARRAY_CHARS:
            raise ProviderPayloadError(f"Polymarket {field} exceeds the bounded encoded-array size")
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProviderPayloadError(f"Polymarket {field} must be a JSON array") from exc
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ProviderPayloadError(f"Polymarket {field} must contain between 1 and 32 items")
    normalized: list[str] = []
    for item in value:
        if strings_only:
            if not isinstance(item, str) or not item.strip() or len(item) > 256:
                raise ProviderPayloadError(f"Polymarket {field} must contain bounded non-empty strings")
            normalized.append(item)
            continue
        if isinstance(item, bool) or not isinstance(item, str | int | float):
            raise ProviderPayloadError(f"Polymarket {field} must contain numeric values")
        if isinstance(item, str) and (not item.strip() or len(item) > 64):
            raise ProviderPayloadError(f"Polymarket {field} must contain bounded numeric values")
        try:
            numeric = Decimal(str(item))
        except (InvalidOperation, ValueError) as exc:
            raise ProviderPayloadError(f"Polymarket {field} must contain numeric values") from exc
        if not numeric.is_finite() or not Decimal(0) <= numeric <= Decimal(1):
            raise ProviderPayloadError(f"Polymarket {field} values must be probabilities between 0 and 1")
        normalized.append(str(item))
    return normalized


def _scalar(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise ProviderPayloadError(f"Polymarket {field} must be a bounded scalar")
    normalized = str(value)
    if not normalized.strip() or len(normalized) > MAX_SCALAR_CHARS:
        raise ProviderPayloadError(f"Polymarket {field} must be a bounded scalar")
    return normalized


def _nonnegative_number(value: object, field: str) -> str | None:
    normalized = _scalar(value, field)
    if normalized is None:
        return None
    try:
        numeric = Decimal(normalized)
    except InvalidOperation as exc:
        raise ProviderPayloadError(f"Polymarket {field} must be numeric") from exc
    if not numeric.is_finite() or numeric < 0:
        raise ProviderPayloadError(f"Polymarket {field} must be a finite non-negative number")
    return normalized


def _fact(name: str, value: str) -> NormalizedFact:
    try:
        return NormalizedFact(name, value)
    except ValueError as exc:
        raise ProviderPayloadError(f"Polymarket {name} is not a valid bounded fact") from exc


def _slug(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_SLUG_CHARS:
        raise ProviderPayloadError(f"Polymarket {field} must be a bounded slug")
    return value.strip()


def _uri(event_slug: str | None, market_slug: str | None, market_id: str) -> str:
    if event_slug is not None:
        path = f"https://polymarket.com/event/{quote(event_slug, safe='')}"
        if market_slug is not None and market_slug != event_slug:
            path = f"{path}/{quote(market_slug, safe='')}"
        return path
    return f"https://gamma-api.polymarket.com/markets/{quote(market_id, safe='')}"


def _pagination(value: object, event_count: int) -> tuple[bool, int | None]:
    if value is None:
        raise ProviderPayloadError("Polymarket search response must contain pagination")
    if not isinstance(value, Mapping):
        raise ProviderPayloadError("Polymarket pagination must be an object")
    has_more = value.get("hasMore")
    if not isinstance(has_more, bool):
        raise ProviderPayloadError("Polymarket pagination.hasMore must be a boolean")
    total_results = value.get("totalResults")
    if total_results is not None and (
        not isinstance(total_results, int)
        or isinstance(total_results, bool)
        or not event_count <= total_results <= MAX_TOTAL_RESULTS
    ):
        raise ProviderPayloadError("Polymarket pagination.totalResults is outside bounded response limits")
    return has_more, cast(int | None, total_results)


@dataclass(frozen=True, slots=True)
class PolymarketProvider:
    support: ProviderSupport

    provider_id: ClassVar[str] = "polymarket"
    specs: ClassVar = provider_specs(provider_id)

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if not isinstance(query, PredictionMarketsQuery):
            raise ValueError(f"{capability} requires its matching typed query")
        response = self.support.request(
            capability,
            query,
            SEARCH_URL,
            params={
                "q": " ".join(term.strip() for term in query.search_terms),
                "events_status": "active",
                "limit_per_type": query.max_items,
                "page": 1,
                "keep_closed_markets": 0,
                "search_tags": "false",
                "search_profiles": "false",
            },
            headers=self.support.headers,
        )
        if isinstance(response, SourceBatch):
            return response
        if not isinstance(response.payload, Mapping):
            raise ProviderPayloadError("Polymarket search response must be an object")
        raw_events = response.payload.get("events")
        if raw_events is None:
            events_value: list[object] = []
        elif isinstance(raw_events, list):
            events_value = raw_events
        else:
            raise ProviderPayloadError("Polymarket search response events must be an array or null")
        if len(events_value) > MAX_EVENTS:
            raise ProviderPayloadError("Polymarket search response exceeds the bounded event limit")
        provider_has_more, total_results = _pagination(response.payload.get("pagination"), len(events_value))

        cutoff = query_instant(query.as_of)
        retrieved = iso(self.support.clock())
        retrieved_instant = instant(retrieved)
        if retrieved is None or retrieved_instant is None:
            raise ValueError("validated adapter clock contains an invalid timestamp")
        historical_gap = (
            "Polymarket Gamma was retrieved after the requested as_of cutoff; current search cannot reconstruct "
            "the market universe or probabilities at that cutoff."
        )
        if retrieved_instant > cutoff:
            return self.support.terminal(capability, query, "unavailable", historical_gap)

        normalized: list[tuple[str, str, str, tuple[NormalizedFact, ...], Mapping[str, object]]] = []
        seen_market_ids: set[str] = set()
        total_markets = 0
        for event_value in events_value:
            if not isinstance(event_value, Mapping):
                raise ProviderPayloadError("Polymarket event entries must be objects")
            event = cast(Mapping[str, object], event_value)
            event_active = event.get("active")
            event_closed = event.get("closed")
            if not isinstance(event_active, bool) or not isinstance(event_closed, bool):
                raise ProviderPayloadError("Polymarket events must contain boolean active and closed fields")
            markets_value = event.get("markets")
            if not isinstance(markets_value, list):
                raise ProviderPayloadError("Polymarket events must contain a markets array")
            if len(markets_value) > MAX_MARKETS_PER_EVENT:
                raise ProviderPayloadError("Polymarket event exceeds the bounded nested-market limit")
            total_markets += len(markets_value)
            if total_markets > MAX_TOTAL_MARKETS:
                raise ProviderPayloadError("Polymarket response exceeds the bounded total-market limit")
            event_slug = _slug(event.get("slug"), "event.slug")
            if not event_active or event_closed:
                continue

            for market_value in markets_value:
                if not isinstance(market_value, Mapping):
                    raise ProviderPayloadError("Polymarket market entries must be objects")
                market = cast(Mapping[str, object], market_value)
                market_active = market.get("active")
                market_closed = market.get("closed")
                if not isinstance(market_active, bool) or not isinstance(market_closed, bool):
                    raise ProviderPayloadError("Polymarket markets must contain boolean active and closed fields")
                if not market_active or market_closed:
                    continue
                market_id = market.get("id")
                question = market.get("question")
                if not isinstance(market_id, str) or not market_id.strip() or len(market_id) > 256:
                    raise ProviderPayloadError("Polymarket active markets must contain a non-empty id")
                if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS:
                    raise ProviderPayloadError("Polymarket active markets must contain a non-empty question")
                if market_id in seen_market_ids:
                    raise ProviderPayloadError("Polymarket search response contains duplicate market ids")
                seen_market_ids.add(market_id)
                updated = iso(market.get("updatedAt"))
                updated_instant = instant(updated)
                if updated is None or updated_instant is None:
                    raise ProviderPayloadError("Polymarket active markets must contain a valid updatedAt")
                if updated_instant > retrieved_instant:
                    raise ProviderPayloadError("Polymarket market updatedAt cannot be later than retrieval time")
                if updated_instant > cutoff:
                    continue
                outcomes = _array(market.get("outcomes"), "outcomes", strings_only=True)
                prices = _array(market.get("outcomePrices"), "outcomePrices", strings_only=False)
                if len(outcomes) != len(prices):
                    raise ProviderPayloadError("Polymarket outcomes and outcomePrices must have equal lengths")
                facts = [
                    _fact("question", question),
                    _fact("outcomes", json.dumps(outcomes, sort_keys=True, separators=(",", ":"))),
                    _fact("outcome_prices", json.dumps(prices, sort_keys=True, separators=(",", ":"))),
                ]
                for fact_name, field_name in (
                    ("volume", "volume"),
                    ("liquidity", "liquidity"),
                    ("end_date", "endDate"),
                    ("resolution_source", "resolutionSource"),
                    ("resolved_by", "resolvedBy"),
                    ("resolution_status", "umaResolutionStatus"),
                ):
                    fact_value = (
                        _nonnegative_number(market.get(field_name), field_name)
                        if field_name in {"volume", "liquidity"}
                        else _scalar(market.get(field_name), field_name)
                    )
                    if fact_value is not None:
                        if field_name == "endDate":
                            fact_value = iso(fact_value) or ""
                            if not fact_value:
                                raise ProviderPayloadError("Polymarket endDate must be a valid timestamp")
                        facts.append(_fact(fact_name, fact_value))
                market_slug = _slug(market.get("slug"), "market.slug")
                uri = _uri(event_slug, market_slug, market_id)
                digest_record: Mapping[str, object] = {
                    "market_id": market_id,
                    "updated_at": updated,
                    "uri": uri,
                    "facts": [fact.to_dict() for fact in facts],
                }
                normalized.append((market_id, uri, updated, tuple(facts), digest_record))

        normalized.sort(key=lambda row: (row[2], row[0], digest(row[4])))
        locally_capped = len(normalized) > query.max_items
        selected = normalized[: query.max_items]
        rows = tuple(
            self.support.observation(
                source_id=f"polymarket-{digest(market_id)[:24]}",
                source_kind="positioning",
                uri=uri,
                observed=retrieved,
                published=retrieved,
                available=retrieved,
                retrieved=retrieved,
                provider="Polymarket Gamma",
                provider_version="public-search-v1",
                license_id="polymarket-gamma-public-metadata-v1",
                facts=facts,
                digest_value=digest_record,
            )
            for market_id, uri, _updated, facts, digest_record in selected
        )
        gaps: list[str] = []
        if provider_has_more:
            result_count = f" of {total_results}" if total_results is not None else ""
            gaps.append(f"Polymarket pagination reports additional matching results beyond page 1{result_count}.")
        if locally_capped:
            gaps.append("Polymarket returned more active markets than max_items; the normalized result was capped.")
        gap = tuple(gaps)
        if gap and not rows:
            return self.support.terminal(capability, query, "unavailable", " ".join(gap))
        return self.support.batch(
            capability,
            query,
            rows,
            "Polymarket Gamma",
            "public-search-v1",
            "polymarket-gamma-public-metadata-v1",
            TERMS_URL,
            status="partial" if gap else "complete",
            limitations=(
                "Polymarket Gamma exposes a current market snapshot and does not provide historical revision "
                "lineage for as-of reconstruction.",
                "Prediction-market prices are positioning signals, not verified outcome facts or executable "
                "trading instructions.",
                *gap,
            ),
            gaps=gap,
            redistributable="unknown",
            entitlement_limitation=(
                "Polymarket metadata redistribution rights are not established; normalized facts are returned "
                "without extracts."
            ),
        )
