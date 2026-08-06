from __future__ import annotations

from dataclasses import dataclass

import pytest

from stock_research_agents.profiles import ProfileDescriptor, ProfileRegistry
from stock_research_agents.publication import PublicationDraft


@dataclass
class FakeProvider:
    descriptor: ProfileDescriptor

    def load_manifest(self) -> dict[str, object]:
        return {"id": self.descriptor.workflow_id}

    def load_schema(self) -> dict[str, object]:
        return {"$id": self.descriptor.terminal_schema}

    def parse_submission(self, payload: object) -> object:
        return payload

    def build_publication(self, submission: object) -> PublicationDraft:
        raise NotImplementedError


def _provider(profile: str = "company-analytics.v1") -> FakeProvider:
    return FakeProvider(
        ProfileDescriptor(
            profile=profile,
            workflow_id=f"stockresearchagents.{profile}",
            terminal_schema="company-analytics-submission.v1",
            artifact_kinds=("research_dossier.v1", "analytics_bundle.v1"),
        )
    )


def test_registry_is_open_for_new_profiles_and_catalog_is_deterministic() -> None:
    analytics = _provider()
    company = _provider("company-research.v1")
    registry = ProfileRegistry((analytics, company))

    assert registry.get("company-analytics.v1") is analytics
    assert [item["profile"] for item in registry.catalog()] == ["company-analytics.v1", "company-research.v1"]


def test_registry_rejects_duplicate_profile_names() -> None:
    registry = ProfileRegistry((_provider(),))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_provider())


def test_profile_descriptor_rejects_ambiguous_artifact_contracts() -> None:
    with pytest.raises(ValueError, match="unique"):
        ProfileDescriptor(
            profile="company-analytics.v1",
            workflow_id="stockresearchagents.company-analytics.v1",
            terminal_schema="company-analytics-submission.v1",
            artifact_kinds=("analytics_bundle.v1", "analytics_bundle.v1"),
        )
