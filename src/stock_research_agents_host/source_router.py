"""Explicit source routing with no silent provider fallback."""

from __future__ import annotations

from threading import RLock

from .contracts import SourceBatch, SourceQuery, validate_source_response
from .ports import SourcePort


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
