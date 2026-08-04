"""Canonical semantic projection for completed portable runs.

The projection intentionally excludes presentation prose, runtime timestamps,
filesystem paths, transport envelopes, and run identifiers.  Its digest can
therefore be compared across Python, CLI, MCP, HTTP, and exported bundles.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .contracts import RunEvent, RunResult
from .reporting import build_report_artifacts, report_groups

SEMANTICS_SCHEMA_VERSION = "completed-run-semantics.v1"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def semantics_digest(value: Mapping[str, object]) -> str:
    """Return the SHA-256 digest of a semantics payload, excluding its digest field."""
    body = {str(key): item for key, item in value.items() if key != "digest"}
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def verify_semantics_digest(value: Mapping[str, object]) -> bool:
    """Verify a serialized semantic projection without trusting its transport."""
    digest = value.get("digest")
    return isinstance(digest, str) and digest == semantics_digest(value)


@dataclass(frozen=True, slots=True)
class CompletedRunSemanticsV1:
    """Transport-neutral meaning of one completed ``RunResult`` and its events."""

    workflow: dict[str, object]
    request_identity: dict[str, object]
    status: str
    evidence_ids: tuple[str, ...]
    report_groups: tuple[dict[str, object], ...]
    decisions: dict[str, str]
    processed_signal: str
    artifact_kinds: tuple[str, ...]
    content_addresses: tuple[dict[str, object], ...]
    limitations: tuple[dict[str, object], ...]
    non_execution: dict[str, dict[str, object]]
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        body: dict[str, object] = {
            "schema_version": self.schema_version,
            "workflow": self.workflow,
            "request_identity": self.request_identity,
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
            "report_groups": [dict(group) for group in self.report_groups],
            "decisions": self.decisions,
            "processed_signal": self.processed_signal,
            "artifact_kinds": list(self.artifact_kinds),
            "content_addresses": [dict(item) for item in self.content_addresses],
            "limitations": [dict(item) for item in self.limitations],
            "non_execution": self.non_execution,
        }
        body["digest"] = semantics_digest(body)
        return body

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CompletedRunSemanticsV1:
        """Load and verify a serialized v1 projection."""
        if value.get("schema_version") != SEMANTICS_SCHEMA_VERSION:
            raise ValueError("unsupported completed-run semantics schema")
        if not verify_semantics_digest(value):
            raise ValueError("completed-run semantics digest mismatch")
        try:
            workflow = _require_string_mapping(value["workflow"], "workflow")
            request_identity = _require_string_mapping(value["request_identity"], "request_identity")
            decisions = {str(key): str(item) for key, item in _require_mapping(value["decisions"], "decisions").items()}
            non_execution = {
                str(key): _require_string_mapping(item, f"non_execution.{key}")
                for key, item in _require_mapping(value["non_execution"], "non_execution").items()
            }
            report_group_values = _require_sequence(value["report_groups"], "report_groups")
            limitation_values = _require_sequence(value["limitations"], "limitations")
            content_address_values = _require_sequence(value["content_addresses"], "content_addresses")
            instance = cls(
                workflow=workflow,
                request_identity=request_identity,
                status=str(value["status"]),
                evidence_ids=tuple(str(item) for item in _require_sequence(value["evidence_ids"], "evidence_ids")),
                report_groups=tuple(_require_string_mapping(item, "report_groups[]") for item in report_group_values),
                decisions=decisions,
                processed_signal=str(value["processed_signal"]),
                artifact_kinds=tuple(
                    str(item) for item in _require_sequence(value["artifact_kinds"], "artifact_kinds")
                ),
                content_addresses=tuple(
                    _require_string_mapping(item, "content_addresses[]") for item in content_address_values
                ),
                limitations=tuple(_require_string_mapping(item, "limitations[]") for item in limitation_values),
                non_execution=non_execution,
            )
        except KeyError as exc:
            raise ValueError(f"completed-run semantics is missing {exc.args[0]}") from exc
        if instance.to_dict() != dict(value):
            raise ValueError("completed-run semantics is not in canonical v1 form")
        return instance


def _require_mapping(value: object, name: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _require_string_mapping(value: object, name: str) -> dict[str, object]:
    mapping = _require_mapping(value, name)
    result: dict[str, object] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise ValueError(f"{name} keys must be strings")
        result[key] = item
    return result


def _require_sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError(f"{name} must be an array")
    return value


def _stage_statuses(result: RunResult, events: tuple[RunEvent, ...]) -> list[dict[str, str]]:
    stage_ids = tuple(stage.id for stage in result.topology.stages)
    statuses = {stage_id: "unknown" for stage_id in stage_ids}
    for event in sorted(events, key=lambda item: item.sequence):
        if event.stage_id in statuses and event.status:
            statuses[event.stage_id] = event.status
    return [{"stage_id": stage_id, "status": statuses[stage_id]} for stage_id in stage_ids]


def _report_group_projection(result: RunResult) -> tuple[dict[str, object], ...]:
    groups = report_groups(build_report_artifacts(result))
    return tuple(
        {
            "id": f"report.group.{group['ordinal']}.{group['slug']}",
            "ordinal": group["ordinal"],
            "slug": group["slug"],
            "section_keys": [
                section["key"]
                for section in group.get("sections", [])
                if isinstance(section, Mapping) and isinstance(section.get("key"), str)
            ],
        }
        for group in groups
    )


def _limitations(result: RunResult) -> tuple[dict[str, object], ...]:
    values: list[dict[str, object]] = []
    values.extend(
        {"scope": "evidence", "id": item.id, "count": len(item.limitations)}
        for item in sorted(result.evidence, key=lambda evidence: evidence.id)
        if item.limitations
    )
    artifact_counts: Counter[str] = Counter()
    for artifact in result.artifacts:
        if isinstance(artifact.content, Mapping):
            limitations = artifact.content.get("limitations")
            if isinstance(limitations, Sequence) and not isinstance(limitations, str | bytes | bytearray):
                artifact_counts[artifact.kind] += len(limitations)
    values.extend(
        {"scope": "artifact_kind", "id": kind, "count": count}
        for kind, count in sorted(artifact_counts.items())
        if count
    )
    for limitation_id, count in (
        ("result.warnings", len(result.warnings)),
        ("risk.constraints", len(result.risk_decision.constraints)),
        ("risk.unresolved", len(result.risk_decision.unresolved)),
        ("trader.caveats", len(result.trader_decision.caveats)),
    ):
        if count:
            values.append({"scope": "decision_or_result", "id": limitation_id, "count": count})
    return tuple(values)


def _content_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _content_addresses(result: RunResult) -> tuple[dict[str, object], ...]:
    """Bind the semantic digest to every authoritative terminal research payload."""
    terminal_research = {
        "request_identity": {
            "symbol": result.request.symbol,
            "as_of_date": result.request.as_of_date,
            "asset_type": result.request.asset_type,
            "analysts": list(result.request.analysts),
            "debate_rounds": result.request.debate_rounds,
            "risk_rounds": result.request.risk_rounds,
            "output_language": result.request.output_language,
        },
        "instrument": result.instrument.to_dict(),
        "topology": result.topology.to_dict(),
        "evidence": [item.to_dict() for item in result.evidence],
        "analyst_reports": [item.to_dict() for item in result.analyst_reports],
        "report_sections": result.report_sections.to_dict(),
        "research_debate": [item.to_dict() for item in result.research_debate],
        "research_debate_snapshot": result.research_debate_snapshot.to_dict(),
        "research_decision": result.research_decision.to_dict(),
        "trader_decision": result.trader_decision.to_dict(),
        "risk_debate": [item.to_dict() for item in result.risk_debate],
        "risk_debate_snapshot": result.risk_debate_snapshot.to_dict(),
        "risk_decision": result.risk_decision.to_dict(),
        "portfolio_decision": result.portfolio_decision.to_dict(),
        "investment_plan": result.investment_plan,
        "trader_investment_plan": result.trader_investment_plan,
        "portfolio_manager_decision": result.portfolio_manager_decision,
        "final_trade_decision": result.final_trade_decision,
        "processed_signal": result.processed_signal,
        "artifacts": [item.to_dict() for item in result.artifacts],
        "warnings": list(result.warnings),
        "prototype_notice": result.prototype_notice,
    }
    addresses: list[dict[str, object]] = [
        {
            "scope": "terminal_research",
            "id": "run.completed",
            "sha256": _content_sha256(terminal_research),
        }
    ]
    addresses.extend(
        {
            "scope": "evidence",
            "id": item.id,
            "sha256": _content_sha256(item.to_dict()),
        }
        for item in sorted(result.evidence, key=lambda evidence: evidence.id)
    )
    addresses.extend(
        {
            "scope": "artifact",
            "id": item.id,
            "kind": item.kind,
            "sha256": _content_sha256(item.to_dict()),
        }
        for item in sorted(result.artifacts, key=lambda artifact: artifact.id)
    )
    addresses.extend(
        {
            "scope": "report_section",
            "id": key,
            "sha256": _content_sha256(value),
        }
        for key, value in sorted(result.report_sections.to_dict().items())
        if key != "schema_version"
    )
    return tuple(addresses)


def build_completed_run_semantics(
    result: RunResult,
    events: Sequence[RunEvent],
) -> CompletedRunSemanticsV1:
    """Build the canonical semantic projection for a completed run."""
    if not isinstance(result, RunResult):
        raise TypeError("result must be a RunResult")
    event_values = tuple(events)
    if not all(isinstance(event, RunEvent) for event in event_values):
        raise TypeError("events must contain only RunEvent values")
    if result.status.value != "completed":
        raise ValueError("completed-run semantics requires a completed result")
    if any(event.run_id != result.run_id for event in event_values):
        raise ValueError("every event must match result.run_id")

    return CompletedRunSemanticsV1(
        workflow={
            "profile": result.topology.name,
            "stage_ids": [stage.id for stage in result.topology.stages],
            "terminal_stage_id": result.topology.terminal_stage,
            "stage_statuses": _stage_statuses(result, event_values),
        },
        request_identity={
            "symbol": result.request.symbol,
            "as_of_date": result.request.as_of_date,
            "asset_type": result.request.asset_type,
            "analysts": sorted(result.request.analysts),
            "debate_rounds": result.request.debate_rounds,
            "risk_rounds": result.request.risk_rounds,
            "output_language": result.request.output_language,
        },
        status=result.status.value,
        evidence_ids=tuple(sorted(item.id for item in result.evidence)),
        report_groups=_report_group_projection(result),
        decisions={
            "research_recommendation": result.research_decision.recommendation,
            "research_projection_quality": result.research_decision.projection_quality,
            "trader_action": result.trader_decision.action,
            "trader_projection_quality": result.trader_decision.projection_quality,
            "risk_level": result.risk_decision.risk_level,
            "portfolio_rating": result.portfolio_decision.rating,
            "portfolio_projection_quality": result.portfolio_decision.projection_quality,
        },
        processed_signal=result.processed_signal,
        artifact_kinds=tuple(sorted({artifact.kind for artifact in result.artifacts})),
        content_addresses=_content_addresses(result),
        limitations=_limitations(result),
        non_execution={
            "trader": {
                "executable": result.trader_decision.executable,
                "execution_authority": result.trader_decision.execution_authority,
                "submitted": result.trader_decision.submitted,
            },
            "portfolio": {
                "executable": result.portfolio_decision.executable,
                "execution_authority": result.portfolio_decision.execution_authority,
                "submitted": result.portfolio_decision.submitted,
            },
            "processed_signal": {
                "executable": False,
                "execution_authority": "none",
                "submitted": False,
            },
        },
    )


# Compact public alias for callers that prefer projection terminology.
completed_run_semantics = build_completed_run_semantics
