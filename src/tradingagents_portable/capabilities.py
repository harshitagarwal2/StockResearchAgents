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


def feature_matrix(legacy_path: str | None = None) -> FeatureCapabilityMatrix:
    available = legacy_available(legacy_path)
    return FeatureCapabilityMatrix(
        features=(
            CapabilityFeature(
                "typed_contracts", SupportLevel.SUPPORTED, "Import-side-effect-free dataclass wire contracts."
            ),
            CapabilityFeature(
                "legacy_full_topology",
                SupportLevel.OPTIONAL,
                "Delegated to upstream TradingAgentsGraph; this adapter maps completed state after the run.",
            ),
            CapabilityFeature(
                "orcl_fixture",
                SupportLevel.SUPPORTED,
                "Verified deterministic and credential-free executor; synthetic ORCL data only.",
            ),
            CapabilityFeature(
                "legacy_adapter",
                SupportLevel.OPTIONAL,
                "Delegation and post-run result mapping are implemented; "
                "runtime/provider readiness is environment-dependent.",
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
                SupportLevel.UNAVAILABLE,
                "The plugin manifest and skill describe host use, but no host-native stage executor is implemented.",
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
                "implementation": "manifest_and_skill_only",
                "verification": "not_implemented",
                "ready": False,
                "checkpoint": "unavailable",
                "cancellation": "unavailable",
            },
        },
    )


def discovery(legacy_path: str | None = None) -> dict[str, object]:
    matrix = feature_matrix(legacy_path)
    return {
        "name": matrix.capability,
        "schema_version": matrix.schema_version,
        "prototype": True,
        "default_fixture": {"symbol": "ORCL", "external_credentials_required": False},
        "executors": {"fixture": True, "legacy": legacy_available(legacy_path)},
        "executor_states": matrix.runtime_readiness,
        "tools": (
            "discover_capability",
            "get_feature_matrix",
            "prepare_fixture",
            "run_fixture",
            "run_legacy",
            "get_run",
            "get_run_events",
            "get_run_result",
            "get_run_view",
            "launch_local_dashboard",
            "get_dashboard_report",
        ),
        "safety_notice": matrix.safety_notice,
    }
