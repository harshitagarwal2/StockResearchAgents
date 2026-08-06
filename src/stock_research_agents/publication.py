"""Atomic, idempotent publication of completed StockResearchAgents run bundles."""

from __future__ import annotations

from dataclasses import dataclass

from .application_ports import ResultPublicationPort
from .contracts import EventKind, RunEvent, RunStatus
from .serialization import StoredResult, serialize_run_events, serialize_run_result


@dataclass(frozen=True, slots=True)
class PublicationDraft:
    """A complete result and event stream ready for one atomic publication."""

    result: StoredResult
    events: tuple[RunEvent, ...]
    decision_memory_records: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        validate_completed_publication(self.result, self.events)


def validate_completed_publication(result: StoredResult, events: tuple[RunEvent, ...]) -> None:
    """Require one complete, ordered event stream for a published result."""
    if result.status is not RunStatus.COMPLETED:
        raise ValueError("only completed results can be published")
    if not result.run_id:
        raise ValueError("published result requires a run_id")
    if not events:
        raise ValueError("published result requires a terminal event stream")
    if not all(isinstance(event, RunEvent) for event in events):
        raise TypeError("published events must contain only RunEvent values")
    sequences = tuple(event.sequence for event in events)
    if any(event.run_id != result.run_id for event in events):
        raise ValueError("all events must reference result.run_id for publication")
    if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(sequences):
        raise ValueError("event sequences must be unique and ordered")
    terminal = events[-1]
    if terminal.status != RunStatus.COMPLETED.value:
        raise ValueError("the final publication event must be completed")
    if terminal.kind is not EventKind.RUN or terminal.stage_id is not None:
        raise ValueError("the final publication event must be a terminal run event")


def _matches_draft(result: StoredResult, events: tuple[RunEvent, ...], draft: PublicationDraft) -> bool:
    return serialize_run_result(result) == serialize_run_result(draft.result) and serialize_run_events(
        events
    ) == serialize_run_events(draft.events)


class PublicationService:
    """Publish drafts atomically and reject conflicting reuse of a run ID."""

    def publish(self, draft: PublicationDraft, store: ResultPublicationPort) -> StoredResult:
        existing = store.get_result(draft.result.run_id)
        if existing is not None:
            existing_events = store.get_events(draft.result.run_id) or ()
            if _matches_draft(existing, existing_events, draft):
                return existing
            raise ValueError(f"run_id already identifies a different publication: {draft.result.run_id}")

        staged = store.get_staged(draft.result.run_id)
        if staged is not None:
            staged_result, staged_events = staged
            if not _matches_draft(staged_result, staged_events, draft):
                raise ValueError(f"run_id already identifies a different staged publication: {draft.result.run_id}")
        else:
            store.stage(draft.result, draft.events)
        result, _ = store.publish_staged(draft.result.run_id)
        return result
