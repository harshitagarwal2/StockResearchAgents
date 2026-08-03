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


class StageExecutor(Protocol):
    """Minimal seam that native-agent and sequential harnesses can implement."""

    def execute_stage(
        self,
        stage: StageSpec,
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
        fallback=raw["fallback"],
    )


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
            role = contract.analyst_roles[analyst]
        except KeyError as exc:
            raise ValueError(f"workflow manifest has no analyst role for {analyst!r}") from exc
        add(f"analyst.{analyst}", StageKind.ANALYST, role)
    for round_number in range(1, request.debate_rounds + 1):
        for role in contract.research_debate:
            add(f"research.{round_number}.{role['slug']}", StageKind.RESEARCH_DEBATE, role["role"])
    add(contract.research_manager["id"], StageKind.RESEARCH_MANAGER, contract.research_manager["role"])
    add(contract.trader["id"], StageKind.TRADER, contract.trader["role"])
    for round_number in range(1, request.risk_rounds + 1):
        for role in contract.risk_debate:
            add(f"risk.{round_number}.{role['slug']}", StageKind.RISK_DEBATE, role["role"])
    add(contract.portfolio_manager["id"], StageKind.PORTFOLIO, contract.portfolio_manager["role"])
    return WorkflowTopology(
        name=contract.id,
        analysts=request.analysts,
        debate_rounds=request.debate_rounds,
        risk_rounds=request.risk_rounds,
        stages=tuple(stages),
        terminal_stage=contract.portfolio_manager["id"],
    )
