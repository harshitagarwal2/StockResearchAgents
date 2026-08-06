from __future__ import annotations

import hashlib
from pathlib import Path

from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents import mcp_server
from stock_research_agents.company_analytics_v1 import CompanyAnalyticsV1Provider
from stock_research_agents.company_lifecycle import STAGE_ENVELOPE_SCHEMA_VERSION, CompanyAnalyticsCoordinator
from stock_research_agents.lifecycle import LifecycleStore
from stock_research_agents.lifecycle_profiles import CompanyAnalyticsLifecycleProfile
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore


def _stage_envelope(stage: dict[str, object], submission: object | None = None) -> dict[str, object]:
    refs = stage["output_refs"]
    assert isinstance(refs, list)
    outputs: dict[str, object] = {
        str(ref): {
            "reference_id": f"host-ref-{hashlib.sha256(str(ref).encode()).hexdigest()[:16]}",
            "media_type": "application/json",
            "sha256": hashlib.sha256(f"output:{ref}".encode()).hexdigest(),
            "byte_length": 0,
            "summary": "Validated stage output retained by the host.",
        }
        for ref in refs
    }
    if submission is not None:
        outputs = {str(refs[0]): submission}
    return {
        "schema_version": STAGE_ENVELOPE_SCHEMA_VERSION,
        "stage_id": stage["id"],
        "output_refs": outputs,
    }


def test_mcp_lifecycle_finalization_returns_path_only_presentation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    submission = complete_analytics_submission("ORCL")
    request = submission["company_research"]["request"]  # type: ignore[index]
    result_store = RunStore(tmp_path / "runs")
    coordinator = CompanyAnalyticsCoordinator(
        LifecycleStore(tmp_path / "lifecycle"),
        result_store,
        profile=CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / "runs" / "quality")),
    )
    created = coordinator.create(
        request,
        research_pack_id="initiating-coverage.v1",
        decision_memory_enabled=False,
    )
    started = coordinator.start(created["run_id"], created["revision"])
    revision = int(started["control"]["revision"])
    for stage in CompanyAnalyticsV1Provider().load_manifest()["stages"]:
        publication = submission if stage["id"] == "publish.completed" else None
        advanced = coordinator.commit_stage(
            created["run_id"],
            stage["id"],
            _stage_envelope(stage, publication),
            revision,
        )
        revision = int(advanced["control"]["revision"])

    assert result_store.get_result(created["run_id"]) is None
    monkeypatch.setattr(mcp_server, "_coordinator_for_run", lambda _run_id: coordinator)

    response = mcp_server.finalize_run(
        created["run_id"],
        revision,
        presentation_mode="path_only",
    )

    assert response["ok"] is True
    assert response["result"]["status"] == "completed"
    assert response["presentation"]["status"] == "path_only"
    assert response["presentation"]["path"] == f"/?run={response['result']['run_id']}"
    assert not (tmp_path / "runs" / ".presentation").exists()
