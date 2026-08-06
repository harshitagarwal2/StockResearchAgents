"""Hermetic source adapter for conformance tests and offline demonstrations."""

from __future__ import annotations

from stock_research_agents_host.contracts import SourceBatch, SourceQuery, validate_source_response


class FixtureSourceAdapter:
    def __init__(self, batches: tuple[SourceBatch, ...]) -> None:
        self._batches = {batch.capability: batch for batch in batches}
        if len(self._batches) != len(batches):
            raise ValueError("fixture batches must use unique capabilities")

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        try:
            batch = self._batches[capability]
        except KeyError as exc:
            raise KeyError(f"fixture has no batch for capability: {capability}") from exc
        return validate_source_response(capability, query, batch)
