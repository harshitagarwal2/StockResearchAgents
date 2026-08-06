"""Explicit source routing with no silent provider fallback."""

from __future__ import annotations

from collections.abc import Iterable
from threading import RLock
from typing import ClassVar, Protocol

from stock_research_agents_host.contracts import SourceBatch, SourceQuery, validate_source_response
from stock_research_agents_host.ports import SourcePort


class ProviderCapabilitySpec(Protocol):
    name: str
    provider_id: str

    def validate(self, query: SourceQuery) -> None: ...


class SourceProvider(Protocol):
    """A provider strategy that owns one or more source capabilities."""

    provider_id: ClassVar[str]
    specs: ClassVar[tuple[ProviderCapabilitySpec, ...]]

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch: ...


class SourceRouter:
    """Route normalized queries by capability; selection remains host-owned."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._ports: dict[str, SourcePort] = {}

    def register(self, capability: str, port: SourcePort) -> None:
        if not capability or not isinstance(port, SourcePort):
            raise ValueError("source routes require a capability and SourcePort")
        with self._lock:
            if capability in self._ports:
                raise ValueError(f"source capability is already registered: {capability}")
            self._ports[capability] = port

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        with self._lock:
            try:
                port = self._ports[capability]
            except KeyError as exc:
                raise KeyError(f"no source adapter registered for capability: {capability}") from exc
        return validate_source_response(capability, query, port.fetch(capability, query))

    def capabilities(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._ports))


class ProviderSourceRouter:
    """Resolve a capability to exactly one provider strategy."""

    def __init__(self, providers: Iterable[SourceProvider]) -> None:
        routes: dict[str, SourceProvider] = {}
        for provider in providers:
            if not provider.provider_id:
                raise ValueError("source provider identity must be non-empty")
            for spec in provider.specs:
                capability = spec.name
                if not capability:
                    raise ValueError("source provider capabilities must be non-empty")
                if spec.provider_id != provider.provider_id:
                    raise ValueError(
                        f"source provider catalog ownership mismatch: {capability} belongs to {spec.provider_id}"
                    )
                if capability in routes:
                    raise ValueError(f"duplicate source provider route: {capability}")
                routes[capability] = provider
        self._routes = routes

    def capabilities(self) -> frozenset[str]:
        return frozenset(self._routes)

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        try:
            provider = self._routes[capability]
        except KeyError as exc:
            raise ValueError(f"no source provider route for capability: {capability}") from exc
        spec = next(spec for spec in provider.specs if spec.name == capability)
        spec.validate(query)
        return validate_source_response(capability, query, provider.fetch(capability, query))
