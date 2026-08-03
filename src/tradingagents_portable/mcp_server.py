"""MCP stdio surface for the portable TradingAgents capability."""

from __future__ import annotations

from typing import Any

from .capabilities import discovery, feature_matrix
from .contracts import RunRequest
from .dashboard import dashboard_report, launch_dashboard
from .fixture import prepare_fixture as prepare_fixture_request
from .fixture import run_fixture as execute_fixture
from .host_native import prepare_host_run as prepare_host_run_request
from .host_native import submit_host_run as execute_host_run_import
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
) -> dict[str, Any]:
    """Run every legacy stage deterministically with synthetic ORCL evidence."""
    result, events = execute_fixture(_request("ORCL", as_of_date, analysts, debate_rounds, risk_rounds, "fixture"))
    return {"ok": True, "result": result.to_dict(), "events": [event.to_dict() for event in events]}


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


def import_host_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a completed host-executed workflow and publish its final dossier atomically."""
    result, events = execute_host_run_import(payload)
    return {
        "ok": True,
        "result": result.to_dict(),
        "events": [event.to_dict() for event in events],
        "view": build_run_view(result, events).to_dict(),
        "dashboard_path": f"/?run={result.run_id}",
    }


def get_run(run_id: str) -> dict[str, Any]:
    """Return a compact dashboard-oriented run record."""
    return dashboard_report(run_id)


def _resolve_run_id(run_id: str) -> str:
    if run_id != "current":
        return run_id
    return RUN_STORE.current_run_id() or run_id


def get_run_events(run_id: str) -> dict[str, Any]:
    """Return the ordered event stream for a run."""
    run_id = _resolve_run_id(run_id)
    events = RUN_STORE.get_events(run_id)
    return {"ok": events is not None, "run_id": run_id, "events": [event.to_dict() for event in events or ()]}


def get_run_result(run_id: str) -> dict[str, Any]:
    """Return the full typed result for a run."""
    run_id = _resolve_run_id(run_id)
    result = RUN_STORE.get_result(run_id)
    return {"ok": result is not None, "result": result.to_dict() if result else None}


def get_run_view(run_id: str) -> dict[str, Any]:
    """Return the complete UI-ready view for inline harness rendering."""
    run_id = _resolve_run_id(run_id)
    result = RUN_STORE.get_result(run_id)
    events = RUN_STORE.get_events(run_id)
    if result is None or events is None:
        return {"ok": False, "run_id": run_id, "view": None}
    return build_run_view(result, events).to_dict()


def launch_local_dashboard(host: str = "127.0.0.1", port: int = 0, run_id: str | None = None) -> dict[str, object]:
    """Launch the Designer-owned dashboard assets on an ephemeral loopback port."""
    return launch_dashboard(host, port, run_id=run_id)


def get_dashboard_report(run_id: str) -> dict[str, object]:
    """Return the presentation-safe summary used by the local dashboard."""
    return dashboard_report(run_id)


def create_server(*, include_legacy_metadata: bool = False) -> MCPServer:
    server = MCPServer(
        "TradingAgents Portable",
        version="0.1.0",
        instructions=(
            "Prototype financial research only. Fixture values are synthetic. "
            "This server never submits, manages, or authorizes orders."
        ),
    )
    read = _annotations(read_only=True, idempotent=True, open_world=False)
    local_write = _annotations(read_only=False, idempotent=True, open_world=False)
    launch = _annotations(read_only=False, idempotent=False, open_world=False)

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
        name="get_run",
        description="Return a compact dashboard-oriented run record.",
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
        name="get_run_view",
        description="Return the complete UI-ready run projection for inline harness rendering.",
        annotations=read,
    )(get_run_view)
    server.tool(
        name="launch_local_dashboard",
        description="Serve the local dashboard assets and JSON APIs on loopback.",
        annotations=launch,
    )(launch_local_dashboard)
    server.tool(
        name="get_dashboard_report",
        description="Return the presentation-safe dashboard summary for a run.",
        annotations=read,
    )(get_dashboard_report)
    return server


mcp = create_server()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
