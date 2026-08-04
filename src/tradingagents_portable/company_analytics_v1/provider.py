"""Profile provider and atomic publication builder for company analytics v1."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, NoReturn

from tradingagents_portable.company_research import build_company_research_draft
from tradingagents_portable.contracts import Artifact, EventKind, RunEvent, RunStatus, StageKind, StageSpec
from tradingagents_portable.profiles import ProfileDescriptor
from tradingagents_portable.publication import PublicationDraft
from tradingagents_portable.reporting import build_report_artifacts
from tradingagents_portable.schema_bundle import load_host_submission_v4_schema_bundle

from .contracts import HostSubmissionV4, parse_host_submission_v4

_WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "workflow"
_MANIFEST = _WORKFLOW_DIR / "company-analytics.v1.json"

_MANIFEST_IDENTITY = {
    "schema_version": "1.0.0",
    "id": "tradingagents.company-analytics.v1",
    "name": "Evidence-first company research with deterministic analytics and evaluation",
    "fallback": "sequential",
}
_EXECUTION_CONTRACT_VERSION = "stage-instructions.v1"
_GLOBAL_POLICY = {
    "host_ownership": "Actual prompt wording, model selection, and runtime implementation remain host-owned.",
    "portable_semantics": "Stage roles, objectives, and completion criteria are portable execution semantics.",
    "tool_policy": (
        "Research tools must be read-only; deterministic calculators must be versioned; "
        "open-world retrieval must preserve source and timing receipts."
    ),
    "credential_policy": (
        "Credentials remain host-owned and must not enter portable inputs, outputs, state, or artifacts."
    ),
    "evidence_policy": "Unavailable, denied, or unlicensed evidence must be represented explicitly.",
    "completion_policy": "A stage must not report completion when its completion criteria are not satisfied.",
    "authority_policy": "No stage grants broker, order-placement, or trading-execution authority.",
}
_CAPABILITY_NEGOTIATION = {
    "full": {
        "description": "Host uses native subagents, parallel tools, and structured output.",
        "implementation": "host_adapter_contract",
        "readiness": "adapter_required",
        "locally_ready": False,
    },
    "compatible": {
        "description": "One host agent executes the same stages through the local sequential runner.",
        "implementation": "implemented_sequential_runner",
        "readiness": "locally_ready",
        "locally_ready": True,
    },
    "tools_only": {
        "description": (
            "A host MCP client owns execution and submits one completed bundle through the implemented "
            "coordination/import contract."
        ),
        "implementation": "implemented_coordination_contract_partial_live_research",
        "readiness": "partial_adapter_required",
        "locally_ready": False,
    },
    "mandatory_fallback": "sequential",
}
_STAGE_IDS = (
    "research.plan",
    "evidence.official",
    "evidence.market",
    "analysis.financial",
    "analysis.company",
    "audit.evidence",
    "verify.numerical",
    "debate.bull",
    "debate.bear",
    "synthesis.valuation",
    "synthesis.risk",
    "research.delta",
    "research.monitor",
    "evaluate.dossier",
    "assemble.dossier",
    "research.hypotheses",
    "analytics.fundamentals",
    "analytics.models",
    "analytics.consensus",
    "analytics.positioning",
    "analytics.events",
    "experiment.plan",
    "experiment.run",
    "experiment.evaluate",
    "quality.issue",
    "publish.completed",
)
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "id",
    "name",
    "execution_contract",
    "terminal_artifact_kinds",
    "contracts",
    "portable_boundary",
    "capability_negotiation",
    "research_packs",
    "history_policy",
    "stages",
    "routing_semantics",
    "fallback",
}
_STAGE_FIELDS = {
    "ordinal",
    "id",
    "role",
    "objective",
    "completion_criteria",
    "depends_on",
    "capabilities",
    "output_refs",
}


def _fail_manifest(reason: str) -> NoReturn:
    raise ValueError(f"invalid company analytics workflow manifest: {reason}")


def _non_empty_unique_strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail_manifest(f"{field} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        _fail_manifest(f"{field} must contain non-empty strings")
    if len(set(value)) != len(value):
        _fail_manifest(f"{field} must not contain duplicates")
    return value


def _validate_manifest(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_FIELDS:
        _fail_manifest("top-level fields do not match the v1 contract")
    if any(value.get(field) != expected for field, expected in _MANIFEST_IDENTITY.items()):
        _fail_manifest("identity does not match company-analytics.v1")

    execution_contract = value.get("execution_contract")
    if not isinstance(execution_contract, dict) or set(execution_contract) != {"schema_version", "global_policy"}:
        _fail_manifest("execution contract fields do not match stage-instructions.v1")
    if execution_contract.get("schema_version") != _EXECUTION_CONTRACT_VERSION:
        _fail_manifest("execution contract version does not match stage-instructions.v1")
    if execution_contract.get("global_policy") != _GLOBAL_POLICY:
        _fail_manifest("global policy does not match the portable execution policy")
    if value.get("capability_negotiation") != _CAPABILITY_NEGOTIATION:
        _fail_manifest("capability readiness must distinguish local sequential execution from adapter modes")

    stages = value.get("stages")
    if not isinstance(stages, list) or len(stages) != len(_STAGE_IDS):
        _fail_manifest("stages must contain exactly 26 entries")
    seen_ids: set[str] = set()
    seen_roles: set[str] = set()
    for ordinal, (stage, expected_id) in enumerate(zip(stages, _STAGE_IDS, strict=True), start=1):
        if not isinstance(stage, dict) or set(stage) != _STAGE_FIELDS:
            _fail_manifest(f"stage {ordinal} fields do not match the stage instruction contract")
        if type(stage.get("ordinal")) is not int or stage["ordinal"] != ordinal:
            _fail_manifest("stage ordinals must be contiguous from 1 through 26")
        stage_id = stage.get("id")
        if stage_id != expected_id or stage_id in seen_ids:
            _fail_manifest(f"stage {ordinal} has an invalid or duplicate id")
        seen_ids.add(stage_id)

        role = stage.get("role")
        if not isinstance(role, str) or not role.strip() or role in seen_roles:
            _fail_manifest(f"stage {stage_id} must have a unique non-empty role")
        seen_roles.add(role)
        objective = stage.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            _fail_manifest(f"stage {stage_id} must have a non-empty objective")
        _non_empty_unique_strings(stage.get("completion_criteria"), f"stage {stage_id} completion_criteria")

        depends_on = stage.get("depends_on")
        if not isinstance(depends_on, list) or any(
            not isinstance(dependency, str) or dependency not in seen_ids for dependency in depends_on
        ):
            _fail_manifest(f"stage {stage_id} dependencies must reference earlier stages only")
        if len(set(depends_on)) != len(depends_on):
            _fail_manifest(f"stage {stage_id} dependencies must not contain duplicates")
        _non_empty_unique_strings(stage.get("capabilities"), f"stage {stage_id} capabilities")
        _non_empty_unique_strings(stage.get("output_refs"), f"stage {stage_id} output_refs")
    return value


class CompanyAnalyticsV1Provider:
    descriptor = ProfileDescriptor(
        profile="company-analytics.v1",
        workflow_id="tradingagents.company-analytics.v1",
        terminal_schema="host-submission.v4",
        artifact_kinds=(
            "research_dossier.v3",
            "analytics_bundle.v1",
            "run_card.v1",
            "hypothesis_ledger.v1",
            "research_iterations.v1",
            "research_quality.v1",
            "forecast_set.v1",
        ),
    )

    def load_manifest(self) -> dict[str, object]:
        manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        return _validate_manifest(manifest)

    def load_schema(self) -> dict[str, object]:
        schema = load_host_submission_v4_schema_bundle()
        if schema.get("$id") != "https://tradingagents-portable.local/schemas/host-submission.v4.json":
            raise ValueError("invalid host-submission.v4 schema")
        return schema

    def parse_submission(self, payload: object) -> HostSubmissionV4:
        return parse_host_submission_v4(payload)

    def build_publication(self, submission: object) -> PublicationDraft:
        parsed = parse_host_submission_v4(submission)
        base = build_company_research_draft(parsed.company_research)
        manifest = self.load_manifest()
        manifest_stages = manifest["stages"]
        if not isinstance(manifest_stages, list):
            raise ValueError("validated company analytics stages must be an array")
        stages = tuple(
            StageSpec(
                id=stage["id"],
                kind=StageKind.WORKFLOW,
                role=stage["role"],
                ordinal=stage["ordinal"],
                depends_on=tuple(stage["depends_on"]),
            )
            for stage in manifest_stages
        )
        artifacts = (
            Artifact(
                id="research.analytics.v1",
                kind="analytics_bundle.v1",
                title=f"Deterministic analytics: {base.result.instrument.requested_symbol}",
                media_type="application/vnd.tradingagents.analytics-bundle.v1+json",
                content=parsed.analytics_bundle.to_dict(),
            ),
            Artifact(
                id="research.run-card.v1",
                kind="run_card.v1",
                title="Research run card",
                media_type="application/vnd.tradingagents.run-card.v1+json",
                content=parsed.run_card.to_dict(),
            ),
            Artifact(
                id="research.hypotheses.v1",
                kind="hypothesis_ledger.v1",
                title="Hypothesis lifecycle",
                media_type="application/vnd.tradingagents.hypothesis-ledger.v1+json",
                content=[item.to_dict() for item in parsed.hypothesis_ledgers],
            ),
            Artifact(
                id="research.iterations.v1",
                kind="research_iterations.v1",
                title="Research iteration receipts",
                media_type="application/vnd.tradingagents.research-iterations.v1+json",
                content=[item.to_dict() for item in parsed.research_iterations],
            ),
            Artifact(
                id="research.quality.v1",
                kind="research_quality.v1",
                title="Research quality receipt",
                media_type="application/vnd.tradingagents.research-quality.v1+json",
                content=parsed.quality_receipt.to_dict(),
            ),
            Artifact(
                id="research.forecasts.v1",
                kind="forecast_set.v1",
                title="Explicit research forecasts",
                media_type="application/vnd.tradingagents.forecast-set.v1+json",
                content=[item.to_dict() for item in parsed.forecasts],
            ),
        )
        result_without_artifacts = replace(
            base.result,
            run_id=parsed.run_card.run_id,
            artifacts=(),
            topology=replace(
                base.result.topology,
                name="tradingagents.company-analytics.v1",
                stages=stages,
                terminal_stage="publish.completed",
            ),
            persistence=replace(
                base.result.persistence,
                outputs=(*base.result.persistence.outputs, *(artifact.kind for artifact in artifacts)),
            ),
            warnings=(*base.result.warnings, *parsed.analytics_bundle.limitations),
            completed_at=parsed.analytics_bundle.completed_at,
        )
        frozen_v3_artifacts = tuple(
            artifact
            for artifact in base.result.artifacts
            if artifact.kind in {"research_dossier.v3", "research_request.v3"}
        )
        result = replace(
            result_without_artifacts,
            artifacts=(
                *build_report_artifacts(result_without_artifacts),
                *frozen_v3_artifacts,
                *artifacts,
            ),
        )
        timestamp = parsed.analytics_bundle.completed_at
        events = tuple(
            replace(
                event,
                id=f"{result.run_id}:{event.sequence:04d}",
                run_id=result.run_id,
                data={"workflow_profile": "company-analytics.v1", "execution_observed": False},
            )
            for event in base.events[:-1]
        )
        sequence = len(events)
        sidecar_events = tuple(
            RunEvent(
                id=f"{result.run_id}:{sequence + index:04d}",
                run_id=result.run_id,
                sequence=sequence + index,
                timestamp=timestamp,
                kind=EventKind.ARTIFACT,
                status="published",
                message=f"Published completed {artifact.kind} artifact.",
                data={"workflow_profile": "company-analytics.v1", "execution_observed": False},
            )
            for index, artifact in enumerate(artifacts, start=1)
        )
        final_sequence = sequence + len(sidecar_events) + 1
        final = RunEvent(
            id=f"{result.run_id}:{final_sequence:04d}",
            run_id=result.run_id,
            sequence=final_sequence,
            timestamp=timestamp,
            kind=EventKind.RUN,
            status=RunStatus.COMPLETED.value,
            message="Company analytics publication completed atomically.",
            data={"workflow_profile": "company-analytics.v1", "execution_observed": False},
        )
        return PublicationDraft(result=result, events=(*events, *sidecar_events, final))
