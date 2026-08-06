from __future__ import annotations

from types import SimpleNamespace

from stock_research_agents import mcp_server


def test_completion_tool_schemas_expose_only_supported_presentation_modes() -> None:
    tools = {tool.name: tool for tool in mcp_server.mcp._tool_manager.list_tools()}

    for name in (
        "import_company_analytics",
        "finalize_run",
    ):
        schema = tools[name].parameters["properties"]["presentation_mode"]
        assert schema["default"] is None
        assert schema["anyOf"] == [
            {"enum": ["auto", "path_only"], "type": "string"},
            {"type": "null"},
        ]


def test_completed_publication_response_forwards_per_call_presentation_mode(monkeypatch) -> None:
    result = SimpleNamespace(run_id="run-1", to_dict=lambda: {"run_id": "run-1"})
    event = SimpleNamespace(to_dict=lambda: {"sequence": 1})
    view = SimpleNamespace(to_dict=lambda: {"run_id": "run-1", "view": True})
    captured: dict[str, object] = {}

    def present(run_id, store, *, coordinator=None, mode=None):
        captured.update(run_id=run_id, store=store, coordinator=coordinator, mode=mode)
        return {"status": "path_only", "path": "/?run=run-1"}

    monkeypatch.setattr(mcp_server, "present_completed_run", present)
    monkeypatch.setattr(mcp_server, "build_run_view", lambda completed, events: view)

    response = mcp_server._completed_publication_response(
        result,
        (event,),
        store="store",
        coordinator="coordinator",
        presentation_mode="path_only",
    )

    assert captured == {
        "run_id": "run-1",
        "store": "store",
        "coordinator": "coordinator",
        "mode": "path_only",
    }
    assert response["presentation"]["status"] == "path_only"
    assert "dashboard_path" not in response


def test_all_completion_tools_forward_per_call_presentation_mode(monkeypatch) -> None:
    completed = (SimpleNamespace(run_id="run-1"), ())
    calls: list[dict[str, object]] = []

    def response(result, events, **kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_completed_publication_response", response)
    monkeypatch.setattr(mcp_server, "execute_company_analytics_import", lambda payload: completed)

    mcp_server.import_company_analytics({}, presentation_mode="path_only")

    coordinator = SimpleNamespace(result_store="lifecycle-store", finalize=lambda run_id, revision: completed)
    monkeypatch.setattr(mcp_server, "_coordinator_for_run", lambda run_id: coordinator)
    mcp_server.finalize_run("run-1", 2, presentation_mode="path_only")

    assert calls[0] == {"presentation_mode": "path_only"}
    assert calls[1] == {
        "store": "lifecycle-store",
        "coordinator": coordinator,
        "presentation_mode": "path_only",
    }
