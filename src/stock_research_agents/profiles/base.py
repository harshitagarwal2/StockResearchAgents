"""Small interfaces shared by versioned StockResearchAgents workflow profiles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from stock_research_agents.publication import PublicationDraft


@dataclass(frozen=True, slots=True)
class ProfileDescriptor:
    """Stable discovery metadata for one independently versioned workflow profile."""

    profile: str
    workflow_id: str
    terminal_schema: str
    artifact_kinds: tuple[str, ...]
    evolution_policy: str = "independent_versioned_contract"

    def __post_init__(self) -> None:
        for name, value in (
            ("profile", self.profile),
            ("workflow_id", self.workflow_id),
            ("terminal_schema", self.terminal_schema),
            ("evolution_policy", self.evolution_policy),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not self.artifact_kinds or len(set(self.artifact_kinds)) != len(self.artifact_kinds):
            raise ValueError("artifact_kinds must be a non-empty unique sequence")
        if any(not isinstance(kind, str) or not kind.strip() for kind in self.artifact_kinds):
            raise ValueError("artifact_kinds must contain non-empty strings")

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "workflow_id": self.workflow_id,
            "terminal_schema": self.terminal_schema,
            "artifact_kinds": list(self.artifact_kinds),
            "evolution_policy": self.evolution_policy,
        }


@runtime_checkable
class ProfileProvider(Protocol):
    """Dependency-inversion boundary implemented by each versioned profile."""

    @property
    def descriptor(self) -> ProfileDescriptor: ...

    def load_manifest(self) -> Mapping[str, object]: ...

    def load_schema(self) -> Mapping[str, object]: ...

    def parse_submission(self, payload: object) -> object: ...

    def build_publication(self, submission: object) -> PublicationDraft: ...
