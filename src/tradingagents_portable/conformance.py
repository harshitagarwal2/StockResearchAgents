"""Credential-free conformance checks for portable observable invariants."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from .contracts import RunEvent, RunResult
from .reporting import report_groups
from .workflow import expand_workflow

PINNED_UPSTREAM_REVISION = "a33fd4c0f134485a43553a2c23a63cb14adbd88f"
CONFORMANCE_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    name: str
    passed: bool
    detail: str
    verified: bool = True

    @property
    def status(self) -> Literal["passed", "failed", "skipped"]:
        if not self.verified:
            return "skipped"
        return "passed" if self.passed else "failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "verified": self.verified,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    run_id: str
    upstream_revision: str | None
    pinned_upstream_revision: str
    checks: tuple[ConformanceCheck, ...]
    schema_version: str = CONFORMANCE_SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return all(check.verified and check.passed for check in self.checks)

    @property
    def verified(self) -> bool:
        return all(check.verified for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "passed": self.passed,
            "verified": self.verified,
            "upstream_revision": self.upstream_revision,
            "pinned_upstream_revision": self.pinned_upstream_revision,
            "checks": [check.to_dict() for check in self.checks],
        }


def upstream_revision(upstream_path: str | Path) -> str:
    root = Path(upstream_path).expanduser().resolve()
    required = root / "tradingagents" / "graph" / "trading_graph.py"
    if not required.is_file():
        raise ValueError(f"upstream TradingAgents checkout not found at {root}")
    completed = subprocess.run(  # noqa: S603 - fixed git invocation and explicit checkout path
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    revision = completed.stdout.strip().lower()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise ValueError("upstream checkout returned an invalid git revision")
    return revision


def _check(name: str, condition: bool, detail: str) -> ConformanceCheck:
    return ConformanceCheck(name, bool(condition), detail)


def _skipped(name: str, detail: str) -> ConformanceCheck:
    return ConformanceCheck(name, False, detail, verified=False)


def _is_safe_receipt_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value[0].isascii()
        and value[0].isalnum()
        and all(character.isascii() and (character.isalnum() or character in "._:-") for character in value)
    )


def _is_safe_lifecycle_completion(
    event: RunEvent,
    events: tuple[RunEvent, ...],
    expected_ordinal: int,
) -> bool:
    digest = event.data.get("output_digest")
    attempt = event.data.get("attempt")
    receipt_ids = event.data.get("execution_receipt_ids")
    valid_boundary = (
        event.status == "completed"
        and event.data.get("output_observed") is True
        and event.data.get("execution_observed") is True
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and isinstance(attempt, int)
        and not isinstance(attempt, bool)
        and attempt >= 1
        and event.data.get("checkpoint_ordinal") == expected_ordinal
        and isinstance(receipt_ids, list)
        and len(receipt_ids) == 2
        and all(_is_safe_receipt_id(receipt_id) for receipt_id in receipt_ids)
        and len(set(receipt_ids)) == 2
    )
    if not valid_boundary:
        return False
    safe_receipt_ids = cast(list[str], receipt_ids)
    for receipt_id, expected_kind in zip(safe_receipt_ids, ("stage_started", "stage_completed"), strict=True):
        matching_receipts = tuple(
            candidate
            for candidate in events
            if candidate.kind.value == "stage"
            and candidate.stage_id == event.stage_id
            and candidate.data.get("receipt_id") == receipt_id
            and candidate.data.get("kind") == expected_kind
            and candidate.data.get("attempt") == attempt
            and (expected_kind != "stage_completed" or candidate.data.get("output_digest") == digest)
        )
        if len(matching_receipts) != 1:
            return False
    return True


def evaluate_conformance(
    result: RunResult,
    events: tuple[RunEvent, ...],
    *,
    upstream_path: str | Path | None = None,
    require_live_stage_receipts: bool | None = None,
) -> ConformanceReport:
    """Validate portable observable invariants and optional pinned-checkout identity.

    Expected behavior comes from the portable workflow contract. An optional
    upstream checkout contributes identity verification only, never behavioral
    expectations, model text, or LangGraph internals.
    """
    if not isinstance(result, RunResult):
        raise TypeError("result must be a RunResult")
    if not isinstance(events, tuple) or not all(isinstance(event, RunEvent) for event in events):
        raise TypeError("events must be a tuple of RunEvent values")
    revision = upstream_revision(upstream_path) if upstream_path is not None else None
    expected_topology = expand_workflow(result.request)
    expected_stage_ids = tuple(stage.id for stage in expected_topology.stages)
    actual_stage_ids = tuple(stage.id for stage in result.topology.stages)
    report_analysts = tuple(report.analyst for report in result.analyst_reports)
    retained_evidence_ids = {item.id for item in result.evidence}
    referenced_evidence_ids = {
        evidence_id for report in result.analyst_reports for evidence_id in report.evidence_ids
    } | {evidence_id for turn in (*result.research_debate, *result.risk_debate) for evidence_id in turn.evidence_ids}
    group_ordinals = tuple(group["ordinal"] for group in report_groups(result.artifacts))
    stage_completion_events = tuple(
        event for event in events if event.kind.value == "stage" and event.status in {"completed", "imported"}
    )
    require_live = (
        result.persistence.checkpoint_enabled if require_live_stage_receipts is None else require_live_stage_receipts
    )
    lifecycle_receipts_present = any(
        event.kind.value == "stage" and event.data.get("kind") in {"stage_started", "stage_completed"}
        for event in events
    )
    safe_completion_stage_ids = tuple(
        event.stage_id
        for event in stage_completion_events
        if event.stage_id is not None
        and event.stage_id in expected_stage_ids
        and _is_safe_lifecycle_completion(event, events, expected_stage_ids.index(event.stage_id) + 1)
    )
    safe_completion_receipts = safe_completion_stage_ids == expected_stage_ids
    if safe_completion_receipts:
        completion_check = _check(
            "stage_completion_receipts",
            True,
            "Every stage has an ordered durable lifecycle completion receipt with a validated output digest.",
        )
    elif require_live or lifecycle_receipts_present:
        completion_check = _check(
            "stage_completion_receipts",
            False,
            "Durable lifecycle completion receipts are required but are missing, incomplete, or invalid.",
        )
    else:
        completion_check = _skipped(
            "stage_completion_receipts",
            "No safe lifecycle completion receipts were available; only structural result conformance was checked.",
        )
    checks = (
        _skipped(
            "pinned_upstream_identity",
            "No upstream checkout was provided; pinned upstream identity was not verified.",
        )
        if revision is None
        else _check(
            "pinned_upstream_identity",
            revision == PINNED_UPSTREAM_REVISION,
            "Checkout matches the pinned observable-contract revision."
            if revision == PINNED_UPSTREAM_REVISION
            else f"Expected {PINNED_UPSTREAM_REVISION}; found {revision}.",
        ),
        _check(
            "workflow_stage_order",
            actual_stage_ids == expected_stage_ids,
            f"Expected and observed {len(expected_stage_ids)} canonical stages.",
        ),
        _check(
            "selected_analyst_order",
            report_analysts == result.request.analysts,
            f"Analyst reports follow request order: {result.request.analysts}.",
        ),
        _check(
            "research_debate_count",
            len(result.research_debate) == 2 * result.request.debate_rounds,
            "Bull/Bear turns equal 2 x configured research rounds.",
        ),
        _check(
            "risk_debate_count",
            len(result.risk_debate) == 3 * result.request.risk_rounds,
            "Aggressive/Conservative/Neutral turns equal 3 x configured risk rounds.",
        ),
        _check(
            "decision_schema_separation",
            result.research_decision.recommendation in {"buy", "overweight", "hold", "underweight", "sell"}
            and result.trader_decision.action in {"buy", "hold", "sell"}
            and result.portfolio_decision.rating in {"buy", "overweight", "hold", "underweight", "sell"},
            "Research and Portfolio use five-tier ratings; Trader uses Buy/Hold/Sell.",
        ),
        _check(
            "non_execution_boundary",
            not result.trader_decision.executable
            and not result.trader_decision.submitted
            and not result.portfolio_decision.executable
            and not result.portfolio_decision.submitted,
            "No decision carries execution authority or a submitted order.",
        ),
        _check(
            "processed_signal_mapping",
            result.processed_signal == result.portfolio_decision.rating.upper(),
            "Processed signal is derived only from the Portfolio rating.",
        ),
        _check(
            "evidence_reference_integrity",
            referenced_evidence_ids <= retained_evidence_ids,
            "Every report/debate evidence reference resolves to retained evidence.",
        ),
        _check(
            "five_report_groups",
            group_ordinals == (1, 2, 3, 4, 5),
            "Analyst, research, trading, risk, and portfolio groups are present.",
        ),
        completion_check,
    )
    return ConformanceReport(result.run_id, revision, PINNED_UPSTREAM_REVISION, checks)


def conformance_digest(report: ConformanceReport) -> str:
    payload = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
