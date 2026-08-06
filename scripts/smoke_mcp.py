"""End-to-end smoke test for the exact MCP stdio command in ``.mcp.json``."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "acknowledge_run_cancellation",
    "append_run_receipts",
    "commit_run_stage",
    "create_company_analytics_run",
    "discover_capability",
    "evaluate_research_quality_cohort",
    "export_completed_run",
    "finalize_run",
    "get_feature_matrix",
    "get_operational_diagnostics",
    "get_run",
    "get_run_events",
    "get_run_result",
    "get_run_semantics",
    "get_run_control",
    "get_run_view",
    "get_validation_report",
    "get_research_report_summary",
    "get_research_quality",
    "launch_research_report",
    "import_company_analytics",
    "pause_run",
    "poll_run_events",
    "prepare_company_analytics",
    "query_decision_memory",
    "record_decision_outcome",
    "record_research_outcome",
    "request_run_cancellation",
    "resume_run",
    "start_run",
}
EXPECTED_RESEARCH_DATA_TOOLS = {
    "research_data_get_regulatory_filings": ["issuer", "jurisdiction", "form_types", "filed_after", "filed_before"],
    "research_data_get_fundamentals": ["symbol", "metrics", "as_of"],
    "research_data_get_financial_statements": ["issuer", "statement_types", "periods", "as_of"],
    "research_data_get_company_news": ["symbol", "published_after", "published_before", "max_items"],
    "research_data_get_global_news": ["topics", "published_after", "published_before", "max_items"],
    "research_data_get_macro": ["series", "regions", "start_time", "end_time", "vintage_as_of"],
    "research_data_get_prediction_markets": ["search_terms", "as_of", "max_items"],
}


def _server_parameters(server_name: str, state_dir: Path | None = None) -> StdioServerParameters:
    manifest = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"][server_name]
    environment = os.environ.copy()
    environment.update(server.get("env", {}))
    if state_dir is not None:
        environment["STOCKRESEARCHAGENTS_STATE_DIR"] = str(state_dir)
        environment["UV_CACHE_DIR"] = str(state_dir / "uv-cache")
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
    temporary_state = tempfile.TemporaryDirectory(prefix="stock-research-agents-mcp-smoke-")
    parameters = _server_parameters("stock-research-agents", Path(temporary_state.name))
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert names == EXPECTED_TOOLS, f"unexpected MCP tools: {sorted(names)}"

            discovery_response = await session.call_tool("discover_capability", arguments={})
            capability = _payload(discovery_response)
            assert capability["active_profile"] == "company-analytics.v1"
            analytics_state = capability["executor_states"]["company_analytics_v1"]
            assert analytics_state["ready"] is True
            assert analytics_state["execution_modes"] == ["native", "sequential", "import"]
            assert set(capability["tools"]) == EXPECTED_TOOLS
            integration_contracts = capability["integration_contracts"]
            research_data_contract = integration_contracts["research_data_tools"]
            research_data_tools = {tool["mcp_name"] for tool in research_data_contract["tools"]}
            assert research_data_contract["implementation_status"] == "partial_live"
            assert {tool["mcp_name"] for tool in research_data_contract["tools"] if tool["default_exposed"]} == set(
                EXPECTED_RESEARCH_DATA_TOOLS
            )
            assert research_data_tools.isdisjoint(names)

            request = json.loads((ROOT / "examples" / "company-request.v1.json").read_text(encoding="utf-8"))
            request["research_plan"]["coverage_dimensions"][-1]["entitlement_policy"] = "caller_entitled_allowed"
            plan_response = await session.call_tool(
                "prepare_company_analytics",
                arguments={"request": request},
            )
            plan = _payload(plan_response)
            assert plan["workflow_id"] == "stockresearchagents.company-analytics.v1"
            assert plan["execution_mode"] == "sequential"
            assert "system_boundary" in plan

            create_response = await session.call_tool(
                "create_company_analytics_run",
                arguments={"request": request, "decision_memory_enabled": False},
            )
            created = _payload(create_response)["control"]
            run_id = created["run_id"]
            assert run_id.startswith("analytics-") and len(run_id) == 22
            started = _payload(
                await session.call_tool(
                    "start_run",
                    arguments={"run_id": run_id, "expected_revision": created["revision"]},
                )
            )
            paused = _payload(
                await session.call_tool(
                    "pause_run",
                    arguments={
                        "run_id": run_id,
                        "expected_revision": started["control"]["revision"],
                        "reason": "stdio smoke pause",
                    },
                )
            )["control"]
            resumed = _payload(
                await session.call_tool(
                    "resume_run",
                    arguments={"run_id": run_id, "expected_revision": paused["revision"]},
                )
            )
            assert resumed["control"]["status"] == "running"
            assert resumed["stage"]["id"] == "research.plan"

            print(f"ok tools={len(names)} run={run_id} profile=company-analytics.v1 executable=false")

    research_parameters = _server_parameters("stock-research-data", Path(temporary_state.name))
    async with stdio_client(research_parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            by_name = {tool.name: tool for tool in tools.tools}
            assert set(by_name) == set(EXPECTED_RESEARCH_DATA_TOOLS)
            for name, required in EXPECTED_RESEARCH_DATA_TOOLS.items():
                schema = by_name[name].input_schema
                assert schema["required"] == required
                assert list(schema["properties"]) == required
                assert not {"api_key", "token", "authorization", "password"}.intersection(schema["properties"])
            print(f"ok research_data_tools={len(by_name)} isolated=true credentials=false")
    temporary_state.cleanup()


def main() -> None:
    asyncio.run(smoke())


if __name__ == "__main__":
    main()
