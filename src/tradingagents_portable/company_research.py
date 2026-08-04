"""Host-owned execution seam for the versioned company-research profile.

The portable package validates a completed evidence dossier and projects it into
the existing run store. It does not retrieve data, create model clients, or own
provider credentials.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from statistics import fmean
from typing import Any, Literal

from .contracts import (
    AnalystReport,
    Artifact,
    CapabilityMetadata,
    DebateSnapshot,
    DebateTurn,
    EventKind,
    EvidenceItem,
    ExecutionConfig,
    InstrumentIdentity,
    PersistenceMetadata,
    PortfolioDecision,
    Provenance,
    ReportSections,
    ResearchDecision,
    RiskDecision,
    RunEvent,
    RunRequest,
    RunResult,
    RunStatus,
    StageKind,
    StageSpec,
    TraderDecision,
    WorkflowTopology,
)
from .publication import PublicationDraft, PublicationService
from .reporting import build_report_artifacts
from .research_conformance import assert_research_dossier_conformant
from .research_contracts import CompanyResearchRequest, HostSubmissionV3, ResearchDossierV3, parse_host_submission_v3
from .store import RUN_STORE, RunStore
from .workflow import load_company_research_manifest, load_host_submission_v3_schema

_CATEGORY_BY_DOCUMENT_KIND = {
    "market": "market",
    "news": "news",
    "regulatory": "news",
    "filing": "fundamentals",
    "earnings_release": "fundamentals",
    "transcript": "fundamentals",
    "company": "fundamentals",
    "other": "other",
}
_ANALYST_ORDER = ("market", "social", "news", "fundamentals")


def _request(value: CompanyResearchRequest | Mapping[str, object]) -> CompanyResearchRequest:
    return value if isinstance(value, CompanyResearchRequest) else CompanyResearchRequest.from_dict(value)


def prepare_company_research(value: CompanyResearchRequest | Mapping[str, object]) -> dict[str, Any]:
    """Return an executable-by-any-harness plan and the frozen terminal schema."""
    request = _request(value)
    manifest = load_company_research_manifest()
    return {
        "ok": True,
        "workflow_profile": "company-research.v2",
        "workflow_id": manifest["id"],
        "request": request.to_dict(),
        "stages": manifest["stages"],
        "routing_semantics": manifest["routing_semantics"],
        "portable_boundary": manifest["portable_boundary"],
        "fallback": manifest["fallback"],
        "terminal_artifact_kind": manifest["terminal_artifact_kind"],
        "submission_schema": load_host_submission_v3_schema(),
        "execution_owner": "host_harness",
        "external_model_api_keys_accepted": False,
        "publication": "atomic_after_complete_validation",
    }


def _run_id(submission: HostSubmissionV3) -> str:
    encoded = json.dumps(submission.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "host-" + hashlib.sha256(encoded.encode()).hexdigest()[:12]


def _evidence(dossier: ResearchDossierV3, *, fixture: bool) -> tuple[EvidenceItem, ...]:
    return tuple(
        EvidenceItem(
            id=document.id,
            category=_CATEGORY_BY_DOCUMENT_KIND[document.kind],
            title=document.title,
            summary=document.extract or "Source retained by reference; no redistributable extract is stored.",
            values={
                "publisher": document.publisher,
                "source_quality": document.kind,
                "locator": document.locator.to_dict(),
                "entitlement": document.entitlement.to_dict(),
                "temporal": document.temporal.to_dict(),
            },
            provenance=Provenance(
                provider=document.publisher,
                source_type=document.kind,
                source_uri=document.locator.canonical_uri,
                retrieved_at=document.temporal.retrieved_at,
                source_date=document.temporal.available_at[:10],
                fixture=fixture,
                notes=(f"entitlement={document.entitlement.access}",),
            ),
            limitations=(document.entitlement.limitation,) if document.entitlement.limitation else (),
        )
        for document in dossier.documents
    )


def _claim_document_ids(dossier: ResearchDossierV3, claim_ids: tuple[str, ...]) -> tuple[str, ...]:
    claims = {claim.id: claim for claim in dossier.claims}
    metric_documents = {metric.id: metric.source_document_ids for metric in dossier.metrics}
    accessible = {item.id for item in dossier.documents if item.entitlement.access != "entitlement_blocked"}
    return tuple(
        dict.fromkeys(
            document_id
            for claim_id in claim_ids
            for document_id in (
                *claims[claim_id].evidence_document_ids,
                *(
                    source_id
                    for metric_id in claims[claim_id].metric_ids
                    for source_id in metric_documents.get(metric_id, ())
                ),
            )
            if document_id in accessible
        )
    )


def _reports(dossier: ResearchDossierV3, evidence: tuple[EvidenceItem, ...]) -> tuple[AnalystReport, ...]:
    evidence_by_category: dict[str, list[str]] = {name: [] for name in _ANALYST_ORDER}
    for item in evidence:
        entitlement = item.values.get("entitlement")
        access = entitlement.get("access") if isinstance(entitlement, Mapping) else None
        if item.category in evidence_by_category and access != "entitlement_blocked":
            evidence_by_category[item.category].append(item.id)
    reports: list[AnalystReport] = []
    for analyst in _ANALYST_ORDER:
        category_ids = set(evidence_by_category[analyst])
        selected_claims = tuple(
            claim for claim in dossier.claims if set(_claim_document_ids(dossier, (claim.id,))) & category_ids
        )
        if not selected_claims:
            continue
        evidence_ids = tuple(
            document_id
            for document_id in _claim_document_ids(dossier, tuple(claim.id for claim in selected_claims))
            if document_id in category_ids
        )
        content = "\n\n".join(f"- {claim.statement}" for claim in selected_claims)
        reports.append(
            AnalystReport(
                analyst=analyst,
                thesis=content.splitlines()[0].removeprefix("- "),
                evidence_ids=evidence_ids,
                confidence=fmean(claim.confidence for claim in selected_claims),
                content=content,
            )
        )
    return tuple(reports)


def _debates(dossier: ResearchDossierV3) -> tuple[tuple[DebateTurn, ...], tuple[DebateTurn, ...]]:
    claims = {claim.id: claim for claim in dossier.claims}
    roles = {argument.id: argument.role for argument in dossier.arguments}
    turns: dict[str, list[DebateTurn]] = {"research": [], "risk": []}
    for argument in sorted(dossier.arguments, key=lambda item: (item.debate, item.round, item.turn)):
        selected = tuple(claims[claim_id] for claim_id in argument.claim_ids)
        turns[argument.debate].append(
            DebateTurn(
                argument.debate,
                argument.round,
                argument.turn,
                argument.role,
                "\n\n".join(claim.statement for claim in selected),
                roles.get(argument.rebuttal_of) if argument.rebuttal_of is not None else None,
                _claim_document_ids(dossier, argument.claim_ids),
            )
        )
    return tuple(turns["research"]), tuple(turns["risk"])


def _snapshot(turns: tuple[DebateTurn, ...], roles: Mapping[str, str], decision: str) -> DebateSnapshot:
    histories = {
        slug: "\n\n".join(turn.position for turn in turns if turn.speaker == role) for slug, role in roles.items()
    }
    current = {
        slug: next((turn.position for turn in reversed(turns) if turn.speaker == role), "")
        for slug, role in roles.items()
    }
    return DebateSnapshot(
        history="\n\n".join(f"{turn.speaker}: {turn.position}" for turn in turns),
        role_histories=histories,
        current_response=turns[-1].position if turns else "",
        current_responses=current,
        judge_decision=decision,
        count=len(turns),
    )


def _risk_level(dossier: ResearchDossierV3) -> Literal["low", "moderate", "high", "unknown"]:
    impacts = {"low": 0, "moderate": 1, "high": 2, "severe": 3, "unknown": 1}
    highest = max((impacts[item.impact] for item in dossier.risks), default=1)
    if highest >= 2:
        return "high"
    if highest == 1:
        return "moderate"
    return "low"


def select_run_coordinator(
    run_id: str,
    company_coordinator: Any,
    host_coordinator: Any,
    additional_company_coordinators: tuple[Any, ...] = (),
) -> Any:
    """Select the lifecycle coordinator that owns ``run_id``."""
    for coordinator in (company_coordinator, *additional_company_coordinators):
        record = coordinator.lifecycle_store.get(run_id)
        if record is not None and coordinator.owns_record(record):
            return coordinator
    return host_coordinator


def _legacy_result(
    submission: HostSubmissionV3,
    *,
    decision_memory_enabled: bool,
    checkpoint_enabled: bool,
) -> RunResult:
    dossier = submission.dossier
    evidence = _evidence(dossier, fixture=submission.request.research_mode == "fixture")
    reports = _reports(dossier, evidence)
    analysts = tuple(report.analyst for report in reports)
    request = RunRequest(
        symbol=dossier.identity.symbol,
        as_of_date=dossier.as_of_at[:10],
        asset_type="crypto" if dossier.identity.asset_type == "crypto" else "stock",
        analysts=analysts,
        debate_rounds=1,
        risk_rounds=1,
        output_language=submission.request.output_language,
        executor="host_native",
        checkpoint_enabled=False,
    )
    research_debate, risk_debate = _debates(dossier)
    recommendation = dossier.recommendation
    trader_action: Literal["buy", "hold", "sell", "unknown"] = (
        "buy"
        if recommendation in {"buy", "overweight"}
        else "sell"
        if recommendation
        in {
            "sell",
            "underweight",
        }
        else "hold"
    )
    base_case = next((item for item in dossier.valuations if item.name == "base"), None)
    thesis = "\n\n".join(claim.statement for claim in dossier.claims if claim.kind == "thesis")
    thesis = thesis or dossier.executive_summary
    constraints = tuple(item.thesis for item in dossier.risks)
    unresolved = tuple(item for argument in dossier.arguments for item in argument.unresolved)
    report_by_analyst = {report.analyst: report.content for report in reports}
    started_at = submission.request.requested_at
    completed_at = dossier.completed_at
    manifest = load_company_research_manifest()
    stages = tuple(
        StageSpec(
            id=stage["id"],
            kind=StageKind.WORKFLOW,
            role=stage["id"],
            ordinal=stage["ordinal"],
            depends_on=tuple(stage["depends_on"]),
        )
        for stage in manifest["stages"]
    )
    result = RunResult(
        run_id=_run_id(submission),
        status=RunStatus.COMPLETED,
        request=request,
        instrument=InstrumentIdentity(
            requested_symbol=dossier.identity.symbol,
            company_of_interest=dossier.identity.issuer_name,
            trade_date=dossier.as_of_at[:10],
            asset_type=request.asset_type,
            instrument_context="; ".join(
                item
                for item in (
                    f"instrument_id={dossier.identity.instrument_id}",
                    f"exchange={dossier.identity.exchange}" if dossier.identity.exchange else "",
                    f"cik={dossier.identity.cik}" if dossier.identity.cik else "",
                )
                if item
            ),
        ),
        topology=WorkflowTopology(
            name="tradingagents.company-research.v2",
            analysts=analysts,
            debate_rounds=1,
            risk_rounds=1,
            stages=stages,
            terminal_stage="publish.dossier",
        ),
        evidence=evidence,
        analyst_reports=reports,
        report_sections=ReportSections(
            market_report=report_by_analyst.get("market", ""),
            sentiment_report=report_by_analyst.get("social", ""),
            news_report=report_by_analyst.get("news", ""),
            fundamentals_report=report_by_analyst.get("fundamentals", ""),
        ),
        research_debate=research_debate,
        research_debate_snapshot=_snapshot(
            research_debate,
            {"bull": "Bull Researcher", "bear": "Bear Researcher"},
            dossier.executive_summary,
        ),
        research_decision=ResearchDecision(
            recommendation=recommendation,
            rationale=dossier.executive_summary,
            strategic_actions="\n".join(item.description for item in dossier.monitoring),
            raw_markdown=dossier.executive_summary,
            supporting_turns=tuple(dict.fromkeys(turn.turn for turn in research_debate)),
            confidence=fmean(claim.confidence for claim in dossier.claims),
            projection_quality="structured",
        ),
        trader_decision=TraderDecision(
            action=trader_action,
            reasoning="Non-executable analytical scenario derived from the completed evidence dossier.",
            raw_markdown=dossier.executive_summary,
            executable=False,
            execution_authority="none",
            submitted=False,
            caveats=("non_executable_analytical_scenario",),
        ),
        risk_debate=risk_debate,
        risk_debate_snapshot=_snapshot(
            risk_debate,
            {
                "aggressive": "Aggressive Analyst",
                "conservative": "Conservative Analyst",
                "neutral": "Neutral Analyst",
            },
            "\n".join(constraints),
        ),
        risk_decision=RiskDecision(risk_level=_risk_level(dossier), constraints=constraints, unresolved=unresolved),
        portfolio_decision=PortfolioDecision(
            rating=recommendation,
            executive_summary=dossier.executive_summary,
            investment_thesis=thesis,
            price_target=base_case.fair_value if base_case is not None else None,
            time_horizon=base_case.horizon if base_case is not None else None,
            raw_markdown=dossier.executive_summary,
            executable=False,
            execution_authority="none",
            submitted=False,
            projection_quality="structured",
        ),
        investment_plan=dossier.executive_summary,
        trader_investment_plan=dossier.executive_summary,
        portfolio_manager_decision=dossier.executive_summary,
        final_trade_decision=f"Rating: {recommendation.title()}\n\n{dossier.executive_summary}",
        processed_signal=recommendation.upper(),
        execution_config=ExecutionConfig(
            executor="host_native",
            output_language=submission.request.output_language,
            checkpoint_enabled=checkpoint_enabled,
        ),
        persistence=PersistenceMetadata(
            decision_memory_enabled=decision_memory_enabled,
            run_logging_enabled=True,
            checkpoint_enabled=checkpoint_enabled,
            writes_expected=False,
            outputs=("research_dossier.v3", "portable_report_bundle"),
        ),
        capability=CapabilityMetadata(
            executor="host_native",
            observation_mode="host_native_submission",
            deterministic=submission.request.research_mode == "fixture",
            live_data=submission.request.research_mode == "live",
            external_credentials_required=False,
            portable_boundary_credentials_required=False,
            host_tool_auth="host_owned_unknown",
            upstream_business_logic=False,
        ),
        warnings=tuple(
            [
                "This is a non-executable research dossier; it has no broker or order authority.",
                f"Research mode: {submission.request.research_mode}.",
            ]
            + [
                f"Coverage {item.area}: {item.status} — {item.limitation}"
                for item in dossier.coverage
                if item.status != "complete"
            ]
            + [
                f"Evaluation {item.id}: {item.status} — {item.notes}"
                for item in dossier.evaluation.checks
                if item.status != "pass"
            ]
            + list(dossier.limitations)
        ),
        started_at=started_at,
        completed_at=completed_at,
    )
    dossier_artifact = Artifact(
        id="research.dossier.v3",
        kind="research_dossier.v3",
        title=f"Complete company research: {dossier.identity.symbol}",
        media_type="application/vnd.tradingagents.research-dossier.v3+json",
        content=dossier.to_dict(),
    )
    request_artifact = Artifact(
        id="research.request.v3",
        kind="research_request.v3",
        title=f"Company research request: {dossier.identity.symbol}",
        media_type="application/vnd.tradingagents.research-request.v3+json",
        content=submission.request.to_dict(),
    )
    return replace(result, artifacts=(*build_report_artifacts(result), dossier_artifact, request_artifact))


def _events(result: RunResult, dossier: ResearchDossierV3) -> tuple[RunEvent, ...]:
    timestamp = datetime.fromisoformat(result.completed_at.replace("Z", "+00:00")).isoformat()
    records = (
        (EventKind.RUN, "validated", "Completed company-research v3 submission accepted."),
        (EventKind.EVIDENCE, "validated", f"Validated {len(dossier.documents)} bounded source documents."),
        (EventKind.DECISION, "completed", f"Published non-executable {dossier.recommendation} research rating."),
        (EventKind.ARTIFACT, "published", "Published completed research_dossier.v3 artifact."),
        (EventKind.RUN, RunStatus.COMPLETED.value, "Company research publication completed atomically."),
    )
    return tuple(
        RunEvent(
            id=f"{result.run_id}:{index:04d}",
            run_id=result.run_id,
            sequence=index,
            timestamp=timestamp,
            kind=kind,
            status=status,
            message=message,
            data={"workflow_profile": "company-research.v2", "execution_observed": False},
        )
        for index, (kind, status, message) in enumerate(records, start=1)
    )


def submit_company_research(
    payload: Mapping[str, object],
    *,
    store: RunStore = RUN_STORE,
) -> tuple[RunResult, tuple[RunEvent, ...]]:
    """Validate and publish one stateless v3 dossier without persistence claims."""
    submission = parse_host_submission_v3(dict(payload))
    draft = build_company_research_draft(submission)
    result = PublicationService().publish(draft, store)
    return result, draft.events


def build_company_research_draft(
    submission: HostSubmissionV3,
    *,
    decision_memory_enabled: bool = False,
    checkpoint_enabled: bool = False,
) -> PublicationDraft:
    """Build a complete v3 publication without mutating a run store."""
    assert_research_dossier_conformant(submission.dossier.to_dict())
    result = _legacy_result(
        submission,
        decision_memory_enabled=decision_memory_enabled,
        checkpoint_enabled=checkpoint_enabled,
    )
    events = _events(result, submission.dossier)
    return PublicationDraft(result=result, events=events)
