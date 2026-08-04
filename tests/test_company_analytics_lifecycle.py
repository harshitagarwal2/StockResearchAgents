from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from company_analytics_fixtures import complete_v4_submission

from tradingagents_portable import cli, dashboard, mcp_server
from tradingagents_portable.company_analytics import get_company_research_quality
from tradingagents_portable.company_analytics_v1 import CompanyAnalyticsV1Provider
from tradingagents_portable.company_lifecycle import (
    STAGE_ENVELOPE_SCHEMA_VERSION,
    CompanyResearchCoordinator,
)
from tradingagents_portable.dashboard import create_dashboard_server, dashboard_report
from tradingagents_portable.lifecycle import LifecycleStatus, LifecycleStore
from tradingagents_portable.lifecycle_profiles import CompanyAnalyticsLifecycleProfile
from tradingagents_portable.research_quality_v1 import QualityStore
from tradingagents_portable.store import RunStore
from tradingagents_portable.view import build_run_view

WEB_ROOT = Path(__file__).resolve().parents[1] / "src" / "tradingagents_portable" / "web"


def _coordinator(tmp_path: Path) -> tuple[CompanyResearchCoordinator, QualityStore]:
    quality_store = QualityStore(tmp_path / "quality")
    return (
        CompanyResearchCoordinator(
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
    coordinator: CompanyResearchCoordinator,
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
    submission = complete_v4_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    coordinator, quality_store = _coordinator(tmp_path)
    control = coordinator.create(
        request,
        research_pack_id="initiating-coverage.v1",
        decision_memory_enabled=False,
    )
    started = coordinator.start(control["run_id"], control["revision"])

    assert started["context"]["research_pack_id"] == "initiating-coverage.v1"
    assert started["context"]["execution_mode"] == "compatible"
    assert started["control"]["workflow_profile"] == "company-analytics.v1"
    assert started["control"]["execution_mode_readiness"] == "locally_ready"
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
    assert len(restarted.control(control["run_id"])["completed_stage_ids"]) == 26
    assert result.run_id == control["run_id"]
    assert result.persistence.checkpoint_enabled is True
    assert result.topology.terminal_stage == "publish.completed"
    for artifact_id in ("data.run_result", "data.run_events"):
        descriptor = next(artifact for artifact in result.artifacts if artifact.id == artifact_id)
        assert descriptor.content["run_id"] == result.run_id  # type: ignore[index]
        assert f"/api/runs/{result.run_id}/" in descriptor.content["availability"]  # type: ignore[index,operator]
    assert view["research_lab"]["analytics"] is not None
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


def test_analytics_publication_recovers_after_publish_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    submission = complete_v4_submission("META")
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
    assert result.run_id == control["run_id"]
    assert restarted.control(control["run_id"])["publication_pending"] is False


def test_analytics_lifecycle_keeps_publication_pending_until_quality_index_is_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = complete_v4_submission("META")
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
    monkeypatch.setattr(dashboard, "RUN_STORE", coordinator.result_store)
    monkeypatch.setattr(dashboard.company_lifecycle, "COMPANY_ANALYTICS_COORDINATOR", coordinator)
    publication_coordinator = dashboard._publication_coordinator(coordinator.result_store, None)
    assert publication_coordinator is not None
    assert publication_coordinator.control(control["run_id"])["workflow_profile"] == "company-analytics.v1"
    assert dashboard_report(control["run_id"], coordinator.result_store)["ok"] is False

    server = create_dashboard_server(
        "127.0.0.1",
        0,
        WEB_ROOT,
        coordinator.result_store,
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
    assert result.run_id == control["run_id"]
    assert recovered["status"] == LifecycleStatus.COMPLETED
    assert recovered["publication_pending"] is False
    assert recovered["sidecars_ready"] is True
    assert coordinator.poll_events(control["run_id"])["events"][-1]["status"] == LifecycleStatus.COMPLETED


def test_cli_and_mcp_create_the_same_durable_analytics_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = complete_v4_submission("META")
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
    submission = complete_v4_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]
    coordinator, _ = _coordinator(tmp_path)
    monkeypatch.setattr(mcp_server, "COMPANY_ANALYTICS_COORDINATOR", coordinator)
    created = mcp_server.create_company_analytics_run(
        request,  # type: ignore[arg-type]
        decision_memory_enabled=False,
    )["control"]
    started = mcp_server.start_host_run(created["run_id"], created["revision"])
    revision = int(started["control"]["revision"])

    for stage in CompanyAnalyticsV1Provider().load_manifest()["stages"]:
        value = submission if stage["id"] == "publish.completed" else None
        advanced = mcp_server.commit_host_stage(
            created["run_id"],
            stage["id"],
            _envelope(stage, value),
            revision,
        )
        revision = int(advanced["control"]["revision"])

    finalized = mcp_server.finalize_host_run(created["run_id"], revision)
    assert finalized["result"]["run_id"] == created["run_id"]
    assert len(finalized["result"]["topology"]["stages"]) == 26
    assert finalized["view"]["research_lab"]["analytics"] is not None
    assert coordinator.control(created["run_id"])["status"] == LifecycleStatus.COMPLETED
