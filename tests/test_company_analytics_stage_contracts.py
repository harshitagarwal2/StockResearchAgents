from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import prepare_company_analytics
from stock_research_agents.company_analytics_v1 import CompanyAnalyticsV1Provider
from stock_research_agents.company_analytics_v1 import provider as provider_module
from stock_research_agents.company_lifecycle import (
    STAGE_ENVELOPE_SCHEMA_VERSION,
    CompanyAnalyticsCoordinator,
)
from stock_research_agents.lifecycle import LifecycleStore
from stock_research_agents.lifecycle_profiles import CompanyAnalyticsLifecycleProfile
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore


def _coordinator(tmp_path: Path) -> CompanyAnalyticsCoordinator:
    return CompanyAnalyticsCoordinator(
        LifecycleStore(tmp_path / "lifecycle"),
        RunStore(tmp_path / "runs"),
        profile=CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / "quality")),
    )


def _opaque_envelope(stage: dict[str, object]) -> dict[str, object]:
    refs = stage["output_refs"]
    assert isinstance(refs, list)
    return {
        "schema_version": STAGE_ENVELOPE_SCHEMA_VERSION,
        "stage_id": stage["id"],
        "output_refs": {
            ref: {
                "reference_id": f"host-ref-{hashlib.sha256(ref.encode()).hexdigest()[:16]}",
                "media_type": "application/json",
                "sha256": hashlib.sha256(f"output:{ref}".encode()).hexdigest(),
                "byte_length": 0,
                "summary": "Validated stage output retained by the host.",
            }
            for ref in refs
        },
    }


def test_prepare_and_durable_next_stage_expose_all_portable_stage_instructions(tmp_path: Path) -> None:
    submission = complete_analytics_submission("ORCL")
    request = submission["company_research"]["request"]  # type: ignore[index]
    plan = prepare_company_analytics(request)  # type: ignore[arg-type]

    execution_contract = plan["execution_contract"]
    assert isinstance(execution_contract, dict)
    assert execution_contract["schema_version"] == "stage-instructions.v1"
    assert set(execution_contract["global_policy"]) == {
        "caller_ownership",
        "workflow_semantics",
        "tool_policy",
        "credential_policy",
        "evidence_policy",
        "completion_policy",
        "authority_policy",
    }
    stages = plan["stages"]
    assert isinstance(stages, list)
    assert len(stages) == 26

    coordinator = _coordinator(tmp_path)
    control = coordinator.create(request, decision_memory_enabled=False)  # type: ignore[arg-type]
    response = coordinator.start(control["run_id"], control["revision"])
    for index, expected in enumerate(stages):
        stage = response["stage"]
        assert stage == expected
        assert isinstance(stage["role"], str) and stage["role"]
        assert isinstance(stage["objective"], str) and stage["objective"]
        assert isinstance(stage["completion_criteria"], list) and stage["completion_criteria"]
        if index == len(stages) - 1:
            break
        response = coordinator.commit_stage(
            control["run_id"],
            stage["id"],
            _opaque_envelope(stage),
            response["control"]["revision"],
        )
        coordinator = _coordinator(tmp_path)
        response = coordinator.next_stage(control["run_id"])


def _mutate_manifest(manifest: dict[str, object], case: str) -> None:
    stages = manifest["stages"]
    assert isinstance(stages, list)
    first = stages[0]
    second = stages[1]
    assert isinstance(first, dict) and isinstance(second, dict)
    if case == "identity":
        manifest["id"] = "stockresearchagents.company-analytics.invalid"
    elif case == "stage_count":
        stages.pop()
    elif case == "ordinal":
        second["ordinal"] = 3
    elif case == "duplicate_id":
        second["id"] = first["id"]
    elif case == "later_dependency":
        first["depends_on"] = [second["id"]]
    elif case == "capabilities":
        first["capabilities"] = []
    elif case == "output_refs":
        first["output_refs"] = []
    elif case == "role":
        first["role"] = ""
    elif case == "objective":
        first["objective"] = ""
    elif case == "completion_criteria":
        first["completion_criteria"] = []
    elif case == "global_policy":
        contract = manifest["execution_contract"]
        assert isinstance(contract, dict)
        policy = contract["global_policy"]
        assert isinstance(policy, dict)
        policy["completion_policy"] = "Best effort completion is acceptable."
    else:  # pragma: no cover - protects the parametrization itself
        raise AssertionError(f"unknown mutation case: {case}")


@pytest.mark.parametrize(
    "case",
    (
        "identity",
        "stage_count",
        "ordinal",
        "duplicate_id",
        "later_dependency",
        "capabilities",
        "output_refs",
        "role",
        "objective",
        "completion_criteria",
        "global_policy",
    ),
)
def test_manifest_mutations_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    manifest = deepcopy(CompanyAnalyticsV1Provider().load_manifest())
    _mutate_manifest(manifest, case)
    mutated_path = tmp_path / "company-analytics.v1.json"
    mutated_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(provider_module, "_MANIFEST", mutated_path)

    with pytest.raises(ValueError, match="invalid company analytics workflow manifest"):
        CompanyAnalyticsV1Provider().load_manifest()


def test_stage_instruction_contract_has_no_harness_or_vendor_coupling() -> None:
    manifest = CompanyAnalyticsV1Provider().load_manifest()
    portable_instructions = json.dumps(
        {
            "execution_contract": manifest["execution_contract"],
            "stages": manifest["stages"],
        },
        sort_keys=True,
    ).lower()

    for coupled_term in ("openai", "anthropic", "codex", "langgraph", "gpt-", "claude", "gemini"):
        assert coupled_term not in portable_instructions
