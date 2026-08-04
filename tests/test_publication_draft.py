from __future__ import annotations

from dataclasses import replace

import pytest

from tradingagents_portable.contracts import EventKind, RunEvent, RunResult, RunStatus
from tradingagents_portable.publication import PublicationDraft, PublicationService
from tradingagents_portable.store import RunStore


def _draft(message: str = "done") -> PublicationDraft:
    result = RunResult(run_id="publication-1", status=RunStatus.COMPLETED)
    event = RunEvent(
        id="publication-1:0001",
        run_id=result.run_id,
        sequence=1,
        timestamp="2026-08-03T00:00:00+00:00",
        kind=EventKind.RUN,
        status=RunStatus.COMPLETED.value,
        message=message,
    )
    return PublicationDraft(result=result, events=(event,))


def test_publication_service_atomically_publishes_and_is_idempotent() -> None:
    store = RunStore()
    service = PublicationService()
    draft = _draft()

    assert service.publish(draft, store) == draft.result
    assert service.publish(draft, store) == draft.result
    assert store.get_staged(draft.result.run_id) is None
    assert store.get_events(draft.result.run_id) == draft.events


def test_publication_service_rejects_conflicting_run_id_reuse() -> None:
    store = RunStore()
    service = PublicationService()
    service.publish(_draft(), store)

    with pytest.raises(ValueError, match="different publication"):
        service.publish(_draft("different"), store)


def test_publication_draft_requires_ordered_matching_completed_events() -> None:
    draft = _draft()
    with pytest.raises(ValueError, match="run_id"):
        PublicationDraft(result=draft.result, events=(replace(draft.events[0], run_id="other"),))
    with pytest.raises(ValueError, match="final publication event"):
        PublicationDraft(result=draft.result, events=(replace(draft.events[0], status="running"),))
