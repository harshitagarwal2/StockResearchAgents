from __future__ import annotations

from dataclasses import replace

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import build_company_analytics_draft
from stock_research_agents.contracts import EventKind
from stock_research_agents.publication import PublicationDraft, PublicationService
from stock_research_agents.store import RunStore


def _draft(message: str = "done") -> PublicationDraft:
    draft = build_company_analytics_draft(complete_analytics_submission("ORCL"))
    return replace(draft, events=(*draft.events[:-1], replace(draft.events[-1], message=message)))


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
    with pytest.raises(ValueError, match="terminal event stream"):
        PublicationDraft(result=draft.result, events=())
    with pytest.raises(ValueError, match="run_id"):
        PublicationDraft(result=draft.result, events=(replace(draft.events[0], run_id="other"),))
    with pytest.raises(ValueError, match="unique and ordered"):
        PublicationDraft(result=draft.result, events=(draft.events[1], draft.events[0], *draft.events[2:]))
    with pytest.raises(ValueError, match="final publication event"):
        PublicationDraft(result=draft.result, events=(replace(draft.events[0], status="running"),))
    forged_terminal = replace(draft.events[-1], kind=EventKind.STAGE, stage_id="publish.completed")
    with pytest.raises(ValueError, match="terminal run event"):
        PublicationDraft(result=draft.result, events=(*draft.events[:-1], forged_terminal))
