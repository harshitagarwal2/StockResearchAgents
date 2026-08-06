"""Shared transport and canonical batch construction for source providers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from stock_research_agents_host.contracts import (
    NormalizedFact,
    SourceBatch,
    SourceCompleteness,
    SourceEntitlement,
    SourceObservation,
    SourcePagination,
    SourceProvenance,
    SourceQuery,
)

ADAPTER_VERSION = "1.0.0"


class ProviderTransportError(RuntimeError):
    """A public provider could not be reached or decoded by the transport."""


class ProviderPayloadError(RuntimeError):
    """A provider returned a successful response with an unusable payload shape."""


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    status: int
    payload: object
    headers: Mapping[str, str] | None = None


class HTTPTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HTTPResponse: ...


def now() -> str:
    return datetime.now(UTC).isoformat()


def iso(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value.strip()
    if len(candidate) == 8 and candidate.isdigit():
        candidate = f"{candidate[:4]}-{candidate[4:6]}-{candidate[6:]}T00:00:00+00:00"
    elif len(candidate) == 10:
        candidate = f"{candidate}T00:00:00+00:00"
    elif len(candidate.removesuffix("Z")) == 15 and candidate[8] == "T":
        compact = candidate.removesuffix("Z")
        candidate = f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}T{compact[9:11]}:{compact[11:13]}:{compact[13:]}+00:00"
    elif candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def instant(value: object) -> datetime | None:
    normalized = iso(value)
    return None if normalized is None else datetime.fromisoformat(normalized).astimezone(UTC)


def query_instant(value: str) -> datetime:
    parsed = instant(value)
    if parsed is None:
        raise ValueError("validated source query contains an invalid timestamp")
    return parsed


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderSupport:
    transport: HTTPTransport
    operator_identity: str
    clock: Callable[[], str] = now

    @property
    def headers(self) -> Mapping[str, str]:
        return {"User-Agent": self.operator_identity}

    def request(
        self,
        capability: str,
        query: SourceQuery,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HTTPResponse | SourceBatch:
        try:
            response = self.transport.get_json(url, params=params, headers=headers)
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderTransportError("public provider transport failed") from exc
        if response.status == 429:
            return self.terminal(capability, query, "rate_limited", "The provider rate limit was reached.")
        if response.status in {401, 403}:
            return self.terminal(capability, query, "denied", "The provider denied host access.")
        if not 200 <= response.status < 300:
            return self.terminal(capability, query, "unavailable", f"Provider returned HTTP {response.status}.")
        return response

    def observation(
        self,
        *,
        source_id: str,
        source_kind: str,
        uri: str,
        observed: str,
        published: str,
        available: str,
        retrieved: str | None = None,
        provider: str,
        provider_version: str,
        license_id: str,
        facts: tuple[NormalizedFact, ...],
        digest_value: object,
    ) -> SourceObservation:
        return SourceObservation(
            source_id=source_id,
            source_kind=cast(object, source_kind),  # type: ignore[arg-type]
            canonical_uri=uri,
            content_sha256=digest(digest_value),
            observed_at=observed,
            published_at=published,
            available_at=available,
            retrieved_at=retrieved or self.clock(),
            provider=provider,
            provider_version=provider_version,
            license_receipt_id=license_id,
            content_sha256_scope="normalized_source_record",
            facts=facts,
            bounded_extract=None,
            limitations=(),
        )

    def batch(
        self,
        capability: str,
        query: SourceQuery,
        items: tuple[SourceObservation, ...],
        provider: str,
        provider_version: str,
        license_id: str,
        terms_uri: str,
        *,
        status: str = "complete",
        limitations: tuple[str, ...] = (),
        gaps: tuple[str, ...] = (),
        next_cursor: str | None = None,
        redistributable: bool | str = True,
        entitlement_limitation: str | None = None,
    ) -> SourceBatch:
        return SourceBatch(
            capability=capability,
            query=query,
            cutoff=query.cutoff_at,
            status=cast(object, status),  # type: ignore[arg-type]
            items=items,
            provenance=SourceProvenance(
                provider, provider_version, "PublicResearchDataAdapter", ADAPTER_VERSION, self.clock()
            ),
            entitlement=SourceEntitlement(
                access="allowed",
                redistributable=cast(object, redistributable),  # type: ignore[arg-type]
                terms_uri=terms_uri,
                license_receipt_id=license_id,
                limitation=entitlement_limitation,
            ),
            completeness=SourceCompleteness(status == "complete", gaps),
            pagination=SourcePagination(next_cursor is not None, next_cursor, len(items), max(1, len(items))),
            limitations=limitations,
        )

    def terminal(self, capability: str, query: SourceQuery, status: str, limitation: str) -> SourceBatch:
        denied = status == "denied"
        return SourceBatch(
            capability=capability,
            query=query,
            cutoff=query.cutoff_at,
            status=cast(object, status),  # type: ignore[arg-type]
            items=(),
            provenance=SourceProvenance("host", "1", "PublicResearchDataAdapter", ADAPTER_VERSION, self.clock()),
            entitlement=SourceEntitlement(
                access="denied" if denied else "unknown",
                redistributable=False if denied else "unknown",
                terms_uri=None,
                license_receipt_id="host-access-not-configured",
                limitation=limitation,
            ),
            completeness=SourceCompleteness(False, (limitation,)),
            pagination=SourcePagination(False, None, 0, 1),
            limitations=(limitation,),
        )
