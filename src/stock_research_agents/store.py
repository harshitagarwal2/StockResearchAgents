"""Thread-safe in-memory or atomic JSON-backed run storage."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from threading import RLock

from .contracts import RunEvent
from .publication import validate_completed_publication
from .serialization import (
    StoredResult,
    deserialize_run_events,
    deserialize_run_result,
    serialize_run_events,
    serialize_run_result,
)

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _default_state_dir() -> Path:
    configured = os.environ.get("STOCKRESEARCHAGENTS_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "stock-research-agents"
    return Path.home() / ".local" / "state" / "stock-research-agents"


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must be a safe identifier containing only letters, digits, '.', '_', or '-'")
    return run_id


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _durable_unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
    if not path.parent.exists():
        return
    directory_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _read_json(path: Path, artifact_kind: str) -> bytes:
    """Read a current-version JSON artifact."""
    content = path.read_bytes()
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"saved {artifact_kind} must be valid JSON: {path}") from exc
    if artifact_kind == "run_events" and payload == []:
        return content
    return content


def _read_current_run_id(path: Path) -> str:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("current run pointer must be valid JSON") from exc
    if not isinstance(current, dict) or set(current) != {"run_id"}:
        raise ValueError("current run pointer must contain only run_id")
    run_id = current.get("run_id")
    if not isinstance(run_id, str):
        raise ValueError("current run pointer run_id must be a string")
    return _validate_run_id(run_id)


def _detach_result(result: StoredResult) -> StoredResult:
    """Detach nested mutable contract values through the strict wire codec."""
    return deserialize_run_result(serialize_run_result(result))


def _detach_events(events: tuple[RunEvent, ...]) -> tuple[RunEvent, ...]:
    """Detach nested event data through the strict wire codec."""
    return deserialize_run_events(serialize_run_events(events))


class RunStore:
    def __init__(
        self,
        state_dir: str | os.PathLike[str] | None = None,
        *,
        _state_dir_factory: Callable[[], Path] | None = None,
    ) -> None:
        if state_dir is not None and _state_dir_factory is not None:
            raise ValueError("state_dir and _state_dir_factory are mutually exclusive")
        self._lock = RLock()
        self._results: dict[str, StoredResult] = {}
        self._events: dict[str, tuple[RunEvent, ...]] = {}
        self._staged: dict[str, tuple[StoredResult, tuple[RunEvent, ...]]] = {}
        self._current_run_id: str | None = None
        self._configured_state_dir = Path(state_dir).expanduser() if state_dir is not None else None
        self._state_dir_factory = _state_dir_factory
        self._resolved_state_dir: Path | None = None
        self._loaded = False

    @property
    def state_dir(self) -> Path | None:
        """Return the durable directory without creating it."""
        with self._lock:
            return self._state_path()

    def _state_path(self) -> Path | None:
        if self._resolved_state_dir is None:
            self._resolved_state_dir = (
                self._configured_state_dir
                if self._configured_state_dir is not None
                else self._state_dir_factory()
                if self._state_dir_factory is not None
                else None
            )
        return self._resolved_state_dir

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        state_dir = self._state_path()
        if state_dir is not None and state_dir.exists():
            self._recover_direct_put(state_dir)
            self._load_events(state_dir / "events")
            self._load_bundles(state_dir / "bundles")
            self._load_results(state_dir / "results")
            current_path = state_dir / "current.json"
            if current_path.is_file():
                run_id = _read_current_run_id(current_path)
                if run_id not in self._results and run_id not in self._events:
                    raise ValueError("current run pointer references an unknown run")
                self._current_run_id = run_id
        self._loaded = True

    def _load_single_durable_bundle(
        self,
        requested_run_id: str,
    ) -> tuple[StoredResult, tuple[RunEvent, ...]] | None:
        """Read one atomic bundle without scanning the complete run history."""
        state_dir = self._state_path()
        if state_dir is None or not state_dir.exists():
            return None
        self._recover_direct_put(state_dir)
        if requested_run_id == "current":
            current_path = state_dir / "current.json"
            if not current_path.is_file():
                return None
            run_id = _read_current_run_id(current_path)
        else:
            run_id = _validate_run_id(requested_run_id)
        cached_result = self._results.get(run_id)
        cached_events = self._events.get(run_id)
        if cached_result is not None and cached_events is not None:
            return cached_result, cached_events
        path = state_dir / "bundles" / f"{run_id}.json"
        if not path.is_file():
            return None
        result, events = self._read_bundle(
            path,
            expected_run_id=run_id,
            description="persisted run bundle",
        )
        self._results[run_id] = result
        self._events[run_id] = events
        if requested_run_id == "current":
            self._current_run_id = run_id
        return result, events

    def _load_results(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.json")):
            run_id = _validate_run_id(path.stem)
            result = deserialize_run_result(_read_json(path, "run_result"))
            if result.run_id != run_id:
                raise ValueError(f"persisted result run_id does not match filename: {path.name}")
            # Split projections are complete only when their event half exists.
            if run_id in self._events:
                validate_completed_publication(result, self._events[run_id])
                self._results.setdefault(run_id, result)

    def _load_events(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.json")):
            run_id = _validate_run_id(path.stem)
            events = deserialize_run_events(_read_json(path, "run_events"))
            self._validate_events(run_id, events)
            self._events.setdefault(run_id, events)

    def _bundle_json(self, result: StoredResult, events: tuple[RunEvent, ...]) -> str:
        return json.dumps(
            {
                "result": json.loads(serialize_run_result(result)),
                "events": json.loads(serialize_run_events(events)),
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _read_bundle(
        self,
        path: Path,
        *,
        expected_run_id: str | None,
        description: str,
    ) -> tuple[StoredResult, tuple[RunEvent, ...]]:
        try:
            payload = json.loads(_read_json(path, "durable_bundle"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{description} must be valid JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {"result", "events"}:
            raise ValueError(f"{description} has an invalid shape")
        result = deserialize_run_result(json.dumps(payload["result"]))
        run_id = _validate_run_id(result.run_id)
        if expected_run_id is not None and run_id != expected_run_id:
            raise ValueError(f"{description} run_id does not match filename: {path.name}")
        events = deserialize_run_events(json.dumps(payload["events"]))
        validate_completed_publication(result, events)
        return result, events

    def _load_bundles(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.json")):
            run_id = _validate_run_id(path.stem)
            result, events = self._read_bundle(
                path,
                expected_run_id=run_id,
                description="persisted run bundle",
            )
            self._results[run_id] = result
            self._events[run_id] = events

    def _publish_durable_bundle(
        self,
        state_dir: Path,
        result: StoredResult,
        events: tuple[RunEvent, ...],
        *,
        write_intent: bool,
    ) -> None:
        run_id = result.run_id
        bundle = self._bundle_json(result, events)
        intent_path = state_dir / "direct-put.json"
        if write_intent:
            _atomic_write(intent_path, bundle)
        _atomic_write(state_dir / "bundles" / f"{run_id}.json", bundle)
        _atomic_write(state_dir / "results" / f"{run_id}.json", serialize_run_result(result))
        _atomic_write(state_dir / "events" / f"{run_id}.json", serialize_run_events(events))
        self._write_current(state_dir, run_id)
        if write_intent:
            _durable_unlink(intent_path)

    def _recover_direct_put(self, state_dir: Path) -> None:
        intent_path = state_dir / "direct-put.json"
        if not intent_path.is_file():
            return
        result, events = self._read_bundle(
            intent_path,
            expected_run_id=None,
            description="direct-put recovery intent",
        )
        self._publish_durable_bundle(state_dir, result, events, write_intent=False)
        _durable_unlink(intent_path)

    @staticmethod
    def _validate_events(run_id: str, events: tuple[RunEvent, ...]) -> None:
        mismatched = [event.id for event in events if event.run_id != run_id]
        if mismatched:
            raise ValueError(f"events must all match run_id {run_id}: {mismatched}")

    def _write_current(self, state_dir: Path, run_id: str) -> None:
        _atomic_write(state_dir / "current.json", json.dumps({"run_id": run_id}, sort_keys=True))

    def put(self, result: StoredResult, events: tuple[RunEvent, ...]) -> None:
        with self._lock:
            self._ensure_loaded()
            detached_result = _detach_result(result)
            detached_events = _detach_events(tuple(events))
            run_id = _validate_run_id(detached_result.run_id)
            validate_completed_publication(detached_result, detached_events)
            state_dir = self._state_path()
            if state_dir is not None:
                self._publish_durable_bundle(state_dir, detached_result, detached_events, write_intent=True)
            self._results[run_id] = detached_result
            self._events[run_id] = detached_events
            self._current_run_id = run_id

    def stage(self, result: StoredResult, events: tuple[RunEvent, ...]) -> None:
        """Persist a hidden finalization bundle without exposing it to readers."""
        with self._lock:
            self._ensure_loaded()
            detached_result = _detach_result(result)
            detached_events = _detach_events(tuple(events))
            run_id = _validate_run_id(detached_result.run_id)
            validate_completed_publication(detached_result, detached_events)
            state_dir = self._state_path()
            if state_dir is not None:
                _atomic_write(
                    state_dir / "staged" / f"{run_id}.json",
                    self._bundle_json(detached_result, detached_events),
                )
            self._staged[run_id] = (detached_result, detached_events)

    def get_staged(self, run_id: str) -> tuple[StoredResult, tuple[RunEvent, ...]] | None:
        """Return a hidden finalization bundle for recovery, if one exists."""
        with self._lock:
            self._ensure_loaded()
            safe_run_id = _validate_run_id(run_id)
            staged = self._staged.get(safe_run_id)
            if staged is not None:
                return _detach_result(staged[0]), _detach_events(staged[1])
            state_dir = self._state_path()
            if state_dir is None:
                return None
            path = state_dir / "staged" / f"{safe_run_id}.json"
            if not path.is_file():
                return None
            result, events = self._read_bundle(
                path,
                expected_run_id=safe_run_id,
                description="staged finalization bundle",
            )
            self._staged[safe_run_id] = (result, events)
            return _detach_result(result), _detach_events(events)

    def publish_staged(self, run_id: str) -> tuple[StoredResult, tuple[RunEvent, ...]]:
        """Idempotently publish a hidden bundle after lifecycle completion."""
        with self._lock:
            safe_run_id = _validate_run_id(run_id)
            staged = self.get_staged(safe_run_id)
            if staged is None:
                result = self.get_result(safe_run_id)
                events = self.get_events(safe_run_id)
                if result is None or events is None:
                    raise KeyError(f"staged finalization bundle not found: {safe_run_id}")
                return result, events
            result, events = staged
            self.put(result, events)
            state_dir = self._state_path()
            if state_dir is not None:
                staged_path = state_dir / "staged" / f"{safe_run_id}.json"
                try:
                    staged_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._staged.pop(safe_run_id, None)
            return _detach_result(result), _detach_events(events)

    def put_events(self, run_id: str, events: Iterable[RunEvent]) -> None:
        """Publish an event-only partial run, replacing its current event stream."""
        with self._lock:
            self._ensure_loaded()
            safe_run_id = _validate_run_id(run_id)
            if safe_run_id in self._results or self.get_staged(safe_run_id) is not None:
                raise ValueError("event-only partial storage cannot replace a completed publication")
            detached_events = _detach_events(tuple(events))
            self._validate_events(safe_run_id, detached_events)
            state_dir = self._state_path()
            if state_dir is not None:
                _atomic_write(
                    state_dir / "events" / f"{safe_run_id}.json",
                    serialize_run_events(detached_events),
                )
                self._write_current(state_dir, safe_run_id)
            self._events[safe_run_id] = detached_events
            self._current_run_id = safe_run_id

    def append_event(self, event: RunEvent) -> None:
        """Atomically append one event to an in-memory or durable partial run."""
        if not isinstance(event, RunEvent):
            raise TypeError("event must be a RunEvent")
        with self._lock:
            self._ensure_loaded()
            detached_event = _detach_events((event,))[0]
            run_id = _validate_run_id(detached_event.run_id)
            if run_id in self._results or self.get_staged(run_id) is not None:
                raise ValueError("event-only partial storage cannot extend a completed publication")
            events = (*self._events.get(run_id, ()), detached_event)
            self._validate_events(run_id, events)
            state_dir = self._state_path()
            if state_dir is not None:
                _atomic_write(state_dir / "events" / f"{run_id}.json", serialize_run_events(events))
                self._write_current(state_dir, run_id)
            self._events[run_id] = events
            self._current_run_id = run_id

    def current_run_id(self) -> str | None:
        with self._lock:
            if not self._loaded:
                publication = self._load_single_durable_bundle("current")
                if publication is not None:
                    return publication[0].run_id
            self._ensure_loaded()
            return self._current_run_id

    def resolve_run_id(self, run_id: str) -> str | None:
        """Resolve the Research Dossier Viewer's stable ``current`` alias under the store lock."""
        with self._lock:
            if not self._loaded:
                publication = self._load_single_durable_bundle(run_id)
                if publication is not None:
                    return publication[0].run_id
            self._ensure_loaded()
            if run_id == "current":
                return self._current_run_id
            safe_run_id = _validate_run_id(run_id)
            return safe_run_id if safe_run_id in self._results or safe_run_id in self._events else None

    def get_result(self, run_id: str) -> StoredResult | None:
        with self._lock:
            if not self._loaded:
                publication = self._load_single_durable_bundle(run_id)
                if publication is not None:
                    return _detach_result(publication[0])
            self._ensure_loaded()
            result = self._results.get(_validate_run_id(run_id))
            return None if result is None else _detach_result(result)

    def get_events(self, run_id: str) -> tuple[RunEvent, ...] | None:
        with self._lock:
            if not self._loaded:
                publication = self._load_single_durable_bundle(run_id)
                if publication is not None:
                    return _detach_events(publication[1])
            self._ensure_loaded()
            events = self._events.get(_validate_run_id(run_id))
            return None if events is None else _detach_events(events)

    def get_events_after(
        self,
        run_id: str,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[RunEvent, ...] | None:
        """Return a bounded event page strictly after the supplied sequence."""
        if not isinstance(after_sequence, int) or isinstance(after_sequence, bool) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer between 1 and 1000")
        with self._lock:
            self._ensure_loaded()
            events = self._events.get(_validate_run_id(run_id))
            if events is None:
                return None
            page = tuple(event for event in events if event.sequence > after_sequence)[:limit]
            return _detach_events(page)

    def list_results(self) -> tuple[StoredResult, ...]:
        with self._lock:
            self._ensure_loaded()
            return tuple(_detach_result(result) for result in self._results.values())


RUN_STORE = RunStore(_state_dir_factory=_default_state_dir)
