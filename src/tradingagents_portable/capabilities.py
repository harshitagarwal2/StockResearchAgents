"""Discovery and feature negotiation for portable executors."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .contracts import CapabilityFeature, FeatureCapabilityMatrix, SupportLevel


def legacy_available(legacy_path: str | None = None) -> bool:
    configured = legacy_path or os.environ.get("TRADINGAGENTS_LEGACY_PATH")
    if configured:
        return (Path(configured) / "tradingagents" / "graph" / "trading_graph.py").is_file()
    return importlib.util.find_spec("tradingagents") is not None


def feature_matrix(legacy_path: str | None = None, *, include_legacy: bool = True) -> FeatureCapabilityMatrix:
    available = legacy_available(legacy_path) if include_legacy else False
    return FeatureCapabilityMatrix(
        features=(
            CapabilityFeature(
                "typed_contracts", SupportLevel.SUPPORTED, "Import-side-effect-free dataclass wire contracts."
            ),
            CapabilityFeature(
                "legacy_full_topology",
                SupportLevel.OPTIONAL if include_legacy else SupportLevel.UNAVAILABLE,
                (
                    "Delegated to upstream TradingAgentsGraph; this adapter maps completed state after the run."
                    if include_legacy
                    else "Not exposed by the credential-free MCP; use the explicit standalone compatibility CLI."
                ),
            ),
            CapabilityFeature(
                "orcl_fixture",
                SupportLevel.SUPPORTED,
                "Verified deterministic and credential-free executor; synthetic ORCL data only.",
            ),
            CapabilityFeature(
                "legacy_adapter",
                SupportLevel.OPTIONAL if include_legacy else SupportLevel.UNAVAILABLE,
                (
                    "Delegation and post-run result mapping are implemented; "
                    "runtime/provider readiness is environment-dependent."
                    if include_legacy
                    else "Excluded from this credential-free server surface."
                ),
            ),
            CapabilityFeature(
                "mcp_stdio", SupportLevel.SUPPORTED, "Discovery, runs, events, results, and dashboard tools."
            ),
            CapabilityFeature("loopback_dashboard", SupportLevel.SUPPORTED, "Binds only to 127.0.0.1 or ::1."),
            CapabilityFeature(
                "checkpoint_resume",
                SupportLevel.OPTIONAL,
                "Delegated to upstream when explicitly enabled; not runtime-verified by this prototype.",
            ),
            CapabilityFeature(
                "live_stage_streaming",
                SupportLevel.UNAVAILABLE,
                "Legacy events are post-run projections until upstream exposes an observer seam.",
            ),
            CapabilityFeature(
                "host_native_executor",
                SupportLevel.SUPPORTED,
                "The host owns reasoning; a strict credential-free import boundary validates "
                "and publishes the final dossier.",
            ),
            CapabilityFeature(
                "run_cancellation",
                SupportLevel.UNAVAILABLE,
                "Neither fixture nor legacy execution currently exposes a cancellation contract.",
            ),
            CapabilityFeature(
                "broker_order_execution",
                SupportLevel.PROHIBITED,
                "Safety exclusion: this research prototype never submits or manages orders.",
            ),
        ),
        runtime_readiness={
            "fixture": {
                "implementation": "implemented",
                "verification": "verified",
                "ready": True,
                "credentials_required": False,
                "event_delivery": "in_process_ordered_events",
                "checkpoint": "not_applicable",
                "cancellation": "unavailable",
            },
            "legacy_upstream": {
                "implementation": "implemented_thin_adapter",
                "surface_exposed": include_legacy,
                "result_mapping": "implemented_post_run",
                "verification": "runtime_unverified",
                "ready": available,
                "credentials": "environment_only_and_runtime_unverified",
                "event_delivery": "post_run_projection",
                "live_stage_streaming": "unavailable_without_upstream_observer_seam",
                "checkpoint": "delegated_opt_in_runtime_unverified",
                "cancellation": "unavailable",
                "detail": "Importability does not prove provider credentials, data access, or a successful live run.",
            },
            "host_native": {
                "implementation": "stateless_plan_and_atomic_import",
                "verification": "locally_verified",
                "ready": True,
                "credentials_required": False,
                "execution_owner": "host_harness",
                "event_delivery": "post_run_import_receipts",
                "checkpoint": "unavailable",
                "cancellation": "unavailable",
            },
        },
    )


def discovery(legacy_path: str | None = None, *, include_legacy: bool = True) -> dict[str, object]:
    matrix = feature_matrix(legacy_path, include_legacy=include_legacy)
    tools = [
        "discover_capability",
        "get_feature_matrix",
        "prepare_fixture",
        "run_fixture",
        "prepare_host_run",
        "import_host_run",
        "get_run",
        "get_run_events",
        "get_run_result",
        "get_run_view",
        "launch_local_dashboard",
        "get_dashboard_report",
    ]
    if include_legacy:
        tools.insert(6, "run_legacy")
    return {
        "name": matrix.capability,
        "schema_version": matrix.schema_version,
        "prototype": True,
        "default_fixture": {"symbol": "ORCL", "external_credentials_required": False},
        "executors": {
            "fixture": True,
            "host_native": True,
            "legacy": legacy_available(legacy_path) if include_legacy else False,
        },
        "executor_states": matrix.runtime_readiness,
        "tools": tuple(tools),
        "safety_notice": matrix.safety_notice,
    }
