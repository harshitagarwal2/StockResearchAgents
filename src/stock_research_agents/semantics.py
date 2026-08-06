"""Canonical transport-neutral semantics for completed company analytics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .company_analytics_v1 import CompanyAnalyticsResultV1
from .contracts import RunEvent
from .reporting import build_report_artifacts, report_groups

SEMANTICS_SCHEMA_VERSION = "company-analytics-semantics.v1"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _content_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def semantics_digest(value: Mapping[str, object]) -> str:
    """Hash a semantic payload without trusting its embedded digest."""
    return _content_sha256({str(key): item for key, item in value.items() if key != "digest"})


def verify_semantics_digest(value: Mapping[str, object]) -> bool:
    digest = value.get("digest")
    return isinstance(digest, str) and digest == semantics_digest(value)


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return dict(value)


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError(f"{name} must be an array")
    return value


@dataclass(frozen=True, slots=True)
class CompletedRunSemanticsV1:
    """Stable meaning of one completed ``CompanyAnalyticsResultV1``."""

    workflow: dict[str, object]
    request_identity: dict[str, object]
    status: str
    document_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    report_groups: tuple[dict[str, object], ...]
    recommendation: str
    artifact_kinds: tuple[str, ...]
    content_addresses: tuple[dict[str, object], ...]
    limitations: tuple[str, ...]
    non_execution: dict[str, object]
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        body: dict[str, object] = {
            "schema_version": self.schema_version,
            "workflow": self.workflow,
            "request_identity": self.request_identity,
            "status": self.status,
            "document_ids": list(self.document_ids),
            "claim_ids": list(self.claim_ids),
            "report_groups": [dict(group) for group in self.report_groups],
            "recommendation": self.recommendation,
            "artifact_kinds": list(self.artifact_kinds),
            "content_addresses": [dict(item) for item in self.content_addresses],
            "limitations": list(self.limitations),
            "non_execution": self.non_execution,
        }
        body["digest"] = semantics_digest(body)
        return body

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CompletedRunSemanticsV1:
        if value.get("schema_version") != SEMANTICS_SCHEMA_VERSION:
            raise ValueError("unsupported company analytics semantics schema")
        if not verify_semantics_digest(value):
            raise ValueError("company analytics semantics digest mismatch")
        try:
            instance = cls(
                workflow=_mapping(value["workflow"], "workflow"),
                request_identity=_mapping(value["request_identity"], "request_identity"),
                status=str(value["status"]),
                document_ids=tuple(str(item) for item in _sequence(value["document_ids"], "document_ids")),
                claim_ids=tuple(str(item) for item in _sequence(value["claim_ids"], "claim_ids")),
                report_groups=tuple(
                    _mapping(item, "report_groups[]") for item in _sequence(value["report_groups"], "report_groups")
                ),
                recommendation=str(value["recommendation"]),
                artifact_kinds=tuple(str(item) for item in _sequence(value["artifact_kinds"], "artifact_kinds")),
                content_addresses=tuple(
                    _mapping(item, "content_addresses[]")
                    for item in _sequence(value["content_addresses"], "content_addresses")
                ),
                limitations=tuple(str(item) for item in _sequence(value["limitations"], "limitations")),
                non_execution=_mapping(value["non_execution"], "non_execution"),
            )
        except KeyError as exc:
            raise ValueError(f"company analytics semantics is missing {exc.args[0]}") from exc
        if instance.to_dict() != dict(value):
            raise ValueError("company analytics semantics is not in canonical v1 form")
        return instance


def build_completed_run_semantics(
    result: CompanyAnalyticsResultV1,
    events: Sequence[RunEvent],
) -> CompletedRunSemanticsV1:
    """Build the canonical semantics projection for one completed publication."""
    if not isinstance(result, CompanyAnalyticsResultV1):
        raise TypeError("result must be a CompanyAnalyticsResultV1")
    event_values = tuple(events)
    if not all(isinstance(event, RunEvent) for event in event_values):
        raise TypeError("events must contain only RunEvent values")
    if any(event.run_id != result.run_id for event in event_values):
        raise ValueError("every event must match result.run_id")

    submission = result.submission
    research = submission.company_research
    dossier = research.dossier
    stage_statuses = [{"stage_id": stage.stage_id, "status": stage.status} for stage in submission.run_card.stages]
    projected_groups = tuple(
        {
            "ordinal": group["ordinal"],
            "slug": group["slug"],
            "title": group["title"],
        }
        for group in report_groups(build_report_artifacts(result))
    )
    artifact_addresses: tuple[dict[str, object], ...] = tuple(
        {
            "scope": "result_artifact",
            "id": artifact.id,
            "kind": artifact.kind,
            "sha256": _content_sha256(artifact.content),
        }
        for artifact in sorted(result.artifacts, key=lambda item: item.id)
    )
    content_addresses: tuple[dict[str, object], ...] = (
        {"scope": "company_research_submission", "sha256": _content_sha256(research.to_dict())},
        {"scope": "analytics_bundle", "sha256": _content_sha256(submission.analytics_bundle.to_dict())},
        {"scope": "source_lineage", "sha256": _content_sha256(submission.source_lineage.to_dict())},
        {"scope": "run_card", "sha256": _content_sha256(submission.run_card.to_dict())},
        {"scope": "research_quality", "sha256": _content_sha256(submission.quality_receipt.to_dict())},
        {"scope": "forecast_set", "sha256": _content_sha256([item.to_dict() for item in submission.forecasts])},
        *artifact_addresses,
    )
    return CompletedRunSemanticsV1(
        workflow={
            "profile": result.profile,
            "workflow_id": submission.workflow_id,
            "workflow_digest": submission.run_card.workflow_digest,
            "stage_ids": [stage.stage_id for stage in submission.run_card.stages],
            "terminal_stage_id": submission.run_card.stages[-1].stage_id,
            "stage_statuses": stage_statuses,
        },
        request_identity=research.request.identity.to_dict(),
        status=result.status.value,
        document_ids=tuple(sorted(item.id for item in dossier.documents)),
        claim_ids=tuple(sorted(item.id for item in dossier.claims)),
        report_groups=projected_groups,
        recommendation=dossier.recommendation,
        artifact_kinds=tuple(sorted({artifact.kind for artifact in result.artifacts})),
        content_addresses=content_addresses,
        limitations=tuple(dict.fromkeys((*dossier.limitations, *result.warnings))),
        non_execution={
            "non_executable": result.non_executable,
            "broker_integration": False,
            "order_submission": False,
            "portfolio_mutation": False,
        },
    )


completed_run_semantics = build_completed_run_semantics
