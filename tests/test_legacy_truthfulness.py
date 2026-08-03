from __future__ import annotations

from typing import Any

from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.legacy import LegacyTradingAgentsAdapter
from tradingagents_portable.store import RunStore


class _MissingOutputGraph:
    def __init__(self, **_: Any) -> None:
        pass

    def propagate(self, *_: object, **__: object) -> tuple[dict[str, object], str]:
        return {}, "SELL"


class _MissingOutputAdapter(LegacyTradingAgentsAdapter):
    def _load(self) -> tuple[type[Any], dict[str, Any]]:
        return _MissingOutputGraph, {}


def test_post_run_events_do_not_claim_unobserved_stage_completion() -> None:
    adapter = _MissingOutputAdapter(store=RunStore())
    request = RunRequest(executor="legacy", analysts=("market",))

    result, events = adapter.run(request)

    stage_events = [event for event in events if event.stage_id]
    assert stage_events
    assert {event.status for event in stage_events} == {"unobserved"}
    assert all(event.data["output_observed"] is False for event in stage_events)
    assert result.trader_decision.stance == "sell"
    assert result.trader_decision.executable is False
    assert result.portfolio_manager_decision == ""
    assert result.final_trade_decision == ""
    assert result.processed_signal == "SELL"
    assert result.persistence.run_logging_enabled is True
    assert result.persistence.writes_expected is True
    assert result.persistence.outputs == ("upstream_decision_memory", "upstream_state_log")
