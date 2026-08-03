from __future__ import annotations

import json

import pytest

from tradingrearchagents.contracts import RunRequest
from tradingrearchagents.topology import build_legacy_topology
from tradingrearchagents.workflow import (
    DEFAULT_MANIFEST,
    expand_workflow,
    load_host_submission_schema,
    load_run_lifecycle_schema,
    load_workflow_manifest,
    stage_runtime_contract,
)


def test_versioned_manifest_expands_the_exact_legacy_topology() -> None:
    request = RunRequest(debate_rounds=2, risk_rounds=2)
    expanded = expand_workflow(request)
    legacy = build_legacy_topology(request.analysts, request.debate_rounds, request.risk_rounds)

    assert [stage.to_dict() for stage in expanded.stages] == [stage.to_dict() for stage in legacy.stages]
    assert expanded.terminal_stage == "portfolio"
    assert expanded.name == "tradingrearchagents.financial-research"


def test_manifest_is_generic_and_declares_sequential_fallback() -> None:
    manifest = load_workflow_manifest()
    assert manifest.schema_version == "1.0.0"
    assert manifest.fallback == "sequential"
    assert [role["slug"] for role in manifest.research_debate] == ["bull", "bear"]
    assert [role["slug"] for role in manifest.risk_debate] == ["aggressive", "conservative", "neutral"]
    assert manifest.defaults["debate_rounds"] == 1
    assert manifest.defaults["risk_rounds"] == 1
    assert "Never request an API key" in manifest.evidence_policy["fallback"]
    assert manifest.parity_scope["claim"] == (
        "Portable feature, information, action, lifecycle, memory, report, and safety contracts are complete; "
        "actual agent spawning, tool invocation, hard interruption, and exact model text remain harness-specific "
        "by design."
    )
    assert manifest.capability_negotiation["portable_fallback"] == "compatible"
    assert manifest.routing_semantics["research_debate"].endswith("2 * debate_rounds turns.")
    assert set(manifest.stage_instructions) == {
        "analyst.market",
        "analyst.social",
        "analyst.news",
        "analyst.fundamentals",
        "research.bull",
        "research.bear",
        "research.manager",
        "trader",
        "risk.aggressive",
        "risk.conservative",
        "risk.neutral",
        "portfolio",
    }


def test_every_expanded_stage_has_an_executable_runtime_contract() -> None:
    manifest = load_workflow_manifest()
    topology = expand_workflow(RunRequest(debate_rounds=2, risk_rounds=2))

    contracts = [stage_runtime_contract(stage, manifest) for stage in topology.stages]

    assert len(contracts) == len(topology.stages)
    assert all(contract["output_ref"].startswith("host-submission.v2.schema.json#/") for contract in contracts)
    assert contracts[0]["allowed_tools"] == [
        "market.price_history",
        "market.indicators",
        "market.verified_snapshot",
    ]
    assert contracts[-1]["id"] == "portfolio"
    assert contracts[-1]["allowed_tools"] == []


def test_host_submission_schema_covers_every_stage_and_final_field() -> None:
    schema = load_host_submission_schema()
    definitions = schema["$defs"]

    assert schema["$ref"] == "#/$defs/submission"
    assert {
        "request",
        "evidence",
        "analystStageOutput",
        "debateStageOutput",
        "researchManagerOutput",
        "traderOutput",
        "portfolioStageOutput",
        "submission",
    } <= set(definitions)
    assert definitions["submission"]["additionalProperties"] is False
    assert set(definitions["submission"]["required"]) >= {
        "request",
        "analyst_reports",
        "research_debate",
        "research_decision",
        "trader_decision",
        "risk_debate",
        "risk_decision",
        "portfolio_decision",
        "final_trade_decision",
    }
    assert definitions["researchManagerOutput"]["properties"]["recommendation"]["enum"] == [
        "Buy",
        "Overweight",
        "Hold",
        "Underweight",
        "Sell",
    ]
    assert definitions["traderOutput"]["properties"]["action"]["enum"] == ["Buy", "Hold", "Sell"]
    assert definitions["portfolioDecision"]["properties"]["rating"]["enum"] == [
        "Buy",
        "Overweight",
        "Hold",
        "Underweight",
        "Sell",
    ]
    assert set(definitions["researchManagerOutput"]["required"]) == {
        "recommendation",
        "rationale",
        "strategic_actions",
        "confidence",
    }
    assert set(definitions["traderOutput"]["required"]) == {"action", "reasoning"}
    assert set(definitions["portfolioDecision"]["required"]) == {
        "rating",
        "executive_summary",
        "investment_thesis",
    }


def test_run_lifecycle_schema_is_separate_and_covers_controls_and_safe_receipts() -> None:
    schema = load_run_lifecycle_schema()

    assert schema["properties"]["status"]["enum"] == [
        "prepared",
        "running",
        "paused",
        "cancel_requested",
        "cancelled",
        "finalizing",
        "completed",
        "failed",
    ]
    assert "receipt" in schema["$defs"]
    assert "api_key" not in json.dumps(schema).lower()


def test_loader_rejects_unknown_schema_version(tmp_path) -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["schema_version"] = "999"
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported workflow schema_version"):
        load_workflow_manifest(path)
