"""MCP stdio surface for the portable TradingAgents capability."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .capabilities import discovery, feature_matrix
from .contracts import RunRequest, reject_secret_shaped_keys, sanitize_legacy_config
from .dashboard import dashboard_report, launch_dashboard
from .errors import CapabilitySetupError
from .fixture import prepare_fixture as prepare_fixture_request
from .fixture import run_fixture as execute_fixture
from .legacy import LegacyTradingAgentsAdapter
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


def _reject_secret_shaped_keys(value: object, path: tuple[str, ...] = ()) -> None:
    """Reject credential-shaped mapping keys at any nesting depth."""
    reject_secret_shaped_keys(value, path)


def _safe_legacy_config(config: Mapping[str, object] | None) -> dict[str, object]:
    return sanitize_legacy_config(config)


def _request(
    symbol: str,
    as_of_date: str,
    analysts: list[str] | None,
    debate_rounds: int,
    risk_rounds: int,
    executor: str,
    asset_type: str = "stock",
    checkpoint_enabled: bool = False,
    legacy_config: Mapping[str, object] | None = None,
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
        executor=executor,  # type: ignore[arg-type]
        checkpoint_enabled=checkpoint_enabled,
        legacy_config=_safe_legacy_config(legacy_config),
    )


def discover_capability(legacy_path: str | None = None) -> dict[str, object]:
    """Discover executors, tools, safety boundaries, and the default fixture."""
    return discovery(legacy_path)


def get_feature_matrix(legacy_path: str | None = None) -> dict[str, Any]:
    """Return supported, optional, and intentionally unavailable features."""
    return feature_matrix(legacy_path).to_dict()


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


def run_legacy(
    symbol: str,
    as_of_date: str,
    asset_type: str = "auto",
    analysts: list[str] | None = None,
    debate_rounds: int | None = None,
    risk_rounds: int | None = None,
    checkpoint_enabled: bool | None = None,
    legacy_path: str | None = None,
    llm_provider: str | None = None,
    deep_think_llm: str | None = None,
    quick_think_llm: str | None = None,
    backend_url: str | None = None,
    output_language: str | None = None,
    temperature: float | None = None,
    llm_max_retries: int | None = None,
    google_thinking_level: str | None = None,
    openai_reasoning_effort: str | None = None,
    anthropic_effort: str | None = None,
    report_output_path: str | None = None,
) -> dict[str, Any]:
    """Delegate upstream with typed non-secret config; credentials come only from the environment."""
    try:
        adapter = LegacyTradingAgentsAdapter(legacy_path)
        canonical_symbol, resolved_asset_type = adapter.resolve_subject(symbol, asset_type)
        defaults = adapter.defaults()
        resolved_debate_rounds = debate_rounds if debate_rounds is not None else int(defaults["max_debate_rounds"])
        resolved_risk_rounds = risk_rounds if risk_rounds is not None else int(defaults["max_risk_discuss_rounds"])
        resolved_checkpoint = (
            checkpoint_enabled if checkpoint_enabled is not None else bool(defaults.get("checkpoint_enabled", False))
        )
        legacy_config = {
            "llm_provider": llm_provider,
            "deep_think_llm": deep_think_llm,
            "quick_think_llm": quick_think_llm,
            "backend_url": backend_url,
            "output_language": output_language,
            "temperature": temperature,
            "llm_max_retries": llm_max_retries,
            "google_thinking_level": google_thinking_level,
            "openai_reasoning_effort": openai_reasoning_effort,
            "anthropic_effort": anthropic_effort,
            "report_output_path": report_output_path,
        }
        request = _request(
            canonical_symbol,
            as_of_date,
            analysts,
            resolved_debate_rounds,
            resolved_risk_rounds,
            "legacy",
            resolved_asset_type,
            resolved_checkpoint,
            legacy_config,
        )
        result, events = adapter.run(request)
        return {"ok": True, "result": result.to_dict(), "events": [event.to_dict() for event in events]}
    except CapabilitySetupError as exc:
        return exc.to_dict()


def get_run(run_id: str) -> dict[str, Any]:
    """Return a compact dashboard-oriented run record."""
    return dashboard_report(run_id)


def get_run_events(run_id: str) -> dict[str, Any]:
    """Return the ordered event stream for a run."""
    events = RUN_STORE.get_events(run_id)
    return {"ok": events is not None, "run_id": run_id, "events": [event.to_dict() for event in events or ()]}


def get_run_result(run_id: str) -> dict[str, Any]:
    """Return the full typed result for a run."""
    result = RUN_STORE.get_result(run_id)
    return {"ok": result is not None, "result": result.to_dict() if result else None}


def get_run_view(run_id: str) -> dict[str, Any]:
    """Return the complete UI-ready view for inline harness rendering."""
    result = RUN_STORE.get_result(run_id)
    events = RUN_STORE.get_events(run_id)
    if result is None or events is None:
        return {"ok": False, "run_id": run_id, "view": None}
    return build_run_view(result, events).to_dict()


def launch_local_dashboard(host: str = "127.0.0.1", port: int = 0) -> dict[str, object]:
    """Launch the Designer-owned dashboard assets on an ephemeral loopback port."""
    return launch_dashboard(host, port)


def get_dashboard_report(run_id: str) -> dict[str, object]:
    """Return the presentation-safe summary used by the local dashboard."""
    return dashboard_report(run_id)


def create_server() -> MCPServer:
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
    legacy_write = _annotations(read_only=False, idempotent=False, open_world=True)
    launch = _annotations(read_only=False, idempotent=False, open_world=False)

    server.tool(
        name="discover_capability",
        description="Discover executors, tools, safety boundaries, and default fixture.",
        annotations=read,
    )(discover_capability)
    server.tool(
        name="get_feature_matrix",
        description="Return implemented features, safety exclusions, and runtime readiness.",
        annotations=read,
    )(get_feature_matrix)
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
        name="run_legacy",
        description=(
            "Delegate to upstream TradingAgentsGraph with typed non-secret settings. "
            "Provider credentials are accepted only through the server environment."
        ),
        annotations=legacy_write,
    )(run_legacy)
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
