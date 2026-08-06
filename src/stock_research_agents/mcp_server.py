"""MCP stdio surface for the standalone StockResearchAgents capability."""

from __future__ import annotations

from typing import Any, Literal

from ._version import __version__
from .application import CompletedPublicationService, CompletedRunQueryService
from .bootstrap import DEFAULT_RUNTIME
from .capabilities import discovery, feature_matrix
from .company_analytics import get_company_research_quality as execute_quality_query
from .company_analytics import prepare_company_analytics as prepare_company_analytics_request
from .company_analytics import quality_projection_for_result
from .company_analytics import record_company_forecast_outcome as execute_outcome_append
from .company_analytics import submit_company_analytics as execute_company_analytics_import
from .company_analytics_v1 import CompanyAnalyticsResultV1
from .company_lifecycle import (
    publication_lifecycle_run_id,
    require_completed_publication,
)
from .conformance import evaluate_validation, validation_digest
from .export import export_run_bundle
from .report_server import ensure_report_viewer, launch_report, present_completed_run, report_summary
from .research_quality_v1 import OutcomeObservation
from .semantics import build_completed_run_semantics
from .view import build_run_view
from .viewer_server import viewer_report

RUN_STORE = DEFAULT_RUNTIME.result_store
COMPANY_ANALYTICS_COORDINATOR = DEFAULT_RUNTIME.coordinator

try:
    from mcp.server import MCPServer
    from mcp.types import ToolAnnotations
except ImportError as exc:  # pragma: no cover - exercised by dependency-free CLI installs
    raise RuntimeError(
        "MCP support requires the 'mcp' package; install this project with its default dependencies."
    ) from exc


def _annotations(*, read_only: bool, idempotent: bool, open_world: bool) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=False,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


def _completed_publication_response(
    result: Any,
    events: tuple[Any, ...],
    *,
    store: Any = None,
    coordinator: Any = None,
    presentation_mode: Literal["auto", "path_only"] | None = None,
) -> dict[str, Any]:
    """Build one transport response for every completed publication.

    Presentation is deliberately best-effort. ``present_completed_run``
    reports viewer failures as data and cannot roll back the saved result.
    """
    publication_store = RUN_STORE if store is None else store
    return CompletedPublicationService(
        result_store=publication_store,
        presenter=present_completed_run,
        view_builder=build_run_view,
        coordinator=coordinator,
    ).response(
        result,
        events,
        presentation_mode=presentation_mode,
        view_before_events=False,
    )


def _completed_run_query(coordinator: Any = None) -> CompletedRunQueryService:
    return CompletedRunQueryService(
        RUN_STORE,
        coordinator=COMPANY_ANALYTICS_COORDINATOR if coordinator is None else coordinator,
        publication_gate=require_completed_publication,
    )


def discover_capability() -> dict[str, object]:
    """Discover the analytics workflow, tools, and safety boundaries."""
    return discovery()


def get_feature_matrix() -> dict[str, Any]:
    """Return supported, optional, and intentionally unavailable features."""
    return feature_matrix().to_dict()


def prepare_company_analytics(
    request: dict[str, Any],
    research_pack_id: str = "initiating-coverage.v1",
    execution_mode: str = "sequential",
) -> dict[str, Any]:
    """Return the 26-stage analytics plan and standalone v1 submission schema."""
    return prepare_company_analytics_request(
        request,
        research_pack_id=research_pack_id,
        execution_mode=execution_mode,
    )


def import_company_analytics(
    payload: dict[str, Any],
    presentation_mode: Literal["auto", "path_only"] | None = None,
) -> dict[str, Any]:
    """Validate and atomically publish completed research plus analytics sidecars."""
    result, events = execute_company_analytics_import(payload)
    return _completed_publication_response(result, events, presentation_mode=presentation_mode)


def record_research_outcome(payload: dict[str, Any]) -> dict[str, object]:
    """Append a resolved forecast outcome or correction and persist its scorecard."""
    observation = OutcomeObservation.from_dict(payload)
    _completed_run_id(observation.forecast_id.split(".", 1)[0])
    return execute_outcome_append(observation)


def get_research_quality(run_id: str) -> dict[str, object]:
    """Return registered forecasts, append-only outcomes, and deterministic scorecards."""
    return execute_quality_query(_completed_run_id(run_id))


def create_company_analytics_run(
    request: dict[str, Any],
    research_pack_id: str = "initiating-coverage.v1",
    decision_memory_enabled: bool = True,
    execution_mode: str = "sequential",
) -> dict[str, Any]:
    """Create a durable 26-stage analytics run for execution by the calling harness."""
    return {
        "ok": True,
        "control": COMPANY_ANALYTICS_COORDINATOR.create(
            request,
            research_pack_id=research_pack_id,
            decision_memory_enabled=decision_memory_enabled,
            execution_mode=execution_mode,
        ),
    }


def _coordinator_for_run(_run_id: str) -> Any:
    return COMPANY_ANALYTICS_COORDINATOR


def start_run(run_id: str, expected_revision: int) -> dict[str, Any]:
    """Start a prepared durable analytics run and return its first stage contract and context."""
    return _coordinator_for_run(run_id).start(run_id, expected_revision)


def append_run_receipts(
    run_id: str,
    receipts: list[dict[str, Any]],
    expected_revision: int,
) -> dict[str, Any]:
    """Append sanitized live stage/tool observations without raw prompts, arguments, or credentials."""
    return _coordinator_for_run(run_id).append_receipts(run_id, receipts, expected_revision)


def commit_run_stage(
    run_id: str,
    stage_id: str,
    output: dict[str, Any],
    expected_revision: int,
    attempt: int | None = None,
) -> dict[str, Any]:
    """Validate and checkpoint one completed analytics stage, then return the next stage contract."""
    return _coordinator_for_run(run_id).commit_stage(
        run_id,
        stage_id,
        output,
        expected_revision,
        attempt=attempt,
    )


def pause_run(run_id: str, expected_revision: int, reason: str) -> dict[str, Any]:
    """Pause a running workflow at its next durable stage boundary."""
    return {"ok": True, "control": _coordinator_for_run(run_id).pause(run_id, expected_revision, reason)}


def resume_run(run_id: str, expected_revision: int) -> dict[str, Any]:
    """Resume at the first incomplete stage; interrupted in-flight work is replayed."""
    return _coordinator_for_run(run_id).resume(run_id, expected_revision)


def get_run_control(run_id: str) -> dict[str, Any]:
    """Return durable status, revision, checkpoint, cancellation, and next-stage information."""
    return {"ok": True, "control": _coordinator_for_run(run_id).control(run_id)}


def poll_run_events(run_id: str, after_sequence: int = 0, limit: int = 100) -> dict[str, Any]:
    """Read live lifecycle events after a monotonic cursor."""
    return _coordinator_for_run(run_id).poll_events(run_id, after_sequence=after_sequence, limit=limit)


def request_run_cancellation(run_id: str, expected_revision: int, reason: str) -> dict[str, Any]:
    """Record cooperative cancellation intent; the caller remains responsible for interrupting its work."""
    return {
        "ok": True,
        "control": _coordinator_for_run(run_id).request_cancel(run_id, expected_revision, reason),
    }


def acknowledge_run_cancellation(
    run_id: str,
    expected_revision: int,
    execution_receipt_id: str,
) -> dict[str, Any]:
    """Acknowledge that the caller stopped its in-flight agents/tools and make cancellation terminal."""
    return {
        "ok": True,
        "control": _coordinator_for_run(run_id).acknowledge_cancel(
            run_id,
            expected_revision,
            execution_receipt_id,
        ),
    }


def finalize_run(
    run_id: str,
    expected_revision: int,
    presentation_mode: Literal["auto", "path_only"] | None = None,
) -> dict[str, Any]:
    """Strictly validate all committed outputs and atomically publish the final dossier."""
    coordinator = _coordinator_for_run(run_id)
    result, events = coordinator.finalize(run_id, expected_revision)
    return _completed_publication_response(
        result,
        events,
        store=getattr(coordinator, "result_store", RUN_STORE),
        coordinator=coordinator,
        presentation_mode=presentation_mode,
    )


def export_completed_run(run_id: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
    """Publish a new bundle atomically or replace a validated prior bundle with crash recovery."""
    run_id, result, events = _completed_run_query().require(run_id)
    lifecycle_run_id = publication_lifecycle_run_id(events)
    if lifecycle_run_id is not None:
        try:
            lifecycle_log = _coordinator_for_run(lifecycle_run_id).lifecycle_log(lifecycle_run_id)
        except KeyError:
            lifecycle_log = ()
    else:
        lifecycle_log = ()
    receipt = export_run_bundle(
        result,
        events,
        destination,
        lifecycle_log=lifecycle_log,
        overwrite=overwrite,
    )
    return {"ok": True, "export": receipt.to_dict()}


def query_decision_memory(
    symbol: str,
    same_symbol_limit: int = 5,
    cross_symbol_limit: int = 3,
    cutoff_at: str | None = None,
) -> dict[str, Any]:
    """Recall bounded decision memory, optionally restricted to an exact historical cutoff."""
    recall = COMPANY_ANALYTICS_COORDINATOR.decision_memory().recall(
        symbol,
        same_symbol_limit=same_symbol_limit,
        cross_symbol_limit=cross_symbol_limit,
        cutoff_at=cutoff_at,
    )
    return {"ok": True, "recall": recall.to_dict()}


def record_decision_outcome(
    outcome: object,
    reflection: str,
    memory_id: str | None = None,
    run_id: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Append an externally observed outcome/reflection to one prior research decision."""
    receipt = COMPANY_ANALYTICS_COORDINATOR.decision_memory().append_outcome(
        outcome=outcome,
        reflection=reflection,
        memory_id=memory_id,
        run_id=run_id,
        observed_at=observed_at,
    )
    return {"ok": True, "memory_receipt": receipt.to_dict()}


def get_validation_report(run_id: str) -> dict[str, Any]:
    """Validate the completed run against repository-owned invariants."""
    run_id, result, events = _completed_run_query().require(run_id)
    if not isinstance(result, CompanyAnalyticsResultV1) or events is None:
        raise ValueError(f"completed run not found: {run_id}")
    report = evaluate_validation(result, events)
    return {"ok": report.passed, "validation": report.to_dict(), "digest": validation_digest(report)}


def get_run(run_id: str) -> dict[str, Any]:
    """Return a compact presentation-oriented run record."""
    run_id = _completed_run_id(run_id)
    return viewer_report(run_id)


def _completed_run_id(run_id: str) -> str:
    return _completed_run_query().resolve(run_id)


def get_run_events(run_id: str) -> dict[str, Any]:
    """Return the ordered event stream for a run."""
    run_id = _completed_run_id(run_id)
    events = RUN_STORE.get_events(run_id)
    return {"ok": events is not None, "run_id": run_id, "events": [event.to_dict() for event in events or ()]}


def get_run_result(run_id: str) -> dict[str, Any]:
    """Return the full typed result for a run."""
    run_id = _completed_run_id(run_id)
    result = RUN_STORE.get_result(run_id)
    return {"ok": result is not None, "result": result.to_dict() if result else None}


def get_run_semantics(run_id: str) -> dict[str, Any]:
    """Return canonical transport-neutral semantics for a completed run."""
    run_id, result, events = _completed_run_query().require(run_id)
    if not isinstance(result, CompanyAnalyticsResultV1) or events is None:
        raise ValueError(f"completed run not found: {run_id}")
    return build_completed_run_semantics(result, events).to_dict()


def get_run_view(run_id: str) -> dict[str, Any]:
    """Return the complete UI-ready view for inline harness rendering."""
    run_id = _completed_run_id(run_id)
    result = RUN_STORE.get_result(run_id)
    events = RUN_STORE.get_events(run_id)
    if not isinstance(result, CompanyAnalyticsResultV1) or events is None:
        return {"ok": False, "run_id": run_id, "view": None}
    return build_run_view(
        result,
        events,
        quality_projection=quality_projection_for_result(result),
    ).to_dict()


def launch_research_report(host: str = "127.0.0.1", port: int = 0, run_id: str | None = None) -> dict[str, object]:
    """Ensure the shared completed-only viewer or launch an explicitly bound viewer server."""
    resolved_run_id = _completed_run_id(run_id or "current")
    if host == "127.0.0.1" and port == 0:
        presentation = ensure_report_viewer(resolved_run_id, mode="auto")
        return {"ok": presentation["status"] == "ready", **presentation}
    return launch_report(host, port, run_id=resolved_run_id)


def get_research_report_summary(run_id: str) -> dict[str, object]:
    """Return the presentation-safe summary for a completed research run."""
    resolved_run_id = _completed_run_id(run_id)
    return report_summary(resolved_run_id)


def create_server() -> MCPServer:
    server = MCPServer(
        "StockResearchAgents",
        version=__version__,
        instructions=(
            "Prototype financial research only. Fixture values are synthetic. "
            "This server never submits, manages, or authorizes orders."
        ),
    )
    read = _annotations(read_only=True, idempotent=True, open_world=False)
    local_write = _annotations(read_only=False, idempotent=False, open_world=False)
    launch = _annotations(read_only=False, idempotent=False, open_world=False)
    export_write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    )

    server.tool(
        name="discover_capability",
        description="Discover the active analytics profile, tools, and safety boundaries.",
        annotations=read,
    )(discover_capability)
    server.tool(
        name="get_feature_matrix",
        description="Return implemented features, safety exclusions, and runtime readiness.",
        annotations=read,
    )(get_feature_matrix)
    server.tool(
        name="prepare_company_analytics",
        description="Return the company-analytics v1 plan, research packs, and standalone submission schema.",
        annotations=read,
    )(prepare_company_analytics)
    server.tool(
        name="import_company_analytics",
        description="Validate deterministic analytics, hypotheses, forecasts, and quality then publish atomically.",
        annotations=local_write,
    )(import_company_analytics)
    server.tool(
        name="record_research_outcome",
        description="Append a forecast outcome or correction and persist deterministic quality scores.",
        annotations=local_write,
    )(record_research_outcome)
    server.tool(
        name="get_research_quality",
        description="Return immutable forecasts, append-only outcome ledgers, and stored quality scorecards.",
        annotations=read,
    )(get_research_quality)
    server.tool(
        name="create_company_analytics_run",
        description="Create a durable 26-stage analytics run with a selected research pack.",
        annotations=local_write,
    )(create_company_analytics_run)
    server.tool(
        name="start_run",
        description="Start a prepared durable analytics run and return its first stage.",
        annotations=local_write,
    )(start_run)
    server.tool(
        name="append_run_receipts",
        description="Append safe live stage/tool receipts without prompts, raw arguments, or credentials.",
        annotations=local_write,
    )(append_run_receipts)
    server.tool(
        name="commit_run_stage",
        description="Commit and checkpoint one completed analytics stage, then return the next stage.",
        annotations=local_write,
    )(commit_run_stage)
    server.tool(
        name="pause_run",
        description="Pause an analytics run at its next stage boundary.",
        annotations=local_write,
    )(pause_run)
    server.tool(
        name="resume_run",
        description="Resume from the first incomplete stage; replay interrupted work.",
        annotations=local_write,
    )(resume_run)
    server.tool(
        name="get_run_control",
        description="Return durable lifecycle status, revision, checkpoint, cancellation, and next stage.",
        annotations=read,
    )(get_run_control)
    server.tool(
        name="poll_run_events",
        description="Read live lifecycle events after a monotonic cursor.",
        annotations=read,
    )(poll_run_events)
    server.tool(
        name="request_run_cancellation",
        description="Request cooperative cancellation; the caller owns interruption.",
        annotations=local_write,
    )(request_run_cancellation)
    server.tool(
        name="acknowledge_run_cancellation",
        description="Acknowledge caller interruption and make cancellation terminal.",
        annotations=local_write,
    )(acknowledge_run_cancellation)
    server.tool(
        name="finalize_run",
        description="Validate all committed stages and atomically publish the completed dossier and sidecars.",
        annotations=local_write,
    )(finalize_run)
    server.tool(
        name="export_completed_run",
        description="Export a bundle with atomic first publication and crash-recoverable validated overwrite.",
        annotations=export_write,
    )(export_completed_run)
    server.tool(
        name="query_decision_memory",
        description="Recall up to five same-symbol and three cross-symbol prior decisions.",
        annotations=read,
    )(query_decision_memory)
    server.tool(
        name="record_decision_outcome",
        description="Append an externally observed outcome and reflection to a prior research decision.",
        annotations=local_write,
    )(record_decision_outcome)
    server.tool(
        name="get_validation_report",
        description="Validate the completed run against repository-owned observable invariants.",
        annotations=read,
    )(get_validation_report)
    server.tool(
        name="get_run",
        description="Return a compact presentation-oriented run record.",
        annotations=read,
    )(get_run)
    server.tool(
        name="get_run_events",
        description="Return the ordered event stream for a run.",
        annotations=read,
    )(get_run_events)
    server.tool(
        name="get_run_result",
        description="Return the full typed result for a run.",
        annotations=read,
    )(get_run_result)
    server.tool(
        name="get_run_semantics",
        description="Return canonical transport-neutral semantics for a completed run.",
        annotations=read,
    )(get_run_semantics)
    server.tool(
        name="get_run_view",
        description="Return the complete UI-ready run projection for inline harness rendering.",
        annotations=read,
    )(get_run_view)
    server.tool(
        name="launch_research_report",
        description="Serve the completed Research Dossier Viewer on loopback.",
        annotations=launch,
    )(launch_research_report)
    server.tool(
        name="get_research_report_summary",
        description="Return the presentation-safe summary for a completed research run.",
        annotations=read,
    )(get_research_report_summary)
    return server


mcp = create_server()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
