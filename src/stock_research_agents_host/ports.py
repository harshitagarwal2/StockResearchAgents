"""Narrow host interface for source adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import SourceBatch, SourceQuery


@runtime_checkable
class SourcePort(Protocol):
    """Open-ended host source adapter selected by an explicit capability route."""

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch: ...
