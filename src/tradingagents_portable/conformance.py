"""Credential-free conformance checks for portable observable invariants."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from .contracts import RunEvent, RunResult
from .reporting import report_groups
from .research_conformance import validate_research_dossier as validate_research_dossier_semantics
from .research_contracts import CompanyResearchRequest
from .workflow import expand_workflow, load_company_research_manifest

PINNED_UPSTREAM_REVISION = "a33fd4c0f134485a43553a2c23a63cb14adbd88f"
CONFORMANCE_SCHEMA_VERSION = "1.1.0"
OPTIONAL_PORTABLE_CHECKS = frozenset({"stage_completion_receipts"})


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
    def portable_checks(self) -> tuple[ConformanceCheck, ...]:
        return tuple(check for check in self.checks if check.name != "pinned_upstream_identity")

    @property
    def upstream_identity_check(self) -> ConformanceCheck:
        return next(check for check in self.checks if check.name == "pinned_upstream_identity")

    @property
    def portable_passed(self) -> bool:
        return self.portable_verified and all(check.passed for check in self.portable_checks if check.verified)

    @property
    def portable_verified(self) -> bool:
        return all(check.verified or check.name in OPTIONAL_PORTABLE_CHECKS for check in self.portable_checks)

    @property
    def passed(self) -> bool:
        """Backward-compatible alias for portable conformance, not upstream compatibility."""

        return self.portable_passed

    @property
    def verified(self) -> bool:
        """Backward-compatible alias for portable verification coverage."""

        return self.portable_verified

    @property
    def upstream_compatible(self) -> bool:
        return self.upstream_identity_check.passed

    @property
    def upstream_compatibility_verified(self) -> bool:
        return self.upstream_identity_check.verified

    @property
    def overall_status(
        self,
    ) -> Literal[
        "portable_unverified",
        "portable_nonconformant",
        "portable_conformant_upstream_unverified",
        "portable_conformant_upstream_incompatible",
        "portable_conformant_upstream_verified",
    ]:
        if not self.portable_verified:
            return "portable_unverified"
        if not self.portable_passed:
            return "portable_nonconformant"
        if not self.upstream_compatibility_verified:
            return "portable_conformant_upstream_unverified"
        if not self.upstream_compatible:
            return "portable_conformant_upstream_incompatible"
        return "portable_conformant_upstream_verified"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "passed": self.passed,
            "verified": self.verified,
            "overall_status": self.overall_status,
            "portable_conformance": {
                "passed": self.portable_passed,
                "verified": self.portable_verified,
            },
            "upstream_compatibility": {
                "passed": self.upstream_compatible,
                "verified": self.upstream_compatibility_verified,
                "status": self.upstream_identity_check.status,
            },
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
    dossier_artifact = next((artifact for artifact in result.artifacts if artifact.kind == "research_dossier.v3"), None)
    request_artifact = next((artifact for artifact in result.artifacts if artifact.kind == "research_request.v3"), None)
    is_company_research = dossier_artifact is not None or result.topology.name == "tradingagents.company-research.v2"
    if is_company_research:
        company_manifest = load_company_research_manifest()
        expected_stage_ids = tuple(stage["id"] for stage in company_manifest["stages"])
        dossier_arguments = (
            dossier_artifact.content.get("arguments", ())
            if dossier_artifact is not None and isinstance(dossier_artifact.content, Mapping)
            else ()
        )
        expected_research_turns = sum(
            1 for item in dossier_arguments if isinstance(item, Mapping) and item.get("debate") == "research"
        )
        expected_risk_turns = sum(
            1 for item in dossier_arguments if isinstance(item, Mapping) and item.get("debate") == "risk"
        )
    else:
        expected_topology = expand_workflow(result.request)
        expected_stage_ids = tuple(stage.id for stage in expected_topology.stages)
        expected_research_turns = 2 * result.request.debate_rounds
        expected_risk_turns = 3 * result.request.risk_rounds
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
    company_check: ConformanceCheck | None = None
    company_request_check: ConformanceCheck | None = None
    if is_company_research:
        if dossier_artifact is None or not isinstance(dossier_artifact.content, Mapping):
            company_check = _check(
                "research_dossier_v3_semantics",
                False,
                "Company research requires a structured research_dossier.v3 artifact.",
            )
        else:
            semantic_report = validate_research_dossier_semantics(dossier_artifact.content)
            company_check = _check(
                "research_dossier_v3_semantics",
                semantic_report.passed,
                "Typed point-in-time, reference, calculation, debate, privacy, and completeness checks passed."
                if semantic_report.passed
                else f"Research dossier has {len(semantic_report.issues)} deterministic semantic issue(s).",
            )
        if request_artifact is None or not isinstance(request_artifact.content, Mapping):
            company_request_check = _check(
                "research_request_v3_truthfulness",
                False,
                "Company research requires a structured research_request.v3 artifact.",
            )
        else:
            try:
                company_request = CompanyResearchRequest.from_dict(request_artifact.content)
                dossier_content = dossier_artifact.content if dossier_artifact is not None else {}
                dossier_identity = dossier_content.get("identity") if isinstance(dossier_content, Mapping) else None
                dossier_cutoff = dossier_content.get("as_of_at") if isinstance(dossier_content, Mapping) else None
                fixture_mode = company_request.research_mode == "fixture"
                truthful = (
                    company_request.identity.symbol == result.request.symbol
                    and dossier_identity == company_request.identity.to_dict()
                    and dossier_cutoff == company_request.cutoff_at
                    and result.capability.deterministic is fixture_mode
                    and result.capability.live_data is (company_request.research_mode == "live")
                    and all(item.provenance.fixture is fixture_mode for item in result.evidence)
                )
            except (TypeError, ValueError):
                truthful = False
            company_request_check = _check(
                "research_request_v3_truthfulness",
                truthful,
                "Research mode, identity, exact cutoff, capability flags, and source provenance agree."
                if truthful
                else "Research request projection conflicts with the dossier, capability flags, or source provenance.",
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
            len(result.research_debate) == expected_research_turns,
            f"Research debate preserves all {expected_research_turns} declared argument turns.",
        ),
        _check(
            "risk_debate_count",
            len(result.risk_debate) == expected_risk_turns,
            f"Risk debate preserves all {expected_risk_turns} declared argument turns.",
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
        *((company_check,) if company_check is not None else ()),
        *((company_request_check,) if company_request_check is not None else ()),
    )
    return ConformanceReport(result.run_id, revision, PINNED_UPSTREAM_REVISION, checks)


def conformance_digest(report: ConformanceReport) -> str:
    payload = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
