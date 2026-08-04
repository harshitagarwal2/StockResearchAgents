from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from research_v3_fixtures import complete_v3_submission

from tradingagents_portable.company_lifecycle import (
    STAGE_ENVELOPE_SCHEMA_VERSION,
    CompanyResearchCoordinator,
    stage_output_digest,
)
from tradingagents_portable.lifecycle import LifecycleStatus, LifecycleStore, RevisionConflict
from tradingagents_portable.memory import DecisionMemoryStore
from tradingagents_portable.research_contracts import CompanyResearchRequest
from tradingagents_portable.store import RunStore
from tradingagents_portable.view import build_run_view
from tradingagents_portable.workflow import load_company_research_manifest


def _request(symbol: str = "ORCL") -> CompanyResearchRequest:
    return CompanyResearchRequest.from_dict(complete_v3_submission(symbol)["request"])


def _coordinator(tmp_path: Path, memory: DecisionMemoryStore | None = None) -> CompanyResearchCoordinator:
    return CompanyResearchCoordinator(
        LifecycleStore(tmp_path / "lifecycle"),
        RunStore(tmp_path / "runs"),
        memory_store=memory,
    )


def _envelope(stage: dict[str, object], value: object | None = None) -> dict[str, object]:
    refs = stage["output_refs"]
    assert isinstance(refs, list)
    output_refs: dict[str, object] = {
        ref: {
            "reference_id": f"host-ref-{hashlib.sha256(ref.encode()).hexdigest()[:16]}",
            "media_type": "application/json",
            "sha256": hashlib.sha256(f"output:{ref}".encode()).hexdigest(),
            "byte_length": 0,
            "summary": "Validated stage output retained by the host.",
        }
        for ref in refs
    }
    if value is not None:
        output_refs = {ref: value for ref in refs}
    return {
        "schema_version": STAGE_ENVELOPE_SCHEMA_VERSION,
        "stage_id": stage["id"],
        "output_refs": output_refs,
    }


def _complete_stages(
    coordinator: CompanyResearchCoordinator,
    run_id: str,
    revision: int,
    submission: dict[str, object],
) -> int:
    manifest = load_company_research_manifest()
    terminal_ref = "host-submission.v3.schema.json#/$defs/hostSubmission"
    for stage in manifest["stages"]:
        value = submission if stage["id"] == "publish.dossier" else None
        envelope = _envelope(stage, value)
        if stage["id"] == "publish.dossier":
            envelope["output_refs"] = {terminal_ref: submission}
        advanced = coordinator.commit_stage(run_id, stage["id"], envelope, revision)
        revision = advanced["control"]["revision"]
    return revision


def test_all_manifest_stages_resume_and_publish_final_result_and_view(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    first = started["stage"]
    assert started["context"]["stage_output_contract"]["output_value_contract"] == {
        "kind": "bounded_opaque_reference",
        "fields": ["reference_id", "media_type", "sha256", "byte_length", "summary"],
        "max_reference_id_chars": 128,
        "reference_id_pattern": "[A-Za-z0-9][A-Za-z0-9._:-]*",
        "max_media_type_chars": 255,
        "media_type_format": "ascii-type/ascii-subtype",
        "sha256_format": "64-lowercase-hex-characters",
        "byte_length_type": "non-negative-integer",
        "max_summary_chars": 1000,
        "summary_type": "non-empty-string",
        "max_byte_length": 2**63 - 1,
        "nested_values_allowed": False,
        "raw_content_allowed": False,
    }
    committed = coordinator.commit_stage(
        control["run_id"], first["id"], _envelope(first), started["control"]["revision"]
    )
    paused = coordinator.pause(control["run_id"], committed["control"]["revision"], "host maintenance")

    restarted = _coordinator(tmp_path)
    resumed = restarted.resume(control["run_id"], paused["revision"])
    assert resumed["stage"]["id"] == "evidence.official"
    revision = resumed["control"]["revision"]
    manifest = load_company_research_manifest()
    submission = complete_v3_submission("ORCL")
    for stage in manifest["stages"][1:]:
        envelope = _envelope(stage, submission if stage["id"] == "publish.dossier" else None)
        revision = restarted.commit_stage(control["run_id"], stage["id"], envelope, revision)["control"]["revision"]

    result, events = restarted.finalize(control["run_id"], revision)
    view = build_run_view(result, events).to_dict()
    assert restarted.control(control["run_id"])["status"] == LifecycleStatus.COMPLETED
    assert len(restarted.control(control["run_id"])["completed_stage_ids"]) == 15
    assert result.run_id == control["run_id"]
    assert any(artifact.kind == "research_dossier.v3" for artifact in result.artifacts)
    assert result.persistence.checkpoint_enabled is True
    assert result.persistence.decision_memory_enabled is False
    assert view["run_id"] == control["run_id"]
    assert restarted.result_store.get_result(control["run_id"]) == result


def test_create_uses_cutoff_safe_memory_recall(tmp_path: Path) -> None:
    memory = DecisionMemoryStore(tmp_path / "memory.sqlite3")
    memory.append_decision(
        run_id="visible",
        symbol="ORCL",
        as_of_date="2026-07-01",
        decision={"rating": "hold"},
        created_at="2026-07-01T00:00:00Z",
    )
    memory.append_decision(
        run_id="future",
        symbol="ORCL",
        as_of_date="2026-08-01",
        decision={"rating": "buy"},
        created_at="2026-08-01T00:00:00Z",
    )

    coordinator = _coordinator(tmp_path, memory)
    control = coordinator.create(_request())
    started = coordinator.start(control["run_id"], control["revision"])

    recalled = started["context"]["optional_past_context"]["same_symbol"]
    assert [entry["run_id"] for entry in recalled] == ["visible"]


def test_stale_revision_is_rejected(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    coordinator.start(control["run_id"], control["revision"])

    with pytest.raises(RevisionConflict):
        coordinator.pause(control["run_id"], control["revision"], "stale caller")


def test_receipts_reject_capability_outside_active_stage_and_raw_material(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    start_receipt = {
        "receipt_id": "start-1",
        "kind": "stage_started",
        "stage_id": "research.plan",
        "attempt": 1,
    }
    accepted = coordinator.append_receipts(control["run_id"], [start_receipt], started["control"]["revision"])

    with pytest.raises(ValueError, match="not allowed"):
        coordinator.append_receipts(
            control["run_id"],
            [
                {
                    "receipt_id": "tool-1",
                    "kind": "tool_started",
                    "stage_id": "research.plan",
                    "capability_id": "official_filings",
                }
            ],
            accepted["control"]["revision"],
        )
    with pytest.raises(ValueError, match="unsupported fields"):
        coordinator.append_receipts(
            control["run_id"],
            [
                {
                    "receipt_id": "tool-2",
                    "kind": "tool_started",
                    "stage_id": "research.plan",
                    "raw_args": {"query": "secret"},
                }
            ],
            accepted["control"]["revision"],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("observed_at", "2026-08-03T12:00:00", "timezone"),
        ("observed_at", 123, "observed_at"),
        ("status", "x" * 65, "status"),
        ("status", ["running"], "status"),
        ("host_call_id", "x" * 129, "host_call_id"),
        ("capability_id", ["model_inference"], "capability_id"),
        ("evidence_ids", [123], "evidence_ids"),
    ],
)
def test_receipts_reject_invalid_timestamps_and_unbounded_or_untyped_fields(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    receipt: dict[str, object] = {
        "receipt_id": "progress-1",
        "kind": "stage_progress",
        "stage_id": started["stage"]["id"],
        field: value,
    }

    with pytest.raises(ValueError, match=message):
        coordinator.append_receipts(control["run_id"], [receipt], started["control"]["revision"])


def test_receipts_reject_secret_shaped_keys_nested_in_list_values(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])

    with pytest.raises(ValueError, match="credential-shaped"):
        coordinator.append_receipts(
            control["run_id"],
            [
                {
                    "receipt_id": "progress-1",
                    "kind": "stage_progress",
                    "stage_id": started["stage"]["id"],
                    "evidence_ids": [{"api_key": "not-portable"}],
                }
            ],
            started["control"]["revision"],
        )


def test_nonterminal_envelopes_reject_raw_content_and_secret_shaped_keys(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    stage = started["stage"]
    envelope = _envelope(stage)
    descriptor = next(iter(cast(dict[str, dict[str, object]], envelope["output_refs"]).values()))
    descriptor["content"] = {"raw_source": "full filing text"}

    with pytest.raises(ValueError, match="bounded opaque reference descriptor"):
        coordinator.commit_stage(control["run_id"], stage["id"], envelope, started["control"]["revision"])

    secret_envelope = _envelope(stage)
    secret_descriptor = next(iter(cast(dict[str, dict[str, object]], secret_envelope["output_refs"]).values()))
    secret_descriptor["metadata"] = [{"access_token": "not-portable"}]
    with pytest.raises(ValueError, match="credential-shaped"):
        coordinator.commit_stage(control["run_id"], stage["id"], secret_envelope, started["control"]["revision"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reference_id", "x" * 129, "reference_id"),
        ("media_type", f"application/{'x' * 245}", "media_type"),
        ("sha256", "A" * 64, "SHA-256"),
        ("byte_length", True, "byte_length"),
        ("summary", ["raw output"], "summary"),
    ],
)
def test_nonterminal_reference_descriptors_reject_unbounded_or_untyped_fields(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    stage = started["stage"]
    envelope = _envelope(stage)
    descriptor = next(iter(cast(dict[str, dict[str, object]], envelope["output_refs"]).values()))
    descriptor[field] = value

    with pytest.raises(ValueError, match=message):
        coordinator.commit_stage(control["run_id"], stage["id"], envelope, started["control"]["revision"])


def test_commit_rejects_mismatched_stage_completion_digest(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    stage = started["stage"]
    envelope = _envelope(stage)
    receipts = [
        {"receipt_id": "start", "kind": "stage_started", "stage_id": stage["id"], "attempt": 1},
        {
            "receipt_id": "complete",
            "kind": "stage_completed",
            "stage_id": stage["id"],
            "attempt": 1,
            "output_digest": "0" * 64,
        },
    ]
    accepted = coordinator.append_receipts(control["run_id"], receipts, started["control"]["revision"])

    assert stage_output_digest(envelope) != "0" * 64
    with pytest.raises(ValueError, match="digest does not match"):
        coordinator.commit_stage(control["run_id"], stage["id"], envelope, accepted["control"]["revision"])


def test_matching_receipts_are_linked_to_observed_stage_completion(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    stage = started["stage"]
    envelope = _envelope(stage)
    receipts = [
        {"receipt_id": "start", "kind": "stage_started", "stage_id": stage["id"], "attempt": 1},
        {
            "receipt_id": "complete",
            "kind": "stage_completed",
            "stage_id": stage["id"],
            "attempt": 1,
            "output_digest": stage_output_digest(envelope),
        },
    ]
    accepted = coordinator.append_receipts(control["run_id"], receipts, started["control"]["revision"])
    coordinator.commit_stage(control["run_id"], stage["id"], envelope, accepted["control"]["revision"])

    completion = coordinator.poll_events(control["run_id"])["events"][-1]
    assert completion["status"] == "committed"
    assert completion["data"]["envelope_observed"] is True
    assert completion["data"]["output_observed"] is False
    assert completion["data"]["output_content_verified"] is False
    assert completion["data"]["host_completion_attested"] is True
    assert completion["data"]["execution_observed"] is False
    assert completion["data"]["execution_receipt_ids"] == ["start", "complete"]


def test_commit_rejects_contradictory_completion_receipts(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    stage = started["stage"]
    envelope = _envelope(stage)
    receipts = [
        {"receipt_id": "start", "kind": "stage_started", "stage_id": stage["id"], "attempt": 1},
        {
            "receipt_id": "complete-good",
            "kind": "stage_completed",
            "stage_id": stage["id"],
            "attempt": 1,
            "output_digest": stage_output_digest(envelope),
        },
        {
            "receipt_id": "complete-conflict",
            "kind": "stage_completed",
            "stage_id": stage["id"],
            "attempt": 1,
            "output_digest": "0" * 64,
        },
    ]
    accepted = coordinator.append_receipts(control["run_id"], receipts, started["control"]["revision"])

    with pytest.raises(ValueError, match="digest does not match"):
        coordinator.commit_stage(control["run_id"], stage["id"], envelope, accepted["control"]["revision"])


def test_terminal_commit_rejects_nonconformant_dossier(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    submission = complete_v3_submission("ORCL")
    revision = started["control"]["revision"]
    manifest = load_company_research_manifest()
    for stage in manifest["stages"][:-1]:
        revision = coordinator.commit_stage(control["run_id"], stage["id"], _envelope(stage), revision)["control"][
            "revision"
        ]
    bad = deepcopy(submission)
    bad_dossier = cast(dict[str, Any], bad["dossier"])
    bad_dossier["calculations"][0]["result"] += 1.0

    with pytest.raises(ValueError, match="calculated metric|conformance"):
        coordinator.commit_stage(control["run_id"], "publish.dossier", _envelope(manifest["stages"][-1], bad), revision)


def test_staged_publication_is_invisible_until_publish_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete_stages(
        coordinator, control["run_id"], started["control"]["revision"], complete_v3_submission("ORCL")
    )
    original_publish = coordinator.result_store.publish_staged

    def fail_publish(run_id: str):
        raise OSError(f"injected publication failure for {run_id}")

    monkeypatch.setattr(coordinator.result_store, "publish_staged", fail_publish)
    with pytest.raises(OSError, match="injected"):
        coordinator.finalize(control["run_id"], revision)
    assert coordinator.result_store.get_result(control["run_id"]) is None
    assert coordinator.result_store.get_events(control["run_id"]) is None
    assert coordinator.result_store.get_staged(control["run_id"]) is not None
    pending = coordinator.control(control["run_id"])
    assert pending["publication_pending"] is True
    assert pending["status"] == LifecycleStatus.FINALIZING

    monkeypatch.setattr(coordinator.result_store, "publish_staged", original_publish)
    result, _ = coordinator.finalize(control["run_id"], pending["revision"])
    assert coordinator.result_store.get_result(control["run_id"]) == result


def test_memory_is_published_only_after_completed_lifecycle(tmp_path: Path) -> None:
    memory = DecisionMemoryStore(tmp_path / "memory.sqlite3")
    coordinator = _coordinator(tmp_path, memory)
    control = coordinator.create(_request())
    started = coordinator.start(control["run_id"], control["revision"])
    revision = _complete_stages(
        coordinator, control["run_id"], started["control"]["revision"], complete_v3_submission("ORCL")
    )
    assert memory.recall("ORCL").same_symbol == ()

    result, events = coordinator.finalize(control["run_id"], revision)

    assert coordinator.control(control["run_id"])["status"] == LifecycleStatus.COMPLETED
    assert [entry.run_id for entry in memory.recall("ORCL").same_symbol] == [control["run_id"]]
    assert result.persistence.decision_memory_enabled is True
    view = build_run_view(result, events).to_dict()
    assert view["persistence"]["metadata"]["decision_memory_enabled"] is True


def test_requested_decision_memory_fails_explicitly_when_unconfigured(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)

    with pytest.raises(RuntimeError, match="decision memory was requested"):
        coordinator.create(_request())


def test_cooperative_cancel_requires_acknowledgement(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    control = coordinator.create(_request(), decision_memory_enabled=False)
    requested = coordinator.request_cancel(control["run_id"], control["revision"], "operator stop")
    assert requested["status"] == LifecycleStatus.CANCEL_REQUESTED

    cancelled = coordinator.acknowledge_cancel(control["run_id"], requested["revision"], "host-ack-1")
    assert cancelled["status"] == LifecycleStatus.CANCELLED
