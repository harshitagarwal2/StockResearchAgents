from __future__ import annotations

import ast
import importlib
import json
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
        "--extra",
        "upstream",
        "python",
        "-m",
        "tradingagents_portable.mcp_server",
    ]
    assert server["cwd"] == "."
    assert server["env"]["PYTHONPATH"] == "src"
    forwarded = set(server["env_vars"])
    assert {
        "TRADINGAGENTS_LEGACY_PATH",
        "TRADINGAGENTS_CODEX_AUTH_PATH",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AWS_BEARER_TOKEN_BEDROCK",
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "ZHIPU_API_KEY",
        "MINIMAX_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "MOONSHOT_API_KEY",
        "GROQ_API_KEY",
        "NVIDIA_API_KEY",
        "OPENAI_COMPATIBLE_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "FRED_API_KEY",
        "TRADINGAGENTS_LLM_PROVIDER",
        "TRADINGAGENTS_RESULTS_DIR",
        "TRADINGAGENTS_CACHE_DIR",
        "TRADINGAGENTS_MEMORY_LOG_PATH",
    } <= forwarded


def test_mcp_discovery_and_function_schemas_cover_required_surface() -> None:
    payload = discovery(legacy_path=str(ROOT / "does-not-exist"))
    expected_tools = {
        "discover_capability",
        "get_feature_matrix",
        "prepare_fixture",
        "run_fixture",
        "run_legacy",
        "get_run",
        "get_run_events",
        "get_run_result",
        "get_run_view",
        "launch_local_dashboard",
        "get_dashboard_report",
    }

    assert set(payload["tools"]) == expected_tools
    assert payload["default_fixture"] == {"symbol": "ORCL", "external_credentials_required": False}
    assert payload["executors"] == {"fixture": True, "legacy": False}

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
    assert defaults("run_legacy")["debate_rounds"] is None
    assert defaults("run_legacy")["risk_rounds"] is None
    assert defaults("run_legacy")["checkpoint_enabled"] is None
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

    assert names == set(discovery(legacy_path=str(ROOT / "does-not-exist"))["tools"])
