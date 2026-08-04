from __future__ import annotations

from copy import deepcopy

import pytest
from company_analytics_fixtures import complete_v4_submission

from tradingagents_portable.company_analytics import prepare_company_analytics, submit_company_analytics
from tradingagents_portable.company_analytics_v1 import HostSubmissionV4, canonical_stage_ids
from tradingagents_portable.research_quality_v1 import QualityStore
from tradingagents_portable.store import RunStore


def test_v4_round_trip_preserves_frozen_v3_and_publishes_all_sidecars() -> None:
    payload = complete_v4_submission("META")
    parsed = HostSubmissionV4.from_dict(payload)
    frozen_v3 = parsed.company_research.to_dict()

    result, events = submit_company_analytics(payload, store=RunStore(), quality_store=QualityStore())

    assert parsed.to_dict()["company_research"] == frozen_v3
    assert result.status.value == "completed"
    kinds = {artifact.kind for artifact in result.artifacts}
    assert {
        "research_dossier.v3",
        "analytics_bundle.v1",
        "run_card.v1",
        "hypothesis_ledger.v1",
        "research_iterations.v1",
        "research_quality.v1",
        "forecast_set.v1",
    } <= kinds
    assert result.topology.name == "tradingagents.company-analytics.v1"
    assert result.topology.terminal_stage == "publish.completed"
    assert events[-1].status == "completed"


def test_v4_publication_is_idempotent_and_rejects_conflicting_sidecars() -> None:
    store = RunStore()
    quality_store = QualityStore()
    payload = complete_v4_submission("ORCL")
    first, _ = submit_company_analytics(payload, store=store, quality_store=quality_store)
    second, _ = submit_company_analytics(payload, store=store, quality_store=quality_store)
    assert first == second

    changed = deepcopy(payload)
    changed["analytics_bundle"]["limitations"] = ["New limitation added after publication."]  # type: ignore[index]
    with pytest.raises(ValueError, match="different publication"):
        submit_company_analytics(changed, store=store, quality_store=quality_store)


def test_prepare_exposes_research_packs_capability_modes_and_no_credentials() -> None:
    payload = complete_v4_submission("META")["company_research"]
    plan = prepare_company_analytics(payload["request"])  # type: ignore[index]

    assert plan["workflow_profile"] == "company-analytics.v1"
    assert plan["execution_mode"] == "compatible"
    assert plan["execution_mode_readiness"] == "locally_ready"
    assert plan["execution_mode_locally_ready"] is True
    assert len(plan["stages"]) == 26
    assert plan["fallback"] == "sequential"
    assert set(plan["capability_negotiation"]) >= {"full", "compatible", "tools_only"}
    assert plan["capability_negotiation"]["compatible"]["readiness"] == "locally_ready"
    assert plan["capability_negotiation"]["compatible"]["locally_ready"] is True
    assert plan["capability_negotiation"]["full"]["readiness"] == "adapter_required"
    assert plan["capability_negotiation"]["full"]["locally_ready"] is False
    assert plan["capability_negotiation"]["tools_only"]["readiness"] == "partial_adapter_required"
    assert plan["capability_negotiation"]["tools_only"]["locally_ready"] is False
    assert plan["external_model_api_keys_accepted"] is False

    full = prepare_company_analytics(payload["request"], execution_mode="full")  # type: ignore[index]
    assert full["execution_mode_readiness"] == "adapter_required"
    assert full["execution_mode_locally_ready"] is False
    tools = prepare_company_analytics(payload["request"], execution_mode="tools_only")  # type: ignore[index]
    assert tools["execution_mode_readiness"] == "partial_adapter_required"
    assert tools["execution_mode_locally_ready"] is False


def test_completed_v4_requires_exact_ordered_canonical_stage_receipts() -> None:
    payload = complete_v4_submission("META")
    assert len(payload["run_card"]["stages"]) == 26  # type: ignore[index]

    one_stage = deepcopy(payload)
    one_stage["run_card"]["stages"] = one_stage["run_card"]["stages"][-1:]  # type: ignore[index]
    one_stage["quality_receipt"]["stage_digests"] = one_stage["quality_receipt"]["stage_digests"][-1:]  # type: ignore[index]
    with pytest.raises(ValueError, match="exact ordered 26-stage"):
        HostSubmissionV4.from_dict(one_stage)

    reordered = deepcopy(payload)
    stages = reordered["run_card"]["stages"]  # type: ignore[index]
    reordered["run_card"]["stages"] = (stages[1], stages[0], *stages[2:])  # type: ignore[index]
    with pytest.raises(ValueError, match="exact ordered 26-stage"):
        HostSubmissionV4.from_dict(reordered)


def test_v4_strictly_rejects_unknown_and_cross_run_fields() -> None:
    payload = complete_v4_submission("META")
    payload["provider_api_key"] = "forbidden"
    with pytest.raises(ValueError, match="credential-shaped"):
        HostSubmissionV4.from_dict(payload)

    payload = complete_v4_submission("META")
    payload["run_card"]["run_id"] = "host-other"  # type: ignore[index]
    with pytest.raises(ValueError, match="derived v3 run_id"):
        HostSubmissionV4.from_dict(payload)


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
def test_v4_source_lineage_rejects_detached_identity_and_entitlement(
    path: tuple[object, ...], replacement: object, message: str
) -> None:
    payload = complete_v4_submission("META")
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    with pytest.raises(ValueError, match=message):
        HostSubmissionV4.from_dict(payload)


def test_v4_source_lineage_preserves_exact_terminal_stage_binding() -> None:
    parsed = HostSubmissionV4.from_dict(complete_v4_submission("META"))
    assert tuple(stage.stage_id for stage in parsed.run_card.stages) == canonical_stage_ids()
    assert len(parsed.run_card.stages) == 26
