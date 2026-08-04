from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from tradingagents_portable.conformance import (
    PINNED_UPSTREAM_REVISION,
    conformance_digest,
    evaluate_conformance,
    upstream_revision,
)
from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.fixture import run_fixture
from tradingagents_portable.store import RunStore

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(os.environ.get("TRADINGAGENTS_UPSTREAM_PATH", ROOT.parent / "tradingAgents"))
REQUIRES_UPSTREAM = pytest.mark.skipif(
    not (UPSTREAM / "tradingagents" / "graph" / "trading_graph.py").is_file(),
    reason="pinned upstream TradingAgents checkout is not available",
)


@REQUIRES_UPSTREAM
def test_pinned_sibling_upstream_identity_is_verified_without_credentials() -> None:
    assert upstream_revision(UPSTREAM) == PINNED_UPSTREAM_REVISION


@REQUIRES_UPSTREAM
def test_fixture_satisfies_observable_upstream_contract() -> None:
    result, events = run_fixture(RunRequest(), store=RunStore())
    completed_ordinal = 0
    receipt_events = []
    for event in events:
        if event.kind.value == "stage" and event.status == "started":
            event = replace(
                event,
                status="stage_started",
                data={
                    "receipt_id": f"start:{event.stage_id}",
                    "kind": "stage_started",
                    "attempt": 1,
                },
            )
        if event.kind.value == "stage" and event.status == "completed":
            completed_ordinal += 1
            output_digest = hashlib.sha256(event.stage_id.encode()).hexdigest()
            receipt_events.append(
                replace(
                    event,
                    id=f"{event.id}:receipt",
                    status="stage_completed",
                    data={
                        "receipt_id": f"complete:{event.stage_id}",
                        "kind": "stage_completed",
                        "attempt": 1,
                        "output_digest": output_digest,
                    },
                )
            )
            event = replace(
                event,
                data={
                    "attempt": 1,
                    "output_digest": output_digest,
                    "output_observed": True,
                    "execution_observed": True,
                    "execution_receipt_ids": [f"start:{event.stage_id}", f"complete:{event.stage_id}"],
                    "checkpoint_ordinal": completed_ordinal,
                },
            )
        receipt_events.append(event)
    report = evaluate_conformance(result, tuple(receipt_events), upstream_path=UPSTREAM)

    assert report.passed is True
    assert report.verified is True
    assert report.schema_version == "1.1.0"
    assert len(conformance_digest(report)) == 64
    assert {check.name for check in report.checks} >= {
        "workflow_stage_order",
        "selected_analyst_order",
        "research_debate_count",
        "risk_debate_count",
        "decision_schema_separation",
        "processed_signal_mapping",
        "five_report_groups",
    }


def test_conformance_detects_signal_drift() -> None:
    result, events = run_fixture(RunRequest(), store=RunStore())
    broken = replace(result, processed_signal="SELL")
    report = evaluate_conformance(broken, events)

    assert report.passed is False
    signal_check = next(check for check in report.checks if check.name == "processed_signal_mapping")
    assert signal_check.passed is False


def test_conformance_without_upstream_checkout_is_explicitly_unverified() -> None:
    result, events = run_fixture(RunRequest(), store=RunStore())

    report = evaluate_conformance(result, events)

    identity = next(check for check in report.checks if check.name == "pinned_upstream_identity")
    assert report.passed is True
    assert report.verified is True
    assert report.portable_passed is True
    assert report.portable_verified is True
    assert report.upstream_compatible is False
    assert report.upstream_compatibility_verified is False
    assert report.overall_status == "portable_conformant_upstream_unverified"
    assert identity.status == "skipped"
    assert identity.passed is False
    assert identity.to_dict()["status"] == "skipped"
    assert report.to_dict()["upstream_compatibility"] == {
        "passed": False,
        "verified": False,
        "status": "skipped",
    }
    assert report.to_dict()["portable_conformance"] == {"passed": True, "verified": True}


def test_upstream_revision_mismatch_does_not_fail_portable_conformance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, events = run_fixture(RunRequest(), store=RunStore())
    monkeypatch.setattr(
        "tradingagents_portable.conformance.upstream_revision",
        lambda _path: "0" * 40,
    )

    report = evaluate_conformance(result, events, upstream_path="unused")

    assert report.passed is True
    assert report.verified is True
    assert report.upstream_compatible is False
    assert report.upstream_compatibility_verified is True
    assert report.overall_status == "portable_conformant_upstream_incompatible"
    compatibility = report.to_dict()["upstream_compatibility"]
    assert isinstance(compatibility, dict)
    assert compatibility["status"] == "failed"


@REQUIRES_UPSTREAM
def test_bare_execution_observed_flags_are_not_safe_lifecycle_receipts() -> None:
    result, events = run_fixture(RunRequest(), store=RunStore())
    flagged_events = tuple(
        replace(event, data={**event.data, "execution_observed": True})
        if event.kind.value == "stage" and event.status == "completed"
        else event
        for event in events
    )

    report = evaluate_conformance(result, flagged_events, upstream_path=UPSTREAM)

    completion = next(check for check in report.checks if check.name == "stage_completion_receipts")
    assert report.passed is True
    assert completion.status == "skipped"
    assert "structural" in completion.detail
