"""MCP stdio surface for the portable TradingAgents capability."""

from __future__ import annotations

from typing import Any, Literal

from ._version import __version__
from .capabilities import discovery, feature_matrix
from .company_analytics import get_company_research_quality as execute_quality_query
from .company_analytics import prepare_company_analytics as prepare_company_analytics_request
from .company_analytics import quality_projection_for_result
from .company_analytics import record_company_forecast_outcome as execute_outcome_append
from .company_analytics import submit_company_analytics as execute_company_analytics_import
from .company_lifecycle import COMPANY_ANALYTICS_COORDINATOR, COMPANY_RESEARCH_COORDINATOR
from .company_research import prepare_company_research as prepare_company_research_request
from .company_research import select_run_coordinator
from .company_research import submit_company_research as execute_company_research_import
from .conformance import conformance_digest, evaluate_conformance
from .contracts import RunRequest
from .dashboard import dashboard_report, launch_dashboard
from .export import export_run_bundle
from .fixture import prepare_fixture as prepare_fixture_request
from .fixture import run_fixture as execute_fixture
from .host_native import prepare_host_run as prepare_host_run_request
from .host_native import submit_host_run as execute_host_run_import
from .lifecycle import HOST_RUN_COORDINATOR, is_lifecycle_run_id
from .report_server import ensure_report_viewer, launch_report, present_completed_run, report_summary
from .semantics import build_completed_run_semantics
from .store import RUN_STORE
from .view import build_run_view

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


def _request(
    symbol: str,
    as_of_date: str,
    analysts: list[str] | None,
    debate_rounds: int,
    risk_rounds: int,
    executor: str,
    asset_type: str = "stock",
    output_language: str = "English",
) -> RunRequest:
    if asset_type not in {"stock", "crypto"}:
        raise ValueError("asset_type must be 'stock' or 'crypto'")
    return RunRequest(
        symbol=symbol,
        as_of_date=as_of_date,
        asset_type=asset_type,  # type: ignore[arg-type]
        analysts=tuple(
            analysts
            if analysts is not None
            else (
                ("market", "social", "news") if asset_type == "crypto" else ("market", "social", "news", "fundamentals")
            )
        ),
        debate_rounds=debate_rounds,
        risk_rounds=risk_rounds,
        output_language=output_language,
        executor=executor,  # type: ignore[arg-type]
        checkpoint_enabled=False,
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
    presentation = present_completed_run(
        result.run_id,
        publication_store,
        coordinator=coordinator,
        mode=presentation_mode,
    )
    return {
        "ok": True,
        "result": result.to_dict(),
        "events": [event.to_dict() for event in events],
        "view": build_run_view(result, events).to_dict(),
        "presentation": presentation,
        "dashboard_path": presentation["path"],
    }


def discover_capability() -> dict[str, object]:
    """Discover executors, tools, safety boundaries, and the default fixture."""
    return discovery(include_legacy=False)


def get_feature_matrix() -> dict[str, Any]:
    """Return supported, optional, and intentionally unavailable features."""
    return feature_matrix(include_legacy=False).to_dict()


def prepare_fixture(
    as_of_date: str = "2026-07-03",
    analysts: list[str] | None = None,
    debate_rounds: int = 1,
    risk_rounds: int = 1,
) -> dict[str, Any]:
    """Validate and expand the deterministic ORCL fixture without running it."""
    return prepare_fixture_request(_request("ORCL", as_of_date, analysts, debate_rounds, risk_rounds, "fixture"))


def run_fixture(
    as_of_date: str = "2026-07-03",
    analysts: list[str] | None = None,
    debate_rounds: int = 1,
    risk_rounds: int = 1,
    presentation_mode: Literal["auto", "path_only"] | None = None,
) -> dict[str, Any]:
    """Run every legacy stage deterministically with synthetic ORCL evidence."""
    result, events = execute_fixture(_request("ORCL", as_of_date, analysts, debate_rounds, risk_rounds, "fixture"))
    return _completed_publication_response(result, events, presentation_mode=presentation_mode)


def prepare_host_run(
    symbol: str,
    as_of_date: str,
    asset_type: str = "stock",
    analysts: list[str] | None = None,
    debate_rounds: int = 1,
    risk_rounds: int = 1,
    output_language: str = "English",
) -> dict[str, Any]:
    """Return the exact workflow plan for the current host harness to execute."""
    return prepare_host_run_request(
        _request(
            symbol,
            as_of_date,
            analysts,
            debate_rounds,
            risk_rounds,
            "host_native",
            asset_type,
            output_language=output_language,
        ),
    )


def import_host_run(
    payload: dict[str, Any],
    presentation_mode: Literal["auto", "path_only"] | None = None,
) -> dict[str, Any]:
    """Validate a completed host-executed workflow and publish its final dossier atomically."""
    result, events = execute_host_run_import(payload)
    return _completed_publication_response(result, events, presentation_mode=presentation_mode)


def prepare_company_research(request: dict[str, Any]) -> dict[str, Any]:
    """Return the point-in-time company-research v2 plan and strict v3 schema."""
    return prepare_company_research_request(request)


def import_company_research(
    payload: dict[str, Any],
    presentation_mode: Literal["auto", "path_only"] | None = None,
) -> dict[str, Any]:
    """Validate and atomically publish one completed evidence-first v3 dossier."""
    result, events = execute_company_research_import(payload)
    return _completed_publication_response(result, events, presentation_mode=presentation_mode)


def prepare_company_analytics(
    request: dict[str, Any],
    research_pack_id: str = "initiating-coverage.v1",
    execution_mode: str = "compatible",
) -> dict[str, Any]:
    """Return the 26-stage analytics plan and strict v4 wrapper schema."""
    return prepare_company_analytics_request(
        request,
        research_pack_id=research_pack_id,
        execution_mode=execution_mode,
    )


def import_company_analytics(
    payload: dict[str, Any],
    presentation_mode: Literal["auto", "path_only"] | None = None,
) -> dict[str, Any]:
    """Validate and atomically publish completed v3 research plus analytics sidecars."""
    result, events = execute_company_analytics_import(payload)
    return _completed_publication_response(result, events, presentation_mode=presentation_mode)


def record_research_outcome(payload: dict[str, Any]) -> dict[str, object]:
    """Append a resolved forecast outcome or correction and persist its scorecard."""
    return execute_outcome_append(payload)


def get_research_quality(run_id: str) -> dict[str, object]:
    """Return registered forecasts, append-only outcomes, and deterministic scorecards."""
    return execute_quality_query(run_id)


def create_company_research_run(
    request: dict[str, Any],
    decision_memory_enabled: bool = True,
) -> dict[str, Any]:
    """Create a durable 15-stage company-research run for the calling harness."""
    return {
        "ok": True,
        "control": COMPANY_RESEARCH_COORDINATOR.create(
            request,
            decision_memory_enabled=decision_memory_enabled,
        ),
    }


def create_company_analytics_run(
    request: dict[str, Any],
    research_pack_id: str = "initiating-coverage.v1",
    decision_memory_enabled: bool = True,
    execution_mode: str = "compatible",
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


def _coordinator_for_run(run_id: str) -> Any:
    return select_run_coordinator(
        run_id,
        COMPANY_RESEARCH_COORDINATOR,
        HOST_RUN_COORDINATOR,
        (COMPANY_ANALYTICS_COORDINATOR,),
    )


def create_host_run(
    symbol: str,
    as_of_date: str,
    asset_type: str = "stock",
    analysts: list[str] | None = None,
    debate_rounds: int = 1,
    risk_rounds: int = 1,
    output_language: str = "English",
    decision_memory_enabled: bool = True,
) -> dict[str, Any]:
    """Create a durable stage-boundary run for execution by the current host harness."""
    request = _request(
        symbol,
        as_of_date,
        analysts,
        debate_rounds,
        risk_rounds,
        "host_native",
        asset_type,
        output_language=output_language,
    )
    return {
        "ok": True,
        "control": HOST_RUN_COORDINATOR.create(request, decision_memory_enabled=decision_memory_enabled),
    }


def start_host_run(run_id: str, expected_revision: int) -> dict[str, Any]:
    """Start a prepared durable run and return its first stage contract and context."""
    return _coordinator_for_run(run_id).start(run_id, expected_revision)


def append_run_receipts(
    run_id: str,
    receipts: list[dict[str, Any]],
    expected_revision: int,
) -> dict[str, Any]:
    """Append sanitized live stage/tool observations without raw prompts, arguments, or credentials."""
    return _coordinator_for_run(run_id).append_receipts(run_id, receipts, expected_revision)


def commit_host_stage(
    run_id: str,
    stage_id: str,
    output: dict[str, Any],
    expected_revision: int,
    attempt: int | None = None,
) -> dict[str, Any]:
    """Validate and checkpoint one completed stage, then return the next stage contract."""
    return _coordinator_for_run(run_id).commit_stage(
        run_id,
        stage_id,
        output,
        expected_revision,
        attempt=attempt,
    )


def pause_host_run(run_id: str, expected_revision: int, reason: str) -> dict[str, Any]:
    """Pause a running workflow at its next portable stage boundary."""
    return {"ok": True, "control": _coordinator_for_run(run_id).pause(run_id, expected_revision, reason)}


def resume_host_run(run_id: str, expected_revision: int) -> dict[str, Any]:
    """Resume at the first incomplete stage; interrupted in-flight work is replayed."""
    return _coordinator_for_run(run_id).resume(run_id, expected_revision)


def get_run_control(run_id: str) -> dict[str, Any]:
    """Return durable status, revision, checkpoint, cancellation, and next-stage information."""
    return {"ok": True, "control": _coordinator_for_run(run_id).control(run_id)}


def poll_run_events(run_id: str, after_sequence: int = 0, limit: int = 100) -> dict[str, Any]:
    """Read live lifecycle events after a monotonic cursor."""
    return _coordinator_for_run(run_id).poll_events(run_id, after_sequence=after_sequence, limit=limit)


def request_run_cancellation(run_id: str, expected_revision: int, reason: str) -> dict[str, Any]:
    """Record cooperative cancellation intent; the host remains responsible for interrupting its work."""
    return {
        "ok": True,
        "control": _coordinator_for_run(run_id).request_cancel(run_id, expected_revision, reason),
    }


def acknowledge_run_cancellation(
    run_id: str,
    expected_revision: int,
    host_receipt_id: str,
) -> dict[str, Any]:
    """Acknowledge that the host stopped its in-flight agents/tools and make cancellation terminal."""
    return {
        "ok": True,
        "control": _coordinator_for_run(run_id).acknowledge_cancel(
            run_id,
            expected_revision,
            host_receipt_id,
        ),
    }


def finalize_host_run(
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
    run_id = _resolve_run_id(run_id)
    _require_completed_publication(run_id)
    result = RUN_STORE.get_result(run_id)
    events = RUN_STORE.get_events(run_id)
    if result is None or events is None:
        raise ValueError(f"completed run not found: {run_id}")
    if is_lifecycle_run_id(run_id):
        try:
            lifecycle_log = _coordinator_for_run(run_id).lifecycle_log(run_id)
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
    recall = HOST_RUN_COORDINATOR.decision_memory().recall(
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
    """Append a host-observed outcome/reflection to one prior research decision."""
    receipt = HOST_RUN_COORDINATOR.decision_memory().append_outcome(
        outcome=outcome,
        reflection=reflection,
        memory_id=memory_id,
        run_id=run_id,
        observed_at=observed_at,
    )
    return {"ok": True, "memory_receipt": receipt.to_dict()}


def get_conformance_report(run_id: str, upstream_path: str | None = None) -> dict[str, Any]:
    """Validate portable invariants and optionally verify pinned checkout identity."""
    run_id = _resolve_run_id(run_id)
    _require_completed_publication(run_id)
    result = RUN_STORE.get_result(run_id)
    events = RUN_STORE.get_events(run_id)
    if result is None or events is None:
        raise ValueError(f"completed run not found: {run_id}")
    report = evaluate_conformance(result, events, upstream_path=upstream_path)
    return {"ok": report.passed, "conformance": report.to_dict(), "digest": conformance_digest(report)}


def get_run(run_id: str) -> dict[str, Any]:
    """Return a compact presentation-oriented run record."""
    run_id = _resolve_run_id(run_id)
    _require_completed_publication(run_id)
    return dashboard_report(run_id)


def _resolve_run_id(run_id: str) -> str:
    if run_id != "current":
        return run_id
    return RUN_STORE.current_run_id() or run_id


def _require_completed_publication(run_id: str) -> None:
    if not is_lifecycle_run_id(run_id):
        return
    try:
        control = _coordinator_for_run(run_id).control(run_id)
    except KeyError:
        return
    if control["status"] != "completed" or control["publication_pending"]:
        raise ValueError(f"run publication is not complete: {run_id}")


def get_run_events(run_id: str) -> dict[str, Any]:
    """Return the ordered event stream for a run."""
    run_id = _resolve_run_id(run_id)
    _require_completed_publication(run_id)
    events = RUN_STORE.get_events(run_id)
    return {"ok": events is not None, "run_id": run_id, "events": [event.to_dict() for event in events or ()]}


def get_run_result(run_id: str) -> dict[str, Any]:
    """Return the full typed result for a run."""
    run_id = _resolve_run_id(run_id)
    _require_completed_publication(run_id)
    result = RUN_STORE.get_result(run_id)
    return {"ok": result is not None, "result": result.to_dict() if result else None}


def get_run_semantics(run_id: str) -> dict[str, Any]:
    """Return canonical transport-neutral semantics for a completed run."""
    run_id = _resolve_run_id(run_id)
    _require_completed_publication(run_id)
    result = RUN_STORE.get_result(run_id)
    events = RUN_STORE.get_events(run_id)
    if result is None or events is None:
        raise ValueError(f"completed run not found: {run_id}")
    return build_completed_run_semantics(result, events).to_dict()


def get_run_view(run_id: str) -> dict[str, Any]:
    """Return the complete UI-ready view for inline harness rendering."""
    run_id = _resolve_run_id(run_id)
    _require_completed_publication(run_id)
    result = RUN_STORE.get_result(run_id)
    events = RUN_STORE.get_events(run_id)
    if result is None or events is None:
        return {"ok": False, "run_id": run_id, "view": None}
    return build_run_view(
        result,
        events,
        quality_projection=quality_projection_for_result(result),
    ).to_dict()


def launch_local_dashboard(host: str = "127.0.0.1", port: int = 0, run_id: str | None = None) -> dict[str, object]:
    """Launch the Designer-owned dashboard assets on an ephemeral loopback port."""
    resolved_run_id = _resolve_run_id(run_id or "current")
    _require_completed_publication(resolved_run_id)
    return launch_dashboard(host, port, run_id=resolved_run_id)


def get_dashboard_report(run_id: str) -> dict[str, object]:
    """Return the presentation-safe summary used by the local dashboard."""
    run_id = _resolve_run_id(run_id)
    _require_completed_publication(run_id)
    return dashboard_report(run_id)


def launch_research_report(host: str = "127.0.0.1", port: int = 0, run_id: str | None = None) -> dict[str, object]:
    """Ensure the shared completed-only viewer or launch an explicitly bound compatibility server."""
    resolved_run_id = _resolve_run_id(run_id or "current")
    _require_completed_publication(resolved_run_id)
    if host == "127.0.0.1" and port == 0:
        presentation = ensure_report_viewer(resolved_run_id, mode="auto")
        return {"ok": presentation["status"] == "ready", **presentation}
    return launch_report(host, port, run_id=resolved_run_id)


def get_research_report_summary(run_id: str) -> dict[str, object]:
    """Return the presentation-safe summary for a completed research run."""
    resolved_run_id = _resolve_run_id(run_id)
    _require_completed_publication(resolved_run_id)
    return report_summary(resolved_run_id)


def create_server(*, include_legacy_metadata: bool = False) -> MCPServer:
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

    capability_tool = discover_capability
    matrix_tool = get_feature_matrix
    if include_legacy_metadata:

        def capability_tool(legacy_path: str | None = None) -> dict[str, object]:
            return discovery(legacy_path, include_legacy=True)

        def matrix_tool(legacy_path: str | None = None) -> dict[str, Any]:
            return feature_matrix(legacy_path, include_legacy=True).to_dict()

    server.tool(
        name="discover_capability",
        description="Discover executors, tools, safety boundaries, and default fixture.",
        annotations=read,
    )(capability_tool)
    server.tool(
        name="get_feature_matrix",
        description="Return implemented features, safety exclusions, and runtime readiness.",
        annotations=read,
    )(matrix_tool)
    server.tool(
        name="prepare_fixture",
        description="Validate and expand the deterministic ORCL fixture without running it.",
        annotations=read,
    )(prepare_fixture)
    server.tool(
        name="run_fixture",
        description="Run all stages deterministically and store the in-memory result and events.",
        annotations=local_write,
    )(run_fixture)
    server.tool(
        name="prepare_host_run",
        description="Return the canonical plan for the active host harness; accepts no model credentials.",
        annotations=read,
    )(prepare_host_run)
    server.tool(
        name="import_host_run",
        description="Validate completed host stage outputs and atomically publish the final dossier.",
        annotations=local_write,
    )(import_host_run)
    server.tool(
        name="prepare_company_research",
        description="Return the company-research v2 plan and frozen credential-free v3 terminal schema.",
        annotations=read,
    )(prepare_company_research)
    server.tool(
        name="import_company_research",
        description="Validate and atomically publish a completed point-in-time research_dossier.v3.",
        annotations=local_write,
    )(import_company_research)
    server.tool(
        name="prepare_company_analytics",
        description="Return the complete company-analytics v1 plan, research packs, and credential-free v4 schema.",
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
        name="create_company_research_run",
        description="Create a durable 15-stage credential-free company-research run for the calling harness.",
        annotations=local_write,
    )(create_company_research_run)
    server.tool(
        name="create_company_analytics_run",
        description="Create a durable 26-stage analytics run with a selected research pack.",
        annotations=local_write,
    )(create_company_analytics_run)
    server.tool(
        name="create_host_run",
        description="Create a durable credential-free host run with decision-memory recall.",
        annotations=local_write,
    )(create_host_run)
    server.tool(
        name="start_host_run",
        description="Start a prepared durable host, company-research, or analytics run and return its first stage.",
        annotations=local_write,
    )(start_host_run)
    server.tool(
        name="append_run_receipts",
        description="Append safe live stage/tool receipts without prompts, raw arguments, or credentials.",
        annotations=local_write,
    )(append_run_receipts)
    server.tool(
        name="commit_host_stage",
        description="Commit and checkpoint one completed portable stage, then return the next stage.",
        annotations=local_write,
    )(commit_host_stage)
    server.tool(
        name="pause_host_run",
        description="Pause a host run at its next portable stage boundary.",
        annotations=local_write,
    )(pause_host_run)
    server.tool(
        name="resume_host_run",
        description="Resume from the first incomplete portable stage; replay interrupted work.",
        annotations=local_write,
    )(resume_host_run)
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
        description="Request cooperative cancellation; the host owns interruption.",
        annotations=local_write,
    )(request_run_cancellation)
    server.tool(
        name="acknowledge_run_cancellation",
        description="Acknowledge host interruption and make cancellation terminal.",
        annotations=local_write,
    )(acknowledge_run_cancellation)
    server.tool(
        name="finalize_host_run",
        description="Validate all committed stages and atomically publish the completed dossier and sidecars.",
        annotations=local_write,
    )(finalize_host_run)
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
        description="Append a host-observed outcome and reflection to a prior research decision.",
        annotations=local_write,
    )(record_decision_outcome)
    server.tool(
        name="get_conformance_report",
        description="Validate portable observable invariants; optionally verify pinned checkout identity.",
        annotations=read,
    )(get_conformance_report)
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
    server.tool(
        name="launch_local_dashboard",
        description="Compatibility alias for launching the completed Research Dossier Viewer.",
        annotations=launch,
    )(launch_local_dashboard)
    server.tool(
        name="get_dashboard_report",
        description="Compatibility alias for the presentation-safe research report summary.",
        annotations=read,
    )(get_dashboard_report)
    return server


mcp = create_server()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
