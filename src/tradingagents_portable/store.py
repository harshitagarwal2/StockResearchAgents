"""Small thread-safe in-memory store shared by CLI, MCP, and dashboard."""

from __future__ import annotations

from threading import RLock

from .contracts import RunEvent, RunResult


class RunStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._results: dict[str, RunResult] = {}
        self._events: dict[str, tuple[RunEvent, ...]] = {}
        self._current_run_id: str | None = None

    def put(self, result: RunResult, events: tuple[RunEvent, ...]) -> None:
        with self._lock:
            self._results[result.run_id] = result
            self._events[result.run_id] = events
            self._current_run_id = result.run_id

    def current_run_id(self) -> str | None:
        with self._lock:
            return self._current_run_id

    def resolve_run_id(self, run_id: str) -> str | None:
        """Resolve the dashboard's stable ``current`` alias under the store lock."""
        with self._lock:
            if run_id == "current":
                return self._current_run_id
            return run_id if run_id in self._results else None

    def get_result(self, run_id: str) -> RunResult | None:
        with self._lock:
            return self._results.get(run_id)

    def get_events(self, run_id: str) -> tuple[RunEvent, ...] | None:
        with self._lock:
            return self._events.get(run_id)

    def list_results(self) -> tuple[RunResult, ...]:
        with self._lock:
            return tuple(self._results.values())


RUN_STORE = RunStore()
