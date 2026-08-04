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
    "commit_host_stage",
    "create_company_research_run",
    "create_company_analytics_run",
    "create_host_run",
    "discover_capability",
    "export_completed_run",
    "finalize_host_run",
    "get_conformance_report",
    "get_dashboard_report",
    "get_feature_matrix",
    "get_run",
    "get_run_events",
    "get_run_result",
    "get_run_semantics",
    "get_run_view",
    "get_run_control",
    "get_research_report_summary",
    "get_research_quality",
    "launch_research_report",
    "launch_local_dashboard",
    "import_host_run",
    "import_company_research",
    "import_company_analytics",
    "pause_host_run",
    "poll_run_events",
    "prepare_host_run",
    "prepare_company_research",
    "prepare_company_analytics",
    "prepare_fixture",
    "query_decision_memory",
    "record_decision_outcome",
    "record_research_outcome",
    "request_run_cancellation",
    "resume_host_run",
    "run_fixture",
    "start_host_run",
}
EXPECTED_RESEARCH_DATA_TOOLS = {
    "research_data_get_regulatory_filings": ["issuer", "jurisdiction", "form_types", "filed_after", "filed_before"],
    "research_data_get_fundamentals": ["symbol", "metrics", "as_of"],
    "research_data_get_financial_statements": ["issuer", "statement_types", "periods", "as_of"],
    "research_data_get_company_news": ["symbol", "published_after", "published_before", "max_items"],
    "research_data_get_global_news": ["topics", "published_after", "published_before", "max_items"],
    "research_data_get_macro": ["series", "regions", "start_time", "end_time", "vintage_as_of"],
}


def _server_parameters(server_name: str, state_dir: Path | None = None) -> StdioServerParameters:
    manifest = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"][server_name]
    environment = os.environ.copy()
    environment.update(server.get("env", {}))
    if state_dir is not None:
        environment["TRADINGAGENTS_PORTABLE_STATE_DIR"] = str(state_dir)
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
    temporary_state = tempfile.TemporaryDirectory(prefix="tradingagents-portable-mcp-smoke-")
    parameters = _server_parameters("tradingagents-portable", Path(temporary_state.name))
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
            transition_contracts = capability["transition_contracts"]
            research_data_contract = transition_contracts["research_data_tools"]
            research_data_tools = {tool["mcp_name"] for tool in research_data_contract["tools"]}
            assert research_data_contract["implementation_status"] == "partial_live"
            assert {tool["mcp_name"] for tool in research_data_contract["tools"] if tool["default_exposed"]} == set(
                EXPECTED_RESEARCH_DATA_TOOLS
            )
            assert research_data_tools.isdisjoint(names)
            legacy_transition = transition_contracts["legacy_transition"]
            assert legacy_transition["removal_allowed"] is False
            assert all(
                gate["status"] == "blocked" and gate["verification"] == "unverified"
                for gate in legacy_transition["removal_gates"]
            )
            executor_states = capability["executor_states"]
            assert executor_states["research_data_adapters"]["surface_exposed"] is True
            assert executor_states["research_data_adapters"]["coordination_mcp_exposed"] is False
            assert executor_states["legacy_transition"]["ready_for_removal"] is False

            plan_response = await session.call_tool(
                "prepare_host_run",
                arguments={"symbol": "ORCL", "as_of_date": "2026-08-01"},
            )
            plan = _payload(plan_response)
            assert plan["execution_owner"] == "host_harness"
            assert plan["external_model_api_keys_accepted"] is False
            assert plan["lifecycle_schema"]["properties"]["status"]["enum"][-1] == "failed"

            created_response = await session.call_tool(
                "create_host_run",
                arguments={
                    "symbol": "ORCL",
                    "as_of_date": "2026-08-01",
                    "analysts": ["market"],
                    "decision_memory_enabled": False,
                },
            )
            created = _payload(created_response)["control"]
            started_response = await session.call_tool(
                "start_host_run",
                arguments={"run_id": created["run_id"], "expected_revision": created["revision"]},
            )
            started = _payload(started_response)
            assert started["stage"]["id"] == "analyst.market"
            cancelled_response = await session.call_tool(
                "request_run_cancellation",
                arguments={
                    "run_id": created["run_id"],
                    "expected_revision": started["control"]["revision"],
                    "reason": "MCP lifecycle smoke completed.",
                },
            )
            cancelled = _payload(cancelled_response)["control"]
            assert cancelled["status"] == "cancel_requested"

            run_response = await session.call_tool(
                "run_fixture",
                arguments={
                    "as_of_date": "2026-07-03",
                    "debate_rounds": 2,
                    "risk_rounds": 2,
                    "presentation_mode": "path_only",
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

            conformance_response = await session.call_tool("get_conformance_report", arguments={"run_id": run_id})
            conformance = _payload(conformance_response)
            assert conformance["ok"] is False
            assert conformance["conformance"]["verified"] is False
            assert not any(check["status"] == "failed" for check in conformance["conformance"]["checks"])

            view_response = await session.call_tool("get_run_view", arguments={"run_id": run_id})
            view_payload = _payload(view_response)
            assert view_payload["ok"] is True
            assert view_payload["run_id"] == run_id
            assert view_payload["overview"]["symbol"] == "ORCL"
            assert len(view_payload["analyst_reports"]) == 4
            intelligence = view_payload["intelligence"]
            assert intelligence["coverage"]["evidence_count"] == 4
            assert intelligence["coverage"]["analyst_count"] == 4
            assert intelligence["coverage"]["source_quality_buckets"] == {"synthetic_fixture": 4}
            assert len(intelligence["evidence_metrics"]) >= 10
            assert len(intelligence["news"]) >= 3
            assert len(intelligence["catalysts"]) >= 3
            assert intelligence["risk_register"]
            assert intelligence["conflicts"]
            assert intelligence["unknowns"]
            assert intelligence["monitoring_conditions"]

            print(
                f"ok tools={len(names)} run={run_id} research_turns=4 risk_turns=6 "
                f"metrics={len(intelligence['evidence_metrics'])} news={len(intelligence['news'])} "
                "executable=false"
            )

    research_parameters = _server_parameters("tradingagents-research-data")
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
