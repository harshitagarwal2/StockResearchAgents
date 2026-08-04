from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "adapters"
CONTRACT_PATH = ADAPTERS / "host-adapters.v1.json"
CHROME_POLICY_PATH = ADAPTERS / "chrome" / "chrome-retrieval-policy.v1.json"


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _chrome_policy() -> dict[str, Any]:
    return json.loads(CHROME_POLICY_PATH.read_text(encoding="utf-8"))


def _expected_servers(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    environment = contract["environment"]
    return {
        server["server_id"]: {
            "transport": "stdio",
            "command": server["installed_command"],
            "args": [],
            "environment": environment,
        }
        for server in contract["servers"].values()
    }


def _render_hermes_template(contract: dict[str, Any]) -> str:
    lines = [
        "# Merge this mapping into ~/.hermes/config.yaml after installing the package.",
        "mcp_servers:",
    ]
    for server in contract["servers"].values():
        lines.extend(
            [
                f"  {server['server_id']}:",
                f"    command: {server['installed_command']}",
                "    args: []",
                "    env:",
            ]
        )
        lines.extend(f'      {key}: "{value}"' for key, value in contract["environment"].items())
    return "\n".join(lines) + "\n"


def _installed_console_command(name: str) -> str | None:
    adjacent = Path(sys.executable).parent / name
    if adjacent.is_file():
        return str(adjacent)
    return shutil.which(name)


def test_installed_package_templates_match_one_host_adapter_contract() -> None:
    contract = _contract()
    assert contract["schema_version"] == "host-adapters.v1"
    assert contract["runtime"] == "installed_python_package"
    assert contract["workflow_profile"] == "company-analytics.v1"
    assert contract["default_execution_mode"] == "compatible"
    assert (ROOT / contract["canonical_skill"]).is_file()

    expected = _expected_servers(contract)

    claude = json.loads((ADAPTERS / contract["templates"]["claude_code"]).read_text(encoding="utf-8"))
    claude_servers = {
        server_id: {
            "transport": config["type"],
            "command": config["command"],
            "args": config["args"],
            "environment": config["env"],
        }
        for server_id, config in claude["mcpServers"].items()
    }
    assert claude_servers == expected
    assert all("cwd" not in config for config in claude["mcpServers"].values())

    opencode = json.loads((ADAPTERS / contract["templates"]["opencode"]).read_text(encoding="utf-8"))
    opencode_servers = {
        server_id: {
            "transport": "stdio" if config["type"] == "local" else config["type"],
            "command": config["command"][0],
            "args": config["command"][1:],
            "environment": config["environment"],
        }
        for server_id, config in opencode["mcp"]["servers"].items()
    }
    assert opencode_servers == expected
    assert all("cwd" not in config for config in opencode["mcp"]["servers"].values())

    hermes_path = ADAPTERS / contract["templates"]["hermes_agent"]
    assert hermes_path.read_text(encoding="utf-8") == _render_hermes_template(contract)

    serialized_templates = "\n".join(
        (ADAPTERS / path).read_text(encoding="utf-8").lower() for path in contract["templates"].values()
    )
    for forbidden in ("api_key", "authorization", "cookie", "password", "token"):
        assert forbidden not in serialized_templates

    for server in contract["servers"].values():
        assert (ROOT / server["source_launcher"]).is_file()


def test_optional_chrome_policy_is_host_owned_and_structured_routes_stay_preferred() -> None:
    contract = _contract()
    assert contract["optional_retrieval_policies"] == {"chrome": "chrome/chrome-retrieval-policy.v1.json"}
    assert ADAPTERS / contract["optional_retrieval_policies"]["chrome"] == CHROME_POLICY_PATH

    policy = _chrome_policy()
    assert set(policy) == {
        "schema_version",
        "adapter_kind",
        "status",
        "host_control",
        "routing",
        "navigation",
        "content_trust",
        "browser_operations",
        "source_lanes",
        "normalization",
        "browser_state",
        "access_controls",
        "failure_reporting",
        "prohibited_actions",
    }
    assert policy["schema_version"] == "chrome-retrieval-policy.v1"
    assert policy["adapter_kind"] == "host_owned_interactive_browser"
    assert policy["status"] == "optional"
    assert policy["host_control"] == {
        "required_conditions": ["chrome_connected", "host_allowed", "run_approved", "domain_approved"],
        "approval_scope": "exact_run_and_domain",
        "approval_must_be_explicit": True,
        "approval_must_not_carry_between_runs": True,
        "portable_may_launch_chrome": False,
        "portable_may_install_chrome": False,
        "portable_may_force_chrome": False,
    }
    assert policy["routing"] == {
        "structured_routes_preferred": [
            {
                "provider": "sec_edgar",
                "capabilities": ["regulatory_filings", "fundamentals", "financial_statements"],
            },
            {"provider": "gdelt", "capabilities": ["company_news", "global_news"]},
            {"provider": "world_bank", "capabilities": ["macro"]},
            {"provider": "polymarket_gamma", "capabilities": ["prediction_markets"]},
        ],
        "chrome_preferred_for": [
            "interactive_open_web",
            "authenticated_source_gaps",
            "opening_attributable_documents_from_discovery",
        ],
        "chrome_must_not_replace_available_structured_routes": True,
    }


def test_optional_chrome_policy_covers_exact_source_lanes_and_normalizes_receipts() -> None:
    policy = _chrome_policy()
    assert policy["source_lanes"] == [
        "regulator_and_filings",
        "issuer_first_party",
        "financial_history_and_market_state",
        "independent_reporting",
        "industry_and_peers",
        "macro_and_policy",
        "expectations_and_positioning",
        "adversarial_checks",
    ]

    normalization = policy["normalization"]
    assert set(normalization) == {
        "output_contracts",
        "source_batch_required_fields",
        "source_portfolio_receipt_required_fields",
        "observation_identity_required_fields",
        "point_in_time_required_fields",
        "entitlement_required_fields",
        "bounded_content",
        "rendered_access",
        "temporal_truth",
        "digest_scope",
        "publisher_attribution",
    }
    assert normalization["output_contracts"] == [
        {"name": "SourceBatch", "version": "1.0.0"},
        {"name": "SourcePortfolioReceipt", "version": "1.0.0"},
    ]
    assert set(normalization["source_batch_required_fields"]) == {
        "version",
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
    assert set(normalization["source_portfolio_receipt_required_fields"]) == {
        "version",
        "capability",
        "query",
        "status",
        "attempts",
        "batches",
        "coverage_gaps",
        "exact_duplicate_clusters",
        "portfolio_sha256",
    }
    assert set(normalization["observation_identity_required_fields"]) == {
        "source_id",
        "canonical_uri",
        "content_sha256",
        "content_sha256_scope",
        "provider",
        "provider_version",
        "license_receipt_id",
    }
    assert set(normalization["point_in_time_required_fields"]) == {
        "observed_at",
        "published_at",
        "available_at",
        "retrieved_at",
        "cutoff",
    }
    assert set(normalization["entitlement_required_fields"]) == {
        "access",
        "redistributable",
        "terms_uri",
        "license_receipt_id",
        "limitation",
    }
    assert normalization["bounded_content"] == {
        "maximum_extract_characters": 4000,
        "maximum_facts_per_observation": 512,
        "maximum_provider_routes": 64,
        "maximum_portfolio_observations": 50000,
        "raw_body_allowed": False,
        "omit_extract_when_redistribution_is_false_or_unknown": True,
    }
    assert normalization["rendered_access"] == {
        "implies_redistribution_permission": False,
        "default_redistributable": "unknown",
        "default_extract": "omitted",
        "affirmative_redistribution_requires_terms_uri": True,
    }
    assert normalization["temporal_truth"] == {
        "published_at_rule": "explicit_source_metadata_only",
        "missing_published_at_result": "visible_gap_without_observation",
        "historical_availability_must_not_be_inferred_from_current_render": True,
        "past_cutoff_rule": "retain_only_when_established_available_at_is_not_after_cutoff",
        "unestablished_past_availability_result": "visible_gap_without_observation",
    }
    assert normalization["digest_scope"] == {
        "default_allowed": ["bounded_extract", "normalized_source_record"],
        "source_content_allowed_only_when_actual_source_bytes_hashed": True,
    }
    assert normalization["publisher_attribution"] == {
        "provider_identity": "attributable_publisher",
        "chrome_is_provider": False,
        "mixed_publishers_require_separate_batches": True,
    }


def test_optional_chrome_policy_allows_only_approved_read_only_public_https_retrieval() -> None:
    policy = _chrome_policy()
    assert policy["navigation"] == {
        "allowed_schemes": ["https"],
        "allowed_network_scope": "public_internet",
        "available_evidence_requires_host_navigation_attestation": {
            "canonical_final_target": "browser_reported_host_and_origin_after_all_redirects",
            "all_contacted_and_resolved_addresses": "globally_routable_unicast",
            "excluded_address_classes": [
                "private",
                "loopback",
                "link_local",
                "reserved",
                "unspecified",
                "multicast",
                "ipv6_site_local",
            ],
            "canonical_raw_ip_target_must_appear_in_contacted_ip_attestation": True,
            "redirect_receipt": {
                "kind": "browser_canonical_host_origin_receipt",
                "maximum_hops": 10,
                "retained_fields": ["hop_index", "host", "origin"],
                "retain_path_query_or_raw_url": False,
                "every_hop_explicitly_approved": True,
                "every_hop_same_approved_publisher_domain": True,
                "final_attested_host_matches_canonical_final_target": True,
                "cross_domain_public_redirect": "denied",
            },
            "raw_percent_encoded_hostname_syntax_rejected": True,
            "non_ascii_hostname_syntax_rejected": True,
            "one_time_portable_dns_lookup_allowed": False,
        },
        "authenticated_page_rule": "only_approved_domain_and_run_relevant_research_page",
        "denied_targets": [
            "file_urls",
            "chrome_internal_urls",
            "extension_urls",
            "localhost",
            "private_networks",
            "account_pages",
            "settings_pages",
            "messages_pages",
            "unrelated_authenticated_pages",
        ],
    }
    assert policy["content_trust"] == {
        "page_content": "untrusted",
        "page_supplied_instructions": "ignored",
        "prompt_injection_behavior": "stop_route_and_emit_visible_gap",
        "page_content_may_change_policy": False,
        "page_content_may_authorize_actions": False,
    }
    assert policy["browser_operations"] == {
        "mode": "read_only",
        "allowed": ["navigate_to_approved_url", "read_rendered_page", "inspect_attributable_links"],
        "denied": [
            "form_submission",
            "http_post",
            "account_change",
            "file_download",
            "page_script_execution",
            "clipboard_write",
        ],
    }


def test_optional_chrome_policy_keeps_browser_state_private_and_cannot_bypass_controls() -> None:
    policy = _chrome_policy()
    assert policy["browser_state"] == {
        "host_only": ["cookies", "credentials", "history", "session_state", "raw_bodies"],
        "portable_storage_allowed": False,
        "portable_logging_allowed": False,
    }
    assert policy["access_controls"] == {
        "respect_paywalls": True,
        "respect_captchas": True,
        "respect_robots_controls": True,
        "bypass_allowed": False,
    }
    assert policy["failure_reporting"] == {
        "visible_route_results": [
            {"path": "chrome_disconnected", "attempt_status": "unavailable"},
            {"path": "host_or_user_denied", "attempt_status": "denied"},
            {"path": "prompt_injection_detected", "attempt_status": "unavailable"},
            {"path": "private_url_denied", "attempt_status": "denied"},
        ],
        "coverage_gap_rule": {
            "required_or_explicitly_user_selected_route_failure": "coverage_gap_required",
            "optional_non_required_route_failure": (
                "visible_attempt_without_gap_when_structured_portfolio_is_fully_covered"
            ),
        },
        "optional_failure_must_not_downgrade_fully_covered_structured_portfolio": True,
        "silent_fallback_allowed": False,
    }
    assert policy["prohibited_actions"] == [
        "broker_integration",
        "order_placement",
        "simulated_fills",
        "portfolio_mutation",
        "executable_trading_action",
    ]


async def _probe_mcp(
    *,
    command: str,
    args: list[str],
    cwd: Path,
    environment: dict[str, str],
    call_discovery: bool,
) -> tuple[str, frozenset[str], dict[str, Any] | None]:
    parameters = StdioServerParameters(command=command, args=args, cwd=cwd, env=environment)
    async with stdio_client(parameters, errlog=sys.stderr) as streams:
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            tools = frozenset(tool.name for tool in (await session.list_tools()).tools)
            discovery = None
            if call_discovery:
                response = await session.call_tool("discover_capability", {})
                assert response.is_error is False
                assert isinstance(response.structured_content, dict)
                discovery = response.structured_content
            return initialized.server_info.name, tools, discovery


def test_installed_and_source_launchers_have_equivalent_mcp_surfaces(tmp_path: Path) -> None:
    contract = _contract()
    base_environment = {
        **contract["environment"],
        "STOCKRESEARCHAGENTS_PRESENTATION_MODE": "path_only",
    }
    if uv_cache_dir := os.environ.get("UV_CACHE_DIR"):
        base_environment["UV_CACHE_DIR"] = uv_cache_dir

    for key, expected_tool in (
        ("coordination", "discover_capability"),
        ("research_data", "research_data_get_regulatory_filings"),
    ):
        server = contract["servers"][key]
        installed_command = _installed_console_command(server["installed_command"])
        assert installed_command is not None, f"missing installed console command: {server['installed_command']}"

        source_result = asyncio.run(
            _probe_mcp(
                command="bash",
                args=[str(ROOT / server["source_launcher"])],
                cwd=tmp_path,
                environment={
                    **base_environment,
                    "STOCKRESEARCHAGENTS_STATE_DIR": str(tmp_path / f"{key}-source-state"),
                },
                call_discovery=key == "coordination",
            )
        )
        installed_result = asyncio.run(
            _probe_mcp(
                command=installed_command,
                args=[],
                cwd=tmp_path,
                environment={
                    **base_environment,
                    "STOCKRESEARCHAGENTS_STATE_DIR": str(tmp_path / f"{key}-installed-state"),
                },
                call_discovery=key == "coordination",
            )
        )

        assert source_result[:2] == installed_result[:2]
        assert expected_tool in source_result[1]
        if key == "coordination":
            assert source_result[2] == installed_result[2]
            assert source_result[2]["default_fixture"] == {
                "symbol": "ORCL",
                "external_credentials_required": False,
            }
