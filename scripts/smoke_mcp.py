"""End-to-end smoke test for the exact MCP stdio command in ``.mcp.json``."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "discover_capability",
    "get_dashboard_report",
    "get_feature_matrix",
    "get_run",
    "get_run_events",
    "get_run_result",
    "get_run_view",
    "launch_local_dashboard",
    "import_host_run",
    "prepare_host_run",
    "prepare_fixture",
    "run_fixture",
}


def _server_parameters() -> StdioServerParameters:
    manifest = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"]["tradingagents-portable"]
    environment = os.environ.copy()
    environment.update(server.get("env", {}))
    for name in server.get("env_vars", ()):
        if name in os.environ:
            environment[name] = os.environ[name]
    cwd = (ROOT / server.get("cwd", ".")).resolve()
    return StdioServerParameters(
        command=server["command"],
        args=server["args"],
        env=environment,
        cwd=cwd,
    )


def _payload(response: CallToolResult) -> dict[str, Any]:
    assert not response.is_error, response
    if isinstance(response.structured_content, dict):
        return response.structured_content
    text_blocks = [block.text for block in response.content if isinstance(block, TextContent)]
    assert text_blocks, "MCP tool response had no structured content or JSON text"
    parsed = json.loads(text_blocks[0])
    assert isinstance(parsed, dict)
    return parsed


async def smoke() -> None:
    parameters = _server_parameters()
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert names == EXPECTED_TOOLS, f"unexpected MCP tools: {sorted(names)}"

            discovery_response = await session.call_tool("discover_capability", arguments={})
            capability = _payload(discovery_response)
            assert capability["executors"]["fixture"] is True
            assert capability["executors"]["host_native"] is True
            assert capability["executors"]["legacy"] is False
            assert "run_legacy" not in capability["tools"]

            plan_response = await session.call_tool(
                "prepare_host_run",
                arguments={"symbol": "ORCL", "as_of_date": "2026-08-01"},
            )
            plan = _payload(plan_response)
            assert plan["execution_owner"] == "host_harness"
            assert plan["external_model_api_keys_accepted"] is False

            run_response = await session.call_tool(
                "run_fixture",
                arguments={
                    "as_of_date": "2026-07-03",
                    "debate_rounds": 2,
                    "risk_rounds": 2,
                },
            )
            run_payload = _payload(run_response)
            result = run_payload["result"]
            run_id = result["run_id"]

            get_response = await session.call_tool("get_run_result", arguments={"run_id": run_id})
            retrieved = _payload(get_response)
            assert retrieved["ok"] is True
            retrieved_result = retrieved["result"]
            assert retrieved_result["run_id"] == run_id
            assert retrieved_result["status"] == "completed"
            assert len(retrieved_result["research_debate"]) == 4
            assert len(retrieved_result["risk_debate"]) == 6
            assert retrieved_result["trader_decision"]["executable"] is False
            assert retrieved_result["portfolio_decision"]["executable"] is False

            view_response = await session.call_tool("get_run_view", arguments={"run_id": run_id})
            view_payload = _payload(view_response)
            assert view_payload["ok"] is True
            assert view_payload["run_id"] == run_id
            assert view_payload["overview"]["symbol"] == "ORCL"
            assert len(view_payload["analyst_reports"]) == 4

            print(f"ok tools={len(names)} run={run_id} research_turns=4 risk_turns=6 executable=false")


def main() -> None:
    asyncio.run(smoke())


if __name__ == "__main__":
    main()
