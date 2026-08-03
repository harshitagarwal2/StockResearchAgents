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
                "decision_schema_parity",
                SupportLevel.SUPPORTED,
                "Research Manager and Portfolio Manager use five-tier ratings; Trader uses Buy/Hold/Sell.",
            ),
            CapabilityFeature(
                "structured_trader_proposal",
                SupportLevel.SUPPORTED,
                "Preserves action, reasoning, entry price, stop loss, sizing scenario, and raw Markdown.",
            ),
            CapabilityFeature(
                "structured_portfolio_rating",
                SupportLevel.SUPPORTED,
                "Preserves rating, executive summary, thesis, target, horizon, and raw Markdown.",
            ),
            CapabilityFeature(
                "legacy_full_topology",
                SupportLevel.SUPPORTED,
                "The manifest and durable coordinator cover every analyst, debate, manager, trader, risk, and "
                "portfolio stage; the host supplies reasoning through its own agents or sequential fallback.",
            ),
            CapabilityFeature(
                "orcl_fixture",
                SupportLevel.SUPPORTED,
                "Verified deterministic and credential-free executor; synthetic ORCL data only.",
            ),
            CapabilityFeature(
                "legacy_adapter",
                SupportLevel.OPTIONAL,
                (
                    "Delegation and post-run result mapping are implemented; "
                    "runtime/provider readiness is environment-dependent."
                    if include_legacy
                    else "Implemented as a separate opt-in compatibility executable and intentionally excluded "
                    "from this credential-free plugin server."
                ),
            ),
            CapabilityFeature(
                "mcp_stdio", SupportLevel.SUPPORTED, "Discovery, runs, events, results, and dashboard tools."
            ),
            CapabilityFeature("loopback_dashboard", SupportLevel.SUPPORTED, "Binds only to 127.0.0.1 or ::1."),
            CapabilityFeature(
                "checkpoint_resume",
                SupportLevel.SUPPORTED,
                "Durable SQLite/WAL lifecycle checkpoints resume at the first incomplete portable stage; an "
                "interrupted in-flight stage is replayed.",
            ),
            CapabilityFeature(
                "live_stage_streaming",
                SupportLevel.SUPPORTED,
                "Hosts append sanitized stage/tool receipts and consumers read them through a monotonic cursor; "
                "raw prompts, arguments, credentials, and transcripts stay host-owned.",
            ),
            CapabilityFeature(
                "host_native_plan_import",
                SupportLevel.SUPPORTED,
                "The host owns execution and reasoning; a strict credential-free import boundary validates "
                "and publishes the final dossier.",
            ),
            CapabilityFeature(
                "native_dynamic_tool_routing",
                SupportLevel.SUPPORTED,
                "The manifest declares allowed capabilities per stage and the lifecycle validates live tool "
                "receipts; concrete tool invocation remains correctly owned by each harness.",
            ),
            CapabilityFeature(
                "decision_memory_semantics",
                SupportLevel.SUPPORTED,
                "Durable decision memory recalls up to five same-symbol and three cross-symbol published decisions "
                "for the Portfolio stage and accepts later host-observed outcomes/reflections.",
            ),
            CapabilityFeature(
                "durable_native_run_store",
                SupportLevel.SUPPORTED,
                "Atomic JSON result/event storage plus SQLite/WAL lifecycle state survive process restarts.",
            ),
            CapabilityFeature(
                "upstream_cli_interaction_parity",
                SupportLevel.SUPPORTED,
                "Portable CLI commands cover interactive setup, stages, receipts, status, resume, cancellation, "
                "memory, export, and final dashboard publication without copying terminal pixels.",
            ),
            CapabilityFeature(
                "run_cancellation",
                SupportLevel.SUPPORTED,
                "Portable cancellation is a cooperative request/host-acknowledgement protocol; each harness owns "
                "the actual interruption of its agents and tools.",
            ),
            CapabilityFeature(
                "filesystem_report_export",
                SupportLevel.SUPPORTED,
                "First publication is atomic; validated prior-bundle replacement is journaled and crash-recoverable. "
                "Bundles include the report tree, result, events, sanitized lifecycle log, and SHA-256 manifest.",
            ),
            CapabilityFeature(
                "portable_observable_conformance",
                SupportLevel.SUPPORTED,
                "Credential-free portable-invariant checks cover workflow order/counts, schemas, signals, evidence, "
                "report groups, and linked receipts; an optional checkout separately verifies the pinned revision.",
            ),
            CapabilityFeature(
                "pinned_upstream_identity",
                SupportLevel.SUPPORTED,
                "When an upstream checkout is supplied, its Git identity is compared with the pinned revision; "
                "this does not derive or prove upstream model behavior.",
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
                "cancellation": "cooperative_lifecycle_when_run_through_host_coordinator",
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
                "implementation": "durable_stage_boundary_coordinator_plus_atomic_canonical_bundle_import",
                "verification": "locally_verified",
                "ready": True,
                "portable_boundary_credentials_required": False,
                "host_tool_auth": "host_owned_unknown",
                "execution_owner": "host_harness",
                "event_delivery": "live_cursor_receipts",
                "checkpoint": "durable_portable_stage_boundaries",
                "cancellation": "cooperative_request_and_host_acknowledgement",
                "decision_memory": "durable_publication_gated_bounded_recall_and_outcomes",
                "report_export": "atomic_first_publish_and_journaled_recoverable_overwrite",
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
        "create_host_run",
        "start_host_run",
        "append_run_receipts",
        "commit_host_stage",
        "pause_host_run",
        "resume_host_run",
        "get_run_control",
        "poll_run_events",
        "request_run_cancellation",
        "acknowledge_run_cancellation",
        "finalize_host_run",
        "export_completed_run",
        "query_decision_memory",
        "record_decision_outcome",
        "get_conformance_report",
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
