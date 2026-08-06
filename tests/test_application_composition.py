from __future__ import annotations

from types import SimpleNamespace

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents import cli, mcp_server
from stock_research_agents.application import CompletedPublicationService, CompletedRunQueryService
from stock_research_agents.bootstrap import create_company_analytics_coordinator, create_runtime
from stock_research_agents.company_lifecycle import CompanyAnalyticsCoordinator
from stock_research_agents.lifecycle import LifecycleStore
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.state import StateLayout
from stock_research_agents.store import RunStore


def test_composition_root_builds_coordinator_from_explicit_ports(tmp_path) -> None:
    lifecycle_store = LifecycleStore(tmp_path / "lifecycle")
    result_store = RunStore(tmp_path / "runs")
    quality_store = QualityStore(tmp_path / "quality")
    memory_store = SimpleNamespace()

    coordinator = create_company_analytics_coordinator(
        lifecycle_store=lifecycle_store,
        result_store=result_store,
        quality_store=quality_store,
        memory_store=memory_store,
    )

    assert isinstance(coordinator, CompanyAnalyticsCoordinator)
    assert coordinator.lifecycle_store is lifecycle_store
    assert coordinator.result_store is result_store
    assert coordinator.profile.quality_store is quality_store
    assert coordinator.memory_store is memory_store


def test_state_layout_resolves_every_store_from_one_root(tmp_path) -> None:
    layout = StateLayout(tmp_path / "state")

    runtime = create_runtime(layout)

    assert runtime.state_layout is layout
    assert runtime.lifecycle_store.state_dir == layout.root
    assert runtime.result_store.state_dir == layout.root
    assert runtime.quality_store.state_dir == layout.quality_dir
    runtime.close()


def test_state_layout_resolution_is_stable_after_environment_changes(tmp_path, monkeypatch) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv("STOCKRESEARCHAGENTS_STATE_DIR", str(first))
    layout = StateLayout.from_environment()

    monkeypatch.setenv("STOCKRESEARCHAGENTS_STATE_DIR", str(second))

    assert layout.root == first
    assert layout.quality_dir == first / "quality"
    assert layout.memory_database == first / "decision-memory.sqlite3"


def test_injected_facade_is_used_by_cli_and_mcp_factories(tmp_path) -> None:
    runtime = create_runtime(StateLayout(tmp_path / "injected"))
    application = runtime.application
    request = complete_analytics_submission("ORCL")["company_research"]["request"]
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "control.json"
    import json

    request_path.write_text(json.dumps(request), encoding="utf-8")
    assert (
        cli.main(
            ["analytics-init", "--input", str(request_path), "--no-decision-memory", "--output", str(output_path)],
            application=application,
        )
        == 0
    )
    cli_run_id = json.loads(output_path.read_text(encoding="utf-8"))["control"]["run_id"]
    assert runtime.lifecycle_store.get(cli_run_id) is not None

    diagnostics_path = tmp_path / "diagnostics.json"
    assert cli.main(["doctor", "--output", str(diagnostics_path)], application=application) == 0
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["schema_version"] == "stockresearchagents-diagnostics.v1"

    server = mcp_server.create_server(application)
    create_tool = next(
        tool for tool in server._tool_manager.list_tools() if tool.name == "create_company_analytics_run"
    )
    mcp_response = create_tool.fn(request, "initiating-coverage.v1", False, "sequential")
    assert runtime.lifecycle_store.get(mcp_response["control"]["run_id"]) is not None
    diagnostics_tool = next(
        tool for tool in server._tool_manager.list_tools() if tool.name == "get_operational_diagnostics"
    )
    assert diagnostics_tool.fn()["schema_version"] == "stockresearchagents-diagnostics.v1"
    runtime.close()


def test_runtime_closes_only_factory_owned_memory(tmp_path) -> None:
    owned = SimpleNamespace(closed=0)
    owned.close = lambda: setattr(owned, "closed", owned.closed + 1)
    coordinator = create_company_analytics_coordinator(
        lifecycle_store=LifecycleStore(),
        result_store=RunStore(),
        quality_store=QualityStore(),
        memory_store_factory=lambda: owned,
        use_default_memory=False,
    )
    assert coordinator.decision_memory() is owned
    coordinator.close()
    coordinator.close()
    assert owned.closed == 1
    with pytest.raises(RuntimeError, match="no decision memory store"):
        coordinator.decision_memory()

    external = SimpleNamespace(closed=0)
    external.close = lambda: setattr(external, "closed", external.closed + 1)
    coordinator = create_company_analytics_coordinator(
        lifecycle_store=LifecycleStore(),
        result_store=RunStore(),
        quality_store=QualityStore(),
        memory_store=external,
        use_default_memory=False,
    )
    coordinator.close()
    assert external.closed == 0


def test_pre_refactor_python_imports_remain_compatible() -> None:
    from stock_research_agents.company_analytics import PROFILE_REGISTRY
    from stock_research_agents.memory import DecisionMemory, DecisionMemoryStore
    from stock_research_agents.research_contracts import (
        FactorExposure,
        FactorSnapshot,
        ResearchDossier,
        ResearchDossierV1,
    )

    assert DecisionMemory is DecisionMemoryStore
    assert FactorExposure is FactorSnapshot
    assert ResearchDossier is ResearchDossierV1
    assert PROFILE_REGISTRY.get("company-analytics.v1").descriptor.profile == "company-analytics.v1"


def test_direct_coordinator_construction_uses_an_isolated_compatibility_profile() -> None:
    coordinator = CompanyAnalyticsCoordinator(LifecycleStore(), RunStore())

    assert coordinator.profile.workflow_profile == "company-analytics.v1"
    assert coordinator.profile.quality_store.state_dir is None


def test_lifecycle_profile_compatibility_surfaces_remain_isolated_and_lazy() -> None:
    from stock_research_agents.bootstrap import DEFAULT_RUNTIME
    from stock_research_agents.lifecycle_profiles import (
        COMPANY_ANALYTICS_LIFECYCLE_PROFILE,
        CompanyAnalyticsLifecycleProfile,
    )

    isolated = CompanyAnalyticsLifecycleProfile()
    assert isolated.quality_store.state_dir is None
    assert COMPANY_ANALYTICS_LIFECYCLE_PROFILE is DEFAULT_RUNTIME.coordinator.profile


def test_completed_publication_service_preserves_event_order_and_injected_presentation() -> None:
    result = SimpleNamespace(run_id="run-1", to_dict=lambda: {"run_id": "run-1"})
    events = (
        SimpleNamespace(to_dict=lambda: {"sequence": 1}),
        SimpleNamespace(to_dict=lambda: {"sequence": 2}),
    )
    captured: dict[str, object] = {}

    def present(run_id, store, *, coordinator=None, mode=None):
        captured.update(run_id=run_id, store=store, coordinator=coordinator, mode=mode)
        return {"status": "path_only", "path": "/?run=run-1"}

    service = CompletedPublicationService(
        result_store="store",
        coordinator="coordinator",
        presenter=present,
        view_builder=lambda completed, ordered_events: SimpleNamespace(
            to_dict=lambda: {
                "run_id": completed.run_id,
                "event_sequences": [event.to_dict()["sequence"] for event in ordered_events],
            }
        ),
    )

    response = service.response(result, events, presentation_mode="path_only")

    assert response == {
        "ok": True,
        "result": {"run_id": "run-1"},
        "view": {"run_id": "run-1", "event_sequences": [1, 2]},
        "events": [{"sequence": 1}, {"sequence": 2}],
        "presentation": {"status": "path_only", "path": "/?run=run-1"},
    }
    assert captured == {
        "run_id": "run-1",
        "store": "store",
        "coordinator": "coordinator",
        "mode": "path_only",
    }


def test_completed_run_query_service_applies_gate_before_reading() -> None:
    calls: list[tuple[object, ...]] = []
    result = object()
    events = (object(),)
    store = SimpleNamespace(
        get_result=lambda run_id: calls.append(("result", run_id)) or result,
        get_events=lambda run_id: calls.append(("events", run_id)) or events,
    )

    def gate(run_id, result_store, coordinator):
        calls.append(("gate", run_id, result_store, coordinator))
        return "resolved-run"

    service = CompletedRunQueryService(store, coordinator="coordinator", publication_gate=gate)

    assert service.resolve("current") == "resolved-run"
    assert service.require("current") == ("resolved-run", result, events)
    assert calls == [
        ("gate", "current", store, "coordinator"),
        ("gate", "current", store, "coordinator"),
        ("result", "resolved-run"),
        ("events", "resolved-run"),
    ]


def test_completed_run_query_service_rejects_missing_publication() -> None:
    store = SimpleNamespace(get_result=lambda run_id: None, get_events=lambda run_id: None)
    service = CompletedRunQueryService(store, publication_gate=lambda run_id, *_: run_id)

    with pytest.raises(ValueError, match="completed run not found: missing"):
        service.require("missing")


def test_cli_and_mcp_wrappers_keep_module_level_injection_seams(monkeypatch) -> None:
    result = SimpleNamespace(run_id="run-1", to_dict=lambda: {"run_id": "run-1"})
    event = SimpleNamespace(to_dict=lambda: {"sequence": 1})
    view = SimpleNamespace(to_dict=lambda: {"run_id": "run-1"})
    calls: list[tuple[object, ...]] = []

    def present(run_id, store, *, coordinator=None, mode=None):
        calls.append((run_id, store, coordinator, mode))
        return {"status": "path_only", "path": "/?run=run-1"}

    for module, response_name in (
        (cli, "_completed_publication_payload"),
        (mcp_server, "_completed_publication_response"),
    ):
        monkeypatch.setattr(module, "present_completed_run", present)
        monkeypatch.setattr(module, "build_run_view", lambda *_: view)
        response = getattr(module, response_name)(
            result,
            (event,),
            store="store",
            coordinator="coordinator",
            **({"foreground_report": True} if module is cli else {"presentation_mode": "path_only"}),
        )
        assert response["events"] == [{"sequence": 1}]
        assert response["view"] == {"run_id": "run-1"}

    assert calls == [
        ("run-1", "store", "coordinator", "path_only"),
        ("run-1", "store", "coordinator", "path_only"),
    ]
