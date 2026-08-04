from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from company_analytics_fixtures import complete_v4_submission

from tradingagents_portable.company_lifecycle import STAGE_ENVELOPE_SCHEMA_VERSION, CompanyResearchCoordinator
from tradingagents_portable.contracts import RunRequest, StageKind, StageSpec
from tradingagents_portable.harness import run_sequential_company_lifecycle, run_sequential_host_workflow
from tradingagents_portable.lifecycle import LifecycleStore
from tradingagents_portable.lifecycle_profiles import CompanyAnalyticsLifecycleProfile
from tradingagents_portable.research_quality_v1 import QualityStore
from tradingagents_portable.store import RunStore


class FakeGenericHarness:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.context_keys: dict[str, set[str]] = {}
        self.instructions: dict[str, str] = {}

    def execute_stage(
        self,
        stage: StageSpec,
        instructions: str,
        context: dict[str, Any],
        allowed_tools: tuple[str, ...],
    ) -> dict[str, Any]:
        self.calls.append((stage.id, allowed_tools))
        self.context_keys[stage.id] = set(context)
        self.instructions[stage.id] = instructions
        request = context["request"]
        evidence_id = f"ev-{stage.id.removeprefix('analyst.')}"
        if stage.kind is StageKind.ANALYST:
            analyst = stage.id.removeprefix("analyst.")
            return {
                "company_of_interest": f"{request['symbol']} Test Company",
                "instrument_context": "Public company research fixture from a generic sequential harness.",
                "evidence": [
                    {
                        "id": evidence_id,
                        "category": analyst,
                        "title": f"{analyst} source",
                        "summary": f"Bounded {analyst} evidence.",
                        "values": {"available": True},
                        "provenance": {
                            "provider": "public-test-source",
                            "source_type": "primary_document",
                            "source_uri": f"https://example.com/{request['symbol']}/{analyst}",
                            "retrieved_at": "2026-08-02T12:00:00+00:00",
                            "source_date": "2026-08-01",
                        },
                        "limitations": ["Conformance fixture, not market research."],
                    }
                ],
                "report": {
                    "thesis": f"{analyst} thesis in {request['output_language']}",
                    "evidence_ids": [evidence_id],
                    "confidence": 0.6,
                    "content": f"Complete {analyst} conformance report.",
                },
            }
        if stage.kind is StageKind.RESEARCH_DEBATE:
            return {"position": f"{stage.role} case.", "evidence_ids": ["ev-market"]}
        if stage.kind is StageKind.RESEARCH_MANAGER:
            return {
                "recommendation": "Hold",
                "rationale": "Balanced conformance synthesis.",
                "strategic_actions": "Wait for additional verified evidence.",
                "confidence": 0.6,
            }
        if stage.kind is StageKind.TRADER:
            return {
                "action": "Hold",
                "reasoning": "Non-executable conformance stance.",
                "entry_price": 100.0,
                "stop_loss": 90.0,
                "position_sizing": "At most 1%.",
                "executable": False,
                "execution_authority": "none",
                "submitted": False,
                "caveats": ["No order."],
            }
        if stage.kind is StageKind.RISK_DEBATE:
            return {"position": f"{stage.role} risk view.", "evidence_ids": ["ev-market"]}
        return {
            "risk_decision": {
                "risk_level": "moderate",
                "constraints": ["No order execution."],
                "unresolved": ["Future results."],
            },
            "portfolio_decision": {
                "rating": "Hold",
                "executive_summary": "Hold as a research conclusion only.",
                "investment_thesis": "The verified evidence is balanced.",
                "price_target": 110.0,
                "time_horizon": "12 months",
                "executable": False,
                "execution_authority": "none",
                "submitted": False,
            },
            "final_trade_decision": "Rating: Hold\nResearch-only conformance result.",
            "warnings": ["Generic sequential harness conformance fixture."],
        }


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


def _analytics_coordinator(tmp_path: Path, name: str) -> CompanyResearchCoordinator:
    return CompanyResearchCoordinator(
        LifecycleStore(tmp_path / name / "lifecycle"),
        RunStore(tmp_path / name / "runs"),
        profile=CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / name / "quality")),
    )


@pytest.mark.parametrize("symbol", ["MSFT", "0700.HK"])
def test_generic_sequential_harness_completes_every_stage_for_arbitrary_companies(symbol: str) -> None:
    harness = FakeGenericHarness()
    result, events = run_sequential_host_workflow(
        RunRequest(
            symbol=symbol,
            as_of_date="2026-08-01",
            output_language="Japanese",
            executor="host_native",
        ),
        harness,
        store=RunStore(),
    )

    assert result.request.symbol == symbol
    assert result.request.output_language == "Japanese"
    assert len(harness.calls) == 12
    assert harness.calls[0][0] == "analyst.market"
    assert harness.calls[0][1] == ("market.price_history", "market.indicators", "market.verified_snapshot")
    assert harness.calls[-1] == ("portfolio", ())
    assert harness.context_keys["analyst.market"] == {"request", "instrument_identity"}
    assert harness.context_keys["research.1.bull"] == {
        "request",
        "evidence",
        "analyst_reports",
        "research_debate_so_far",
    }
    assert harness.instructions["portfolio"]
    assert len(result.analyst_reports) == 4
    assert len(result.research_debate) == 2
    assert len(result.risk_debate) == 3
    assert result.research_decision.strategic_actions == "Wait for additional verified evidence."
    assert result.trader_decision.entry_price == 100.0
    assert result.trader_decision.stop_loss == 90.0
    assert result.trader_decision.position_sizing == "At most 1%."
    assert result.trader_decision.execution_authority == "none"
    assert result.trader_decision.submitted is False
    assert result.portfolio_decision.rating == "hold"
    assert result.portfolio_decision.investment_thesis == "The verified evidence is balanced."
    assert result.portfolio_decision.price_target == 110.0
    assert result.portfolio_decision.time_horizon == "12 months"
    assert result.portfolio_decision.execution_authority == "none"
    assert result.portfolio_decision.submitted is False
    assert result.final_trade_decision == "Rating: Hold\nResearch-only conformance result."
    assert len([event for event in events if event.kind.value == "stage"]) == 12
    assert events[0].status == "running"
    assert events[-1].status == "completed"


@pytest.mark.parametrize(
    ("run_request", "expected_reports", "expected_research", "expected_risk", "expected_stages"),
    [
        (
            RunRequest(
                symbol="MSFT",
                as_of_date="2026-08-01",
                analysts=("market", "news"),
                debate_rounds=2,
                risk_rounds=2,
                executor="host_native",
            ),
            2,
            4,
            6,
            15,
        ),
        (
            RunRequest(
                symbol="BTC-USD",
                as_of_date="2026-08-01",
                asset_type="crypto",
                analysts=("market", "social", "news", "fundamentals"),
                executor="host_native",
            ),
            3,
            2,
            3,
            11,
        ),
    ],
)
def test_sequential_fallback_supports_rounds_reduced_analysts_and_crypto(
    run_request: RunRequest,
    expected_reports: int,
    expected_research: int,
    expected_risk: int,
    expected_stages: int,
) -> None:
    harness = FakeGenericHarness()

    result, _events = run_sequential_host_workflow(run_request, harness, store=RunStore())

    assert len(result.analyst_reports) == expected_reports
    assert len(result.research_debate) == expected_research
    assert len(result.risk_debate) == expected_risk
    assert len(harness.calls) == expected_stages
    if run_request.asset_type == "crypto":
        assert all(report.analyst != "fundamentals" for report in result.analyst_reports)


def test_company_analytics_sequential_lifecycle_completes_all_26_stages_in_order(tmp_path: Path) -> None:
    submission = complete_v4_submission("META")
    harness = FakeAnalyticsLifecycleHarness(submission)
    profile = CompanyAnalyticsLifecycleProfile(QualityStore(tmp_path / "complete" / "quality"))

    result, events = run_sequential_company_lifecycle(
        harness,
        request=submission["company_research"]["request"],  # type: ignore[index]
        profile=profile,
        research_pack_id="initiating-coverage.v1",
    )

    stage_ids = [stage["id"] for stage, _context in harness.calls]
    assert len(stage_ids) == 26
    assert stage_ids == [stage.id for stage in result.topology.stages]
    assert stage_ids[0] == "research.plan"
    assert stage_ids[-1] == "publish.completed"
    for ordinal, (stage, context) in enumerate(harness.calls):
        assert set(context) == {
            "request",
            "prior_stage_outputs",
            "optional_past_context",
            "portable_boundary",
            "research_pack_id",
            "execution_mode",
            "stage_output_contract",
        }
        assert [output["stage_id"] for output in context["prior_stage_outputs"]] == stage_ids[:ordinal]
        assert context["stage_output_contract"]["required_output_refs"] == stage["output_refs"]
    assert result.status.value == "completed"
    assert len([event for event in events if event.kind.value == "stage" and event.status == "committed"]) == 26
    terminal_commit = next(
        event for event in events if event.stage_id == "publish.completed" and event.status == "committed"
    )
    assert terminal_commit.data["output_content_verified"] is True


def test_company_analytics_sequential_lifecycle_resumes_at_first_incomplete_stage_equivalently(
    tmp_path: Path,
) -> None:
    submission = complete_v4_submission("META")
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
    assert resumed_result.request == baseline_result.request
    assert resumed_result.instrument == baseline_result.instrument
    assert resumed_result.topology == baseline_result.topology
    assert resumed_result.report_sections == baseline_result.report_sections
    assert [artifact.id for artifact in resumed_result.artifacts] == [
        artifact.id for artifact in baseline_result.artifacts
    ]
    assert restarted_coordinator.control(control["run_id"])["completed_stage_ids"] == baseline_ids


def test_primary_sequential_runner_is_part_of_the_public_python_api() -> None:
    import tradingagents_portable

    assert tradingagents_portable.run_sequential_company_lifecycle is run_sequential_company_lifecycle
