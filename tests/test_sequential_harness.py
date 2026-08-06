from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_lifecycle import STAGE_ENVELOPE_SCHEMA_VERSION, CompanyAnalyticsCoordinator
from stock_research_agents.conformance import evaluate_validation
from stock_research_agents.harness import run_sequential_company_lifecycle
from stock_research_agents.lifecycle import LifecycleStore
from stock_research_agents.lifecycle_profiles import CompanyAnalyticsLifecycleProfile
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore


class FakeAnalyticsLifecycleHarness:
    def __init__(self, submission: dict[str, object], *, interrupt_at: int | None = None) -> None:
        self.submission = submission
        self.interrupt_at = interrupt_at
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def execute_stage(
        self,
        stage: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((stage, context))
        if self.interrupt_at is not None and len(self.calls) == self.interrupt_at:
            raise RuntimeError("injected sequential interruption")
        output_refs = {
            ref: {
                "reference_id": f"host-ref-{hashlib.sha256(ref.encode()).hexdigest()[:16]}",
                "media_type": "application/json",
                "sha256": hashlib.sha256(f"output:{ref}".encode()).hexdigest(),
                "byte_length": 0,
                "summary": "Validated sequential analytics output retained by the host.",
            }
            for ref in stage["output_refs"]
        }
        if stage["id"] == "publish.completed":
            output_refs = {stage["output_refs"][0]: self.submission}
        return {
            "schema_version": STAGE_ENVELOPE_SCHEMA_VERSION,
            "stage_id": stage["id"],
            "output_refs": output_refs,
        }


def _analytics_coordinator(tmp_path: Path, name: str) -> CompanyAnalyticsCoordinator:
    return CompanyAnalyticsCoordinator(
        LifecycleStore(tmp_path / name / "lifecycle"),
        RunStore(tmp_path / name / "runs"),
        profile=CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / name / "quality")),
    )


def test_company_analytics_sequential_lifecycle_completes_all_26_stages_in_order(tmp_path: Path) -> None:
    submission = complete_analytics_submission("META")
    harness = FakeAnalyticsLifecycleHarness(submission)
    coordinator = CompanyAnalyticsCoordinator(
        LifecycleStore(tmp_path / "complete" / "lifecycle"),
        RunStore(tmp_path / "complete" / "runs"),
        profile=CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / "complete" / "quality")),
    )

    result, events = run_sequential_company_lifecycle(
        harness,
        request=submission["company_research"]["request"],  # type: ignore[index]
        coordinator=coordinator,
        research_pack_id="initiating-coverage.v1",
    )

    stage_ids = [stage["id"] for stage, _context in harness.calls]
    assert len(stage_ids) == 26
    assert stage_ids == [stage.stage_id for stage in result.submission.run_card.stages]
    assert stage_ids[0] == "research.plan"
    assert stage_ids[-1] == "publish.completed"
    for ordinal, (stage, context) in enumerate(harness.calls):
        assert set(context) == {
            "request",
            "prior_stage_outputs",
            "optional_past_context",
            "system_boundary",
            "research_pack_id",
            "execution_mode",
            "stage_output_contract",
        }
        assert [output["stage_id"] for output in context["prior_stage_outputs"]] == stage_ids[:ordinal]
        assert context["stage_output_contract"]["required_output_refs"] == stage["output_refs"]
    assert result.status.value == "completed"
    stage_events = [event for event in events if event.kind.value == "stage"]
    assert len(stage_events) == 26
    assert [event.stage_id for event in stage_events] == stage_ids
    assert all(event.status == "completed" for event in stage_events)
    assert evaluate_validation(result, events).passed is True


def test_company_analytics_sequential_lifecycle_resumes_at_first_incomplete_stage_equivalently(
    tmp_path: Path,
) -> None:
    submission = complete_analytics_submission("META")
    request = submission["company_research"]["request"]  # type: ignore[index]

    baseline_harness = FakeAnalyticsLifecycleHarness(submission)
    baseline_result, _ = run_sequential_company_lifecycle(
        baseline_harness,
        request=request,
        coordinator=_analytics_coordinator(tmp_path, "baseline"),
        research_pack_id="initiating-coverage.v1",
    )

    interrupted_coordinator = _analytics_coordinator(tmp_path, "resumed")
    control = interrupted_coordinator.create(
        request,
        research_pack_id="initiating-coverage.v1",
        decision_memory_enabled=False,
    )
    interrupted_harness = FakeAnalyticsLifecycleHarness(submission, interrupt_at=12)
    with pytest.raises(RuntimeError, match="injected sequential interruption"):
        run_sequential_company_lifecycle(
            interrupted_harness,
            run_id=control["run_id"],
            coordinator=interrupted_coordinator,
        )

    restarted_coordinator = _analytics_coordinator(tmp_path, "resumed")
    resumed_harness = FakeAnalyticsLifecycleHarness(submission)
    resumed_result, _ = run_sequential_company_lifecycle(
        resumed_harness,
        run_id=control["run_id"],
        coordinator=restarted_coordinator,
    )

    attempted_ids = [stage["id"] for stage, _context in interrupted_harness.calls]
    resumed_ids = [stage["id"] for stage, _context in resumed_harness.calls]
    baseline_ids = [stage["id"] for stage, _context in baseline_harness.calls]
    assert attempted_ids == baseline_ids[:12]
    assert resumed_ids == baseline_ids[11:]
    assert attempted_ids[:-1] + resumed_ids == baseline_ids
    assert resumed_result.submission == baseline_result.submission
    assert resumed_result.profile == baseline_result.profile == "company-analytics.v1"
    assert resumed_result.non_executable is baseline_result.non_executable is True
    assert [artifact.id for artifact in resumed_result.artifacts] == [
        artifact.id for artifact in baseline_result.artifacts
    ]
    assert restarted_coordinator.control(control["run_id"])["completed_stage_ids"] == baseline_ids


def test_primary_sequential_runner_is_part_of_the_public_python_api() -> None:
    import stock_research_agents

    assert stock_research_agents.run_sequential_company_lifecycle is run_sequential_company_lifecycle
