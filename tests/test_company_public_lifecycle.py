from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from research_v3_fixtures import complete_v3_submission

from tradingagents_portable import cli, mcp_server
from tradingagents_portable.company_lifecycle import (
    STAGE_ENVELOPE_SCHEMA_VERSION,
    CompanyResearchCoordinator,
    stage_output_digest,
)
from tradingagents_portable.lifecycle import LifecycleStatus, LifecycleStore
from tradingagents_portable.store import RunStore
from tradingagents_portable.workflow import load_company_research_manifest

_TERMINAL_REF = "host-submission.v3.schema.json#/$defs/hostSubmission"


def _coordinator(tmp_path: Path) -> CompanyResearchCoordinator:
    return CompanyResearchCoordinator(
        LifecycleStore(tmp_path / "lifecycle"),
        RunStore(tmp_path / "runs"),
    )


def _envelope(stage: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
    if stage["id"] == "publish.dossier":
        output_refs: dict[str, Any] = {_TERMINAL_REF: submission}
    else:
        output_refs = {
            ref: {
                "reference_id": f"host-ref-{hashlib.sha256(ref.encode()).hexdigest()[:16]}",
                "media_type": "application/json",
                "sha256": hashlib.sha256(f"output:{ref}".encode()).hexdigest(),
                "byte_length": 0,
                "summary": "Validated output retained by the host.",
            }
            for ref in stage["output_refs"]
        }
    return {
        "schema_version": STAGE_ENVELOPE_SCHEMA_VERSION,
        "stage_id": stage["id"],
        "output_refs": output_refs,
    }


def _append_execution_receipts(
    run_id: str,
    stage: dict[str, Any],
    envelope: dict[str, Any],
    revision: int,
) -> int:
    ordinal = int(stage["ordinal"])
    started = mcp_server.append_run_receipts(
        run_id,
        [
            {
                "receipt_id": f"stage-start-{ordinal}",
                "kind": "stage_started",
                "stage_id": stage["id"],
                "attempt": 1,
            }
        ],
        revision,
    )
    completed = mcp_server.append_run_receipts(
        run_id,
        [
            {
                "receipt_id": f"stage-complete-{ordinal}",
                "kind": "stage_completed",
                "stage_id": stage["id"],
                "attempt": 1,
                "output_digest": stage_output_digest(envelope),
            }
        ],
        started["control"]["revision"],
    )
    return int(completed["control"]["revision"])


def test_mcp_generic_operations_publish_all_fifteen_company_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = _coordinator(tmp_path)
    monkeypatch.setattr(mcp_server, "COMPANY_RESEARCH_COORDINATOR", coordinator)
    submission = complete_v3_submission("ORCL")

    created = mcp_server.create_company_research_run(submission["request"], decision_memory_enabled=False)
    run_id = created["control"]["run_id"]
    started = mcp_server.start_host_run(run_id, created["control"]["revision"])
    revision = int(started["control"]["revision"])

    for stage in load_company_research_manifest()["stages"]:
        envelope = _envelope(stage, submission)
        revision = _append_execution_receipts(run_id, stage, envelope, revision)
        committed = mcp_server.commit_host_stage(run_id, stage["id"], envelope, revision, attempt=1)
        revision = int(committed["control"]["revision"])

    events = mcp_server.poll_run_events(run_id, after_sequence=0, limit=100)
    finalized = mcp_server.finalize_host_run(run_id, revision)

    assert len(events["events"]) == 47
    assert events["last_sequence"] == events["events"][-1]["sequence"]
    assert finalized["result"]["run_id"] == run_id
    assert finalized["result"]["request"]["symbol"] == "ORCL"
    assert finalized["view"]["research_dossier"]["identity"]["symbol"] == "ORCL"
    assert finalized["dashboard_path"] == f"/?run={run_id}"
    assert mcp_server.get_run_control(run_id)["control"]["status"] == LifecycleStatus.COMPLETED


def test_mcp_generic_operations_pause_and_resume_company_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = _coordinator(tmp_path)
    monkeypatch.setattr(mcp_server, "COMPANY_RESEARCH_COORDINATOR", coordinator)
    submission = complete_v3_submission("META")
    created = mcp_server.create_company_research_run(submission["request"], decision_memory_enabled=False)["control"]
    started = mcp_server.start_host_run(created["run_id"], created["revision"])

    paused = mcp_server.pause_host_run(created["run_id"], started["control"]["revision"], "host maintenance")["control"]
    resumed = mcp_server.resume_host_run(created["run_id"], paused["revision"])

    assert paused["status"] == LifecycleStatus.PAUSED
    assert resumed["control"]["status"] == LifecycleStatus.RUNNING
    assert resumed["stage"]["id"] == "research.plan"


def test_mcp_wrong_run_identifier_is_rejected_by_generic_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_server, "COMPANY_RESEARCH_COORDINATOR", _coordinator(tmp_path / "company"))
    monkeypatch.setattr(mcp_server, "HOST_RUN_COORDINATOR", _coordinator(tmp_path / "host"))

    with pytest.raises(ValueError, match="run_id must match"):
        mcp_server.get_run_control("host-does-not-exist")


def test_mcp_unknown_valid_run_is_rejected_by_generic_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_server, "COMPANY_RESEARCH_COORDINATOR", _coordinator(tmp_path / "company"))
    monkeypatch.setattr(mcp_server, "HOST_RUN_COORDINATOR", _coordinator(tmp_path / "host"))

    with pytest.raises(KeyError, match="unknown lifecycle run"):
        mcp_server.get_run_control("host-0123456789ab")


def test_mcp_active_cancellation_blocks_stage_work_and_duplicate_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = _coordinator(tmp_path)
    monkeypatch.setattr(mcp_server, "COMPANY_RESEARCH_COORDINATOR", coordinator)
    submission = complete_v3_submission("NVDA")
    created = mcp_server.create_company_research_run(submission["request"], decision_memory_enabled=False)["control"]
    started = mcp_server.start_host_run(created["run_id"], created["revision"])
    requested = mcp_server.request_run_cancellation(created["run_id"], started["control"]["revision"], "operator stop")[
        "control"
    ]

    stage = started["stage"]
    with pytest.raises(ValueError, match="cannot start another stage"):
        mcp_server.append_run_receipts(
            created["run_id"],
            [
                {
                    "receipt_id": "late-start",
                    "kind": "stage_started",
                    "stage_id": stage["id"],
                    "attempt": 1,
                }
            ],
            requested["revision"],
        )

    cancelled = mcp_server.acknowledge_run_cancellation(created["run_id"], requested["revision"], "host-ack-1")[
        "control"
    ]
    with pytest.raises(ValueError, match="only be acknowledged"):
        mcp_server.acknowledge_run_cancellation(created["run_id"], cancelled["revision"], "host-ack-1")

    assert cancelled["status"] == LifecycleStatus.CANCELLED
    assert mcp_server.poll_run_events(created["run_id"])["events"][-1]["status"] == "cancelled"


def test_cli_generic_routing_controls_company_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = _coordinator(tmp_path)
    monkeypatch.setattr(cli, "COMPANY_RESEARCH_COORDINATOR", coordinator)
    request_path = tmp_path / "request.json"
    init_path = tmp_path / "init.json"
    start_path = tmp_path / "start.json"
    pause_path = tmp_path / "pause.json"
    resume_path = tmp_path / "resume.json"
    request_path.write_text(json.dumps(complete_v3_submission("MSFT")["request"]), encoding="utf-8")

    assert (
        cli.main(["company-init", "--input", str(request_path), "--no-decision-memory", "--output", str(init_path)])
        == 0
    )
    initialized = json.loads(init_path.read_text(encoding="utf-8"))["control"]
    assert (
        cli.main(
            [
                "host-start",
                initialized["run_id"],
                "--revision",
                str(initialized["revision"]),
                "--output",
                str(start_path),
            ]
        )
        == 0
    )
    started = json.loads(start_path.read_text(encoding="utf-8"))
    assert (
        cli.main(
            [
                "host-pause",
                initialized["run_id"],
                "--revision",
                str(started["control"]["revision"]),
                "--reason",
                "operator pause",
                "--output",
                str(pause_path),
            ]
        )
        == 0
    )
    paused = json.loads(pause_path.read_text(encoding="utf-8"))["control"]
    assert (
        cli.main(
            [
                "host-resume",
                initialized["run_id"],
                "--revision",
                str(paused["revision"]),
                "--output",
                str(resume_path),
            ]
        )
        == 0
    )

    resumed = json.loads(resume_path.read_text(encoding="utf-8"))
    assert started["stage"]["id"] == "research.plan"
    assert paused["status"] == LifecycleStatus.PAUSED
    assert resumed["control"]["status"] == LifecycleStatus.RUNNING
    assert resumed["stage"]["id"] == "research.plan"


def test_mcp_publication_failure_recovers_with_fresh_coordinator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = _coordinator(tmp_path)
    monkeypatch.setattr(mcp_server, "COMPANY_RESEARCH_COORDINATOR", coordinator)
    submission = complete_v3_submission("ORCL")
    created = mcp_server.create_company_research_run(submission["request"], decision_memory_enabled=False)["control"]
    started = mcp_server.start_host_run(created["run_id"], created["revision"])
    revision = int(started["control"]["revision"])
    for stage in load_company_research_manifest()["stages"]:
        envelope = _envelope(stage, submission)
        committed = mcp_server.commit_host_stage(created["run_id"], stage["id"], envelope, revision)
        revision = int(committed["control"]["revision"])

    def fail_publish(run_id: str) -> None:
        raise OSError(f"injected publication failure for {run_id}")

    monkeypatch.setattr(coordinator.result_store, "publish_staged", fail_publish)
    with pytest.raises(OSError, match="injected publication failure"):
        mcp_server.finalize_host_run(created["run_id"], revision)

    fresh = _coordinator(tmp_path)
    monkeypatch.setattr(mcp_server, "COMPANY_RESEARCH_COORDINATOR", fresh)
    pending = mcp_server.get_run_control(created["run_id"])["control"]
    finalized = mcp_server.finalize_host_run(created["run_id"], pending["revision"])

    assert pending["publication_pending"] is True
    assert finalized["result"]["run_id"] == created["run_id"]
    assert fresh.control(created["run_id"])["status"] == LifecycleStatus.COMPLETED
