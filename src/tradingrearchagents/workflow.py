"""Versioned workflow manifest loader and harness execution seam."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .contracts import RunRequest, StageKind, StageSpec, WorkflowTopology

WORKFLOW_SCHEMA_VERSION = "1.0.0"
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "workflow" / "financial-research.v1.json"
DEFAULT_SUBMISSION_SCHEMA = Path(__file__).resolve().parent / "workflow" / "host-submission.v2.schema.json"
DEFAULT_LIFECYCLE_SCHEMA = Path(__file__).resolve().parent / "workflow" / "run-lifecycle.v1.schema.json"


class StageExecutor(Protocol):
    """Minimal seam that native-agent and sequential harnesses can implement."""

    def execute_stage(
        self,
        stage: StageSpec,
        instructions: str,
        context: Mapping[str, Any],
        allowed_tools: tuple[str, ...],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class WorkflowManifest:
    schema_version: str
    id: str
    name: str
    analyst_roles: Mapping[str, str]
    research_debate: tuple[Mapping[str, str], ...]
    research_manager: Mapping[str, str]
    trader: Mapping[str, str]
    risk_debate: tuple[Mapping[str, str], ...]
    portfolio_manager: Mapping[str, str]
    defaults: Mapping[str, Any]
    evidence_policy: Mapping[str, Any]
    stage_instructions: Mapping[str, str]
    contracts: Mapping[str, Any]
    capability_negotiation: Mapping[str, Any]
    tool_capabilities: Mapping[str, Any]
    stage_contracts: Mapping[str, Any]
    routing_semantics: Mapping[str, Any]
    state_contract: Mapping[str, Any]
    parity_scope: Mapping[str, Any]
    fallback: str


def load_workflow_manifest(path: str | Path = DEFAULT_MANIFEST) -> WorkflowManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
        raise ValueError(f"unsupported workflow schema_version: {raw.get('schema_version')!r}")
    if raw.get("fallback") != "sequential":
        raise ValueError("workflow fallback must be sequential")
    return WorkflowManifest(
        schema_version=raw["schema_version"],
        id=raw["id"],
        name=raw["name"],
        analyst_roles=dict(raw["analyst_roles"]),
        research_debate=tuple(dict(item) for item in raw["research_debate"]),
        research_manager=dict(raw["research_manager"]),
        trader=dict(raw["trader"]),
        risk_debate=tuple(dict(item) for item in raw["risk_debate"]),
        portfolio_manager=dict(raw["portfolio_manager"]),
        defaults=dict(raw["defaults"]),
        evidence_policy=dict(raw["evidence_policy"]),
        stage_instructions=dict(raw["stage_instructions"]),
        contracts=dict(raw["contracts"]),
        capability_negotiation=dict(raw["capability_negotiation"]),
        tool_capabilities=dict(raw["tool_capabilities"]),
        stage_contracts=dict(raw["stage_contracts"]),
        routing_semantics=dict(raw["routing_semantics"]),
        state_contract=dict(raw["state_contract"]),
        parity_scope=dict(raw["parity_scope"]),
        fallback=raw["fallback"],
    )


def load_host_submission_schema(path: str | Path = DEFAULT_SUBMISSION_SCHEMA) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("$id") != "https://tradingrearchagents.local/schemas/host-submission.v2.json":
        raise ValueError("unexpected host submission schema id")
    return raw


def load_run_lifecycle_schema(path: str | Path = DEFAULT_LIFECYCLE_SCHEMA) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("$id") != "https://tradingrearchagents.local/schemas/run-lifecycle.v1.json":
        raise ValueError("unexpected run lifecycle schema id")
    return raw


def stage_contract_key(stage_id: str) -> str:
    if stage_id.startswith("analyst."):
        return stage_id
    if stage_id.startswith("research.") and stage_id != "research.manager":
        return f"research.{stage_id.rsplit('.', 1)[-1]}"
    if stage_id.startswith("risk."):
        return f"risk.{stage_id.rsplit('.', 1)[-1]}"
    return stage_id


def stage_runtime_contract(stage: StageSpec, manifest: WorkflowManifest) -> dict[str, Any]:
    key = stage_contract_key(stage.id)
    try:
        contract = dict(manifest.stage_contracts[key])
        instruction = manifest.stage_instructions[key]
    except KeyError as exc:
        raise ValueError(f"workflow manifest has no runtime contract for {stage.id!r}") from exc
    return {
        "id": stage.id,
        "role": stage.role,
        "kind": stage.kind.value,
        "sequence": stage.ordinal,
        "depends_on": list(stage.depends_on),
        "instruction": instruction,
        **contract,
    }


def expand_workflow(request: RunRequest, manifest: WorkflowManifest | None = None) -> WorkflowTopology:
    contract = manifest or load_workflow_manifest()
    stages: list[StageSpec] = []
    previous: tuple[str, ...] = ()

    def add(stage_id: str, kind: StageKind, role: str) -> None:
        nonlocal previous
        stages.append(StageSpec(stage_id, kind, role, len(stages) + 1, previous))
        previous = (stage_id,)

    for analyst in request.analysts:
        try:
            analyst_role = contract.analyst_roles[analyst]
        except KeyError as exc:
            raise ValueError(f"workflow manifest has no analyst role for {analyst!r}") from exc
        add(f"analyst.{analyst}", StageKind.ANALYST, analyst_role)
    for round_number in range(1, request.debate_rounds + 1):
        for debate_role in contract.research_debate:
            add(
                f"research.{round_number}.{debate_role['slug']}",
                StageKind.RESEARCH_DEBATE,
                debate_role["role"],
            )
    add(contract.research_manager["id"], StageKind.RESEARCH_MANAGER, contract.research_manager["role"])
    add(contract.trader["id"], StageKind.TRADER, contract.trader["role"])
    for round_number in range(1, request.risk_rounds + 1):
        for risk_role in contract.risk_debate:
            add(f"risk.{round_number}.{risk_role['slug']}", StageKind.RISK_DEBATE, risk_role["role"])
    add(contract.portfolio_manager["id"], StageKind.PORTFOLIO, contract.portfolio_manager["role"])
    return WorkflowTopology(
        name=contract.id,
        analysts=request.analysts,
        debate_rounds=request.debate_rounds,
        risk_rounds=request.risk_rounds,
        stages=tuple(stages),
        terminal_stage=contract.portfolio_manager["id"],
    )
