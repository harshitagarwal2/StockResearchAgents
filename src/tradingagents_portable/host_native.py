"""Credential-free import boundary for research performed by the host harness.

The host (Codex, another agent harness, or a sequential single-agent fallback)
owns model reasoning.  This module validates the completed stage outputs,
normalizes them into the common TradingAgents contracts, derives an ordered
event ledger, and stores only the completed dossier for the read-only UI.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from .application_ports import ResultPublicationPort
from .contracts import (
    SCHEMA_VERSION,
    AnalystReport,
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
    TraderDecision,
    reject_secret_shaped_keys,
)
from .reporting import build_report_artifacts
from .store import RUN_STORE
from .workflow import (
    WorkflowManifest,
    expand_workflow,
    load_host_submission_schema,
    load_run_lifecycle_schema,
    load_workflow_manifest,
    stage_runtime_contract,
)

_MAX_SUBMISSION_BYTES = 2_000_000
_ANALYST_REPORT_FIELDS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}
_RESEARCH_SPEAKERS = ("Bull Researcher", "Bear Researcher")
_RISK_SPEAKERS = ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst")
_SIGNALS = {"buy", "overweight", "hold", "underweight", "sell"}
_TRADER_ACTIONS = {"buy", "hold", "sell"}
_RATING_PATTERN = re.compile(
    r"(?im)^\s*(?:\*\*)?rating(?:\*\*)?\s*:\s*(?:\*\*)?"
    r"(buy|overweight|hold|underweight|sell)(?:\*\*)?\b"
)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError(f"{name} must be an array")
    return value


def _text(value: object, name: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{name}[{index}]") for index, item in enumerate(_sequence(value, name)))


def _optional_string_tuple(value: Mapping[str, Any], key: str, name: str) -> tuple[str, ...]:
    if key not in value:
        return ()
    return _string_tuple(value[key], name)


def _confidence(value: object, name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    confidence = float(value)
    if not 0 <= confidence <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return confidence


def _optional_text(value: Mapping[str, Any], key: str, name: str) -> str | None:
    if key not in value or value[key] is None:
        return None
    return _text(value[key], name)


def _optional_number(value: Mapping[str, Any], key: str, name: str) -> float | None:
    if key not in value or value[key] is None:
        return None
    raw = value[key]
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        raise ValueError(f"{name} must be a number or null")
    number = float(raw)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return number


def _final_rating(final_text: str) -> str:
    match = _RATING_PATTERN.search(final_text)
    if match is None:
        raise ValueError(
            "final_trade_decision must contain an explicit Rating: Buy, Overweight, Hold, Underweight, or Sell"
        )
    return match.group(1).lower()


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{name} contains unsupported fields: {unknown}")


def _source_uri(value: object, name: str) -> str:
    uri = _text(value, name)
    parsed = urlsplit(uri)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{name} must be a public http(s) URL without userinfo")
    return uri


def _iso_datetime(value: object, name: str) -> str:
    raw = _text(value, name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone offset")
    return raw


def _source_date(value: object, name: str, as_of_date: date) -> str:
    raw = _text(value, name)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc
    if parsed > as_of_date:
        raise ValueError(f"{name} must not be after request.as_of_date")
    return raw


def _parse_evidence(items: object, as_of_date: date) -> tuple[EvidenceItem, ...]:
    parsed: list[EvidenceItem] = []
    seen: set[str] = set()
    for index, raw in enumerate(_sequence(items, "evidence")):
        item = _mapping(raw, f"evidence[{index}]")
        _reject_unknown_keys(
            item,
            {"id", "category", "title", "summary", "values", "provenance", "limitations"},
            f"evidence[{index}]",
        )
        evidence_id = _text(item.get("id"), f"evidence[{index}].id")
        if evidence_id in seen:
            raise ValueError(f"duplicate evidence id: {evidence_id}")
        seen.add(evidence_id)
        provenance = _mapping(item.get("provenance"), f"evidence[{index}].provenance")
        _reject_unknown_keys(
            provenance,
            {"provider", "source_type", "source_uri", "retrieved_at", "source_date", "notes"},
            f"evidence[{index}].provenance",
        )
        values = item.get("values", {})
        if not isinstance(values, Mapping):
            raise ValueError(f"evidence[{index}].values must be an object")
        parsed.append(
            EvidenceItem(
                id=evidence_id,
                category=_text(item.get("category"), f"evidence[{index}].category"),
                title=_text(item.get("title"), f"evidence[{index}].title"),
                summary=_text(item.get("summary"), f"evidence[{index}].summary"),
                values=dict(values),
                provenance=Provenance(
                    provider=_text(provenance.get("provider"), f"evidence[{index}].provenance.provider"),
                    source_type=_text(provenance.get("source_type"), f"evidence[{index}].provenance.source_type"),
                    source_uri=_source_uri(provenance.get("source_uri"), f"evidence[{index}].provenance.source_uri"),
                    retrieved_at=_iso_datetime(
                        provenance.get("retrieved_at"), f"evidence[{index}].provenance.retrieved_at"
                    ),
                    source_date=_source_date(
                        provenance.get("source_date"),
                        f"evidence[{index}].provenance.source_date",
                        as_of_date,
                    ),
                    fixture=False,
                    notes=_optional_string_tuple(
                        provenance,
                        "notes",
                        f"evidence[{index}].provenance.notes",
                    ),
                ),
                limitations=_optional_string_tuple(item, "limitations", f"evidence[{index}].limitations"),
            )
        )
    if not parsed:
        raise ValueError("evidence must not be empty")
    return tuple(parsed)


def _parse_reports(
    items: object, request: RunRequest, evidence_by_id: Mapping[str, EvidenceItem]
) -> tuple[AnalystReport, ...]:
    reports: list[AnalystReport] = []
    seen: set[str] = set()
    for index, raw in enumerate(_sequence(items, "analyst_reports")):
        item = _mapping(raw, f"analyst_reports[{index}]")
        _reject_unknown_keys(
            item,
            {"analyst", "thesis", "evidence_ids", "confidence", "content"},
            f"analyst_reports[{index}]",
        )
        analyst = _text(item.get("analyst"), f"analyst_reports[{index}].analyst")
        if analyst != analyst.lower():
            raise ValueError(f"analyst_reports[{index}].analyst must be lowercase")
        if analyst in seen:
            raise ValueError(f"duplicate analyst report: {analyst}")
        if analyst not in request.analysts:
            raise ValueError(f"unexpected analyst report: {analyst}")
        seen.add(analyst)
        referenced = _string_tuple(item.get("evidence_ids"), f"analyst_reports[{index}].evidence_ids")
        if not referenced:
            raise ValueError(f"analyst report {analyst} must reference at least one evidence item")
        if len(set(referenced)) != len(referenced):
            raise ValueError(f"analyst report {analyst} contains duplicate evidence references")
        missing = set(referenced) - set(evidence_by_id)
        if missing:
            raise ValueError(f"analyst report {analyst} references unknown evidence: {sorted(missing)}")
        if not any(evidence_by_id[evidence_id].category.lower() == analyst for evidence_id in referenced):
            raise ValueError(f"analyst report {analyst} must reference evidence in the {analyst} category")
        content = _text(item.get("content"), f"analyst_reports[{index}].content")
        reports.append(
            AnalystReport(
                analyst=analyst,
                thesis=_text(item.get("thesis"), f"analyst_reports[{index}].thesis"),
                evidence_ids=referenced,
                confidence=_confidence(item.get("confidence"), f"analyst_reports[{index}].confidence"),
                content=content,
            )
        )
    missing_reports = set(request.analysts) - seen
    if missing_reports:
        raise ValueError(f"missing analyst reports: {sorted(missing_reports)}")
    order = {name: index for index, name in enumerate(request.analysts)}
    return tuple(sorted(reports, key=lambda report: order[report.analyst]))


def _parse_debate(
    items: object,
    *,
    debate: str,
    rounds: int,
    speakers: tuple[str, ...],
    evidence_ids: set[str],
) -> tuple[DebateTurn, ...]:
    raw_items = _sequence(items, f"{debate}_debate")
    expected = rounds * len(speakers)
    if len(raw_items) != expected:
        raise ValueError(f"{debate}_debate requires exactly {expected} turns")
    turns: list[DebateTurn] = []
    for index, raw in enumerate(raw_items):
        item = _mapping(raw, f"{debate}_debate[{index}]")
        _reject_unknown_keys(
            item,
            {"round", "speaker", "position", "responds_to", "evidence_ids"},
            f"{debate}_debate[{index}]",
        )
        expected_round = index // len(speakers) + 1
        expected_speaker = speakers[index % len(speakers)]
        round_number = _integer(item.get("round"), f"{debate}_debate[{index}].round")
        speaker = _text(item.get("speaker"), f"{debate}_debate[{index}].speaker")
        if round_number != expected_round or speaker != expected_speaker:
            raise ValueError(
                f"{debate}_debate turn {index + 1} must be round {expected_round} speaker {expected_speaker}"
            )
        referenced = _string_tuple(item.get("evidence_ids"), f"{debate}_debate[{index}].evidence_ids")
        if not referenced:
            raise ValueError(f"{debate}_debate[{index}] must reference at least one evidence item")
        if len(set(referenced)) != len(referenced):
            raise ValueError(f"{debate}_debate[{index}] contains duplicate evidence references")
        missing = set(referenced) - evidence_ids
        if missing:
            raise ValueError(f"{debate} debate references unknown evidence: {sorted(missing)}")
        responds_to = item.get("responds_to")
        turns.append(
            DebateTurn(
                debate=debate,  # type: ignore[arg-type]
                round=expected_round,
                turn=index + 1,
                speaker=speaker,
                position=_text(item.get("position"), f"{debate}_debate[{index}].position"),
                responds_to=_text(responds_to, f"{debate}_debate[{index}].responds_to")
                if responds_to is not None
                else None,
                evidence_ids=referenced,
            )
        )
    return tuple(turns)


def _snapshot(turns: tuple[DebateTurn, ...], roles: Mapping[str, str], judge_decision: str) -> DebateSnapshot:
    histories = {
        slug: "\n\n".join(turn.position for turn in turns if turn.speaker == speaker) for slug, speaker in roles.items()
    }
    current = {
        slug: next((turn.position for turn in reversed(turns) if turn.speaker == speaker), "")
        for slug, speaker in roles.items()
    }
    return DebateSnapshot(
        history="\n\n".join(f"{turn.speaker}: {turn.position}" for turn in turns),
        role_histories=histories,
        current_response=turns[-1].position if turns else "",
        current_responses=current,
        judge_decision=judge_decision,
        count=len(turns),
    )


def _run_id(payload: Mapping[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return "host-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _stage_output_contracts(manifest: WorkflowManifest, schema: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Project the advertised stage fields directly from the submission schema."""
    contract_keys = {
        "analyst": "analyst_stage_output",
        "research_debate": "debate_stage_output",
        "research_manager": "research_manager_output",
        "trader": "trader_output",
        "risk_debate": "debate_stage_output",
        "portfolio": "portfolio_stage_output",
    }
    definitions = _mapping(schema.get("$defs"), "submission schema $defs")
    advertised: dict[str, dict[str, Any]] = {}
    for stage_name, contract_key in contract_keys.items():
        output_ref = manifest.contracts[contract_key]
        prefix = "host-submission.v2.schema.json#/$defs/"
        if not isinstance(output_ref, str) or not output_ref.startswith(prefix):
            raise ValueError(f"unexpected output contract reference: {output_ref!r}")
        definition_name = output_ref.removeprefix(prefix)
        definition = _mapping(definitions.get(definition_name), f"submission schema $defs.{definition_name}")
        required = _sequence(definition.get("required"), f"submission schema $defs.{definition_name}.required")
        properties = _mapping(definition.get("properties"), f"submission schema $defs.{definition_name}.properties")
        advertised[stage_name] = {
            "output_ref": output_ref,
            "required": list(required),
            "properties": list(properties),
            "additional_properties": definition.get("additionalProperties", True),
        }
    return advertised


def prepare_host_run(request: RunRequest) -> dict[str, Any]:
    """Return the canonical plan and required output shapes without creating a run."""
    if request.executor != "host_native":
        request = replace(request, executor="host_native", checkpoint_enabled=False, legacy_config={})
    topology = expand_workflow(request)
    manifest = load_workflow_manifest()
    submission_schema = load_host_submission_schema()
    return {
        "ok": True,
        "request": {
            "schema_version": SCHEMA_VERSION,
            "symbol": request.symbol,
            "as_of_date": request.as_of_date,
            "asset_type": request.asset_type,
            "analysts": list(request.analysts),
            "debate_rounds": request.debate_rounds,
            "risk_rounds": request.risk_rounds,
            "output_language": request.output_language,
            "executor": "host_native",
            "checkpoint_enabled": False,
        },
        "topology": topology.to_dict(),
        "stages": [stage_runtime_contract(stage, manifest) for stage in topology.stages],
        "execution_owner": "host_harness",
        "external_model_api_keys_accepted": False,
        "publication": "atomic_after_complete_validation",
        "stage_output_contracts": _stage_output_contracts(manifest, submission_schema),
        "workflow_semantics": {
            "defaults": dict(manifest.defaults),
            "evidence_policy": dict(manifest.evidence_policy),
            "stage_instructions": dict(manifest.stage_instructions),
            "capability_negotiation": dict(manifest.capability_negotiation),
            "tool_capabilities": dict(manifest.tool_capabilities),
            "routing_semantics": dict(manifest.routing_semantics),
            "state_contract": dict(manifest.state_contract),
            "parity_scope": dict(manifest.parity_scope),
        },
        "submission_schema": submission_schema,
        "lifecycle_schema": load_run_lifecycle_schema(),
    }


def _events(result: RunResult) -> tuple[RunEvent, ...]:
    started = datetime.fromisoformat(result.started_at)
    events: list[RunEvent] = []

    def emit(
        kind: EventKind,
        status: str,
        message: str,
        stage_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        sequence = len(events) + 1
        events.append(
            RunEvent(
                id=f"{result.run_id}:{sequence:04d}",
                run_id=result.run_id,
                sequence=sequence,
                timestamp=(started + timedelta(milliseconds=sequence)).isoformat(),
                kind=kind,
                stage_id=stage_id,
                status=status,
                message=message,
                data=data or {},
            )
        )

    emit(
        EventKind.RUN,
        RunStatus.RUNNING.value,
        "Host-native research submission accepted for validation.",
        data={"executor": "host_native", "external_model_api_keys_accepted": False},
    )
    reports = {report.analyst: report for report in result.analyst_reports}
    evidence = {item.id: item for item in result.evidence}
    research_turns = {
        f"research.{turn.round}.{'bull' if turn.speaker == 'Bull Researcher' else 'bear'}": turn
        for turn in result.research_debate
    }
    risk_slugs = {
        "Aggressive Analyst": "aggressive",
        "Conservative Analyst": "conservative",
        "Neutral Analyst": "neutral",
    }
    risk_turns = {f"risk.{turn.round}.{risk_slugs[turn.speaker]}": turn for turn in result.risk_debate}
    for stage in result.topology.stages:
        detail: dict[str, Any] = {
            "role": stage.role,
            "kind": stage.kind.value,
            "output_observed": True,
            "execution_observed": False,
        }
        if stage.id.startswith("analyst."):
            analyst = stage.id.split(".", 1)[1]
            report = reports[analyst]
            detail["report"] = report.to_dict()
            detail["evidence"] = [evidence[evidence_id].to_dict() for evidence_id in report.evidence_ids]
        elif stage.id in research_turns:
            turn = research_turns[stage.id]
            detail["debate_turn"] = turn.to_dict()
        elif stage.id == "research.manager":
            detail["decision"] = result.research_decision.to_dict()
        elif stage.id == "trader":
            detail["decision"] = result.trader_decision.to_dict()
        elif stage.id in risk_turns:
            turn = risk_turns[stage.id]
            detail["debate_turn"] = turn.to_dict()
        elif stage.id == "portfolio":
            detail["decision"] = result.portfolio_decision.to_dict()
        emit(
            EventKind.STAGE,
            "imported",
            f"{stage.role} completed output imported; execution was owned by the host harness.",
            stage.id,
            detail,
        )
    for warning in result.warnings:
        emit(EventKind.WARNING, "recorded", warning, data={"executor": "host_native"})
    emit(
        EventKind.RUN,
        RunStatus.COMPLETED.value,
        "Host-native research dossier completed.",
        data={"artifact_ids": [artifact.id for artifact in result.artifacts]},
    )
    return tuple(events)


def build_host_run(
    payload: Mapping[str, Any],
    *,
    run_id_override: str | None = None,
) -> tuple[RunResult, tuple[RunEvent, ...]]:
    """Validate and build one completed host-executed workflow submission.

    ``run_id_override`` is an internal coordinator seam. It is deliberately not
    part of the host submission wire contract, so a lifecycle can retain the
    identity allocated before execution without letting submissions choose
    arbitrary storage identifiers. This builder performs no persistence.
    """
    reject_secret_shaped_keys(payload)
    _reject_unknown_keys(
        payload,
        {
            "request",
            "company_of_interest",
            "instrument_context",
            "evidence",
            "analyst_reports",
            "research_debate",
            "research_decision",
            "trader_decision",
            "risk_debate",
            "risk_decision",
            "portfolio_decision",
            "final_trade_decision",
            "warnings",
        },
        "submission",
    )
    encoded = json.dumps(payload, default=str).encode("utf-8")
    if len(encoded) > _MAX_SUBMISSION_BYTES:
        raise ValueError("host-native submission exceeds the 2 MB limit")

    request_data = _mapping(payload.get("request"), "request")
    _reject_unknown_keys(
        request_data,
        {
            "schema_version",
            "symbol",
            "as_of_date",
            "asset_type",
            "analysts",
            "debate_rounds",
            "risk_rounds",
            "output_language",
            "executor",
            "checkpoint_enabled",
        },
        "request",
    )
    required_request_fields = {
        "schema_version",
        "symbol",
        "as_of_date",
        "asset_type",
        "analysts",
        "debate_rounds",
        "risk_rounds",
        "output_language",
        "executor",
        "checkpoint_enabled",
    }
    missing_request_fields = sorted(required_request_fields - set(request_data))
    if missing_request_fields:
        raise ValueError(f"request is missing required fields: {missing_request_fields}")
    schema_version = _text(request_data.get("schema_version"), "request.schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"request.schema_version must be {SCHEMA_VERSION}")
    executor = _text(request_data.get("executor"), "request.executor")
    if executor != "host_native":
        raise ValueError("request.executor must be host_native")
    if request_data.get("checkpoint_enabled") is not False:
        raise ValueError("request.checkpoint_enabled must be false")
    analysts = tuple(
        _text(item, f"request.analysts[{index}]")
        for index, item in enumerate(_sequence(request_data.get("analysts"), "request.analysts"))
    )
    if any(analyst != analyst.lower() for analyst in analysts):
        raise ValueError("request.analysts values must be lowercase")
    request = RunRequest(
        symbol=_text(request_data.get("symbol"), "request.symbol"),
        as_of_date=_text(request_data.get("as_of_date"), "request.as_of_date"),
        asset_type=_text(request_data.get("asset_type", "stock"), "request.asset_type"),  # type: ignore[arg-type]
        analysts=analysts,
        debate_rounds=_integer(request_data.get("debate_rounds"), "request.debate_rounds"),
        risk_rounds=_integer(request_data.get("risk_rounds"), "request.risk_rounds"),
        output_language=_text(request_data.get("output_language"), "request.output_language"),
        executor="host_native",
        checkpoint_enabled=False,
    )
    evidence = _parse_evidence(payload.get("evidence"), date.fromisoformat(request.as_of_date))
    evidence_by_id = {item.id: item for item in evidence}
    evidence_ids = set(evidence_by_id)
    reports = _parse_reports(payload.get("analyst_reports"), request, evidence_by_id)
    research_turns = _parse_debate(
        payload.get("research_debate"),
        debate="research",
        rounds=request.debate_rounds,
        speakers=_RESEARCH_SPEAKERS,
        evidence_ids=evidence_ids,
    )
    risk_turns = _parse_debate(
        payload.get("risk_debate"),
        debate="risk",
        rounds=request.risk_rounds,
        speakers=_RISK_SPEAKERS,
        evidence_ids=evidence_ids,
    )

    research_data = _mapping(payload.get("research_decision"), "research_decision")
    _reject_unknown_keys(
        research_data,
        {"recommendation", "rationale", "strategic_actions", "raw_markdown", "confidence"},
        "research_decision",
    )
    raw_research_label = _text(research_data.get("recommendation"), "research_decision.recommendation")
    if raw_research_label not in {label.title() for label in _SIGNALS}:
        raise ValueError("research_decision.recommendation must be Buy, Overweight, Hold, Underweight, or Sell")
    research_label = raw_research_label.lower()
    research_decision = ResearchDecision(
        recommendation=research_label,  # type: ignore[arg-type]
        rationale=_text(research_data.get("rationale"), "research_decision.rationale"),
        strategic_actions=_text(
            research_data.get("strategic_actions"),
            "research_decision.strategic_actions",
        ),
        raw_markdown=_optional_text(research_data, "raw_markdown", "research_decision.raw_markdown") or "",
        supporting_turns=tuple(range(1, len(research_turns) + 1)),
        confidence=_confidence(research_data.get("confidence"), "research_decision.confidence"),
    )
    if not research_decision.raw_markdown:
        research_decision = replace(research_decision, raw_markdown=research_decision.render_markdown())

    trader_data = _mapping(payload.get("trader_decision"), "trader_decision")
    _reject_unknown_keys(
        trader_data,
        {
            "action",
            "reasoning",
            "entry_price",
            "stop_loss",
            "position_sizing",
            "raw_markdown",
            "caveats",
            "executable",
            "execution_authority",
            "submitted",
        },
        "trader_decision",
    )
    trader_executable = trader_data.get("executable")
    if trader_executable is not None and trader_executable is not False:
        raise ValueError("trader_decision.executable must be false")
    trader_authority = trader_data.get("execution_authority")
    if trader_authority is not None and trader_authority != "none":
        raise ValueError("trader_decision.execution_authority must be none")
    trader_submitted = trader_data.get("submitted")
    if trader_submitted is not None and trader_submitted is not False:
        raise ValueError("trader_decision.submitted must be false")
    raw_trader_action = _text(trader_data.get("action"), "trader_decision.action")
    if raw_trader_action not in {action.title() for action in _TRADER_ACTIONS}:
        raise ValueError("trader_decision.action must be Buy, Hold, or Sell")
    trader_action = raw_trader_action.lower()
    trader_decision = TraderDecision(
        action=trader_action,  # type: ignore[arg-type]
        reasoning=_text(trader_data.get("reasoning"), "trader_decision.reasoning"),
        entry_price=_optional_number(trader_data, "entry_price", "trader_decision.entry_price"),
        stop_loss=_optional_number(trader_data, "stop_loss", "trader_decision.stop_loss"),
        position_sizing=_optional_text(trader_data, "position_sizing", "trader_decision.position_sizing"),
        raw_markdown=_optional_text(trader_data, "raw_markdown", "trader_decision.raw_markdown") or "",
        executable=False,
        execution_authority="none",
        submitted=False,
        caveats=_optional_string_tuple(trader_data, "caveats", "trader_decision.caveats"),
    )
    if not trader_decision.raw_markdown:
        trader_decision = replace(trader_decision, raw_markdown=trader_decision.render_markdown())

    risk_data = _mapping(payload.get("risk_decision"), "risk_decision")
    _reject_unknown_keys(risk_data, {"risk_level", "constraints", "unresolved"}, "risk_decision")
    risk_level = _text(risk_data.get("risk_level"), "risk_decision.risk_level")
    if risk_level not in {"low", "moderate", "high", "unknown"}:
        raise ValueError(f"unsupported risk level: {risk_level}")
    risk_decision = RiskDecision(
        risk_level=risk_level,  # type: ignore[arg-type]
        constraints=_string_tuple(risk_data.get("constraints"), "risk_decision.constraints"),
        unresolved=_string_tuple(risk_data.get("unresolved"), "risk_decision.unresolved"),
    )
    portfolio_data = _mapping(payload.get("portfolio_decision"), "portfolio_decision")
    _reject_unknown_keys(
        portfolio_data,
        {
            "rating",
            "executive_summary",
            "investment_thesis",
            "price_target",
            "time_horizon",
            "raw_markdown",
            "executable",
            "execution_authority",
            "submitted",
        },
        "portfolio_decision",
    )
    portfolio_executable = portfolio_data.get("executable")
    if portfolio_executable is not None and portfolio_executable is not False:
        raise ValueError("portfolio_decision.executable must be false")
    portfolio_authority = portfolio_data.get("execution_authority")
    if portfolio_authority is not None and portfolio_authority != "none":
        raise ValueError("portfolio_decision.execution_authority must be none")
    portfolio_submitted = portfolio_data.get("submitted")
    if portfolio_submitted is not None and portfolio_submitted is not False:
        raise ValueError("portfolio_decision.submitted must be false")
    raw_portfolio_rating = _text(portfolio_data.get("rating"), "portfolio_decision.rating")
    if raw_portfolio_rating not in {label.title() for label in _SIGNALS}:
        raise ValueError("portfolio_decision.rating must be Buy, Overweight, Hold, Underweight, or Sell")
    portfolio_rating = raw_portfolio_rating.lower()
    portfolio_decision = PortfolioDecision(
        rating=portfolio_rating,  # type: ignore[arg-type]
        executive_summary=_text(
            portfolio_data.get("executive_summary"),
            "portfolio_decision.executive_summary",
        ),
        investment_thesis=_text(
            portfolio_data.get("investment_thesis"),
            "portfolio_decision.investment_thesis",
        ),
        price_target=_optional_number(portfolio_data, "price_target", "portfolio_decision.price_target"),
        time_horizon=_optional_text(portfolio_data, "time_horizon", "portfolio_decision.time_horizon"),
        raw_markdown=_optional_text(portfolio_data, "raw_markdown", "portfolio_decision.raw_markdown") or "",
        executable=False,
        execution_authority="none",
        submitted=False,
    )
    if not portfolio_decision.raw_markdown:
        portfolio_decision = replace(portfolio_decision, raw_markdown=portfolio_decision.render_markdown())

    warnings = _optional_string_tuple(payload, "warnings", "warnings")
    report_content = {report.analyst: report.content for report in reports}
    report_sections = ReportSections(
        **{field: report_content.get(analyst, "") for analyst, field in _ANALYST_REPORT_FIELDS.items()}
    )
    final_trade_decision = _text(payload.get("final_trade_decision"), "final_trade_decision")
    final_rating = _final_rating(final_trade_decision)
    if final_rating != portfolio_rating:
        raise ValueError("final_trade_decision Rating must match portfolio_decision.rating")
    processed_signal = portfolio_rating.upper()
    if run_id_override is not None and not re.fullmatch(r"host-[a-f0-9]{12}", run_id_override):
        raise ValueError("run_id_override must match host- followed by 12 lowercase hexadecimal characters")
    run_id = run_id_override or _run_id(payload)
    started_at = datetime.now(UTC).isoformat()
    topology = expand_workflow(request)
    base_result = RunResult(
        run_id=run_id,
        request=request,
        instrument=InstrumentIdentity(
            requested_symbol=request.symbol,
            company_of_interest=_text(payload.get("company_of_interest", request.symbol), "company_of_interest"),
            trade_date=request.as_of_date,
            asset_type=request.asset_type,
            instrument_context=_text(payload.get("instrument_context", ""), "instrument_context", required=False),
        ),
        topology=topology,
        evidence=evidence,
        analyst_reports=reports,
        report_sections=report_sections,
        research_debate=research_turns,
        research_debate_snapshot=_snapshot(
            research_turns,
            {"bull": "Bull Researcher", "bear": "Bear Researcher"},
            research_decision.raw_markdown,
        ),
        research_decision=research_decision,
        trader_decision=trader_decision,
        risk_debate=risk_turns,
        risk_debate_snapshot=_snapshot(
            risk_turns,
            {
                "aggressive": "Aggressive Analyst",
                "conservative": "Conservative Analyst",
                "neutral": "Neutral Analyst",
            },
            portfolio_decision.raw_markdown,
        ),
        risk_decision=risk_decision,
        portfolio_decision=portfolio_decision,
        investment_plan=research_decision.raw_markdown,
        trader_investment_plan=trader_decision.raw_markdown,
        portfolio_manager_decision=portfolio_decision.raw_markdown,
        final_trade_decision=final_trade_decision,
        processed_signal=processed_signal,
        execution_config=ExecutionConfig(
            executor="host_native",
            output_language=request.output_language,
            checkpoint_enabled=False,
            max_debate_rounds=request.debate_rounds,
            max_risk_discuss_rounds=request.risk_rounds,
        ),
        persistence=PersistenceMetadata(
            decision_memory_enabled=False,
            run_logging_enabled=False,
            checkpoint_enabled=False,
            writes_expected=False,
            outputs=("in_memory_run_store",),
        ),
        capability=CapabilityMetadata(
            executor="host_native",
            observation_mode="host_native_submission",
            deterministic=False,
            live_data=all(item.provenance.source_uri is not None and not item.provenance.fixture for item in evidence),
            external_credentials_required=False,
            portable_boundary_credentials_required=False,
            host_tool_auth="host_owned_unknown",
            upstream_business_logic=False,
        ),
        warnings=(
            "Reasoning was supplied by the active host harness; StockResearchAgents accepted no model API key.",
            "Evidence provenance was supplied by the host and structurally validated; the importer did not fetch it.",
            "Host-native events are validated completion receipts, not token-by-token model telemetry.",
            *warnings,
        ),
        started_at=started_at,
        completed_at=datetime.now(UTC).isoformat(),
    )
    result = replace(base_result, artifacts=build_report_artifacts(base_result))
    events = _events(result)
    return result, events


def submit_host_run(
    payload: Mapping[str, Any],
    *,
    store: ResultPublicationPort = RUN_STORE,
    run_id_override: str | None = None,
) -> tuple[RunResult, tuple[RunEvent, ...]]:
    """Validate and atomically publish one completed host workflow submission."""
    result, events = build_host_run(payload, run_id_override=run_id_override)
    existing_result = store.get_result(result.run_id)
    existing_events = store.get_events(result.run_id)
    if existing_result is not None and existing_events is not None:
        return existing_result, existing_events
    store.stage(result, events)
    return store.publish_staged(result.run_id)
