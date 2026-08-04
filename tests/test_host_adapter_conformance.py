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


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


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
