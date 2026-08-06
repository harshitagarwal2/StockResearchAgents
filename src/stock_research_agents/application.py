"""Application services shared by CLI, MCP, and other inbound adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .application_ports import CompletedResultReader
from .company_lifecycle import require_completed_publication

PublicationGate = Callable[[str, CompletedResultReader, Any], str]
Presenter = Callable[..., dict[str, Any]]
ViewBuilder = Callable[[Any, tuple[Any, ...]], Any]


@dataclass(frozen=True, slots=True)
class CompletedPublicationService:
    """Build the common completed-publication response for inbound adapters."""

    result_store: CompletedResultReader
    presenter: Presenter
    view_builder: ViewBuilder
    coordinator: Any = None

    def response(
        self,
        result: Any,
        events: tuple[Any, ...],
        *,
        presentation_mode: str | None = None,
        view_before_events: bool = True,
    ) -> dict[str, Any]:
        presentation = self.presenter(
            result.run_id,
            self.result_store,
            coordinator=self.coordinator,
            mode=presentation_mode,
        )
        serialized_events = [event.to_dict() for event in events]
        serialized_view = self.view_builder(result, events).to_dict()
        response: dict[str, Any] = {"ok": True, "result": result.to_dict()}
        if view_before_events:
            response.update(view=serialized_view, events=serialized_events)
        else:
            response.update(events=serialized_events, view=serialized_view)
        response["presentation"] = presentation
        return response


@dataclass(frozen=True, slots=True)
class CompletedRunQueryService:
    """Apply the completed-publication gate before serving durable results."""

    result_store: CompletedResultReader
    coordinator: Any = None
    publication_gate: PublicationGate = require_completed_publication

    def resolve(self, run_id: str) -> str:
        return self.publication_gate(run_id, self.result_store, self.coordinator)

    def require(self, run_id: str) -> tuple[str, Any, tuple[Any, ...]]:
        resolved = self.resolve(run_id)
        result = self.result_store.get_result(resolved)
        events = self.result_store.get_events(resolved)
        if result is None or events is None:
            raise ValueError(f"completed run not found: {resolved}")
        return resolved, result, events
