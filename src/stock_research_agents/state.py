"""Single-source state layout for every durable application resource."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StateLayout:
    """Resolve the caller-selected state root once and derive all resource paths."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve(strict=False))

    @property
    def quality_dir(self) -> Path:
        return self.root / "quality"

    @property
    def memory_database(self) -> Path:
        return self.root / "decision-memory.sqlite3"

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        home: Path | None = None,
    ) -> StateLayout:
        values = os.environ if environment is None else environment
        configured = values.get("STOCKRESEARCHAGENTS_STATE_DIR")
        if configured:
            return cls(Path(configured))
        xdg_state_home = values.get("XDG_STATE_HOME")
        if xdg_state_home:
            return cls(Path(xdg_state_home) / "stock-research-agents")
        return cls((Path.home() if home is None else home) / ".local" / "state" / "stock-research-agents")


DEFAULT_STATE_LAYOUT = StateLayout.from_environment()


__all__ = ["DEFAULT_STATE_LAYOUT", "StateLayout"]
