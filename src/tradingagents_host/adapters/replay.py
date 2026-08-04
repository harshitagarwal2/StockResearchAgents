"""Replay previously normalized source observations without provider access."""

from __future__ import annotations

import json
from pathlib import Path

from tradingagents_host.contracts import (
    SourceBatch,
    SourceQuery,
    validate_source_response,
)


class ReplaySourceAdapter:
    """Load a bounded normalized batch from a local JSON receipt."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("replay source must contain valid JSON") from exc
        batch = SourceBatch.from_dict(raw)
        return validate_source_response(capability, query, batch)
