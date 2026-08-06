from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from company_analytics_fixtures import complete_analytics_submission
from jsonschema import Draft202012Validator

from stock_research_agents import cli, mcp_server, viewer_server
from stock_research_agents.company_analytics import (
    get_company_research_quality,
    record_company_forecast_outcome,
)
from stock_research_agents.company_analytics_v1 import CompanyAnalyticsV1Provider
from stock_research_agents.company_lifecycle import (
    STAGE_ENVELOPE_SCHEMA_VERSION,
    CompanyAnalyticsCoordinator,
    publication_lifecycle_run_id,
)
from stock_research_agents.conformance import evaluate_validation
from stock_research_agents.lifecycle import LifecycleStatus, LifecycleStore
from stock_research_agents.lifecycle_profiles import CompanyAnalyticsLifecycleProfile
from stock_research_agents.memory import DecisionMemoryStore
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore
from stock_research_agents.view import build_run_view
from stock_research_agents.viewer_server import create_viewer_server, viewer_report

WEB_ROOT = Path(__file__).resolve().parents[1] / "src" / "stock_research_agents" / "web"


def _assert_run_control_schema(control: dict[str, object]) -> None:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stock_research_agents"
        / "workflow"
        / "run-control.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(control)


def _coordinator(tmp_path: Path) -> tuple[CompanyAnalyticsCoordinator, QualityStore]:
    quality_store = QualityStore(tmp_path / "quality")
    return (
        CompanyAnalyticsCoordinator(
            LifecycleStore(tmp_path / "lifecycle"),
            RunStore(tmp_path / "runs"),
            profile=CompanyAnalyticsLifecycleProfile(quality_store),
        ),
        quality_store,
    )


def _envelope(stage: dict[str, object], submission: object | None = None) -> dict[str, object]:
    refs = stage["output_refs"]
    assert isinstance(refs, list)
    output_refs: dict[str, object] = {
        ref: {
            "reference_id": f"host-ref-{hashlib.sha256(ref.encode()).hexdigest()[:16]}",
            "media_type": "application/json",
            "sha256": hashlib.sha256(f"output:{ref}".encode()).hexdigest(),
            "byte_length": 0,
            "summary": "Validated analytics stage output retained by the host.",
        }
        for ref in refs
    }
    if submission is not None:
        output_refs = {str(refs[0]): submission}
    return {
        "schema_version": STAGE_ENVELOPE_SCHEMA_VERSION,
        "stage_id": stage["id"],
        "output_refs": output_refs,
    }


def _complete(
    coordinator: CompanyAnalyticsCoordinator,
    run_id: str,
    revision: int,
    submission: dict[str, object],
) -> int:
    manifest = CompanyAnalyticsV1Provider().load_manifest()
    for stage in manifest["stages"]:
        value = submission if stage["id"] == "publish.completed" else None
        advanced = coordinator.commit_stage(run_id, stage["id"], _envelope(stage, value), revision)
        revision = int(advanced["control"]["revision"])
    return revision


def test_analytics_profile_has_full_durable_lifecycle_and_completed_only_view(tmp_path: Path) -> None:
    submission = complete_analytics_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    coordinator, quality_store = _coordinator(tmp_path)
    control = coordinator.create(
        request,
        research_pack_id="initiating-coverage.v1",
        decision_memory_enabled=False,
    )
    started = coordinator.start(control["run_id"], control["revision"])

    assert started["context"]["research_pack_id"] == "initiating-coverage.v1"
    assert started["context"]["execution_mode"] == "sequential"
    assert started["control"]["workflow_profile"] == "company-analytics.v1"
    assert started["control"]["execution_mode_readiness"] == "executor_required"
    assert started["control"]["execution_mode_locally_ready"] is False
    assert coordinator.result_store.get_result(control["run_id"]) is None

    first = started["stage"]
    advanced = coordinator.commit_stage(
        control["run_id"],
        first["id"],
        _envelope(first),
        started["control"]["revision"],
    )
    paused = coordinator.pause(control["run_id"], advanced["control"]["revision"], "restart proof")

    restarted, restarted_quality_store = _coordinator(tmp_path)
    resumed = restarted.resume(control["run_id"], paused["revision"])
    revision = int(resumed["control"]["revision"])
    for stage in CompanyAnalyticsV1Provider().load_manifest()["stages"][1:]:
        value = submission if stage["id"] == "publish.completed" else None
        advanced = restarted.commit_stage(control["run_id"], stage["id"], _envelope(stage, value), revision)
        revision = int(advanced["control"]["revision"])

    result, events = restarted.finalize(control["run_id"], revision)
    validation = evaluate_validation(result, events)
    quality = get_company_research_quality(
        result.run_id,
        quality_store=restarted_quality_store,
        run_store=restarted.result_store,
    )
    view = build_run_view(
        result,
        events,
        quality_projection=quality["research_quality"],  # type: ignore[arg-type]
    ).to_dict()

    assert restarted.control(control["run_id"])["status"] == LifecycleStatus.COMPLETED
    assert validation.passed is True
    assert publication_lifecycle_run_id(events) == control["run_id"]
    assert len(events) == 34
    assert len(restarted.control(control["run_id"])["completed_stage_ids"]) == 26
    completed_control = restarted.control(control["run_id"])
    assert completed_control["result_run_id"] == result.run_id
    assert result.submission.run_card.stages[-1].stage_id == "publish.completed"
    assert len(result.submission.run_card.stages) == 26
    view_artifacts = view["artifacts"]
    for artifact_id in ("data.company-analytics-result.v1", "data.run-events.v1"):
        descriptor = next(artifact for artifact in view_artifacts if artifact["id"] == artifact_id)
        assert descriptor["content"]["run_id"] == result.run_id
        assert f"/api/runs/{result.run_id}/" in descriptor["content"]["availability"]
    assert view["analytics"] is not None
    assert view["research_lab"]["quality_history"] is not None
    assert quality["quality_run_id"].startswith("analytics-")  # type: ignore[union-attr]
    assert quality_store.state_dir == restarted_quality_store.state_dir
    run_card_artifact = next(artifact for artifact in result.artifacts if artifact.kind == "run_card.v1")
    commitments = run_card_artifact.content["coordinator_commitments"]  # type: ignore[index]
    stages = run_card_artifact.content["stages"]  # type: ignore[index]
    assert len(commitments) == 26
    assert [item["stage_id"] for item in commitments] == [item["stage_id"] for item in stages]
    assert [item["envelope_digest"] for item in commitments] == [item["output_digest"] for item in stages]
    assert all(len(item["receipt_digest"]) == 64 for item in commitments)


def test_canonical_result_and_lifecycle_alias_stay_hidden_until_memory_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = complete_analytics_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    result_store = RunStore(tmp_path / "runs")
    memory_store = DecisionMemoryStore(tmp_path / "decision-memory.sqlite3")
    quality_store = QualityStore(tmp_path / "quality")
    coordinator = CompanyAnalyticsCoordinator(
        LifecycleStore(tmp_path / "lifecycle"),
        result_store,
        memory_store=memory_store,
        profile=CompanyAnalyticsLifecycleProfile(quality_store),
    )
    control = coordinator.create(request, decision_memory_enabled=True)
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete(coordinator, control["run_id"], started["control"]["revision"], submission)
    original_publish = memory_store.publish_decision

    def fail_memory_publish(run_id: str):
        raise OSError(f"injected decision-memory publication failure for {run_id}")

    monkeypatch.setattr(memory_store, "publish_decision", fail_memory_publish)
    with pytest.raises(OSError, match="injected decision-memory publication failure"):
        coordinator.finalize(control["run_id"], revision)

    pending = coordinator.control(control["run_id"])
    result_run_id = pending["result_run_id"]
    assert isinstance(result_run_id, str)
    result = result_store.get_result(result_run_id)
    events = result_store.get_events(result_run_id)
    assert result is not None and events is not None
    assert evaluate_validation(result, events).passed is True
    assert publication_lifecycle_run_id(events) == control["run_id"]
    assert pending["publication_pending"] is True
    assert pending["memory_ready"] is False
    outcome = {
        "schema_version": "research-quality.v1",
        "observation_id": "outcome.pending-gate",
        "forecast_id": result.submission.forecasts[0].forecast_id,
        "observed_at": "2027-08-01T00:00:00Z",
        "available_at": "2027-08-01T01:00:00Z",
        "resolved_at": "2027-08-01T02:00:00Z",
        "resolution_status": "resolved",
        "binary_outcome": True,
        "numeric_outcome": None,
        "realized_return": None,
        "benchmark_return": None,
        "outcome_document_ids": ["outcome.document"],
        "evaluator": "fixture evaluator",
        "supersedes_observation_id": None,
    }
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(outcome), encoding="utf-8")
    for requested_run_id in (control["run_id"], result_run_id):
        assert viewer_report(requested_run_id, result_store, coordinator=coordinator)["ok"] is False

    monkeypatch.setattr(cli, "COMPANY_ANALYTICS_COORDINATOR", coordinator)
    monkeypatch.setattr(cli, "RUN_STORE", result_store)
    monkeypatch.setattr(
        cli,
        "get_company_research_quality",
        lambda run_id: get_company_research_quality(run_id, quality_store=quality_store, run_store=result_store),
    )
    monkeypatch.setattr(
        cli,
        "record_company_forecast_outcome",
        lambda payload: record_company_forecast_outcome(payload, quality_store=quality_store),
    )
    monkeypatch.setattr(mcp_server, "COMPANY_ANALYTICS_COORDINATOR", coordinator)
    monkeypatch.setattr(mcp_server, "RUN_STORE", result_store)
    monkeypatch.setattr(
        mcp_server,
        "execute_quality_query",
        lambda run_id: get_company_research_quality(run_id, quality_store=quality_store, run_store=result_store),
    )
    monkeypatch.setattr(
        mcp_server,
        "execute_outcome_append",
        lambda payload: record_company_forecast_outcome(payload, quality_store=quality_store),
    )
    for requested_run_id in (control["run_id"], result_run_id):
        with pytest.raises(ValueError, match="publication is not complete"):
            mcp_server.get_run_result(requested_run_id)
        with pytest.raises(ValueError, match="publication is not complete"):
            mcp_server.get_research_quality(requested_run_id)
        assert cli.main(["quality-show", requested_run_id, "--output", str(tmp_path / "pending-quality.json")]) == 2
        for command in ("run-export", "run-validate", "run-semantics"):
            command_args = [command, requested_run_id]
            if command == "run-export":
                command_args.extend(["--destination", str(tmp_path / f"pending-export-{requested_run_id}")])
            command_args.extend(["--output", str(tmp_path / f"pending-{command}-{requested_run_id}.json")])
            assert cli.main(command_args) == 2
    with pytest.raises(ValueError, match="publication is not complete"):
        mcp_server.record_research_outcome(outcome)
    assert (
        cli.main(["quality-outcome", "--input", str(outcome_path), "--output", str(tmp_path / "pending-outcome.json")])
        == 2
    )

    monkeypatch.setattr(memory_store, "publish_decision", original_publish)
    recovered_result, recovered_events = coordinator.finalize(control["run_id"], pending["revision"])
    assert evaluate_validation(recovered_result, recovered_events).passed is True
    assert coordinator.control(control["run_id"])["publication_pending"] is False
    for requested_run_id in (control["run_id"], result_run_id):
        assert viewer_report(requested_run_id, result_store, coordinator=coordinator)["ok"] is True
        assert mcp_server.get_run_result(requested_run_id)["result"]["run_id"] == result_run_id
        assert mcp_server.get_research_quality(requested_run_id)["quality_run_id"] == result_run_id
        assert cli.main(["quality-show", requested_run_id, "--output", str(tmp_path / "quality.json")]) == 0
        for command in ("run-export", "run-validate", "run-semantics"):
            command_args = [command, requested_run_id]
            if command == "run-export":
                command_args.extend(["--destination", str(tmp_path / f"export-{requested_run_id}")])
            command_args.extend(["--output", str(tmp_path / f"{command}-{requested_run_id}.json")])
            assert cli.main(command_args) == 0
    assert cli.main(["quality-outcome", "--input", str(outcome_path), "--output", str(tmp_path / "outcome.json")]) == 0
    assert mcp_server.record_research_outcome(outcome)["ok"] is True


def test_every_run_control_response_path_validates_against_the_shipped_schema(tmp_path: Path) -> None:
    submission = complete_analytics_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    coordinator, _ = _coordinator(tmp_path)

    created = coordinator.create(request, decision_memory_enabled=False)
    _assert_run_control_schema(created)

    started = coordinator.start(str(created["run_id"]), int(created["revision"]))
    _assert_run_control_schema(started["control"])

    first_stage = started["stage"]
    committed = coordinator.commit_stage(
        str(created["run_id"]),
        first_stage["id"],
        _envelope(first_stage),
        int(started["control"]["revision"]),
    )
    _assert_run_control_schema(committed["control"])

    paused = coordinator.pause(
        str(created["run_id"]),
        int(committed["control"]["revision"]),
        "schema validation checkpoint",
    )
    _assert_run_control_schema(paused)

    resumed = coordinator.resume(str(created["run_id"]), int(paused["revision"]))
    _assert_run_control_schema(resumed["control"])
    _assert_run_control_schema(coordinator.control(str(created["run_id"])))


def test_analytics_publication_recovers_after_publish_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    submission = complete_analytics_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    coordinator, _ = _coordinator(tmp_path)
    control = coordinator.create(request, decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete(coordinator, control["run_id"], started["control"]["revision"], submission)
    original_publish = coordinator.result_store.publish_staged

    def fail_publish(run_id: str):
        raise OSError(f"injected analytics publication failure for {run_id}")

    monkeypatch.setattr(coordinator.result_store, "publish_staged", fail_publish)
    with pytest.raises(OSError, match="injected analytics publication failure"):
        coordinator.finalize(control["run_id"], revision)
    assert coordinator.result_store.get_result(control["run_id"]) is None

    monkeypatch.setattr(coordinator.result_store, "publish_staged", original_publish)
    restarted, _ = _coordinator(tmp_path)
    current = restarted.control(control["run_id"])
    result, _ = restarted.finalize(control["run_id"], current["revision"])
    completed = restarted.control(control["run_id"])
    assert completed["result_run_id"] == result.run_id
    assert completed["publication_pending"] is False


def test_analytics_lifecycle_keeps_publication_pending_until_quality_index_is_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = complete_analytics_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    coordinator, quality_store = _coordinator(tmp_path)
    control = coordinator.create(request, decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete(coordinator, control["run_id"], started["control"]["revision"], submission)
    original_publish = quality_store.publish_registration

    def fail_quality_publish(run_id: str):
        raise OSError(f"injected quality visibility failure for {run_id}")

    monkeypatch.setattr(quality_store, "publish_registration", fail_quality_publish)
    with pytest.raises(OSError, match="injected quality visibility failure"):
        coordinator.finalize(control["run_id"], revision)

    interrupted = coordinator.control(control["run_id"])
    assert interrupted["status"] == LifecycleStatus.FINALIZING
    assert interrupted["publication_pending"] is True
    assert interrupted["sidecars_ready"] is False
    pending_events = coordinator.poll_events(control["run_id"])
    assert pending_events["publication_pending"] is True
    assert all(event["status"] != LifecycleStatus.COMPLETED for event in pending_events["events"])
    assert coordinator.result_store.get_result(control["run_id"]) is None
    publication_coordinator = viewer_server._publication_coordinator(coordinator.result_store, coordinator)
    assert publication_coordinator is not None
    assert publication_coordinator.control(control["run_id"])["workflow_profile"] == "company-analytics.v1"
    assert viewer_report(control["run_id"], coordinator.result_store, coordinator=coordinator)["ok"] is False

    server = create_viewer_server(
        "127.0.0.1",
        0,
        WEB_ROOT,
        coordinator.result_store,
        coordinator=coordinator,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"http://{host}:{port}/api/runs/{control['run_id']}/view", timeout=5)  # noqa: S310
        assert exc_info.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    monkeypatch.setattr(quality_store, "publish_registration", original_publish)
    result, _ = coordinator.finalize(control["run_id"], interrupted["revision"])
    recovered = coordinator.control(control["run_id"])
    assert recovered["status"] == LifecycleStatus.COMPLETED
    assert recovered["result_run_id"] == result.run_id
    assert recovered["publication_pending"] is False
    assert recovered["sidecars_ready"] is True
    assert coordinator.poll_events(control["run_id"])["events"][-1]["status"] == LifecycleStatus.COMPLETED


def test_cli_and_mcp_create_the_same_durable_analytics_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = complete_analytics_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    coordinator, _ = _coordinator(tmp_path)
    monkeypatch.setattr(cli, "COMPANY_ANALYTICS_COORDINATOR", coordinator)
    monkeypatch.setattr(mcp_server, "COMPANY_ANALYTICS_COORDINATOR", coordinator)
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "created.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    assert (
        cli.main(
            [
                "analytics-init",
                "--input",
                str(request_path),
                "--pack",
                "initiating-coverage.v1",
                "--no-decision-memory",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    cli_control = json.loads(output_path.read_text(encoding="utf-8"))["control"]
    mcp_control = mcp_server.create_company_analytics_run(
        request,  # type: ignore[arg-type]
        research_pack_id="initiating-coverage.v1",
        decision_memory_enabled=False,
    )["control"]

    assert cli_control["workflow_profile"] == "company-analytics.v1"
    assert mcp_control["workflow_profile"] == "company-analytics.v1"
    assert cli_control["next_stage_id"] == mcp_control["next_stage_id"] == "research.plan"


def test_mcp_shared_lifecycle_controls_publish_all_26_analytics_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = complete_analytics_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    coordinator, _ = _coordinator(tmp_path)
    monkeypatch.setattr(mcp_server, "COMPANY_ANALYTICS_COORDINATOR", coordinator)
    created = mcp_server.create_company_analytics_run(
        request,  # type: ignore[arg-type]
        decision_memory_enabled=False,
    )["control"]
    started = mcp_server.start_run(created["run_id"], created["revision"])
    revision = int(started["control"]["revision"])

    for stage in CompanyAnalyticsV1Provider().load_manifest()["stages"]:
        value = submission if stage["id"] == "publish.completed" else None
        advanced = mcp_server.commit_run_stage(
            created["run_id"],
            stage["id"],
            _envelope(stage, value),
            revision,
        )
        revision = int(advanced["control"]["revision"])

    finalized = mcp_server.finalize_run(created["run_id"], revision)
    assert finalized["result"]["run_id"] == finalized["result"]["submission"]["run_card"]["run_id"]
    assert len(finalized["result"]["submission"]["run_card"]["stages"]) == 26
    assert finalized["view"]["analytics"] is not None
    completed = coordinator.control(created["run_id"])
    assert completed["status"] == LifecycleStatus.COMPLETED
    assert completed["result_run_id"] == finalized["result"]["run_id"]
