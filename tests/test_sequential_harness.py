from __future__ import annotations

from typing import Any

import pytest

from tradingrearchagents.contracts import RunRequest, StageKind, StageSpec
from tradingrearchagents.harness import run_sequential_host_workflow
from tradingrearchagents.store import RunStore


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
