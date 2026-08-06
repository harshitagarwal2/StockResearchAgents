from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import prepare_company_analytics, submit_company_analytics
from stock_research_agents.company_analytics_v1 import (
    CompanyAnalyticsResultV1,
    CompanyAnalyticsSubmissionV1,
    canonical_stage_ids,
)
from stock_research_agents.company_analytics_v1.contracts import analytics_run_id
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore


def test_analytics_round_trip_preserves_base_research_and_publishes_all_sidecars() -> None:
    payload = complete_analytics_submission("META")
    parsed = CompanyAnalyticsSubmissionV1.from_dict(payload)
    base_research = parsed.company_research.to_dict()

    result, events = submit_company_analytics(payload, store=RunStore(), quality_store=QualityStore())

    assert parsed.to_dict()["company_research"] == base_research
    assert result.status.value == "completed"
    kinds = {artifact.kind for artifact in result.artifacts}
    assert {
        "research_dossier.v1",
        "analytics_bundle.v1",
        "run_card.v1",
        "hypothesis_ledger.v1",
        "research_iterations.v1",
        "research_quality.v1",
        "forecast_set.v1",
    } <= kinds
    assert isinstance(result, CompanyAnalyticsResultV1)
    assert result.schema_version == "company-analytics-result.v1"
    assert result.profile == "company-analytics.v1"
    assert tuple(stage.stage_id for stage in result.submission.run_card.stages) == canonical_stage_ids()
    assert result.submission.run_card.stages[-1].stage_id == "publish.completed"
    assert result.non_executable is True
    assert {
        "request",
        "topology",
        "execution_config",
        "analyst_reports",
        "trader_decision",
        "portfolio_decision",
    }.isdisjoint(result.to_dict())
    assert events[-1].status == "completed"


def test_analytics_run_id_hashes_forecast_content_from_the_full_outer_submission() -> None:
    payload = complete_analytics_submission("META")
    changed = deepcopy(payload)
    changed["forecasts"][0]["probability"] = 0.55  # type: ignore[index]

    assert analytics_run_id(payload) != analytics_run_id(changed)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_submission_requires_exactly_seven_unique_canonical_artifact_kinds(mutation: str) -> None:
    payload = complete_analytics_submission("META")
    kinds = list(payload["run_card"]["artifact_kinds"])  # type: ignore[index]
    if mutation == "missing":
        kinds.remove("research_iterations.v1")
    elif mutation == "extra":
        kinds.append("other.v1")
    else:
        kinds[-1] = kinds[0]
    payload["run_card"]["artifact_kinds"] = kinds  # type: ignore[index]

    with pytest.raises(ValueError, match="artifact"):
        CompanyAnalyticsSubmissionV1.from_dict(payload)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_result_requires_exactly_seven_unique_canonical_artifact_kinds(mutation: str) -> None:
    result, _ = submit_company_analytics(
        complete_analytics_submission("META"), store=RunStore(), quality_store=QualityStore()
    )
    artifacts = list(result.artifacts)
    if mutation == "missing":
        artifacts = [artifact for artifact in artifacts if artifact.kind != "research_iterations.v1"]
    elif mutation == "extra":
        artifacts.append(replace(artifacts[0], id="extra", kind="other.v1"))
    else:
        artifacts[-1] = replace(artifacts[-1], kind=artifacts[0].kind)

    with pytest.raises(ValueError, match="exactly the seven canonical artifact kinds"):
        replace(result, artifacts=tuple(artifacts))


@pytest.mark.parametrize(
    "path",
    [
        ("analytics_bundle", "run_id"),
        ("run_card", "run_id"),
        ("hypothesis_ledgers", 0, "run_id"),
        ("research_iterations", 0, "run_id"),
        ("quality_receipt", "run_id"),
    ],
)
def test_submission_rejects_each_nested_run_id_that_differs_from_canonical(path: tuple[object, ...]) -> None:
    payload = complete_analytics_submission("META")
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = "analytics-other"  # type: ignore[index]

    with pytest.raises(ValueError, match="derived research run_id"):
        CompanyAnalyticsSubmissionV1.from_dict(payload)


def test_submission_rejects_forecast_run_id_that_differs_from_canonical() -> None:
    payload = complete_analytics_submission("META")
    forecast = payload["forecasts"][0]  # type: ignore[index]
    forecast["run_id"] = "analytics-other"  # type: ignore[index]
    forecast["forecast_id"] = "analytics-other.forecast.meta.primary"  # type: ignore[index]

    with pytest.raises(ValueError, match="forecast must bind to the derived research run_id"):
        CompanyAnalyticsSubmissionV1.from_dict(payload)


def test_analytics_publication_is_idempotent_and_rejects_conflicting_sidecars() -> None:
    store = RunStore()
    quality_store = QualityStore()
    payload = complete_analytics_submission("ORCL")
    first, _ = submit_company_analytics(payload, store=store, quality_store=quality_store)
    second, _ = submit_company_analytics(payload, store=store, quality_store=quality_store)
    assert first == second

    changed = deepcopy(payload)
    changed["analytics_bundle"]["limitations"] = ["New limitation added after publication."]  # type: ignore[index]
    with pytest.raises(ValueError, match="different publication"):
        submit_company_analytics(changed, store=store, quality_store=quality_store)


def test_prepare_exposes_research_packs_capability_modes_and_no_credentials() -> None:
    payload = complete_analytics_submission("META")["company_research"]
    plan = prepare_company_analytics(payload["request"])  # type: ignore[index]

    assert plan["workflow_profile"] == "company-analytics.v1"
    assert plan["execution_mode"] == "sequential"
    assert plan["execution_mode_readiness"] == "executor_required"
    assert plan["execution_mode_locally_ready"] is False
    assert len(plan["stages"]) == 26
    assert plan["fallback"] == "sequential"
    assert set(plan["capability_negotiation"]) >= {"native", "sequential", "import"}
    assert plan["capability_negotiation"]["sequential"]["readiness"] == "executor_required"
    assert plan["capability_negotiation"]["sequential"]["locally_ready"] is False
    assert plan["capability_negotiation"]["native"]["implementation"] == "runtime_adapter_contract"
    assert plan["capability_negotiation"]["native"]["readiness"] == "adapter_required"
    assert plan["capability_negotiation"]["native"]["locally_ready"] is False
    assert plan["capability_negotiation"]["import"]["readiness"] == "partial_adapter_required"
    assert plan["capability_negotiation"]["import"]["locally_ready"] is False
    assert plan["external_model_api_keys_accepted"] is False

    native = prepare_company_analytics(payload["request"], execution_mode="native")  # type: ignore[index]
    assert native["execution_mode_readiness"] == "adapter_required"
    assert native["execution_mode_locally_ready"] is False
    imported = prepare_company_analytics(payload["request"], execution_mode="import")  # type: ignore[index]
    assert imported["execution_mode_readiness"] == "partial_adapter_required"
    assert imported["execution_mode_locally_ready"] is False


def test_completed_analytics_requires_exact_ordered_canonical_stage_receipts() -> None:
    payload = complete_analytics_submission("META")
    assert len(payload["run_card"]["stages"]) == 26  # type: ignore[index]

    one_stage = deepcopy(payload)
    one_stage["run_card"]["stages"] = one_stage["run_card"]["stages"][-1:]  # type: ignore[index]
    one_stage["quality_receipt"]["stage_digests"] = one_stage["quality_receipt"]["stage_digests"][-1:]  # type: ignore[index]
    with pytest.raises(ValueError, match="exact ordered 26-stage"):
        CompanyAnalyticsSubmissionV1.from_dict(one_stage)

    reordered = deepcopy(payload)
    stages = reordered["run_card"]["stages"]  # type: ignore[index]
    reordered["run_card"]["stages"] = (stages[1], stages[0], *stages[2:])  # type: ignore[index]
    with pytest.raises(ValueError, match="exact ordered 26-stage"):
        CompanyAnalyticsSubmissionV1.from_dict(reordered)


def test_analytics_strictly_rejects_unknown_and_cross_run_fields() -> None:
    payload = complete_analytics_submission("META")
    payload["provider_api_key"] = "forbidden"
    with pytest.raises(ValueError, match="credential-shaped"):
        CompanyAnalyticsSubmissionV1.from_dict(payload)

    payload = complete_analytics_submission("META")
    payload["run_card"]["run_id"] = "host-other"  # type: ignore[index]
    with pytest.raises(ValueError, match="derived research run_id"):
        CompanyAnalyticsSubmissionV1.from_dict(payload)


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        (("source_lineage", "bindings", 0, "source_batch_id"), "detached-batch", "run-card source_batch_ids"),
        (("source_lineage", "bindings", 0, "dossier_document_id"), "missing-doc", "every dossier document"),
        (("source_lineage", "bindings", 0, "canonical_uri"), "https://example.test/other", "canonical URI"),
        (("source_lineage", "bindings", 0, "content_sha256"), "0" * 64, "content digest"),
        (("source_lineage", "bindings", 0, "analytics_source_id"), "detached-source", "analytics source ID"),
        (("source_lineage", "bindings", 0, "terms_uri"), "https://example.test/terms", "terms URI"),
    ],
)
def test_analytics_source_lineage_rejects_detached_identity_and_entitlement(
    path: tuple[object, ...], replacement: object, message: str
) -> None:
    payload = complete_analytics_submission("META")
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    with pytest.raises(ValueError, match=message):
        CompanyAnalyticsSubmissionV1.from_dict(payload)


def test_analytics_source_lineage_preserves_exact_terminal_stage_binding() -> None:
    parsed = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("META"))
    assert tuple(stage.stage_id for stage in parsed.run_card.stages) == canonical_stage_ids()
    assert len(parsed.run_card.stages) == 26
