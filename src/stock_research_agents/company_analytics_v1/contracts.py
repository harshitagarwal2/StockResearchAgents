"""Strict company-analytics.v1 wrapper around the base research submission."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from stock_research_agents.analytics_v1 import AnalyticsBundleV1
from stock_research_agents.analytics_v1.validators import assert_analytics_bundle_conformant
from stock_research_agents.contracts import (
    PROTOTYPE_NOTICE,
    SCHEMA_VERSION,
    Artifact,
    RunStatus,
    reject_secret_shaped_keys,
)
from stock_research_agents.research_contracts import CompanyResearchSubmissionV1, parse_company_research_submission_v1
from stock_research_agents.research_lab_v1 import HypothesisLedger, ResearchIterationReceipt, RunCardV1
from stock_research_agents.research_quality_v1 import (
    Forecast,
    ResearchQualityReceipt,
    validate_quality_bundle,
)

from .source_lineage import SourceLineageCrosswalkV1

COMPANY_ANALYTICS_SCHEMA_VERSION = "company-analytics.v1"
COMPANY_ANALYTICS_WORKFLOW_ID = "stockresearchagents.company-analytics.v1"
COMPANY_ANALYTICS_RESULT_SCHEMA_VERSION = "company-analytics-result.v1"
_WORKFLOW_MANIFEST = Path(__file__).resolve().parent.parent / "workflow" / "company-analytics.v1.json"
_FIELDS = {
    "schema_version",
    "workflow_id",
    "company_research",
    "analytics_bundle",
    "source_lineage",
    "run_card",
    "hypothesis_ledgers",
    "research_iterations",
    "quality_receipt",
    "forecasts",
}
_RESULT_FIELDS = {
    "schema_version",
    "run_id",
    "status",
    "profile",
    "submission",
    "artifacts",
    "warnings",
    "started_at",
    "completed_at",
    "prototype_notice",
    "non_executable",
}
_ARTIFACT_FIELDS = {"schema_version", "id", "kind", "title", "media_type", "content"}
_REQUIRED_ARTIFACT_KINDS = frozenset(
    {
        "research_dossier.v1",
        "analytics_bundle.v1",
        "run_card.v1",
        "hypothesis_ledger.v1",
        "research_iterations.v1",
        "research_quality.v1",
        "forecast_set.v1",
    }
)
_RUN_ID_SENTINEL = "<canonical-run-id>"


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def canonical_workflow_manifest() -> dict[str, object]:
    """Load the shipped workflow whose digest defines completed v1 publications."""
    value = json.loads(_WORKFLOW_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("company analytics workflow manifest must be an object")
    return value


def canonical_workflow_digest() -> str:
    return _canonical_digest(canonical_workflow_manifest())


def canonical_stage_ids() -> tuple[str, ...]:
    stages = canonical_workflow_manifest().get("stages")
    if not isinstance(stages, list):
        raise ValueError("company analytics workflow stages must be an array")
    return tuple(str(stage["id"]) for stage in stages if isinstance(stage, dict))


def base_submission_digest(submission: CompanyResearchSubmissionV1) -> str:
    return _canonical_digest(submission.to_dict())


def base_request_digest(submission: CompanyResearchSubmissionV1) -> str:
    return _canonical_digest(submission.request.to_dict())


def _normalized_run_identity(value: object) -> object:
    """Normalize fields whose values are derived from the canonical run ID."""
    run_ids: set[str] = set()

    def collect(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if key == "run_id" and isinstance(nested, str):
                    run_ids.add(nested)
                collect(nested)
        elif isinstance(item, list | tuple):
            for nested in item:
                collect(nested)

    collect(value)

    def normalize(item: object, *, field_name: object | None = None) -> object:
        if field_name == "run_id":
            return _RUN_ID_SENTINEL
        if isinstance(item, Mapping):
            return {str(key): normalize(nested, field_name=key) for key, nested in item.items()}
        if isinstance(item, list | tuple):
            return [normalize(nested) for nested in item]
        if field_name == "forecast_id" and isinstance(item, str):
            for run_id in sorted(run_ids, key=len, reverse=True):
                prefix = f"{run_id}."
                if item.startswith(prefix):
                    return f"{_RUN_ID_SENTINEL}.{item.removeprefix(prefix)}"
        return item

    return normalize(value)


def analytics_run_id(submission: CompanyAnalyticsSubmissionV1 | Mapping[str, object]) -> str:
    """Hash the normalized full outer submission into its canonical run ID."""
    payload = dict(submission) if isinstance(submission, Mapping) else submission.to_dict()
    return "analytics-" + _canonical_digest(_normalized_run_identity(payload))[:12]


@dataclass(frozen=True, slots=True)
class CompanyAnalyticsSubmissionV1:
    schema_version: Literal["company-analytics.v1"]
    workflow_id: Literal["stockresearchagents.company-analytics.v1"]
    company_research: CompanyResearchSubmissionV1
    analytics_bundle: AnalyticsBundleV1
    source_lineage: SourceLineageCrosswalkV1
    run_card: RunCardV1
    hypothesis_ledgers: tuple[HypothesisLedger, ...]
    research_iterations: tuple[ResearchIterationReceipt, ...]
    quality_receipt: ResearchQualityReceipt
    forecasts: tuple[Forecast, ...]

    def __post_init__(self) -> None:
        if self.schema_version != COMPANY_ANALYTICS_SCHEMA_VERSION:
            raise ValueError("unsupported company analytics schema version")
        if self.workflow_id != COMPANY_ANALYTICS_WORKFLOW_ID:
            raise ValueError("unexpected company analytics workflow ID")
        run_id = self.run_card.run_id
        submission_digest = base_submission_digest(self.company_research)
        request_digest = base_request_digest(self.company_research)
        dossier_digest = self.company_research.dossier.digest()
        if self.analytics_bundle.run_id != run_id:
            raise ValueError("analytics bundle and run card must bind to the derived research run_id")
        if self.quality_receipt.run_id != run_id:
            raise ValueError("quality receipt must bind to the derived research run_id")
        if self.analytics_bundle.base_submission_digest != submission_digest:
            raise ValueError("analytics bundle base_submission_digest does not match base research")
        if self.analytics_bundle.base_dossier_digest != dossier_digest:
            raise ValueError("analytics bundle base_dossier_digest does not match base research")
        if self.run_card.submission_digest != submission_digest:
            raise ValueError("run card submission_digest does not match base research")
        if self.quality_receipt.request_sha256 != request_digest:
            raise ValueError("quality receipt request digest does not match base research")
        if self.quality_receipt.dossier_sha256 != dossier_digest:
            raise ValueError("quality receipt dossier digest does not match base research")
        if self.run_card.workflow_digest != self.quality_receipt.workflow_sha256:
            raise ValueError("run card and quality receipt workflow digests must match")
        if self.run_card.workflow_digest != canonical_workflow_digest():
            raise ValueError("completed analytics publication must bind to the canonical workflow digest")
        stage_ids = tuple(stage.stage_id for stage in self.run_card.stages)
        if stage_ids != canonical_stage_ids():
            raise ValueError("completed analytics publication requires the exact ordered 26-stage receipt set")
        if any(stage.status != "completed" for stage in self.run_card.stages):
            raise ValueError("completed analytics publication requires every canonical stage to be completed")
        if self.run_card.profile != COMPANY_ANALYTICS_SCHEMA_VERSION:
            raise ValueError("run card profile must be company-analytics.v1")
        if self.run_card.started_at != self.company_research.request.requested_at:
            raise ValueError("run card started_at must match the base request")
        if self.run_card.completed_at != self.analytics_bundle.completed_at:
            raise ValueError("run card completed_at must match analytics completion")
        artifact_kinds = self.run_card.artifact_kinds
        if len(artifact_kinds) != 7 or len(set(artifact_kinds)) != 7 or set(artifact_kinds) != _REQUIRED_ARTIFACT_KINDS:
            raise ValueError("run card must declare exactly the seven canonical analytics artifact kinds")
        completed_stage_digests = tuple(
            (stage.stage_id, stage.output_digest or "") for stage in self.run_card.stages if stage.status == "completed"
        )
        if self.quality_receipt.stage_digests != completed_stage_digests:
            raise ValueError("quality receipt stage digests must match completed run-card stages")
        self._validate_references(run_id)
        self._validate_source_lineage()
        assert_analytics_bundle_conformant(self.analytics_bundle)
        quality = validate_quality_bundle(self.quality_receipt, self.forecasts, ())
        if not quality.passed:
            raise ValueError(
                "research quality sidecar is not conformant: "
                + "; ".join(f"{issue.path}: {issue.detail}" for issue in quality.issues)
            )
        if run_id != analytics_run_id(self):
            raise ValueError(
                "submission run IDs do not match the derived research run_id for this different publication"
            )

    def _validate_references(self, run_id: str) -> None:
        document_ids = {document.id for document in self.company_research.dossier.documents}
        claim_ids = {claim.id for claim in self.company_research.dossier.claims}
        hypothesis_ids: set[str] = set()
        for ledger in self.hypothesis_ledgers:
            if ledger.run_id != run_id:
                raise ValueError("hypothesis ledger must bind to the derived research run_id")
            hypothesis_id = ledger.hypothesis.hypothesis_id
            if hypothesis_id in hypothesis_ids:
                raise ValueError("hypothesis ledger IDs must be unique")
            hypothesis_ids.add(hypothesis_id)
            missing = set(ledger.hypothesis.evidence_ids) - document_ids
            if missing:
                raise ValueError(f"hypothesis references unknown documents: {sorted(missing)}")
        forecast_ids: set[str] = set()
        for forecast in self.forecasts:
            if forecast.forecast_id in forecast_ids:
                raise ValueError("forecast IDs must be unique")
            forecast_ids.add(forecast.forecast_id)
            if forecast.run_id != run_id:
                raise ValueError("forecast must bind to the derived research run_id")
            if forecast.instrument_id != self.company_research.dossier.identity.instrument_id:
                raise ValueError("forecast instrument does not match the base dossier")
            if forecast.claim_id not in claim_ids:
                raise ValueError(f"forecast references an unknown claim: {forecast.claim_id}")
            missing = set(forecast.evidence_document_ids) - document_ids
            if missing:
                raise ValueError(f"forecast references unknown documents: {sorted(missing)}")
        iteration_ids: set[str] = set()
        for iteration in self.research_iterations:
            if iteration.run_id != run_id:
                raise ValueError("research iteration must bind to the derived research run_id")
            if iteration.iteration_id in iteration_ids:
                raise ValueError("research iteration IDs must be unique")
            iteration_ids.add(iteration.iteration_id)
            missing = set(iteration.hypothesis_ids) - hypothesis_ids
            if missing:
                raise ValueError(f"research iteration references unknown hypotheses: {sorted(missing)}")

    def _validate_source_lineage(self) -> None:
        documents = {document.id: document for document in self.company_research.dossier.documents}
        licenses = {receipt.receipt_id: receipt for receipt in self.analytics_bundle.source_licenses}
        bindings = self.source_lineage.bindings
        batch_ids = tuple(dict.fromkeys(binding.source_batch_id for binding in bindings))
        if batch_ids != self.run_card.source_batch_ids:
            raise ValueError("source lineage batch IDs must exactly match run-card source_batch_ids in order")
        if {binding.dossier_document_id for binding in bindings} != set(documents):
            raise ValueError("source lineage must bind every dossier document exactly once")
        if {binding.analytics_license_receipt_id for binding in bindings} != set(licenses):
            raise ValueError("source lineage must bind every analytics source license exactly once")
        for binding in bindings:
            document = documents[binding.dossier_document_id]
            receipt = licenses[binding.analytics_license_receipt_id]
            if binding.analytics_source_id != receipt.source_id:
                raise ValueError("source lineage analytics source ID does not match its license receipt")
            if receipt.source_id != document.id:
                raise ValueError("analytics source ID must resolve to the bound dossier document")
            if binding.canonical_uri != document.locator.canonical_uri:
                raise ValueError("source lineage canonical URI does not match the dossier document")
            if binding.content_sha256 != document.locator.content_sha256:
                raise ValueError("source lineage content digest does not match the dossier document")
            if binding.entitlement_access != document.entitlement.access:
                raise ValueError("source lineage access does not match the dossier entitlement")
            if binding.redistributable != document.entitlement.redistributable:
                raise ValueError("source lineage redistribution does not match the dossier entitlement")
            if binding.terms_uri != document.entitlement.terms_uri or receipt.terms_uri != binding.terms_uri:
                raise ValueError("source lineage terms URI must match dossier and analytics entitlements")
            if receipt.access != binding.entitlement_access:
                raise ValueError("analytics source license access does not match source lineage")
            if binding.redistributable and receipt.redistribution not in {"allowed", "bounded_extract"}:
                raise ValueError("redistributable lineage requires an analytics redistribution grant")
            if not binding.redistributable and receipt.redistribution not in {"reference_only", "denied"}:
                raise ValueError("non-redistributable lineage requires reference-only or denied analytics use")
            if binding.entitlement_access == "entitlement_blocked" and receipt.machine_use != "denied":
                raise ValueError("entitlement-blocked lineage requires machine-use denial")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "company_research": self.company_research.to_dict(),
            "analytics_bundle": self.analytics_bundle.to_dict(),
            "source_lineage": self.source_lineage.to_dict(),
            "run_card": self.run_card.to_dict(),
            "hypothesis_ledgers": [item.to_dict() for item in self.hypothesis_ledgers],
            "research_iterations": [item.to_dict() for item in self.research_iterations],
            "quality_receipt": self.quality_receipt.to_dict(),
            "forecasts": [item.to_dict() for item in self.forecasts],
        }
        reject_secret_shaped_keys(payload)
        return payload

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> CompanyAnalyticsSubmissionV1:
        if not isinstance(value, Mapping):
            raise ValueError("CompanyAnalyticsSubmissionV1 must be an object")
        payload = dict(value)
        reject_secret_shaped_keys(payload)
        unknown = sorted(set(payload) - _FIELDS)
        missing = sorted(_FIELDS - set(payload))
        if unknown or missing:
            raise ValueError(f"CompanyAnalyticsSubmissionV1 fields mismatch; missing={missing}, unknown={unknown}")
        ledgers = payload["hypothesis_ledgers"]
        iterations = payload["research_iterations"]
        forecasts = payload["forecasts"]
        if not isinstance(ledgers, list | tuple) or not isinstance(iterations, list | tuple):
            raise ValueError("hypothesis_ledgers and research_iterations must be arrays")
        if not isinstance(forecasts, list | tuple):
            raise ValueError("forecasts must be an array")
        return cls(
            schema_version=payload["schema_version"],  # type: ignore[arg-type]
            workflow_id=payload["workflow_id"],  # type: ignore[arg-type]
            company_research=parse_company_research_submission_v1(payload["company_research"]),
            analytics_bundle=AnalyticsBundleV1.from_dict(payload["analytics_bundle"]),
            source_lineage=SourceLineageCrosswalkV1.from_dict(payload["source_lineage"]),
            run_card=RunCardV1.from_dict(payload["run_card"]),
            hypothesis_ledgers=tuple(HypothesisLedger.from_dict(item) for item in ledgers),
            research_iterations=tuple(ResearchIterationReceipt.from_dict(item) for item in iterations),
            quality_receipt=ResearchQualityReceipt.from_dict(payload["quality_receipt"]),
            forecasts=tuple(Forecast.from_dict(item) for item in forecasts),
        )


def parse_company_analytics_submission_v1(value: object) -> CompanyAnalyticsSubmissionV1:
    return value if isinstance(value, CompanyAnalyticsSubmissionV1) else CompanyAnalyticsSubmissionV1.from_dict(value)


def _artifact_from_dict(value: object) -> Artifact:
    if not isinstance(value, Mapping):
        raise ValueError("CompanyAnalyticsResultV1 artifact must be an object")
    payload = dict(value)
    unknown = sorted(set(payload) - _ARTIFACT_FIELDS)
    missing = sorted(_ARTIFACT_FIELDS - set(payload))
    if unknown or missing:
        raise ValueError(f"Artifact fields mismatch; missing={missing}, unknown={unknown}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"artifact.schema_version must be {SCHEMA_VERSION}")
    for field_name in ("id", "kind", "title", "media_type"):
        if not isinstance(payload[field_name], str) or not payload[field_name]:
            raise ValueError(f"artifact.{field_name} must be a non-empty string")
    return Artifact(
        id=payload["id"],
        kind=payload["kind"],
        title=payload["title"],
        media_type=payload["media_type"],
        content=payload["content"],
    )


@dataclass(frozen=True, slots=True)
class CompanyAnalyticsResultV1:
    """First-party completed publication for the ``company-analytics.v1`` profile."""

    schema_version: Literal["company-analytics-result.v1"]
    run_id: str
    status: RunStatus
    profile: Literal["company-analytics.v1"]
    submission: CompanyAnalyticsSubmissionV1
    artifacts: tuple[Artifact, ...]
    warnings: tuple[str, ...]
    started_at: str
    completed_at: str
    prototype_notice: str
    non_executable: Literal[True]

    def __post_init__(self) -> None:
        if self.schema_version != COMPANY_ANALYTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported company analytics result schema version")
        if self.status is not RunStatus.COMPLETED:
            raise ValueError("company analytics result status must be completed")
        if self.profile != COMPANY_ANALYTICS_SCHEMA_VERSION:
            raise ValueError("company analytics result profile must be company-analytics.v1")
        if self.run_id != self.submission.run_card.run_id:
            raise ValueError("company analytics result run_id must match the canonical submission run card")
        if self.started_at != self.submission.run_card.started_at:
            raise ValueError("company analytics result started_at must match the canonical submission run card")
        if self.completed_at != self.submission.run_card.completed_at:
            raise ValueError("company analytics result completed_at must match the canonical submission run card")
        if self.prototype_notice != PROTOTYPE_NOTICE:
            raise ValueError("company analytics result must retain the canonical prototype notice")
        if self.non_executable is not True:
            raise ValueError("company analytics result must be non-executable")
        if not self.artifacts:
            raise ValueError("company analytics result requires completed artifact projections")
        artifact_ids = tuple(artifact.id for artifact in self.artifacts)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("company analytics result artifact IDs must be unique")
        artifact_kinds = tuple(artifact.kind for artifact in self.artifacts)
        if len(artifact_kinds) != 7 or len(set(artifact_kinds)) != 7 or set(artifact_kinds) != _REQUIRED_ARTIFACT_KINDS:
            raise ValueError("company analytics result requires exactly the seven canonical artifact kinds")
        if any(not warning for warning in self.warnings):
            raise ValueError("company analytics result warnings must be non-empty strings")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status.value,
            "profile": self.profile,
            "submission": self.submission.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "warnings": list(self.warnings),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "prototype_notice": self.prototype_notice,
            "non_executable": self.non_executable,
        }
        reject_secret_shaped_keys(payload)
        return payload

    @classmethod
    def from_dict(cls, value: object) -> CompanyAnalyticsResultV1:
        if not isinstance(value, Mapping):
            raise ValueError("CompanyAnalyticsResultV1 must be an object")
        payload = dict(value)
        reject_secret_shaped_keys(payload)
        unknown = sorted(set(payload) - _RESULT_FIELDS)
        missing = sorted(_RESULT_FIELDS - set(payload))
        if unknown or missing:
            raise ValueError(f"CompanyAnalyticsResultV1 fields mismatch; missing={missing}, unknown={unknown}")
        artifacts = payload["artifacts"]
        warnings = payload["warnings"]
        if not isinstance(artifacts, list | tuple):
            raise ValueError("CompanyAnalyticsResultV1.artifacts must be an array")
        if not isinstance(warnings, list | tuple) or any(not isinstance(item, str) for item in warnings):
            raise ValueError("CompanyAnalyticsResultV1.warnings must be an array of strings")
        try:
            status = RunStatus(payload["status"])
        except (TypeError, ValueError) as exc:
            raise ValueError("CompanyAnalyticsResultV1.status must be completed") from exc
        return cls(
            schema_version=payload["schema_version"],  # type: ignore[arg-type]
            run_id=payload["run_id"],  # type: ignore[arg-type]
            status=status,
            profile=payload["profile"],  # type: ignore[arg-type]
            submission=parse_company_analytics_submission_v1(payload["submission"]),
            artifacts=tuple(_artifact_from_dict(item) for item in artifacts),
            warnings=tuple(warnings),
            started_at=payload["started_at"],  # type: ignore[arg-type]
            completed_at=payload["completed_at"],  # type: ignore[arg-type]
            prototype_notice=payload["prototype_notice"],  # type: ignore[arg-type]
            non_executable=payload["non_executable"],  # type: ignore[arg-type]
        )


def parse_company_analytics_result_v1(value: object) -> CompanyAnalyticsResultV1:
    return value if isinstance(value, CompanyAnalyticsResultV1) else CompanyAnalyticsResultV1.from_dict(value)
