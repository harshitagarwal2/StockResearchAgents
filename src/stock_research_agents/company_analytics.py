"""Public prepare/import APIs for the harness-neutral analytics profile."""

from __future__ import annotations

from collections.abc import Mapping

from .application_ports import QualitySidecarPort, ResultPublicationPort
from .company_analytics_v1 import CompanyAnalyticsResultV1, CompanyAnalyticsV1Provider
from .contracts import RunEvent
from .profiles import ProfileRegistry
from .publication import PublicationDraft, PublicationService
from .research_contracts import CompanyResearchRequest
from .research_lab_v1 import research_pack_catalog
from .research_quality_v1 import (
    QUALITY_STORE,
    Forecast,
    OutcomeLedger,
    OutcomeObservation,
    ResearchQualityReceipt,
    score_forecast,
)
from .store import RUN_STORE

_PROVIDER = CompanyAnalyticsV1Provider()
PROFILE_REGISTRY = ProfileRegistry((_PROVIDER,))


class AnalyticsPublicationService:
    """Coordinate recoverable result and quality-index publication."""

    def publish(
        self,
        submission: object,
        draft: PublicationDraft,
        *,
        store: ResultPublicationPort,
        quality_store: QualitySidecarPort,
    ) -> CompanyAnalyticsResultV1:
        parsed = _PROVIDER.parse_submission(submission)
        quality_store.stage_registration(parsed.quality_receipt, parsed.forecasts)
        result = PublicationService().publish(draft, store)
        if not isinstance(result, CompanyAnalyticsResultV1):
            raise TypeError("company analytics publication returned an incompatible stored result")
        quality_store.publish_registration(parsed.quality_receipt.run_id)
        return result


def prepare_company_analytics(
    value: CompanyResearchRequest | Mapping[str, object],
    *,
    research_pack_id: str = "initiating-coverage.v1",
    execution_mode: str = "sequential",
) -> dict[str, object]:
    """Return a caller-executable plan; StockResearchAgents performs no retrieval."""
    request = value if isinstance(value, CompanyResearchRequest) else CompanyResearchRequest.from_dict(value)
    manifest = _PROVIDER.load_manifest()
    packs = {item["pack_id"]: item for item in research_pack_catalog()}
    if research_pack_id not in packs:
        raise ValueError(f"unknown research_pack_id: {research_pack_id}")
    negotiation = manifest["capability_negotiation"]
    if not isinstance(negotiation, Mapping) or execution_mode not in {"native", "sequential", "import"}:
        raise ValueError("execution_mode must be one of: native, sequential, import")
    mode_contract = negotiation[execution_mode]
    if not isinstance(mode_contract, Mapping):
        raise ValueError(f"invalid capability negotiation contract for {execution_mode}")
    return {
        "ok": True,
        "workflow_profile": _PROVIDER.descriptor.profile,
        "workflow_id": _PROVIDER.descriptor.workflow_id,
        "request": request.to_dict(),
        "research_pack": packs[research_pack_id],
        "research_pack_catalog": tuple(packs.values()),
        "execution_mode": execution_mode,
        "execution_mode_readiness": mode_contract["readiness"],
        "execution_mode_locally_ready": mode_contract["locally_ready"],
        "execution_contract": manifest["execution_contract"],
        "stages": manifest["stages"],
        "routing_semantics": manifest["routing_semantics"],
        "capability_negotiation": manifest["capability_negotiation"],
        "history_policy": manifest["history_policy"],
        "system_boundary": manifest["system_boundary"],
        "fallback": manifest["fallback"],
        "terminal_artifact_kinds": manifest["terminal_artifact_kinds"],
        "submission_schema": _PROVIDER.load_schema(),
        "execution_owner": "caller",
        "external_model_api_keys_accepted": False,
        "publication": "atomic_after_complete_validation",
    }


def build_company_analytics_draft(payload: object) -> PublicationDraft:
    submission = _PROVIDER.parse_submission(payload)
    return _PROVIDER.build_publication(submission)


def submit_company_analytics(
    payload: object,
    *,
    store: ResultPublicationPort = RUN_STORE,
    quality_store: QualitySidecarPort = QUALITY_STORE,
) -> tuple[CompanyAnalyticsResultV1, tuple[RunEvent, ...]]:
    """Validate and atomically publish one completed analytics bundle."""
    submission = _PROVIDER.parse_submission(payload)
    draft = _PROVIDER.build_publication(submission)
    result = AnalyticsPublicationService().publish(
        submission,
        draft,
        store=store,
        quality_store=quality_store,
    )
    return result, draft.events


def record_company_forecast_outcome(
    payload: object,
    *,
    quality_store: QualitySidecarPort = QUALITY_STORE,
) -> dict[str, object]:
    """Append one outcome/correction and return its deterministic scorecard."""
    observation = payload if isinstance(payload, OutcomeObservation) else OutcomeObservation.from_dict(payload)
    scorecard = quality_store.append_outcome(observation)
    return {"ok": True, "outcome": observation.to_dict(), "scorecard": scorecard.to_dict()}


def get_company_research_quality(
    run_id: str,
    *,
    quality_store: QualitySidecarPort = QUALITY_STORE,
    run_store: ResultPublicationPort = RUN_STORE,
) -> dict[str, object]:
    """Return the immutable forecast registration, outcome ledgers, and scorecards."""
    quality_run_id = run_id
    projection = quality_store.projection(quality_run_id)
    if projection is None:
        result = run_store.get_result(run_id)
        if result is not None:
            recovered = _quality_projection_from_completed_artifacts(result)
            if recovered is not None:
                quality_run_id, ephemeral_projection = recovered
                projection = quality_store.projection(quality_run_id) or ephemeral_projection
    if projection is None:
        raise KeyError(f"research quality run not found: {run_id}")
    return {
        "ok": True,
        "run_id": run_id,
        "quality_run_id": quality_run_id,
        "research_quality": projection,
    }


def quality_projection_for_result(
    result: CompanyAnalyticsResultV1,
    *,
    quality_store: QualitySidecarPort = QUALITY_STORE,
) -> Mapping[str, object] | None:
    """Resolve lifecycle aliases to the immutable quality sidecar run ID."""
    direct = quality_store.projection(result.run_id)
    if direct is not None:
        return direct
    recovered = _quality_projection_from_completed_artifacts(result)
    if recovered is None:
        return None
    quality_run_id, ephemeral_projection = recovered
    return quality_store.projection(quality_run_id) or ephemeral_projection


def _quality_projection_from_completed_artifacts(
    result: CompanyAnalyticsResultV1,
) -> tuple[str, dict[str, object]] | None:
    """Build a read-only quality projection from authoritative completed artifacts."""
    receipt_artifact = next((item for item in result.artifacts if item.kind == "research_quality.v1"), None)
    forecast_artifact = next((item for item in result.artifacts if item.kind == "forecast_set.v1"), None)
    if receipt_artifact is None or forecast_artifact is None:
        return None
    if not isinstance(receipt_artifact.content, Mapping) or not isinstance(forecast_artifact.content, list | tuple):
        return None
    receipt = ResearchQualityReceipt.from_dict(receipt_artifact.content)
    forecasts = tuple(Forecast.from_dict(item) for item in forecast_artifact.content)
    ledgers = tuple(OutcomeLedger("research-quality.v1", forecast.forecast_id, ()) for forecast in forecasts)
    return receipt.run_id, {
        "receipt": receipt.to_dict(),
        "forecasts": [forecast.to_dict() for forecast in forecasts],
        "outcome_ledgers": [ledger.to_dict() for ledger in ledgers],
        "scorecards": [
            score_forecast(forecast, ledger).to_dict() for forecast, ledger in zip(forecasts, ledgers, strict=True)
        ],
        "complete": True,
    }
