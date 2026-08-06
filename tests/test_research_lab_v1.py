from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from stock_research_agents.research_lab_v1 import (
    Hypothesis,
    HypothesisLedger,
    HypothesisTransition,
    RunCardV1,
    StageReceipt,
    get_research_pack,
    research_pack_catalog,
)


def _stage(status: str = "completed") -> StageReceipt:
    return StageReceipt(
        stage_id="resolve.identity",
        status=status,  # type: ignore[arg-type]
        started_at="2026-08-01T12:00:00+00:00",
        completed_at="2026-08-01T12:01:00+00:00",
        input_digest="a" * 64,
        output_digest="b" * 64 if status == "completed" else None,
        attempts=1,
        limitation=None if status == "completed" else "Source was not licensed for machine use.",
    )


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        hypothesis_id="hypothesis.margin-expansion",
        statement="Operating margin expands as infrastructure utilization improves.",
        falsification_criteria="Two reported quarters show lower utilization and contracting margin.",
        expected_observation="Operating margin improves by at least 100 basis points.",
        horizon_at="2027-08-01T00:00:00+00:00",
        created_at="2026-08-01T12:00:00+00:00",
        evidence_ids=("filing.2026q2",),
        related_hypothesis_ids=(),
    )


def test_pack_catalog_exposes_complete_repeatable_workflows() -> None:
    catalog = research_pack_catalog()

    assert len(catalog) == 8
    assert get_research_pack("initiating-coverage.v1").history_policy == "structural"
    assert all(item["output_artifact_kinds"] for item in catalog)


def test_run_card_is_complete_immutable_and_digestible() -> None:
    card = RunCardV1(
        run_id="host-meta-analytics",
        profile="company-analytics.v1",
        research_pack_id="initiating-coverage.v1",
        submission_digest="a" * 64,
        workflow_digest="b" * 64,
        executor_runtime="codex-app",
        execution_mode="sequential",
        started_at="2026-08-01T12:00:00+00:00",
        completed_at="2026-08-01T13:00:00+00:00",
        stages=(_stage(),),
        source_batch_ids=("batch.sec",),
        artifact_kinds=("research_dossier.v1", "run_card.v1"),
        limitations=(),
        complete=True,
    )

    assert len(card.digest()) == 64
    assert card.to_dict()["executor_runtime"] == "codex-app"
    assert "harness" not in card.to_dict()
    with pytest.raises(ValueError, match="unique"):
        replace(card, stages=(_stage(), _stage()))
    with pytest.raises(ValueError, match="source batch IDs must be unique"):
        replace(card, source_batch_ids=("batch.sec", "batch.sec"))


def test_run_card_schema_rejects_duplicate_source_batch_ids() -> None:
    schema_path = (
        Path(__file__).parents[1] / "src" / "stock_research_agents" / "workflow" / "research-lab.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    run_card_schema = {"$schema": schema["$schema"], "$ref": "#/$defs/runCard", "$defs": schema["$defs"]}
    card = RunCardV1(
        run_id="host-meta-analytics",
        profile="company-analytics.v1",
        research_pack_id="initiating-coverage.v1",
        submission_digest="a" * 64,
        workflow_digest="b" * 64,
        executor_runtime="codex-app",
        execution_mode="sequential",
        started_at="2026-08-01T12:00:00+00:00",
        completed_at="2026-08-01T13:00:00+00:00",
        stages=(_stage(),),
        source_batch_ids=("batch.sec",),
        artifact_kinds=("run_card.v1",),
        limitations=(),
        complete=True,
    ).to_dict()
    card["source_batch_ids"] = ["batch.sec", "batch.sec"]

    assert list(Draft202012Validator(run_card_schema).iter_errors(card))


def test_hypothesis_ledger_enforces_append_only_chronological_transitions() -> None:
    hypothesis = _hypothesis()
    proposed = HypothesisTransition(
        transition_id="transition.1",
        hypothesis_id=hypothesis.hypothesis_id,
        from_status=None,
        to_status="proposed",
        changed_at="2026-08-01T12:00:00+00:00",
        reason="Initial hypothesis registered before synthesis.",
        evidence_ids=(),
    )
    supported = HypothesisTransition(
        transition_id="transition.2",
        hypothesis_id=hypothesis.hypothesis_id,
        from_status="proposed",
        to_status="supported",
        changed_at="2026-08-01T12:30:00+00:00",
        reason="Reported utilization and margin both improved.",
        evidence_ids=("filing.2026q2",),
    )

    ledger = HypothesisLedger("host-meta", hypothesis, (proposed, supported), "supported")
    assert ledger.final_status == "supported"
    with pytest.raises(ValueError, match="append-only"):
        HypothesisLedger("host-meta", hypothesis, (supported,), "supported")


def test_blocked_stage_requires_a_limitation_and_no_output_digest() -> None:
    assert _stage("blocked").limitation
    with pytest.raises(ValueError, match="limitation"):
        replace(_stage("blocked"), limitation=None)
