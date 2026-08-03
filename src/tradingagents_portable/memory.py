"""Durable, provider-neutral decision memory backed by SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .contracts import SCHEMA_VERSION, RunResult, reject_secret_shaped_keys


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalized_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip() or len(symbol.strip()) > 32:
        raise ValueError("symbol must be a non-empty string no longer than 32 characters")
    normalized = symbol.strip().upper()
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_/" for character in normalized):
        raise ValueError("symbol contains unsupported characters")
    return normalized


def _json_value(value: object, name: str) -> Any:
    reject_secret_shaped_keys(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-compatible and contain only finite numbers") from exc
    return decoded


def _json_object(value: Mapping[str, object], name: str) -> dict[str, Any]:
    decoded = _json_value(dict(value), name)
    if not isinstance(decoded, dict):  # pragma: no cover - guarded by Mapping input
        raise ValueError(f"{name} must be a JSON object")
    return decoded


@dataclass(frozen=True, slots=True)
class MemoryOutcome:
    outcome_id: str
    outcome: Any
    reflection: str
    observed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "outcome": self.outcome,
            "reflection": self.reflection,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class DecisionMemoryEntry:
    memory_id: str
    run_id: str
    symbol: str
    as_of_date: str
    decision: dict[str, Any]
    context: dict[str, Any]
    created_at: str
    outcomes: tuple[MemoryOutcome, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "run_id": self.run_id,
            "symbol": self.symbol,
            "as_of_date": self.as_of_date,
            "decision": self.decision,
            "context": self.context,
            "created_at": self.created_at,
            "outcomes": [item.to_dict() for item in self.outcomes],
        }


@dataclass(frozen=True, slots=True)
class DecisionMemoryReceipt:
    operation: str
    memory_id: str
    run_id: str
    symbol: str
    persisted_at: str
    outcome_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "memory_id": self.memory_id,
            "run_id": self.run_id,
            "symbol": self.symbol,
            "persisted_at": self.persisted_at,
            "outcome_id": self.outcome_id,
        }


@dataclass(frozen=True, slots=True)
class DecisionMemoryRecall:
    symbol: str
    same_symbol: tuple[DecisionMemoryEntry, ...]
    cross_symbol: tuple[DecisionMemoryEntry, ...]
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "same_symbol": [entry.to_dict() for entry in self.same_symbol],
            "cross_symbol": [entry.to_dict() for entry in self.cross_symbol],
        }


class DecisionMemoryStore:
    """Append-only decision and outcome memory with bounded retrieval."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        raw_path = os.fspath(path)
        self.path = raw_path if raw_path == ":memory:" else str(Path(raw_path).expanduser())
        if self.path != ":memory:":
            database_path = Path(self.path)
            database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()
        if self.path != ":memory:":
            os.chmod(self.path, 0o600)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{self.path}{suffix}")
                if sidecar.exists():
                    os.chmod(sidecar, 0o600)

    def _initialize(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    published INTEGER NOT NULL DEFAULT 1 CHECK (published IN (0, 1))
                );
                CREATE INDEX IF NOT EXISTS decisions_symbol_recent
                    ON decisions(symbol, sequence DESC);
                CREATE INDEX IF NOT EXISTS decisions_run_recent
                    ON decisions(run_id, sequence DESC);
                CREATE TABLE IF NOT EXISTS outcomes (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    outcome_id TEXT NOT NULL UNIQUE,
                    memory_id TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    reflection TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES decisions(memory_id)
                );
                CREATE INDEX IF NOT EXISTS outcomes_memory_order
                    ON outcomes(memory_id, sequence ASC);
                """
            )
            columns = {str(row[1]) for row in self._connection.execute("PRAGMA table_info(decisions)").fetchall()}
            if "published" not in columns:
                self._connection.execute(
                    "ALTER TABLE decisions ADD COLUMN published INTEGER NOT NULL DEFAULT 1 CHECK (published IN (0, 1))"
                )
            duplicates = self._connection.execute(
                "SELECT run_id FROM decisions GROUP BY run_id HAVING COUNT(*) > 1 LIMIT 1"
            ).fetchone()
            if duplicates is not None:
                raise RuntimeError(
                    "decision memory contains duplicate run_id entries and cannot guarantee idempotent finalization"
                )
            self._connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS decisions_run_unique ON decisions(run_id)")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> DecisionMemoryStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def append_decision(
        self,
        *,
        run_id: str,
        symbol: str,
        as_of_date: str,
        decision: Mapping[str, object],
        context: Mapping[str, object] | None = None,
        created_at: str | None = None,
        published: bool = True,
    ) -> DecisionMemoryReceipt:
        if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 128:
            raise ValueError("run_id must be a non-empty string no longer than 128 characters")
        if not isinstance(as_of_date, str) or not as_of_date.strip():
            raise ValueError("as_of_date must be a non-empty string")
        normalized = _normalized_symbol(symbol)
        decision_value = _json_object(decision, "decision")
        context_value = _json_object(context or {}, "context")
        persisted_at = created_at or _utc_now()
        memory_id = f"mem_{uuid4().hex}"
        decision_json = json.dumps(
            decision_value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        context_json = json.dumps(
            context_value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR IGNORE INTO decisions
                   (memory_id, run_id, symbol, as_of_date, decision_json, context_json, created_at, published)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    run_id.strip(),
                    normalized,
                    as_of_date.strip(),
                    decision_json,
                    context_json,
                    persisted_at,
                    int(published),
                ),
            )
            existing = self._connection.execute(
                """SELECT memory_id, symbol, as_of_date, decision_json, context_json, created_at
                   FROM decisions WHERE run_id = ?""",
                (run_id.strip(),),
            ).fetchone()
            if existing is None:  # pragma: no cover - INSERT OR IGNORE plus unique index guarantees a row
                raise RuntimeError("decision memory insert did not produce a durable row")
            if (
                existing["symbol"] != normalized
                or existing["as_of_date"] != as_of_date.strip()
                or existing["decision_json"] != decision_json
                or existing["context_json"] != context_json
            ):
                raise ValueError(f"run_id already has a different decision memory entry: {run_id.strip()}")
            if published:
                self._connection.execute("UPDATE decisions SET published = 1 WHERE run_id = ?", (run_id.strip(),))
            return DecisionMemoryReceipt(
                "decision_appended" if published else "decision_staged",
                str(existing["memory_id"]),
                run_id.strip(),
                normalized,
                str(existing["created_at"]),
            )

    def append_final_decision(
        self,
        result: RunResult,
        *,
        context: Mapping[str, object] | None = None,
    ) -> DecisionMemoryReceipt:
        if not isinstance(result, RunResult):
            raise TypeError("result must be a RunResult")
        decision = {
            "portfolio_decision": result.portfolio_decision.to_dict(),
            "final_trade_decision": result.final_trade_decision,
            "processed_signal": result.processed_signal,
            "prototype_notice": result.prototype_notice,
        }
        return self.append_decision(
            run_id=result.run_id,
            symbol=result.request.symbol,
            as_of_date=result.request.as_of_date,
            decision=decision,
            context=context,
            created_at=result.completed_at or None,
        )

    def stage_final_decision(
        self,
        result: RunResult,
        *,
        context: Mapping[str, object] | None = None,
    ) -> DecisionMemoryReceipt:
        """Idempotently stage a final decision without exposing it to recall."""
        if not isinstance(result, RunResult):
            raise TypeError("result must be a RunResult")
        decision = {
            "portfolio_decision": result.portfolio_decision.to_dict(),
            "final_trade_decision": result.final_trade_decision,
            "processed_signal": result.processed_signal,
            "prototype_notice": result.prototype_notice,
        }
        return self.append_decision(
            run_id=result.run_id,
            symbol=result.request.symbol,
            as_of_date=result.request.as_of_date,
            decision=decision,
            context=context,
            created_at=result.completed_at or None,
            published=False,
        )

    def publish_decision(self, run_id: str) -> DecisionMemoryReceipt:
        """Publish a staged decision so it becomes available to bounded recall."""
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT memory_id, run_id, symbol, created_at FROM decisions WHERE run_id = ?",
                (run_id.strip(),),
            ).fetchone()
            if row is None:
                raise KeyError("staged decision memory entry not found")
            self._connection.execute("UPDATE decisions SET published = 1 WHERE run_id = ?", (run_id.strip(),))
            return DecisionMemoryReceipt(
                "decision_appended",
                str(row["memory_id"]),
                str(row["run_id"]),
                str(row["symbol"]),
                str(row["created_at"]),
            )

    def is_published(self, run_id: str) -> bool:
        """Return whether one run's decision is visible to recall."""
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        with self._lock:
            row = self._connection.execute(
                "SELECT published FROM decisions WHERE run_id = ?",
                (run_id.strip(),),
            ).fetchone()
        return row is not None and int(row["published"]) == 1

    def append_outcome(
        self,
        *,
        outcome: object,
        reflection: str,
        memory_id: str | None = None,
        run_id: str | None = None,
        observed_at: str | None = None,
    ) -> DecisionMemoryReceipt:
        if (memory_id is None) == (run_id is None):
            raise ValueError("provide exactly one of memory_id or run_id")
        if not isinstance(reflection, str):
            raise TypeError("reflection must be a string")
        outcome_value = _json_value(outcome, "outcome")
        persisted_at = observed_at or _utc_now()
        with self._lock, self._connection:
            if memory_id is None:
                row = self._connection.execute(
                    """SELECT memory_id, run_id, symbol FROM decisions
                       WHERE run_id = ? AND published = 1 ORDER BY sequence DESC LIMIT 1""",
                    (run_id,),
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT memory_id, run_id, symbol FROM decisions WHERE memory_id = ? AND published = 1",
                    (memory_id,),
                ).fetchone()
            if row is None:
                raise KeyError("decision memory entry not found")
            outcome_id = f"out_{uuid4().hex}"
            self._connection.execute(
                """INSERT INTO outcomes
                   (outcome_id, memory_id, outcome_json, reflection, observed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    outcome_id,
                    row["memory_id"],
                    json.dumps(
                        outcome_value,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    reflection,
                    persisted_at,
                ),
            )
        return DecisionMemoryReceipt(
            "outcome_appended",
            row["memory_id"],
            row["run_id"],
            row["symbol"],
            persisted_at,
            outcome_id,
        )

    def recall(
        self,
        symbol: str,
        *,
        same_symbol_limit: int = 5,
        cross_symbol_limit: int = 3,
    ) -> DecisionMemoryRecall:
        normalized = _normalized_symbol(symbol)
        for name, limit, maximum in (
            ("same_symbol_limit", same_symbol_limit, 5),
            ("cross_symbol_limit", cross_symbol_limit, 3),
        ):
            if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= maximum:
                raise ValueError(f"{name} must be an integer between 0 and {maximum}")
        with self._lock:
            same_rows = self._connection.execute(
                "SELECT * FROM decisions WHERE symbol = ? AND published = 1 ORDER BY sequence DESC LIMIT ?",
                (normalized, same_symbol_limit),
            ).fetchall()
            cross_rows = self._connection.execute(
                "SELECT * FROM decisions WHERE symbol <> ? AND published = 1 ORDER BY sequence DESC LIMIT ?",
                (normalized, cross_symbol_limit),
            ).fetchall()
            same = tuple(self._entry(row) for row in same_rows)
            cross = tuple(self._entry(row) for row in cross_rows)
        return DecisionMemoryRecall(normalized, same, cross)

    def _entry(self, row: sqlite3.Row) -> DecisionMemoryEntry:
        outcome_rows = self._connection.execute(
            "SELECT * FROM outcomes WHERE memory_id = ? ORDER BY sequence ASC",
            (row["memory_id"],),
        ).fetchall()
        outcomes = tuple(
            MemoryOutcome(
                outcome_id=item["outcome_id"],
                outcome=json.loads(item["outcome_json"]),
                reflection=item["reflection"],
                observed_at=item["observed_at"],
            )
            for item in outcome_rows
        )
        return DecisionMemoryEntry(
            memory_id=row["memory_id"],
            run_id=row["run_id"],
            symbol=row["symbol"],
            as_of_date=row["as_of_date"],
            decision=json.loads(row["decision_json"]),
            context=json.loads(row["context_json"]),
            created_at=row["created_at"],
            outcomes=outcomes,
        )


# Concise alias for integration surfaces that do not need to expose storage details.
DecisionMemory = DecisionMemoryStore
