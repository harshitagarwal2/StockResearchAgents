from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents_portable.capabilities import discovery

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_and_skill_are_complete() -> None:
    plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    skill = (ROOT / "skills" / "tradingagents-portable" / "SKILL.md").read_text(encoding="utf-8")

    assert plugin["name"] == "tradingagents-portable"
    assert plugin["version"]
    assert plugin["skills"] == "./skills/"
    assert plugin["mcpServers"] == "./.mcp.json"
    assert skill.startswith("---\nname: tradingagents-portable\n")
    assert "run_fixture" in skill
    assert "launch_local_dashboard" in skill
    assert "checkpoint_enabled" in skill
    assert "decision/report persistence" in skill
    assert "must never place" in skill


def test_mcp_manifest_has_exact_local_stdio_launch_command() -> None:
    manifest = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"]["tradingagents-portable"]

    assert server["command"] == "uv"
    assert server["args"] == [
        "run",
        "--no-project",
        "--with",
        "mcp>=2.0,<3",
        "python",
        "-m",
        "tradingagents_portable.mcp_server",
    ]
    assert server["cwd"] == "."
    assert server["env"]["PYTHONPATH"] == "src"
    assert "--no-project" in server["args"]
    assert "env_vars" not in server
    assert "API_KEY" not in json.dumps(server)
    assert "CODEX_AUTH" not in json.dumps(server)


def test_mcp_discovery_and_function_schemas_cover_required_surface() -> None:
    payload = discovery(legacy_path=str(ROOT / "does-not-exist"), include_legacy=False)
    expected_tools = {
        "discover_capability",
        "get_feature_matrix",
        "prepare_fixture",
        "run_fixture",
        "prepare_host_run",
        "import_host_run",
        "create_host_run",
        "start_host_run",
        "append_run_receipts",
        "commit_host_stage",
        "pause_host_run",
        "resume_host_run",
        "get_run_control",
        "poll_run_events",
        "request_run_cancellation",
        "acknowledge_run_cancellation",
        "finalize_host_run",
        "export_completed_run",
        "query_decision_memory",
        "record_decision_outcome",
        "get_conformance_report",
        "get_run",
        "get_run_events",
        "get_run_result",
        "get_run_view",
        "launch_local_dashboard",
        "get_dashboard_report",
    }

    assert set(payload["tools"]) == expected_tools
    assert payload["default_fixture"] == {"symbol": "ORCL", "external_credentials_required": False}
    assert payload["executors"] == {"fixture": True, "host_native": True, "legacy": False}

    source = (ROOT / "src" / "tradingagents_portable" / "mcp_server.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    schemas = {
        node.name: node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in expected_tools
    }
    assert set(schemas) == expected_tools

    def defaults(function_name: str) -> dict[str, object]:
        node = schemas[function_name]
        positional = [*node.args.posonlyargs, *node.args.args]
        padded = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
        return {
            parameter.arg: ast.literal_eval(default)
            for parameter, default in zip(positional, padded, strict=True)
            if default is not None
        }

    assert defaults("run_fixture")["debate_rounds"] == 1
    assert defaults("run_fixture")["risk_rounds"] == 1
    assert defaults("prepare_host_run")["debate_rounds"] == 1
    assert defaults("prepare_host_run")["risk_rounds"] == 1
    assert defaults("launch_local_dashboard")["host"] == "127.0.0.1"
    assert defaults("launch_local_dashboard")["port"] == 0

    parameter_names = {
        parameter.arg.lower()
        for node in schemas.values()
        for parameter in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    }
    assert not parameter_names.intersection({"api_key", "secret", "password", "token", "broker", "order"})


def test_registered_mcp_tool_names_match_discovery() -> None:
    pytest.importorskip("mcp")
    mcp_server = importlib.import_module("tradingagents_portable.mcp_server")
    registered = mcp_server.mcp._tool_manager.list_tools()
    names = {tool.name for tool in registered}

    assert names == set(discovery(legacy_path=str(ROOT / "does-not-exist"), include_legacy=False)["tools"])
    assert "run_legacy" not in names


def test_export_mcp_tool_truthfully_declares_destructive_non_idempotent_behavior() -> None:
    pytest.importorskip("mcp")
    mcp_server = importlib.import_module("tradingagents_portable.mcp_server")
    export_tool = next(
        tool for tool in mcp_server.mcp._tool_manager.list_tools() if tool.name == "export_completed_run"
    )

    assert export_tool.annotations is not None
    assert export_tool.annotations.read_only_hint is False
    assert export_tool.annotations.destructive_hint is True
    assert export_tool.annotations.idempotent_hint is False
    assert export_tool.annotations.open_world_hint is False


def test_mutating_mcp_tools_do_not_invite_automatic_idempotent_retries() -> None:
    pytest.importorskip("mcp")
    mcp_server = importlib.import_module("tradingagents_portable.mcp_server")
    mutating = [
        tool
        for tool in mcp_server.mcp._tool_manager.list_tools()
        if tool.annotations is not None and tool.annotations.read_only_hint is False
    ]

    assert mutating
    assert all(tool.annotations.idempotent_hint is False for tool in mutating)


def test_opt_in_legacy_mcp_adds_only_the_explicit_legacy_tool() -> None:
    pytest.importorskip("mcp")
    safe_server = importlib.import_module("tradingagents_portable.mcp_server")
    legacy_server = importlib.import_module("tradingagents_portable.legacy_mcp_server")
    safe_names = {tool.name for tool in safe_server.mcp._tool_manager.list_tools()}
    legacy_names = {tool.name for tool in legacy_server.mcp._tool_manager.list_tools()}

    assert legacy_names == safe_names | {"run_legacy"}


def test_safe_mcp_import_does_not_load_legacy_or_upstream_modules() -> None:
    script = """
import importlib
import json
import sys
importlib.import_module('tradingagents_portable.mcp_server')
loaded = sorted(
    name for name in sys.modules
    if name == 'tradingagents_portable.legacy' or name == 'tradingagents' or name.startswith('tradingagents.')
)
print(json.dumps(loaded))
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned script
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []


def test_legacy_adapter_top_level_export_is_lazy() -> None:
    script = """
import json
import sys
import tradingagents_portable
before = 'tradingagents_portable.legacy' in sys.modules
adapter = tradingagents_portable.LegacyTradingAgentsAdapter
after = 'tradingagents_portable.legacy' in sys.modules
print(json.dumps({'before': before, 'after': after, 'name': adapter.__name__}))
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned script
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "before": False,
        "after": True,
        "name": "LegacyTradingAgentsAdapter",
    }
