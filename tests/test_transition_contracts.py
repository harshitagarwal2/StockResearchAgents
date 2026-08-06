from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from stock_research_agents.capabilities import discovery, feature_matrix
from stock_research_agents.workflow import integration_contract_catalog, load_research_data_tools_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_research_data_integration_metadata_is_standalone_and_receipt_gated() -> None:
    manifest = load_research_data_tools_manifest()

    assert manifest["id"] == "stockresearchagents.research-data-tools.v1"
    assert manifest["kind"] == "integration_metadata"
    assert manifest["provider_neutral"] is True
    assert manifest["exposure"] == {
        "server": "stock-research-data",
        "default_mcp_exposed": True,
        "coordination_mcp_exposed": False,
        "registration_policy": "register_only_receipted_capabilities",
        "auth_owner": "host",
        "provider_selection_owner": "host",
        "credentials_in_core_contracts": False,
    }
    serialized = json.dumps(manifest).lower()
    assert "transition" not in serialized
    assert "conformance" not in serialized
    assert "tradingagents" not in serialized


def test_integration_catalog_is_discoverable_without_registering_data_tools() -> None:
    payload = discovery()
    matrix = feature_matrix()

    assert payload["integration_contracts"] == integration_contract_catalog()
    assert "transition_contracts" not in payload
    assert (
        matrix.runtime_readiness["research_data_adapters"]["contract"]
        == payload["integration_contracts"]["research_data_tools"]
    )
    assert not any(str(name).startswith("research_data_") for name in payload["tools"])


def test_research_data_manifest_rejects_retired_identity(tmp_path: Path) -> None:
    manifest = load_research_data_tools_manifest()
    manifest["id"] = "tradingagents.research-data-tools.v1"
    path = tmp_path / "research-data-tools.v1.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="contract identity"):
        load_research_data_tools_manifest(path)


def test_coordination_mcp_excludes_research_data_and_retired_tools() -> None:
    pytest.importorskip("mcp")
    mcp_server = importlib.import_module("stock_research_agents.mcp_server")
    registered = {tool.name for tool in mcp_server.mcp._tool_manager.list_tools()}

    assert registered == set(discovery()["tools"])
    assert not any(name.startswith("research_data_") for name in registered)
    assert not registered.intersection(
        {
            "run_legacy",
            "get_conformance_report",
            "prepare_host_run",
            "import_host_run",
            "prepare_company_research",
            "import_company_research",
            "create_host_run",
            "create_company_research_run",
            "launch_local_dashboard",
            "get_viewer_report",
        }
    )
