"""Versioned workflow manifest loader and harness execution seam."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .contracts import RunRequest, StageKind, StageSpec, WorkflowTopology

WORKFLOW_SCHEMA_VERSION = "1.0.0"
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "workflow" / "financial-research.v1.json"
DEFAULT_SUBMISSION_SCHEMA = Path(__file__).resolve().parent / "workflow" / "host-submission.v2.schema.json"
DEFAULT_LIFECYCLE_SCHEMA = Path(__file__).resolve().parent / "workflow" / "run-lifecycle.v1.schema.json"
COMPANY_RESEARCH_MANIFEST = Path(__file__).resolve().parent / "workflow" / "company-research.v2.json"
COMPANY_RESEARCH_SUBMISSION_SCHEMA = Path(__file__).resolve().parent / "workflow" / "host-submission.v3.schema.json"
RESEARCH_DATA_TOOLS_MANIFEST = Path(__file__).resolve().parent / "workflow" / "research-data-tools.v1.json"
LEGACY_TRANSITION_MANIFEST = Path(__file__).resolve().parent / "workflow" / "legacy-transition.v1.json"

LEGACY_WORKFLOW_PROFILE = "financial-research.v1"
COMPANY_RESEARCH_PROFILE = "company-research.v2"

_RESEARCH_DATA_MCP_NAMES = {
    "prices": "research_data_get_prices",
    "indicators": "research_data_get_indicators",
    "regulatory_filings": "research_data_get_regulatory_filings",
    "fundamentals": "research_data_get_fundamentals",
    "financial_statements": "research_data_get_financial_statements",
    "company_news": "research_data_get_company_news",
    "global_news": "research_data_get_global_news",
    "macro": "research_data_get_macro",
    "stocktwits": "research_data_get_stocktwits",
    "reddit": "research_data_get_reddit",
}
_RESEARCH_DATA_REQUIRED_QUERY_FIELDS = {
    "prices": ["symbol", "start_time", "end_time", "interval"],
    "indicators": ["symbol", "indicator", "start_time", "end_time", "parameters"],
    "regulatory_filings": ["issuer", "jurisdiction", "form_types", "filed_after", "filed_before"],
    "fundamentals": ["symbol", "metrics", "as_of"],
    "financial_statements": ["issuer", "statement_types", "periods", "as_of"],
    "company_news": ["symbol", "published_after", "published_before", "max_items"],
    "global_news": ["topics", "published_after", "published_before", "max_items"],
    "macro": ["series", "regions", "start_time", "end_time", "vintage_as_of"],
    "stocktwits": ["symbol", "start_time", "end_time", "max_items"],
    "reddit": ["symbol", "start_time", "end_time", "max_items"],
}
_RESEARCH_DATA_CAPABILITY_POLICY = {
    "prices": ("licensed_host_source_port_required", False, "host_licensed_source_port"),
    "indicators": ("licensed_host_source_port_required", False, "host_licensed_source_port"),
    "regulatory_filings": ("implemented_public_default", True, "SEC EDGAR"),
    "fundamentals": ("implemented_public_default", True, "SEC EDGAR"),
    "financial_statements": ("implemented_public_default", True, "SEC EDGAR"),
    "company_news": ("implemented_public_default", True, "GDELT"),
    "global_news": ("implemented_public_default", True, "GDELT"),
    "macro": ("implemented_public_default", True, "World Bank"),
    "stocktwits": ("denied_unregistered", False, "none"),
    "reddit": ("host_oauth_source_port_required", False, "host_reddit_oauth_source_port"),
}
_SOURCE_BATCH_REQUIRED_FIELDS = {
    "capability",
    "query",
    "cutoff",
    "status",
    "items",
    "provenance",
    "entitlement",
    "completeness",
    "pagination",
    "limitations",
}
_BATCH_STATUSES = {"complete", "partial", "unavailable", "denied", "rate_limited", "stale"}
_LEGACY_REMOVAL_GATES = {
    "parity_ledger",
    "source_contracts_and_concrete_adapter_mcp",
    "deterministic_dual_run_semantic_conformance",
    "representative_live_and_failure_matrix",
    "python_cli_mcp_ui_equivalence",
    "saved_result_migration",
    "published_deprecation_release",
    "major_version_boundary",
}
_LEGACY_SURFACE_IDENTIFIERS = {
    "research",
    "tradingagents-portable-legacy-mcp",
    "run_legacy",
    "upstream",
    "LegacyTradingAgentsAdapter",
    "legacy",
    "legacy_config",
    "legacy_post_run",
    "investment_plan",
    "trader_investment_plan",
    "portfolio_manager_decision",
    "final_trade_decision",
    "processed_signal",
    "--report-output",
    "checkpoint_enabled",
    "RunResult",
}


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
    if raw.get("$id") != "https://tradingagents-portable.local/schemas/host-submission.v2.json":
        raise ValueError("unexpected host submission schema id")
    return raw


def load_company_research_manifest(path: str | Path = COMPANY_RESEARCH_MANIFEST) -> dict[str, Any]:
    """Load and structurally validate the provider-neutral company-research profile."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "2.0.0":
        raise ValueError("unsupported company research workflow schema_version")
    if raw.get("id") != "tradingagents.company-research.v2":
        raise ValueError("unexpected company research workflow id")
    if raw.get("fallback") != "sequential":
        raise ValueError("company research fallback must be sequential")
    if raw.get("terminal_artifact_kind") != "research_dossier.v3":
        raise ValueError("company research terminal artifact must be research_dossier.v3")

    stages = raw.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("company research workflow requires ordered stages")
    seen: set[str] = set()
    for expected_ordinal, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            raise ValueError(f"company research stage {expected_ordinal} must be an object")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id or stage_id in seen:
            raise ValueError(f"company research stage {expected_ordinal} has an invalid or duplicate id")
        if stage.get("ordinal") != expected_ordinal:
            raise ValueError(f"company research stage {stage_id!r} has a non-contiguous ordinal")
        dependencies = stage.get("depends_on")
        if not isinstance(dependencies, list) or any(item not in seen for item in dependencies):
            raise ValueError(f"company research stage {stage_id!r} depends on an unknown or later stage")
        capabilities = stage.get("capabilities")
        if (
            not isinstance(capabilities, list)
            or not capabilities
            or any(not isinstance(item, str) or not item for item in capabilities)
        ):
            raise ValueError(f"company research stage {stage_id!r} requires capability identifiers")
        output_refs = stage.get("output_refs")
        if (
            not isinstance(output_refs, list)
            or not output_refs
            or any(
                not isinstance(item, str) or not item.startswith("host-submission.v3.schema.json#/$defs/")
                for item in output_refs
            )
        ):
            raise ValueError(f"company research stage {stage_id!r} has invalid output contracts")
        seen.add(stage_id)
    if stages[-1]["id"] != "publish.dossier":
        raise ValueError("company research terminal stage must be publish.dossier")
    return raw


def load_host_submission_v3_schema(path: str | Path = COMPANY_RESEARCH_SUBMISSION_SCHEMA) -> dict[str, Any]:
    """Load the frozen terminal company-research schema without widening v2."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("$id") != "https://tradingagents-portable.local/schemas/host-submission.v3.json":
        raise ValueError("unexpected host submission v3 schema id")
    if raw.get("$ref") != "#/$defs/hostSubmission" or not isinstance(raw.get("$defs"), dict):
        raise ValueError("host submission v3 schema must expose the hostSubmission definition")
    return raw


def _load_json_object(path: str | Path, contract_name: str) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{contract_name} must be a JSON object")
    return raw


def load_research_data_tools_manifest(path: str | Path = RESEARCH_DATA_TOOLS_MANIFEST) -> dict[str, Any]:
    """Load authoritative SourceBatch v1 research-data implementation metadata."""
    raw = _load_json_object(path, "research data tools manifest")
    if raw.get("schema_version") != "1.0.0" or raw.get("id") != "tradingagents.research-data-tools.v1":
        raise ValueError("unexpected research data tools contract identity")
    if raw.get("kind") != "authoritative_transition_metadata" or raw.get("provider_neutral") is not True:
        raise ValueError("research data tools must be provider-neutral transition metadata")
    if raw.get("implementation_status") != "partial_live":
        raise ValueError("research data tools must report their partial live implementation exactly")

    exposure = raw.get("exposure")
    expected_exposure = {
        "server": "tradingagents-research-data",
        "default_mcp_exposed": True,
        "coordination_mcp_exposed": False,
        "registration_policy": "register_only_conformance_receipted_capabilities",
        "auth_owner": "host",
        "provider_selection_owner": "host",
        "credentials_in_portable_contracts": False,
    }
    if exposure != expected_exposure:
        raise ValueError("research data MCP exposure must match the isolated conformance-gated server policy")

    versioning = raw.get("versioning")
    if not isinstance(versioning, dict) or any(
        versioning.get(key) != "1.0.0" for key in ("capability_semantics", "query_semantics", "response_semantics")
    ):
        raise ValueError("research data capability, query, and response semantics must be versioned at 1.0.0")

    source_batch = raw.get("source_batch")
    if not isinstance(source_batch, dict) or source_batch.get("type") != "SourceBatch":
        raise ValueError("research data responses must use SourceBatch")
    if source_batch.get("version") != "1.0.0" or source_batch.get("implementation_status") != "implemented":
        raise ValueError("unsupported SourceBatch version")
    required_fields = source_batch.get("required_fields")
    if (
        not isinstance(required_fields, list)
        or len(required_fields) != len(_SOURCE_BATCH_REQUIRED_FIELDS)
        or set(required_fields) != _SOURCE_BATCH_REQUIRED_FIELDS
    ):
        raise ValueError("SourceBatch must require cutoff, provenance, entitlement, completeness, and limitations")
    semantics = source_batch.get("semantics")
    normalized_fields = _SOURCE_BATCH_REQUIRED_FIELDS.difference({"capability", "query"})
    if not isinstance(semantics, dict) or not normalized_fields.issubset(semantics):
        raise ValueError("SourceBatch field semantics are incomplete")

    batch_status = raw.get("batch_status")
    if not isinstance(batch_status, dict) or batch_status.get("field") != "status":
        raise ValueError("SourceBatch requires a typed status field")
    status_values = batch_status.get("values")
    if (
        not isinstance(status_values, list)
        or any(not isinstance(status, str) for status in status_values)
        or set(status_values) != _BATCH_STATUSES
    ):
        raise ValueError("SourceBatch status values are incomplete")
    if len(status_values) != len(_BATCH_STATUSES) or batch_status.get("terminal_for_query") is not True:
        raise ValueError("SourceBatch status values must be unique and terminal for the query")

    entitlement = raw.get("entitlement")
    entitlement_fields = {"access", "redistributable", "terms_uri", "license_receipt_id", "limitation"}
    if not isinstance(entitlement, dict) or entitlement.get("status") != "implemented_v1":
        raise ValueError("SourceBatch requires implemented v1 entitlement metadata")
    required_entitlement_fields = entitlement.get("required_fields")
    if (
        not isinstance(required_entitlement_fields, list)
        or any(not isinstance(field, str) for field in required_entitlement_fields)
        or set(required_entitlement_fields) != entitlement_fields
    ):
        raise ValueError("SourceBatch entitlement fields are incomplete")
    if entitlement.get("access_values") != ["allowed", "denied", "unknown"]:
        raise ValueError("SourceBatch entitlement access values are invalid")
    if entitlement.get("redistributable_values") != [True, False, "unknown"]:
        raise ValueError("SourceBatch entitlement redistribution values are invalid")
    if entitlement.get("credentials_allowed") is not False:
        raise ValueError("SourceBatch entitlement metadata must exclude credentials")
    nonredistributable_rule = entitlement.get("nonredistributable_rule")
    if nonredistributable_rule != "when_redistributable_is_false_return_metadata_and_reference_only_with_no_extract":
        raise ValueError("nonredistributable sources must be metadata/reference only with no extract")

    pagination = raw.get("pagination")
    pagination_fields = {"has_more", "next_cursor", "returned_items", "bounded_items"}
    if not isinstance(pagination, dict):
        raise ValueError("SourceBatch pagination metadata is required")
    required_pagination_fields = pagination.get("required_fields")
    if (
        not isinstance(required_pagination_fields, list)
        or any(not isinstance(field, str) for field in required_pagination_fields)
        or set(required_pagination_fields) != pagination_fields
    ):
        raise ValueError("SourceBatch pagination fields are incomplete")
    if not all(
        isinstance(pagination.get(key), str) and pagination[key]
        for key in ("cursor_semantics", "completeness_semantics", "partial_semantics")
    ):
        raise ValueError("SourceBatch pagination and completeness semantics are incomplete")

    social_bounds = raw.get("social_bounds")
    if not isinstance(social_bounds, dict):
        raise ValueError("research data tools require explicit social bounds")
    if social_bounds.get("required_query_fields") != ["symbol", "start_time", "end_time", "max_items"]:
        raise ValueError("social queries require bounded symbol, time, and item inputs")
    if social_bounds.get("maximum_items") != 30:
        raise ValueError("social maximum_items must be exactly 30")
    if social_bounds.get("maximum_window_days") != 7:
        raise ValueError("social maximum_window_days must be exactly 7")
    if social_bounds.get("unbounded_collection") is not False:
        raise ValueError("unbounded social collection is prohibited")

    tools = raw.get("tools")
    if not isinstance(tools, list) or len(tools) != len(_RESEARCH_DATA_MCP_NAMES):
        raise ValueError("research data manifest must define each adapter capability exactly once")
    seen_capabilities: set[str] = set()
    seen_names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError("research data tool entries must be objects")
        capability = tool.get("capability")
        mcp_name = tool.get("mcp_name")
        if capability not in _RESEARCH_DATA_MCP_NAMES or mcp_name != _RESEARCH_DATA_MCP_NAMES[capability]:
            raise ValueError(f"unexpected research data adapter mapping: {capability!r} -> {mcp_name!r}")
        if capability in seen_capabilities or mcp_name in seen_names:
            raise ValueError("research data capabilities and MCP names must be unique")
        expected_status, expected_exposed, expected_provider = _RESEARCH_DATA_CAPABILITY_POLICY[capability]
        if (
            tool.get("implementation_status") != expected_status
            or tool.get("default_exposed") is not expected_exposed
            or tool.get("provider") != expected_provider
        ):
            raise ValueError(f"research data tool {mcp_name!r} must match its exact status and exposure policy")
        if not isinstance(tool.get("limitation"), str) or not tool["limitation"]:
            raise ValueError(f"research data tool {mcp_name!r} requires an explicit limitation")
        query = tool.get("query")
        response = tool.get("response")
        if not isinstance(query, dict) or query.get("version") != "1.0.0":
            raise ValueError(f"research data tool {mcp_name!r} requires versioned query semantics")
        query_fields = query.get("required")
        if (
            not isinstance(query_fields, list)
            or not query_fields
            or any(not isinstance(field, str) or not field for field in query_fields)
            or len(query_fields) != len(set(query_fields))
            or not query.get("semantics")
        ):
            raise ValueError(f"research data tool {mcp_name!r} has incomplete query semantics")
        if query_fields != _RESEARCH_DATA_REQUIRED_QUERY_FIELDS[capability]:
            raise ValueError(f"research data tool {mcp_name!r} must require its exact ordered query fields")
        if not isinstance(response, dict) or response.get("version") != "1.0.0":
            raise ValueError(f"research data tool {mcp_name!r} requires versioned response semantics")
        if response.get("type") != "SourceBatch" or not response.get("item_semantics"):
            raise ValueError(f"research data tool {mcp_name!r} must return normalized SourceBatch records")
        if capability in {"stocktwits", "reddit"} and query_fields != social_bounds["required_query_fields"]:
            raise ValueError(f"social research data tool {mcp_name!r} must apply the declared bounds")
        seen_capabilities.add(capability)
        seen_names.add(mcp_name)
    if seen_capabilities != set(_RESEARCH_DATA_MCP_NAMES):
        raise ValueError("research data capability coverage is incomplete")
    return raw


def load_legacy_transition_manifest(path: str | Path = LEGACY_TRANSITION_MANIFEST) -> dict[str, Any]:
    """Load the pinned oracle-retention and executor-removal gate contract."""
    raw = _load_json_object(path, "legacy transition manifest")
    if raw.get("schema_version") != "1.0.0" or raw.get("id") != "tradingagents.legacy-transition.v1":
        raise ValueError("unexpected legacy transition contract identity")
    if raw.get("kind") != "authoritative_transition_metadata" or raw.get("current_phase") != "oracle_retained":
        raise ValueError("legacy transition must remain in the oracle_retained phase")

    oracle = raw.get("oracle")
    if not isinstance(oracle, dict) or oracle.get("exact_revision") != "a33fd4c0f134485a43553a2c23a63cb14adbd88f":
        raise ValueError("legacy oracle must use the exact authoritative revision")
    for key in ("whitelist", "exclusions"):
        values = oracle.get(key)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value for value in values)
            or len(values) != len(set(values))
        ):
            raise ValueError(f"legacy oracle {key} must be a non-empty unique list")

    retention = raw.get("post_executor_retention")
    required_artifacts = {
        "frozen_legacy_lifecycle_identifiers",
        "frozen_legacy_wire_schemas",
        "historical_legacy_result_readers",
        "historical_legacy_event_readers",
        "historical_legacy_export_readers",
        "representative_sanitized_legacy_results",
        "representative_sanitized_legacy_fixtures",
        "copy_on_write_legacy_migrations",
    }
    if not isinstance(retention, dict) or retention.get("required") is not True:
        raise ValueError("frozen legacy readers, schemas, and results must survive executor removal")
    retained_artifacts = retention.get("artifacts")
    if (
        not isinstance(retained_artifacts, list)
        or any(not isinstance(artifact, str) for artifact in retained_artifacts)
        or set(retained_artifacts) != required_artifacts
    ):
        raise ValueError("post-executor legacy retention artifacts are incomplete")

    surfaces = raw.get("user_facing_legacy_surfaces")
    if not isinstance(surfaces, list) or any(not isinstance(item, dict) for item in surfaces):
        raise ValueError("legacy transition must enumerate every user-facing surface")
    if any(not isinstance(item.get("identifier"), str) or not item["identifier"] for item in surfaces):
        raise ValueError("legacy public/runtime surface identifiers must be non-empty strings")
    identifiers = {item.get("identifier") for item in surfaces}
    if not _LEGACY_SURFACE_IDENTIFIERS.issubset(identifiers):
        missing = sorted(_LEGACY_SURFACE_IDENTIFIERS.difference(identifiers))
        raise ValueError(f"legacy transition is missing required public/runtime identifiers: {missing}")
    if len(identifiers) != len(surfaces):
        raise ValueError("legacy public/runtime surface identifiers must be unique")
    if any(not item.get("identifier") or not item.get("migration_target") for item in surfaces):
        raise ValueError("legacy user-facing surfaces require identifiers and migration targets")

    gates = raw.get("removal_gates")
    if not isinstance(gates, list) or len(gates) != len(_LEGACY_REMOVAL_GATES):
        raise ValueError("legacy transition must define every hard removal gate exactly once")
    if any(not isinstance(gate, dict) for gate in gates):
        raise ValueError("legacy removal gate entries must be objects")
    if any(not isinstance(gate.get("id"), str) or not gate["id"] for gate in gates):
        raise ValueError("legacy removal gate identifiers must be non-empty strings")
    gate_ids = {gate.get("id") for gate in gates}
    if gate_ids != _LEGACY_REMOVAL_GATES:
        raise ValueError("legacy removal gate coverage is incomplete")
    for gate in gates:
        gate_id = gate["id"]
        if gate.get("status") not in {"blocked", "passed"}:
            raise ValueError(f"legacy removal gate {gate_id!r} has an invalid status")
        if gate.get("verification") not in {"unverified", "verified"}:
            raise ValueError(f"legacy removal gate {gate_id!r} has an invalid verification state")
        if not gate.get("required_evidence"):
            raise ValueError(f"legacy removal gate {gate_id!r} requires evidence criteria")
        if not isinstance(gate.get("owner"), str) or not gate["owner"]:
            raise ValueError(f"legacy removal gate {gate_id!r} requires an owner")
        evidence_artifacts = gate.get("evidence_artifacts")
        sign_off = gate.get("sign_off")
        if not isinstance(evidence_artifacts, list) or not isinstance(sign_off, list):
            raise ValueError(f"legacy removal gate {gate_id!r} requires evidence and sign-off lists")
        if (gate["status"], gate["verification"]) not in {("blocked", "unverified"), ("passed", "verified")}:
            raise ValueError(f"legacy removal gate {gate_id!r} has inconsistent status and verification")
        if gate["verification"] == "unverified":
            if evidence_artifacts or gate.get("last_verified_commit") is not None:
                raise ValueError(f"unverified legacy removal gate {gate_id!r} cannot claim evidence")
            if gate.get("last_verified_at") is not None or sign_off:
                raise ValueError(f"unverified legacy removal gate {gate_id!r} cannot claim verification")
            continue
        if not evidence_artifacts or any(not isinstance(item, str) or not item for item in evidence_artifacts):
            raise ValueError(f"verified legacy removal gate {gate_id!r} requires evidence artifacts")
        commit = gate.get("last_verified_commit")
        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise ValueError(f"verified legacy removal gate {gate_id!r} requires a full Git commit")
        verified_at = gate.get("last_verified_at")
        try:
            parsed_verified_at = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError(
                f"verified legacy removal gate {gate_id!r} requires an ISO-8601 verification date"
            ) from exc
        if parsed_verified_at.tzinfo is None:
            raise ValueError(f"verified legacy removal gate {gate_id!r} requires a timezone-aware date")
        if not sign_off or any(not isinstance(item, str) or not item for item in sign_off):
            raise ValueError(f"verified legacy removal gate {gate_id!r} requires sign-off")

    all_gates_verified = all(gate["status"] == "passed" and gate["verification"] == "verified" for gate in gates)
    if raw.get("removal_allowed") is not False and not all_gates_verified:
        raise ValueError("legacy executor removal cannot be allowed while any hard gate is unverified")
    if not isinstance(raw.get("removal_allowed"), bool):
        raise ValueError("legacy removal_allowed must be a boolean")
    return raw


def transition_contract_catalog() -> dict[str, dict[str, Any]]:
    """Return authoritative metadata without registering its prospective tools."""
    return {
        "research_data_tools": load_research_data_tools_manifest(),
        "legacy_transition": load_legacy_transition_manifest(),
    }


def workflow_profile_catalog() -> tuple[dict[str, Any], ...]:
    """Advertise immutable profiles and their compatibility relationship."""
    legacy = load_workflow_manifest()
    company = load_company_research_manifest()
    from .company_analytics_v1 import CompanyAnalyticsV1Provider

    return (
        {
            "profile": LEGACY_WORKFLOW_PROFILE,
            "workflow_id": legacy.id,
            "terminal_schema": "host-submission.v2",
            "compatibility": "legacy_full_topology",
        },
        {
            "profile": COMPANY_RESEARCH_PROFILE,
            "workflow_id": company["id"],
            "terminal_schema": "host-submission.v3",
            "compatibility": "parallel_versioned_extension",
        },
        CompanyAnalyticsV1Provider().descriptor.to_dict(),
    )


def load_run_lifecycle_schema(path: str | Path = DEFAULT_LIFECYCLE_SCHEMA) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("$id") != "https://tradingagents-portable.local/schemas/run-lifecycle.v1.json":
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
