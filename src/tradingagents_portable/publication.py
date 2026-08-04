"""Atomic, idempotent publication of completed portable run bundles."""

from __future__ import annotations

from dataclasses import dataclass

from .application_ports import ResultPublicationPort
from .contracts import RunEvent, RunResult, RunStatus
from .serialization import serialize_run_events, serialize_run_result


@dataclass(frozen=True, slots=True)
class PublicationDraft:
    """A complete result and event stream ready for one atomic publication."""

    result: RunResult
    events: tuple[RunEvent, ...]
    decision_memory_records: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        if self.result.status is not RunStatus.COMPLETED:
            raise ValueError("only completed results can be published")
        if not self.result.run_id:
            raise ValueError("published result requires a run_id")
        if not self.events:
            raise ValueError("published result requires a terminal event stream")
        sequences = tuple(event.sequence for event in self.events)
        if any(event.run_id != self.result.run_id for event in self.events):
            raise ValueError("all events must reference the publication run_id")
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(sequences):
            raise ValueError("event sequences must be unique and ordered")
        terminal = self.events[-1]
        if terminal.status != RunStatus.COMPLETED.value:
            raise ValueError("the final publication event must be completed")


def _matches_draft(result: RunResult, events: tuple[RunEvent, ...], draft: PublicationDraft) -> bool:
    return serialize_run_result(result) == serialize_run_result(draft.result) and serialize_run_events(
        events
    ) == serialize_run_events(draft.events)


class PublicationService:
    """Publish drafts atomically and reject conflicting reuse of a run ID."""

    def publish(self, draft: PublicationDraft, store: ResultPublicationPort) -> RunResult:
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
