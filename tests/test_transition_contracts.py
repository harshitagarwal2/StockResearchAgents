from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingagents_portable.capabilities import discovery, feature_matrix
from tradingagents_portable.workflow import (
    load_legacy_transition_manifest,
    load_research_data_tools_manifest,
)

EXPECTED_DATA_CAPABILITIES = {
    "prices",
    "indicators",
    "regulatory_filings",
    "fundamentals",
    "financial_statements",
    "company_news",
    "global_news",
    "macro",
    "prediction_markets",
    "stocktwits",
    "reddit",
}
EXPECTED_REQUIRED_QUERY_FIELDS = {
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
EXPECTED_CAPABILITY_POLICY = {
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
EXPECTED_REMOVAL_GATES = {
    "parity_ledger",
    "source_contracts_and_concrete_adapter_mcp",
    "deterministic_dual_run_semantic_conformance",
    "representative_live_and_failure_matrix",
    "python_cli_mcp_ui_equivalence",
    "saved_result_migration",
    "published_deprecation_release",
    "major_version_boundary",
}


def _write_manifest(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_research_data_contract_reports_exact_implemented_exposure_and_sourcebatch_v1() -> None:
    manifest = load_research_data_tools_manifest()

    assert manifest["provider_neutral"] is True
    assert manifest["implementation_status"] == "partial_live"
    assert manifest["exposure"] == {
        "server": "tradingagents-research-data",
        "default_mcp_exposed": True,
        "coordination_mcp_exposed": False,
        "registration_policy": "register_only_conformance_receipted_capabilities",
        "auth_owner": "host",
        "provider_selection_owner": "host",
        "credentials_in_portable_contracts": False,
    }
    assert manifest["versioning"]["capability_semantics"] == "1.0.0"
    assert manifest["versioning"]["query_semantics"] == "1.0.0"
    assert manifest["versioning"]["response_semantics"] == "1.0.0"

    source_batch = manifest["source_batch"]
    assert source_batch["type"] == "SourceBatch"
    assert source_batch["implementation_status"] == "implemented"
    assert {
        "cutoff",
        "status",
        "provenance",
        "entitlement",
        "completeness",
        "pagination",
        "limitations",
    }.issubset(source_batch["required_fields"])
    assert set(manifest["batch_status"]["values"]) == {
        "complete",
        "partial",
        "unavailable",
        "denied",
        "rate_limited",
        "stale",
    }
    assert set(manifest["entitlement"]["required_fields"]) == {
        "access",
        "redistributable",
        "terms_uri",
        "license_receipt_id",
        "limitation",
    }
    assert manifest["entitlement"]["status"] == "implemented_v1"
    assert (
        manifest["entitlement"]["nonredistributable_rule"]
        == "when_redistributable_is_false_return_metadata_and_reference_only_with_no_extract"
    )
    assert manifest["pagination"]["completeness_semantics"]
    assert manifest["pagination"]["partial_semantics"]

    tools = manifest["tools"]
    assert {tool["capability"] for tool in tools} == EXPECTED_DATA_CAPABILITIES
    assert len({tool["mcp_name"] for tool in tools}) == len(EXPECTED_DATA_CAPABILITIES)
    assert all(tool["mcp_name"].startswith("research_data_get_") for tool in tools)
    assert {
        tool["capability"]: (tool["implementation_status"], tool["default_exposed"], tool["provider"]) for tool in tools
    } == EXPECTED_CAPABILITY_POLICY
    assert sum(tool["default_exposed"] is True for tool in tools) == 7
    assert all(tool["limitation"] for tool in tools)
    assert all(tool["response"]["type"] == "SourceBatch" for tool in tools)
    assert {tool["capability"]: tool["query"]["required"] for tool in tools} == EXPECTED_REQUIRED_QUERY_FIELDS

    social = manifest["social_bounds"]
    assert social["unbounded_collection"] is False
    assert social["maximum_items"] == 30
    assert social["maximum_window_days"] == 7
    for tool in tools:
        if tool["capability"] in {"stocktwits", "reddit"}:
            assert tool["query"]["required"] == social["required_query_fields"]


@pytest.mark.parametrize("capability", EXPECTED_REQUIRED_QUERY_FIELDS)
@pytest.mark.parametrize("mutation", ["remove", "add", "reorder"])
def test_research_data_loader_rejects_changed_query_contract(
    tmp_path: Path,
    capability: str,
    mutation: str,
) -> None:
    manifest = load_research_data_tools_manifest()
    tool = next(item for item in manifest["tools"] if item["capability"] == capability)
    required = tool["query"]["required"]

    if mutation == "remove":
        required.pop()
    elif mutation == "add":
        required.append("unexpected_field")
    else:
        required[0], required[1] = required[1], required[0]

    path = _write_manifest(tmp_path, f"{capability}-{mutation}.json", manifest)
    with pytest.raises(ValueError, match="must require its exact ordered query fields"):
        load_research_data_tools_manifest(path)


@pytest.mark.parametrize("field", ["implementation_status", "default_exposed", "provider"])
def test_research_data_loader_rejects_changed_capability_policy(tmp_path: Path, field: str) -> None:
    manifest = load_research_data_tools_manifest()
    tool = manifest["tools"][0]
    tool[field] = "unexpected" if field != "default_exposed" else True

    with pytest.raises(ValueError, match="exact status and exposure policy"):
        load_research_data_tools_manifest(_write_manifest(tmp_path, f"changed-{field}.json", manifest))


def test_research_data_loader_rejects_changed_server_exposure_and_incomplete_source_batch(tmp_path: Path) -> None:
    exposed = load_research_data_tools_manifest()
    exposed["exposure"]["coordination_mcp_exposed"] = True
    with pytest.raises(ValueError, match="isolated conformance-gated server policy"):
        load_research_data_tools_manifest(_write_manifest(tmp_path, "exposed.json", exposed))

    incomplete = load_research_data_tools_manifest()
    incomplete["source_batch"]["required_fields"].remove("entitlement")
    with pytest.raises(ValueError, match="SourceBatch must require"):
        load_research_data_tools_manifest(_write_manifest(tmp_path, "incomplete.json", incomplete))


def test_research_data_loader_rejects_extracts_for_nonredistributable_sources(tmp_path: Path) -> None:
    manifest = load_research_data_tools_manifest()
    manifest["entitlement"]["nonredistributable_rule"] = (
        "when_redistributable_is_false_return_only_a_bounded_attributed_extract_permitted_by_host_entitlement"
    )

    with pytest.raises(ValueError, match="metadata/reference only with no extract"):
        load_research_data_tools_manifest(_write_manifest(tmp_path, "unsafe-entitlement.json", manifest))

    wrong_social_bound = load_research_data_tools_manifest()
    wrong_social_bound["social_bounds"]["maximum_items"] = 31
    with pytest.raises(ValueError, match="exactly 30"):
        load_research_data_tools_manifest(_write_manifest(tmp_path, "wrong-social-bound.json", wrong_social_bound))


def test_legacy_transition_retains_exact_oracle_surfaces_and_frozen_artifacts() -> None:
    manifest = load_legacy_transition_manifest()

    assert manifest["current_phase"] == "oracle_retained"
    assert manifest["removal_allowed"] is False
    assert manifest["oracle"]["exact_revision"] == "a33fd4c0f134485a43553a2c23a63cb14adbd88f"
    assert manifest["oracle"]["whitelist"]
    assert manifest["oracle"]["exclusions"]
    assert set(manifest["post_executor_retention"]["artifacts"]) == {
        "frozen_legacy_lifecycle_identifiers",
        "frozen_legacy_wire_schemas",
        "historical_legacy_result_readers",
        "historical_legacy_event_readers",
        "historical_legacy_export_readers",
        "representative_sanitized_legacy_results",
        "representative_sanitized_legacy_fixtures",
        "copy_on_write_legacy_migrations",
    }
    surface_ids = {surface["identifier"] for surface in manifest["user_facing_legacy_surfaces"]}
    assert {
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
    }.issubset(surface_ids)
    assert {
        "--clear-checkpoints",
        "--legacy-path",
        "create_legacy_server",
        "resolve_subject",
        "clear_checkpoints",
        "report_output_path",
    }.issubset(surface_ids)
    assert all(surface["migration_target"] for surface in manifest["user_facing_legacy_surfaces"])

    gates = manifest["removal_gates"]
    assert {gate["id"] for gate in gates} == EXPECTED_REMOVAL_GATES
    assert all(gate["status"] == "blocked" for gate in gates)
    assert all(gate["verification"] == "unverified" for gate in gates)
    assert all(gate["owner"] for gate in gates)
    assert all(gate["evidence_artifacts"] == [] for gate in gates)
    assert all(gate["last_verified_commit"] is None for gate in gates)
    assert all(gate["last_verified_at"] is None for gate in gates)
    assert all(gate["sign_off"] == [] for gate in gates)


@pytest.mark.parametrize("unverified_gate", sorted(EXPECTED_REMOVAL_GATES))
def test_removal_cannot_be_true_while_any_gate_is_unverified(tmp_path: Path, unverified_gate: str) -> None:
    manifest = load_legacy_transition_manifest()
    manifest["removal_allowed"] = True
    for gate in manifest["removal_gates"]:
        gate["status"] = "passed"
        gate["verification"] = "verified"
        gate["evidence_artifacts"] = [f"evidence/{gate['id']}.json"]
        gate["last_verified_commit"] = "1" * 40
        gate["last_verified_at"] = "2026-08-03T12:00:00Z"
        gate["sign_off"] = [gate["owner"]]

    gate = next(gate for gate in manifest["removal_gates"] if gate["id"] == unverified_gate)
    gate["status"] = "blocked"
    gate["verification"] = "unverified"
    gate["evidence_artifacts"] = []
    gate["last_verified_commit"] = None
    gate["last_verified_at"] = None
    gate["sign_off"] = []

    path = _write_manifest(tmp_path, f"{unverified_gate}.json", manifest)
    with pytest.raises(ValueError, match="cannot be allowed"):
        load_legacy_transition_manifest(path)


def test_verified_legacy_gate_requires_evidence_commit_date_and_signoff(tmp_path: Path) -> None:
    manifest = load_legacy_transition_manifest()
    gate = manifest["removal_gates"][0]
    gate["status"] = "passed"
    gate["verification"] = "verified"

    path = _write_manifest(tmp_path, "unsupported-verification.json", manifest)
    with pytest.raises(ValueError, match="requires evidence artifacts"):
        load_legacy_transition_manifest(path)


def test_transition_metadata_is_discoverable_without_registering_fake_tools() -> None:
    payload = discovery(include_legacy=False)
    matrix = feature_matrix(include_legacy=False)
    features = {feature.name: feature for feature in matrix.features}
    research_contract = payload["transition_contracts"]["research_data_tools"]
    data_tool_names = {tool["mcp_name"] for tool in research_contract["tools"]}

    assert payload["transition_contracts"]["legacy_transition"]["removal_allowed"] is False
    assert "upstream_cli_interaction_parity" not in features
    assert features["portable_cli_interaction_coverage"].level.value == "partial"
    assert "externally gated" in features["portable_cli_interaction_coverage"].detail
    readiness = matrix.runtime_readiness["research_data_adapters"]
    assert readiness["surface_exposed"] is True
    assert readiness["coordination_mcp_exposed"] is False
    assert readiness["ready_for_default_public_tools"] is True
    assert readiness["ready_for_full_live_company_research"] is False
    assert readiness["tools_only_live_company_research"] == "partial"
    assert matrix.runtime_readiness["company_analytics_v1"]["capability_mode_readiness"] == {
        "full": "adapter_required",
        "compatible": "locally_ready",
        "tools_only": "partial_adapter_required",
    }
    assert matrix.runtime_readiness["legacy_transition"]["ready_for_removal"] is False
    assert "run_legacy" not in payload["tools"]
    assert data_tool_names.isdisjoint(payload["tools"])


def test_coordination_mcp_registration_excludes_legacy_and_research_data_tools() -> None:
    pytest.importorskip("mcp")
    from tradingagents_portable import mcp_server

    registered = {tool.name for tool in mcp_server.mcp._tool_manager.list_tools()}
    prospective = {tool["mcp_name"] for tool in load_research_data_tools_manifest()["tools"]}

    assert "run_legacy" not in registered
    assert prospective.isdisjoint(registered)
