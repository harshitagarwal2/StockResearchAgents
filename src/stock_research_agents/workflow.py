"""Standalone workflow and schema metadata loaders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUN_CONTROL_SCHEMA = Path(__file__).resolve().parent / "workflow" / "run-control.v1.schema.json"
COMPANY_RESEARCH_MANIFEST = Path(__file__).resolve().parent / "workflow" / "company-research.v1.json"
COMPANY_RESEARCH_SUBMISSION_SCHEMA = (
    Path(__file__).resolve().parent / "workflow" / "company-research-submission.v1.schema.json"
)
RESEARCH_DATA_TOOLS_MANIFEST = Path(__file__).resolve().parent / "workflow" / "research-data-tools.v1.json"

_RESEARCH_DATA_MCP_NAMES = {
    "prices": "research_data_get_prices",
    "indicators": "research_data_get_indicators",
    "regulatory_filings": "research_data_get_regulatory_filings",
    "fundamentals": "research_data_get_fundamentals",
    "financial_statements": "research_data_get_financial_statements",
    "company_news": "research_data_get_company_news",
    "global_news": "research_data_get_global_news",
    "macro": "research_data_get_macro",
    "prediction_markets": "research_data_get_prediction_markets",
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
    "prediction_markets": ["search_terms", "as_of", "max_items"],
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
    "prediction_markets": ("implemented_public_default", True, "Polymarket Gamma"),
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


def load_company_research_manifest(path: str | Path = COMPANY_RESEARCH_MANIFEST) -> dict[str, Any]:
    """Load and structurally validate the provider-neutral company-research profile."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1.0.0":
        raise ValueError("unsupported company research workflow schema_version")
    if raw.get("id") != "stockresearchagents.company-research.v1":
        raise ValueError("unexpected company research workflow id")
    if raw.get("fallback") != "sequential":
        raise ValueError("company research fallback must be sequential")
    if raw.get("terminal_artifact_kind") != "research_dossier.v1":
        raise ValueError("company research terminal artifact must be research_dossier.v1")

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
                not isinstance(item, str) or not item.startswith("company-research-submission.v1.schema.json#/$defs/")
                for item in output_refs
            )
        ):
            raise ValueError(f"company research stage {stage_id!r} has invalid output contracts")
        seen.add(stage_id)
    if stages[-1]["id"] != "publish.dossier":
        raise ValueError("company research terminal stage must be publish.dossier")
    return raw


def load_company_research_submission_v1_schema(path: str | Path = COMPANY_RESEARCH_SUBMISSION_SCHEMA) -> dict[str, Any]:
    """Load the strict terminal company-research v1 schema."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("$id") != "https://stock-research-agents.local/schemas/company-research-submission.v1.json":
        raise ValueError("unexpected company research submission schema id")
    if raw.get("$ref") != "#/$defs/companyResearchSubmission" or not isinstance(raw.get("$defs"), dict):
        raise ValueError("company research submission schema must expose companyResearchSubmission")
    return raw


def _load_json_object(path: str | Path, contract_name: str) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{contract_name} must be a JSON object")
    return raw


def load_research_data_tools_manifest(path: str | Path = RESEARCH_DATA_TOOLS_MANIFEST) -> dict[str, Any]:
    """Load authoritative SourceBatch v1 research-data implementation metadata."""
    raw = _load_json_object(path, "research data tools manifest")
    if raw.get("schema_version") != "1.0.0" or raw.get("id") != "stockresearchagents.research-data-tools.v1":
        raise ValueError("unexpected research data tools contract identity")
    if raw.get("kind") != "integration_metadata" or raw.get("provider_neutral") is not True:
        raise ValueError("research data tools must be provider-neutral integration metadata")
    if raw.get("implementation_status") != "partial_live":
        raise ValueError("research data tools must report their partial live implementation exactly")

    exposure = raw.get("exposure")
    expected_exposure = {
        "server": "stock-research-data",
        "default_mcp_exposed": True,
        "coordination_mcp_exposed": False,
        "registration_policy": "register_only_receipted_capabilities",
        "auth_owner": "host",
        "provider_selection_owner": "host",
        "credentials_in_core_contracts": False,
    }
    if exposure != expected_exposure:
        raise ValueError("research data MCP exposure must match the isolated receipt-gated server policy")

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


def integration_contract_catalog() -> dict[str, dict[str, Any]]:
    """Return StockResearchAgents-owned integration metadata."""
    return {"research_data_tools": load_research_data_tools_manifest()}


def workflow_profile_catalog() -> tuple[dict[str, Any], ...]:
    """Advertise the standalone active workflow profile."""
    from .company_analytics_v1 import CompanyAnalyticsV1Provider

    return (CompanyAnalyticsV1Provider().descriptor.to_dict(),)


def load_run_control_schema(path: str | Path = RUN_CONTROL_SCHEMA) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("$id") != "https://stock-research-agents.local/schemas/run-control.v1.json":
        raise ValueError("unexpected run control schema id")
    return raw
