from __future__ import annotations

import json
from pathlib import Path

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.memory import DecisionMemoryStore
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore


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
    result, _events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=RunStore(),
        quality_store=QualityStore(),
    )
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
    dossier = result.submission.company_research.dossier
    expected = {
        "schema_version": "analytics-memory-projection.v1",
        "executive_summary": dossier.executive_summary,
        "recommendation": dossier.recommendation,
        "valuation": [item.to_dict() for item in dossier.valuations],
        "risk": [item.to_dict() for item in dossier.risks],
        "monitoring": [item.to_dict() for item in dossier.monitoring],
    }
    assert entry.decision == json.loads(json.dumps(expected))
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


def test_recall_exact_cutoff_filters_decisions_before_limits_and_outcomes_independently(tmp_path: Path) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        older_id = _append(memory, "older", "AAPL", 1)
        _append(memory, "future", "AAPL", 3)
        memory.append_outcome(
            memory_id=older_id,
            outcome={"status": "known"},
            reflection="Known at cutoff.",
            observed_at="2026-07-01T12:00:00Z",
        )
        memory.append_outcome(
            memory_id=older_id,
            outcome={"status": "future"},
            reflection="Not known yet.",
            observed_at="2026-07-02T12:00:00Z",
        )

        recall = memory.recall(
            "AAPL",
            same_symbol_limit=1,
            cutoff_at="2026-07-02T00:00:00+00:00",
        )

    assert [entry.run_id for entry in recall.same_symbol] == ["older"]
    assert [outcome.reflection for outcome in recall.same_symbol[0].outcomes] == ["Known at cutoff."]


def test_recall_cutoff_excludes_memory_with_later_embedded_evidence(tmp_path: Path) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        memory.append_decision(
            run_id="leaky",
            symbol="AAPL",
            as_of_date="2026-07-01",
            decision={"rating": "buy"},
            context={"evidence": [{"id": "ev-1", "available_at": "2026-07-03T00:00:00Z"}]},
            created_at="2026-07-01T00:00:00Z",
        )

        recall = memory.recall("AAPL", cutoff_at="2026-07-02T00:00:00Z")

    assert recall.same_symbol == ()


@pytest.mark.parametrize("available_at", ["not-a-time", 123])
def test_recall_cutoff_fails_closed_on_malformed_embedded_availability(
    tmp_path: Path,
    available_at: object,
) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        memory.append_decision(
            run_id="malformed-availability",
            symbol="AAPL",
            as_of_date="2026-07-01",
            decision={"rating": "buy"},
            context={"evidence": [{"id": "ev-1", "available_at": available_at}]},
            created_at="2026-07-01T00:00:00Z",
        )

        recall = memory.recall("AAPL", cutoff_at="2026-07-02T00:00:00Z")

    assert recall.same_symbol == ()


@pytest.mark.parametrize("cutoff", ["2026-07-02", "not-a-timestamp", ""])
def test_recall_cutoff_requires_an_exact_offset_timestamp(tmp_path: Path, cutoff: str) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        with pytest.raises(ValueError, match="cutoff"):
            memory.recall("AAPL", cutoff_at=cutoff)


def test_recall_accepts_exact_cutoff_at(tmp_path: Path) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        _append(memory, "visible", "AAPL", 1)

        recall = memory.recall("AAPL", cutoff_at="2026-07-02T00:00:00Z")

    assert [entry.run_id for entry in recall.same_symbol] == ["visible"]


def test_recall_cutoff_fails_closed_when_decision_as_of_date_is_later(tmp_path: Path) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        memory.append_decision(
            run_id="future-as-of",
            symbol="AAPL",
            as_of_date="2026-07-03",
            decision={"rating": "hold"},
            created_at="2026-07-01T00:00:00Z",
        )

        recall = memory.recall("AAPL", cutoff_at="2026-07-02T23:59:59Z")

    assert recall.same_symbol == ()


@pytest.mark.parametrize("timestamp_key", ["filed_at", "event_at", "as_of_at", "evaluated_at", "occurred_at"])
def test_recall_cutoff_fails_closed_for_all_known_availability_timestamps(
    tmp_path: Path,
    timestamp_key: str,
) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        memory.append_decision(
            run_id=f"future-{timestamp_key}",
            symbol="AAPL",
            as_of_date="2026-07-01",
            decision={"rating": "hold"},
            context={"record": {timestamp_key: "2026-07-03T00:00:00Z"}},
            created_at="2026-07-01T00:00:00Z",
        )

        recall = memory.recall("AAPL", cutoff_at="2026-07-02T00:00:00Z")

    assert recall.same_symbol == ()


def test_recall_keeps_cutoff_safe_forecast_with_future_economic_period(tmp_path: Path) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        memory.append_decision(
            run_id="safe-forecast",
            symbol="AAPL",
            as_of_date="2026-07-01",
            decision={"rating": "hold"},
            context={
                "metric": {
                    "basis": "estimated",
                    "as_of_at": "2026-07-01T12:00:00Z",
                    "period_end": "2027-06-30T23:59:59Z",
                }
            },
            created_at="2026-07-01T12:00:00Z",
        )

        recall = memory.recall("AAPL", cutoff_at="2026-07-02T00:00:00Z")

    assert [entry.run_id for entry in recall.same_symbol] == ["safe-forecast"]


def test_recall_skips_corrupt_row_and_outcome_without_aborting_safe_entries(tmp_path: Path) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        safe = memory.append_decision(
            run_id="safe",
            symbol="AAPL",
            as_of_date="2026-07-01",
            decision={"rating": "hold"},
            created_at="2026-07-01T00:00:00Z",
        )
        memory.append_outcome(
            memory_id=safe.memory_id,
            outcome={"return": 0.01},
            reflection="bounded",
            observed_at="2026-07-01T12:00:00Z",
        )
        memory.append_decision(
            run_id="corrupt",
            symbol="AAPL",
            as_of_date="2026-07-01",
            decision={"rating": "buy"},
            created_at="2026-07-01T01:00:00Z",
        )
        memory._connection.execute("UPDATE decisions SET created_at = ? WHERE run_id = ?", ("not-a-time", "corrupt"))
        memory._connection.execute(
            "UPDATE outcomes SET observed_at = ? WHERE memory_id = ?",
            ("not-a-time", safe.memory_id),
        )

        recall = memory.recall("AAPL", cutoff_at="2026-07-02T00:00:00Z")

    assert [entry.run_id for entry in recall.same_symbol] == ["safe"]
    assert recall.same_symbol[0].outcomes == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [("created_at", "not-a-time"), ("created_at", "2026-07-01")],
)
def test_memory_rejects_malformed_decision_write_timestamps(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    with DecisionMemoryStore(tmp_path / "memory.sqlite3") as memory:
        with pytest.raises(ValueError, match=field):
            memory.append_decision(
                run_id="invalid-time",
                symbol="AAPL",
                as_of_date="2026-07-01",
                decision={"rating": "hold"},
                created_at=value,
            )
