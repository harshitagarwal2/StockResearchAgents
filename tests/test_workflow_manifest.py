from __future__ import annotations

import json

import pytest

from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.topology import build_legacy_topology
from tradingagents_portable.workflow import DEFAULT_MANIFEST, expand_workflow, load_workflow_manifest


def test_versioned_manifest_expands_the_exact_legacy_topology() -> None:
    request = RunRequest(debate_rounds=2, risk_rounds=2)
    expanded = expand_workflow(request)
    legacy = build_legacy_topology(request.analysts, request.debate_rounds, request.risk_rounds)

    assert [stage.to_dict() for stage in expanded.stages] == [stage.to_dict() for stage in legacy.stages]
    assert expanded.terminal_stage == "portfolio"
    assert expanded.name == "tradingagents.financial-research"


def test_manifest_is_generic_and_declares_sequential_fallback() -> None:
    manifest = load_workflow_manifest()
    assert manifest.schema_version == "1.0.0"
    assert manifest.fallback == "sequential"
    assert [role["slug"] for role in manifest.research_debate] == ["bull", "bear"]
    assert [role["slug"] for role in manifest.risk_debate] == ["aggressive", "conservative", "neutral"]


def test_loader_rejects_unknown_schema_version(tmp_path) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["schema_version"] = "999"
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported workflow schema_version"):
        load_workflow_manifest(path)
