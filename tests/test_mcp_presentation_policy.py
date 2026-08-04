from __future__ import annotations

from types import SimpleNamespace

from tradingagents_portable import mcp_server


def test_completion_tool_schemas_expose_only_supported_presentation_modes() -> None:
    tools = {tool.name: tool for tool in mcp_server.mcp._tool_manager.list_tools()}

    for name in (
        "run_fixture",
        "import_host_run",
        "import_company_research",
        "import_company_analytics",
        "finalize_host_run",
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
    assert response["dashboard_path"] == "/?run=run-1"


def test_all_completion_tools_forward_per_call_presentation_mode(monkeypatch) -> None:
    completed = (SimpleNamespace(run_id="run-1"), ())
    calls: list[dict[str, object]] = []

    def response(result, events, **kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_completed_publication_response", response)
    monkeypatch.setattr(mcp_server, "execute_fixture", lambda request: completed)
    monkeypatch.setattr(mcp_server, "execute_host_run_import", lambda payload: completed)
    monkeypatch.setattr(mcp_server, "execute_company_research_import", lambda payload: completed)
    monkeypatch.setattr(mcp_server, "execute_company_analytics_import", lambda payload: completed)

    mcp_server.run_fixture(presentation_mode="path_only")
    mcp_server.import_host_run({}, presentation_mode="path_only")
    mcp_server.import_company_research({}, presentation_mode="path_only")
    mcp_server.import_company_analytics({}, presentation_mode="path_only")

    coordinator = SimpleNamespace(result_store="lifecycle-store", finalize=lambda run_id, revision: completed)
    monkeypatch.setattr(mcp_server, "_coordinator_for_run", lambda run_id: coordinator)
    mcp_server.finalize_host_run("run-1", 2, presentation_mode="path_only")

    assert calls[:4] == [{"presentation_mode": "path_only"}] * 4
    assert calls[4] == {
        "store": "lifecycle-store",
        "coordinator": coordinator,
        "presentation_mode": "path_only",
    }


def test_launch_local_dashboard_preserves_legacy_launch_response(monkeypatch) -> None:
    legacy_response = {
        "ok": True,
        "url": "http://127.0.0.1:12345/?run=run-1",
        "run_id": "run-1",
        "host": "127.0.0.1",
        "port": 12345,
    }
    calls: list[tuple[str, int, str]] = []

    monkeypatch.setattr(mcp_server, "_resolve_run_id", lambda run_id: "run-1")
    monkeypatch.setattr(mcp_server, "_require_completed_publication", lambda run_id: None)

    def launch(host, port, *, run_id):
        calls.append((host, port, run_id))
        return legacy_response

    monkeypatch.setattr(mcp_server, "launch_dashboard", launch)

    response = mcp_server.launch_local_dashboard()

    assert response is legacy_response
    assert calls == [("127.0.0.1", 0, "run-1")]
