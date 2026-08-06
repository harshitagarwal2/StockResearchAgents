from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from stock_research_agents.capabilities import discovery

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_and_skill_use_standalone_identity() -> None:
    plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    skill = (ROOT / "skills" / "stock-research-agents" / "SKILL.md").read_text(encoding="utf-8")

    assert plugin["name"] == "stock-research-agents"
    assert plugin["skills"] == "./skills/"
    assert plugin["mcpServers"] == "./.mcp.json"
    assert skill.startswith("---\nname: stock-research-agents\n")
    assert "prepare_company_analytics" in skill
    assert "launch_research_report" in skill
    assert "must never place" in skill


def test_mcp_manifest_has_exact_local_stdio_launch_commands() -> None:
    manifest = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))

    assert set(manifest["mcpServers"]) == {"stock-research-agents", "stock-research-data"}
    assert manifest["mcpServers"]["stock-research-agents"] == {
        "type": "stdio",
        "command": "bash",
        "args": ["scripts/run-stock-research-mcp"],
        "env": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"},
    }
    assert manifest["mcpServers"]["stock-research-data"] == {
        "type": "stdio",
        "command": "bash",
        "args": ["scripts/run-stock-research-data-mcp"],
        "env": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"},
    }
    assert "API_KEY" not in json.dumps(manifest)


def test_mcp_discovery_and_function_schemas_match_exactly() -> None:
    payload = discovery()
    expected_tools = set(payload["tools"])
    source = (ROOT / "src" / "stock_research_agents" / "mcp_server.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    schemas = {
        node.name: node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in expected_tools
    }

    assert set(schemas) == expected_tools
    assert payload["active_profile"] == "company-analytics.v1"

    parameter_names = {
        parameter.arg.lower()
        for node in schemas.values()
        for parameter in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    }
    assert not parameter_names.intersection(
        {"api_key", "secret", "password", "token", "broker", "order", "upstream_path", "legacy_path"}
    )


def test_registered_mcp_tool_names_match_discovery() -> None:
    pytest.importorskip("mcp")
    mcp_server = importlib.import_module("stock_research_agents.mcp_server")
    registered = mcp_server.mcp._tool_manager.list_tools()

    assert {tool.name for tool in registered} == set(discovery()["tools"])


def test_isolated_research_data_mcp_registers_only_public_tools() -> None:
    pytest.importorskip("mcp")
    research_server = importlib.import_module("stock_research_agents_host.research_data_mcp")
    registered = {tool.name for tool in research_server.mcp._tool_manager.list_tools()}

    assert registered == {
        "research_data_get_regulatory_filings",
        "research_data_get_fundamentals",
        "research_data_get_financial_statements",
        "research_data_get_company_news",
        "research_data_get_global_news",
        "research_data_get_macro",
        "research_data_get_prediction_markets",
    }


def test_export_mcp_tool_declares_destructive_non_idempotent_behavior() -> None:
    pytest.importorskip("mcp")
    mcp_server = importlib.import_module("stock_research_agents.mcp_server")
    export_tool = next(
        tool for tool in mcp_server.mcp._tool_manager.list_tools() if tool.name == "export_completed_run"
    )

    assert export_tool.annotations is not None
    assert export_tool.annotations.read_only_hint is False
    assert export_tool.annotations.destructive_hint is True
    assert export_tool.annotations.idempotent_hint is False
    assert export_tool.annotations.open_world_hint is False


def test_mcp_validation_report_has_no_external_compatibility_state() -> None:
    pytest.importorskip("mcp")
    from company_analytics_fixtures import complete_analytics_submission

    from stock_research_agents.company_analytics import submit_company_analytics
    from stock_research_agents.mcp_server import get_validation_report
    from stock_research_agents.research_quality_v1 import QualityStore
    from stock_research_agents.store import RUN_STORE

    result, _events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=RUN_STORE,
        quality_store=QualityStore(),
    )
    payload = get_validation_report(result.run_id)

    assert payload["ok"] is True
    assert payload["validation"]["overall_status"] == "validation_passed"
    assert "upstream_compatibility" not in payload["validation"]


def test_safe_mcp_import_does_not_load_retired_dependencies() -> None:
    script = """
import importlib
import json
import sys
importlib.import_module('stock_research_agents.mcp_server')
loaded = sorted(
    name for name in sys.modules
    if name == 'tradingagents' or name.startswith(('tradingagents.', 'langgraph', 'langchain'))
)
print(json.dumps(loaded))
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned source
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []
