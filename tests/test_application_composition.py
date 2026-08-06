from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents import cli, mcp_server
from stock_research_agents.application import (
    CompletedPublicationService,
    CompletedRunQueryService,
    StockResearchApplication,
)
from stock_research_agents.bootstrap import ApplicationRuntime, create_company_analytics_coordinator, create_runtime
from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.company_lifecycle import CompanyAnalyticsCoordinator
from stock_research_agents.contracts import EventKind, RunEvent
from stock_research_agents.lifecycle import LifecycleStore
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.serialization import StoredResult
from stock_research_agents.state import StateLayout
from stock_research_agents.state_migrations import STATE_SCHEMA_VERSION
from stock_research_agents.store import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _entrypoint_environment(state_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["STOCKRESEARCHAGENTS_STATE_DIR"] = str(state_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(PROJECT_ROOT / "src"), environment.get("PYTHONPATH", "")))
    )
    return environment


def _run_module(module: str, state_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *arguments],
        cwd=PROJECT_ROOT,
        env=_entrypoint_environment(state_root),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _state_snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class _GenericResultAdapter:
    """Result port adapter with no bundled viewer or filesystem surface."""

    def __init__(self) -> None:
        self._store = RunStore()

    def get_result(self, run_id: str) -> StoredResult | None:
        return self._store.get_result(run_id)

    def get_events(self, run_id: str) -> tuple[RunEvent, ...] | None:
        return self._store.get_events(run_id)

    def get_staged(self, run_id: str) -> tuple[StoredResult, tuple[RunEvent, ...]] | None:
        return self._store.get_staged(run_id)

    def stage(self, result: StoredResult, events: tuple[RunEvent, ...]) -> None:
        self._store.stage(result, events)

    def publish_staged(self, run_id: str) -> tuple[StoredResult, tuple[RunEvent, ...]]:
        return self._store.publish_staged(run_id)


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


def test_runtime_initializes_empty_state_schema(tmp_path) -> None:
    layout = StateLayout(tmp_path / "state")

    runtime = create_runtime(layout)

    manifest = json.loads((layout.root / "state-schema.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == STATE_SCHEMA_VERSION
    runtime.close()


def test_runtime_rejects_unversioned_non_empty_state(tmp_path) -> None:
    layout = StateLayout(tmp_path / "state")
    layout.root.mkdir()
    (layout.root / "unversioned.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="backup-first state migration"):
        create_runtime(layout)


def test_runtime_rejects_future_state_schema(tmp_path) -> None:
    layout = StateLayout(tmp_path / "state")
    layout.root.mkdir()
    (layout.root / "state-schema.json").write_text(
        json.dumps(
            {
                "schema_version": "99.0.0",
                "source_schema_version": None,
                "migrated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported state schema version"):
        create_runtime(layout)


def test_default_cli_rejects_unversioned_state_without_writes(tmp_path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "unversioned.json").write_text("{}\n", encoding="utf-8")
    before = _state_snapshot(state_root)

    completed = _run_module(
        "stock_research_agents.cli",
        state_root,
        "run-control",
        "analytics-aaaaaaaaaaaa",
    )

    assert completed.returncode != 0
    assert "backup-first state migration" in completed.stderr
    assert _state_snapshot(state_root) == before


def test_default_cli_rejects_future_state_schema_without_writes(tmp_path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "state-schema.json").write_text(
        json.dumps(
            {
                "schema_version": "99.0.0",
                "source_schema_version": None,
                "migrated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    before = _state_snapshot(state_root)

    completed = _run_module(
        "stock_research_agents.cli",
        state_root,
        "run-control",
        "analytics-aaaaaaaaaaaa",
    )

    assert completed.returncode != 0
    assert "unsupported state schema version" in completed.stderr
    assert _state_snapshot(state_root) == before


def test_default_cli_initializes_empty_state_with_exact_manifest(tmp_path) -> None:
    state_root = tmp_path / "state"

    completed = _run_module(
        "stock_research_agents.cli",
        state_root,
        "analytics-import",
        "--input",
        str(tmp_path / "missing.json"),
    )

    assert completed.returncode == 2
    manifest = json.loads((state_root / "state-schema.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"schema_version", "source_schema_version", "migrated_at"}
    assert manifest["schema_version"] == STATE_SCHEMA_VERSION
    assert manifest["source_schema_version"] is None
    assert isinstance(manifest["migrated_at"], str)


def test_default_cli_doctor_does_not_initialize_missing_state(tmp_path) -> None:
    state_root = tmp_path / "state"
    output = tmp_path / "doctor.json"

    completed = _run_module(
        "stock_research_agents.cli",
        state_root,
        "doctor",
        "--output",
        str(output),
    )

    assert completed.returncode == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "degraded"
    assert next(check for check in report["checks"] if check["check_id"] == "state_root")["status"] == "warning"
    assert not state_root.exists()


def test_default_mcp_startup_rejects_unversioned_state_without_writes(tmp_path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "unversioned.json").write_text("{}\n", encoding="utf-8")
    before = _state_snapshot(state_root)

    completed = _run_module("stock_research_agents.mcp_server", state_root)

    assert completed.returncode != 0
    assert "backup-first state migration" in completed.stderr
    assert _state_snapshot(state_root) == before


def test_runtime_keeps_relative_state_bound_after_chdir(tmp_path, monkeypatch) -> None:
    original = tmp_path / "original"
    other = tmp_path / "other"
    original.mkdir()
    other.mkdir()
    monkeypatch.chdir(original)
    layout = StateLayout(Path("relative-state"))
    runtime = create_runtime(layout)

    monkeypatch.chdir(other)
    event = RunEvent(
        id="stable-run:1",
        run_id="stable-run",
        sequence=1,
        timestamp="2026-01-01T00:00:00+00:00",
        kind=EventKind.RUN,
        status="running",
        message="State path remains stable.",
    )
    assert isinstance(runtime.result_store, RunStore)
    runtime.result_store.put_events("stable-run", (event,))

    assert layout.root == (original / "relative-state").resolve()
    assert (original / "relative-state" / "events" / "stable-run.json").is_file()
    assert not (other / "relative-state").exists()
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


def test_cli_report_server_uses_the_injected_run_store(tmp_path, monkeypatch, capsys) -> None:
    runtime = create_runtime(StateLayout(tmp_path / "injected"))
    application = runtime.application
    captured: dict[str, object] = {}

    def create_server(host, port, *, store, coordinator):
        captured.update(host=host, port=port, store=store, coordinator=coordinator)
        return SimpleNamespace(
            server_address=(host, 49152),
            serve_forever=lambda: captured.update(served=True),
            server_close=lambda: captured.update(closed=True),
        )

    monkeypatch.setattr(cli, "create_report_server", create_server)
    try:
        cli._serve_report("127.0.0.1", 0, application=application)
    finally:
        runtime.close()

    assert captured["store"] is application.result_store
    assert captured["coordinator"] is application.coordinator
    assert captured["served"] is True
    assert captured["closed"] is True
    assert "http://127.0.0.1:49152/" in capsys.readouterr().out


def test_cli_report_call_sites_forward_the_injected_application(tmp_path, monkeypatch) -> None:
    runtime = create_runtime(StateLayout(tmp_path / "injected"))
    application = runtime.application
    calls: list[tuple[str, int, str | None, StockResearchApplication | None]] = []

    def serve_report(
        host: str,
        port: int,
        run_id: str | None = None,
        *,
        application: StockResearchApplication | None = None,
    ) -> None:
        calls.append((host, port, run_id, application))

    monkeypatch.setattr(cli, "_serve_report", serve_report)
    submission_path = tmp_path / "submission.json"
    output_path = tmp_path / "result.json"
    submission_path.write_text(json.dumps(complete_analytics_submission("ORCL")), encoding="utf-8")
    try:
        assert cli.main(["report", "--port", "0"], application=application) == 0
        assert (
            cli.main(
                [
                    "analytics-import",
                    "--input",
                    str(submission_path),
                    "--output",
                    str(output_path),
                    "--report",
                    "--port",
                    "0",
                ],
                application=application,
            )
            == 0
        )
    finally:
        runtime.close()

    assert calls[0] == ("127.0.0.1", 0, None, application)
    assert calls[1][0:2] == ("127.0.0.1", 0)
    assert calls[1][2] == json.loads(output_path.read_text(encoding="utf-8"))["result"]["run_id"]
    assert calls[1][3] is application


def test_injected_facade_owns_completed_run_cli_queries(tmp_path, monkeypatch) -> None:
    runtime = create_runtime(StateLayout(tmp_path / "injected"))
    try:
        result, _ = submit_company_analytics(
            complete_analytics_submission("ORCL"),
            store=runtime.result_store,
            quality_store=runtime.quality_store,
        )
        monkeypatch.setattr(cli, "RUN_STORE", RunStore(tmp_path / "unrelated-global-runs"))

        commands = {
            "run-export": ["--destination", str(tmp_path / "export")],
            "run-validate": [],
            "run-semantics": [],
        }
        for command, extra_args in commands.items():
            output = tmp_path / f"{command}.json"
            assert (
                cli.main(
                    [command, result.run_id, *extra_args, "--output", str(output)],
                    application=runtime.application,
                )
                == 0
            )
    finally:
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


def test_generic_result_adapter_keeps_completed_query_view_and_path_presentation_substitutable() -> None:
    lifecycle_store = LifecycleStore()
    result_store = _GenericResultAdapter()
    quality_store = QualityStore()
    coordinator = create_company_analytics_coordinator(
        lifecycle_store=lifecycle_store,
        result_store=result_store,
        quality_store=quality_store,
        use_default_memory=False,
    )
    runtime = ApplicationRuntime(lifecycle_store, result_store, quality_store, coordinator)
    result, events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=result_store,
        quality_store=quality_store,
    )

    completed = runtime.application.completed_runs().get(result.run_id)
    response = runtime.application.completed_response(result, events, presentation_mode="path_only")

    assert completed.result == result
    assert completed.events == events
    assert response["view"]["run_id"] == result.run_id
    assert response["presentation"] == {
        "schema": "presentation-link.v1",
        "schema_version": "presentation-link.v1",
        "run_id": result.run_id,
        "encoded_path": f"/?run={result.run_id}",
        "path": f"/?run={result.run_id}",
        "url": None,
        "status": "path_only",
        "loopback_only": True,
        "reused": False,
        "error": None,
        "url_scope": "none",
        "idle_ttl_seconds": None,
    }


def test_generic_result_adapter_reports_auto_viewer_boundary_without_failing_response() -> None:
    lifecycle_store = LifecycleStore()
    result_store = _GenericResultAdapter()
    quality_store = QualityStore()
    coordinator = create_company_analytics_coordinator(
        lifecycle_store=lifecycle_store,
        result_store=result_store,
        quality_store=quality_store,
        use_default_memory=False,
    )
    runtime = ApplicationRuntime(lifecycle_store, result_store, quality_store, coordinator)
    result, events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=result_store,
        quality_store=quality_store,
    )

    response = runtime.application.completed_response(result, events, presentation_mode="auto")

    assert response["ok"] is True
    assert response["result"]["run_id"] == result.run_id
    assert response["view"]["run_id"] == result.run_id
    assert response["presentation"]["status"] == "unavailable"
    assert response["presentation"]["error"] == {
        "code": "automatic_presentation_requires_run_store",
        "message": "automatic viewer presentation requires the bundled RunStore adapter",
    }


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
