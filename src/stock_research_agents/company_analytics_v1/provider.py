"""Profile provider and atomic publication builder for company analytics v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

from stock_research_agents.contracts import PROTOTYPE_NOTICE, Artifact, EventKind, RunEvent, RunStatus
from stock_research_agents.profiles import ProfileDescriptor
from stock_research_agents.publication import PublicationDraft
from stock_research_agents.schema_bundle import load_company_analytics_submission_v1_schema_bundle

from .contracts import CompanyAnalyticsResultV1, CompanyAnalyticsSubmissionV1, parse_company_analytics_submission_v1

_WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "workflow"
_MANIFEST = _WORKFLOW_DIR / "company-analytics.v1.json"

_MANIFEST_IDENTITY = {
    "schema_version": "1.0.0",
    "id": "stockresearchagents.company-analytics.v1",
    "name": "Evidence-first company research with deterministic analytics and evaluation",
    "fallback": "sequential",
}
_EXECUTION_CONTRACT_VERSION = "stage-instructions.v1"
_GLOBAL_POLICY = {
    "caller_ownership": "Actual prompt wording, model selection, and runtime implementation remain caller-owned.",
    "workflow_semantics": "Stage roles, objectives, and completion criteria are stable execution semantics.",
    "tool_policy": (
        "Research tools must be read-only; deterministic calculators must be versioned; "
        "open-world retrieval must preserve source and timing receipts."
    ),
    "credential_policy": (
        "Credentials remain caller-owned and must not enter core inputs, outputs, state, or artifacts."
    ),
    "evidence_policy": "Unavailable, denied, or unlicensed evidence must be represented explicitly.",
    "completion_policy": "A stage must not report completion when its completion criteria are not satisfied.",
    "authority_policy": "No stage grants broker, order-placement, or trading-execution authority.",
}
_CAPABILITY_NEGOTIATION = {
    "native": {
        "description": "The caller uses its native agents, parallel tools, and structured output.",
        "implementation": "runtime_adapter_contract",
        "readiness": "adapter_required",
        "locally_ready": False,
    },
    "sequential": {
        "description": "A caller-supplied executor processes the same ordered stages through the sequential adapter.",
        "implementation": "caller_supplied_sequential_executor",
        "readiness": "executor_required",
        "locally_ready": False,
    },
    "import": {
        "description": (
            "A caller owns execution and submits one completed bundle through the coordination/import contract."
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
    "system_boundary",
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
        _fail_manifest("global policy does not match the StockResearchAgents execution policy")
    if value.get("capability_negotiation") != _CAPABILITY_NEGOTIATION:
        _fail_manifest("capability readiness must distinguish caller-supplied execution from adapter modes")

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


class CompanyAnalyticsWorkflowDefinition:
    """Versioned workflow definition and terminal publication builder."""

    descriptor = ProfileDescriptor(
        profile="company-analytics.v1",
        workflow_id="stockresearchagents.company-analytics.v1",
        terminal_schema="company-analytics-submission.v1",
        artifact_kinds=(
            "research_dossier.v1",
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
        schema = load_company_analytics_submission_v1_schema_bundle()
        if schema.get("$id") != "https://stock-research-agents.local/schemas/company-analytics-submission.v1.json":
            raise ValueError("invalid company-analytics-submission.v1 schema")
        return schema

    def parse_submission(self, payload: object) -> CompanyAnalyticsSubmissionV1:
        return parse_company_analytics_submission_v1(payload)

    def build_publication(self, submission: object) -> PublicationDraft:
        parsed = parse_company_analytics_submission_v1(submission)
        symbol = parsed.company_research.request.identity.symbol

        def projection(value: object) -> object:
            return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))

        artifacts = (
            Artifact(
                id="research.dossier.v1",
                kind="research_dossier.v1",
                title=f"Completed research dossier: {symbol}",
                media_type="application/vnd.stockresearchagents.research-dossier.v1+json",
                content=projection(parsed.company_research.dossier.to_dict()),
            ),
            Artifact(
                id="research.analytics.v1",
                kind="analytics_bundle.v1",
                title=f"Deterministic analytics: {symbol}",
                media_type="application/vnd.stockresearchagents.analytics-bundle.v1+json",
                content=projection(parsed.analytics_bundle.to_dict()),
            ),
            Artifact(
                id="research.run-card.v1",
                kind="run_card.v1",
                title="Research run card",
                media_type="application/vnd.stockresearchagents.run-card.v1+json",
                content=projection(parsed.run_card.to_dict()),
            ),
            Artifact(
                id="research.hypotheses.v1",
                kind="hypothesis_ledger.v1",
                title="Hypothesis lifecycle",
                media_type="application/vnd.stockresearchagents.hypothesis-ledger.v1+json",
                content=projection([item.to_dict() for item in parsed.hypothesis_ledgers]),
            ),
            Artifact(
                id="research.iterations.v1",
                kind="research_iterations.v1",
                title="Research iteration receipts",
                media_type="application/vnd.stockresearchagents.research-iterations.v1+json",
                content=projection([item.to_dict() for item in parsed.research_iterations]),
            ),
            Artifact(
                id="research.quality.v1",
                kind="research_quality.v1",
                title="Research quality receipt",
                media_type="application/vnd.stockresearchagents.research-quality.v1+json",
                content=projection(parsed.quality_receipt.to_dict()),
            ),
            Artifact(
                id="research.forecasts.v1",
                kind="forecast_set.v1",
                title="Explicit research forecasts",
                media_type="application/vnd.stockresearchagents.forecast-set.v1+json",
                content=projection([item.to_dict() for item in parsed.forecasts]),
            ),
        )
        result = CompanyAnalyticsResultV1(
            schema_version="company-analytics-result.v1",
            run_id=parsed.run_card.run_id,
            status=RunStatus.COMPLETED,
            profile="company-analytics.v1",
            submission=parsed,
            artifacts=artifacts,
            warnings=tuple(
                dict.fromkeys(
                    (
                        *parsed.company_research.dossier.limitations,
                        *parsed.analytics_bundle.limitations,
                        *parsed.run_card.limitations,
                    )
                )
            ),
            started_at=parsed.run_card.started_at,
            completed_at=parsed.run_card.completed_at,
            prototype_notice=PROTOTYPE_NOTICE,
            non_executable=True,
        )
        stage_events = tuple(
            RunEvent(
                id=f"{result.run_id}:{sequence:04d}",
                run_id=result.run_id,
                sequence=sequence,
                timestamp=receipt.completed_at,
                kind=EventKind.STAGE,
                stage_id=receipt.stage_id,
                status=receipt.status,
                message=f"Recorded completed {receipt.stage_id} stage receipt.",
                data={
                    "workflow_profile": result.profile,
                    "input_digest": receipt.input_digest,
                    "output_digest": receipt.output_digest,
                    "attempts": receipt.attempts,
                    "limitation": receipt.limitation,
                },
            )
            for sequence, receipt in enumerate(parsed.run_card.stages, start=1)
        )
        sidecar_events = tuple(
            RunEvent(
                id=f"{result.run_id}:{len(stage_events) + index:04d}",
                run_id=result.run_id,
                sequence=len(stage_events) + index,
                timestamp=result.completed_at,
                kind=EventKind.ARTIFACT,
                status="published",
                message=f"Published completed {artifact.kind} artifact.",
                data={"workflow_profile": result.profile, "artifact_id": artifact.id, "artifact_kind": artifact.kind},
            )
            for index, artifact in enumerate(artifacts, start=1)
        )
        final_sequence = len(stage_events) + len(sidecar_events) + 1
        final = RunEvent(
            id=f"{result.run_id}:{final_sequence:04d}",
            run_id=result.run_id,
            sequence=final_sequence,
            timestamp=result.completed_at,
            kind=EventKind.RUN,
            status=RunStatus.COMPLETED.value,
            message="Company analytics publication completed atomically.",
            data={"workflow_profile": result.profile, "schema_version": result.schema_version},
        )
        return PublicationDraft(result=result, events=(*stage_events, *sidecar_events, final))


# Compatibility name retained for callers that imported the pre-refactor class.
CompanyAnalyticsV1Provider = CompanyAnalyticsWorkflowDefinition
