from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.fixture import run_fixture
from tradingagents_portable.memory import DecisionMemoryStore
from tradingagents_portable.store import RunStore


def _append(memory: DecisionMemoryStore, run_id: str, symbol: str, sequence: int) -> str:
    receipt = memory.append_decision(
        run_id=run_id,
        symbol=symbol,
        as_of_date=f"2026-07-{sequence:02d}",
        decision={"rating": "hold", "sequence": sequence},
        context={"source": "test"},
        created_at=f"2026-07-{sequence:02d}T00:00:00Z",
    )
    json.dumps(receipt.to_dict(), allow_nan=False)
    return receipt.memory_id


def test_memory_is_durable_and_recall_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    with DecisionMemoryStore(path) as memory:
        for sequence in range(1, 8):
            _append(memory, f"same-{sequence}", "aapl", sequence)
        for sequence, symbol in enumerate(("MSFT", "ORCL", "NVDA", "META"), 8):
            _append(memory, f"cross-{sequence}", symbol, sequence)

    with DecisionMemoryStore(path) as reopened:
        recall = reopened.recall("AAPL")

    assert [entry.run_id for entry in recall.same_symbol] == ["same-7", "same-6", "same-5", "same-4", "same-3"]
    assert [entry.symbol for entry in recall.cross_symbol] == ["META", "NVDA", "ORCL"]
    assert json.loads(json.dumps(recall.to_dict()))["schema_version"]


def test_final_decision_can_receive_later_outcomes_and_reflections(tmp_path: Path) -> None:
    result, _events = run_fixture(RunRequest(symbol="ORCL"), RunStore())
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        decision_receipt = memory.append_final_decision(result, context={"research_mode": "fixture"})
        outcome_receipt = memory.append_outcome(
            memory_id=decision_receipt.memory_id,
            outcome={"return_pct": 2.5, "horizon_days": 30},
            reflection="The neutral stance matched the bounded evidence.",
            observed_at="2026-08-02T00:00:00Z",
        )
        entry = memory.recall("ORCL").same_symbol[0]

    assert outcome_receipt.operation == "outcome_appended"
    assert entry.decision["portfolio_decision"]["rating"] == result.portfolio_decision.rating
    assert entry.outcomes[0].outcome == {"horizon_days": 30, "return_pct": 2.5}
    assert entry.outcomes[0].reflection.startswith("The neutral stance")


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "forbidden"},
        {"nested": {"authorization_header": "forbidden"}},
        {"notes": [{"access_token": "forbidden"}]},
    ],
)
def test_memory_rejects_secret_shaped_keys(tmp_path: Path, payload: dict[str, object]) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        with pytest.raises(ValueError, match="credential-shaped"):
            memory.append_decision(
                run_id="run-1",
                symbol="AAPL",
                as_of_date="2026-08-02",
                decision=payload,
            )


def test_recall_limits_cannot_exceed_portable_context_contract(tmp_path: Path) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        with pytest.raises(ValueError, match="same_symbol_limit"):
            memory.recall("AAPL", same_symbol_limit=6)
        with pytest.raises(ValueError, match="cross_symbol_limit"):
            memory.recall("AAPL", cross_symbol_limit=4)
