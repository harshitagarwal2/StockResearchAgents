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
    assert "launch_research_report" in skill
    assert "launch_local_dashboard" in skill
    assert "checkpoint_enabled" in skill
    assert "decision/report persistence" in skill
    assert "adaptive-history policy" in skill
    assert "five fiscal years" in skill
    assert "eight comparable quarters" in skill
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

    research_data = manifest["mcpServers"]["tradingagents-research-data"]
    assert research_data == {
        "command": "uv",
        "args": [
            "run",
            "--no-project",
            "--with",
            "mcp>=2.0,<3",
            "python",
            "-m",
            "tradingagents_host.research_data_mcp",
        ],
        "cwd": ".",
        "env": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "src"},
    }
    assert "API_KEY" not in json.dumps(research_data)
    assert "CODEX_AUTH" not in json.dumps(research_data)


def test_mcp_discovery_and_function_schemas_cover_required_surface() -> None:
    payload = discovery(legacy_path=str(ROOT / "does-not-exist"), include_legacy=False)
    expected_tools = {
        "discover_capability",
        "get_feature_matrix",
        "prepare_fixture",
        "run_fixture",
        "prepare_host_run",
        "import_host_run",
        "prepare_company_research",
        "import_company_research",
        "prepare_company_analytics",
        "import_company_analytics",
        "record_research_outcome",
        "get_research_quality",
        "create_company_research_run",
        "create_company_analytics_run",
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
        "get_run_semantics",
        "get_run_view",
        "launch_research_report",
        "get_research_report_summary",
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
    assert defaults("launch_research_report")["host"] == "127.0.0.1"
    assert defaults("launch_research_report")["port"] == 0

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


def test_isolated_research_data_mcp_registers_only_receipted_public_tools() -> None:
    pytest.importorskip("mcp")
    research_server = importlib.import_module("tradingagents_host.research_data_mcp")
    registered = {tool.name for tool in research_server.mcp._tool_manager.list_tools()}

    assert registered == {
        "research_data_get_regulatory_filings",
        "research_data_get_fundamentals",
        "research_data_get_financial_statements",
        "research_data_get_company_news",
        "research_data_get_global_news",
        "research_data_get_macro",
    }
    assert not {"research_data_get_prices", "research_data_get_indicators", "research_data_get_reddit"}.intersection(
        registered
    )
    assert "research_data_get_stocktwits" not in registered


def test_mcp_publication_gate_uses_lifecycle_namespace_without_masking_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mcp")
    mcp_server = importlib.import_module("tradingagents_portable.mcp_server")

    class StrictCoordinator:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def control(self, run_id: str) -> dict[str, object]:
            self.calls.append(run_id)
            raise ValueError("corrupt lifecycle state")

    coordinator = StrictCoordinator()
    monkeypatch.setattr(mcp_server, "HOST_RUN_COORDINATOR", coordinator)

    mcp_server._require_completed_publication("fixture-direct")
    assert coordinator.calls == []
    with pytest.raises(ValueError, match="corrupt lifecycle state"):
        mcp_server._require_completed_publication("host-abcdef012345")


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


def test_mcp_conformance_keeps_upstream_identity_separate() -> None:
    pytest.importorskip("mcp")
    from tradingagents_portable.contracts import RunRequest
    from tradingagents_portable.fixture import run_fixture
    from tradingagents_portable.mcp_server import get_conformance_report

    result, _events = run_fixture(RunRequest())
    payload = get_conformance_report(result.run_id)

    assert payload["ok"] is True
    assert payload["conformance"]["portable_conformance"] == {"passed": True, "verified": True}
    assert payload["conformance"]["overall_status"] == "portable_conformant_upstream_unverified"
    assert payload["conformance"]["upstream_compatibility"] == {
        "passed": False,
        "verified": False,
        "status": "skipped",
    }


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


def test_default_cli_import_does_not_load_legacy_or_upstream_modules() -> None:
    script = """
import importlib
import json
import sys
importlib.import_module('tradingagents_portable.cli')
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
