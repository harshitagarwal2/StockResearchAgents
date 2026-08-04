"""Discovery and feature negotiation for portable executors."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .contracts import CapabilityFeature, FeatureCapabilityMatrix, SupportLevel
from .workflow import transition_contract_catalog, workflow_profile_catalog


def legacy_available(legacy_path: str | None = None) -> bool:
    configured = legacy_path or os.environ.get("TRADINGAGENTS_LEGACY_PATH")
    if configured:
        return (Path(configured) / "tradingagents" / "graph" / "trading_graph.py").is_file()
    return importlib.util.find_spec("tradingagents") is not None


def feature_matrix(legacy_path: str | None = None, *, include_legacy: bool = True) -> FeatureCapabilityMatrix:
    available = legacy_available(legacy_path) if include_legacy else False
    transition_contracts = transition_contract_catalog()
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
                "mcp_stdio", SupportLevel.SUPPORTED, "Discovery, runs, events, results, and dossier-viewer tools."
            ),
            CapabilityFeature(
                "loopback_dashboard",
                SupportLevel.SUPPORTED,
                "One generic Research Dossier Viewer is reused per durable state directory and binds only to "
                "127.0.0.1 or ::1; completed operations return a run-specific presentation receipt.",
            ),
            CapabilityFeature(
                "automatic_completed_presentation",
                SupportLevel.SUPPORTED,
                "CLI and MCP completion adapters return a ready loopback URL when possible, with path-only and "
                "structured unavailable fallbacks that never roll back research publication.",
            ),
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
                "evidence_first_company_research_v3",
                SupportLevel.SUPPORTED,
                "A parallel versioned profile validates point-in-time sources, claims, calculations, filings, "
                "transcripts, peers, factors, valuation, risks, monitoring, evaluation, and completed dossiers.",
            ),
            CapabilityFeature(
                "workflow_profile_negotiation",
                SupportLevel.SUPPORTED,
                "Discovery advertises frozen legacy v1/v2, company-research v2/v3, and the parallel "
                "company-analytics v1 extension.",
            ),
            CapabilityFeature(
                "company_analytics_v1",
                SupportLevel.SUPPORTED,
                "A parallel outer profile adds source-policy receipts, point-in-time fundamentals, ratios, DCF, "
                "reverse DCF, comparables, consensus, positioning, catalysts, experiments, hypotheses, forecasts, "
                "and research-quality receipts without widening research_dossier.v3.",
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
                "portable_cli_interaction_coverage",
                SupportLevel.PARTIAL,
                "Local tests cover portable CLI setup, stages, receipts, status, resume, cancellation, memory, "
                "export, and final dashboard publication. Upstream interaction parity remains externally gated "
                "and is not claimed by this local coverage.",
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
                "research_data_adapter_contracts",
                SupportLevel.PARTIAL,
                "The isolated research-data MCP implements SourceBatch v1 and six default public tools; licensed "
                "market data and lawful social providers remain optional host-conformance surfaces.",
            ),
            CapabilityFeature(
                "legacy_executor_transition",
                SupportLevel.OPTIONAL,
                "The pinned legacy oracle remains retained and executor removal is blocked until every published "
                "hard gate is verified and passed.",
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
            "company_research_v2": {
                "implementation": "durable_fifteen_stage_evidence_first_coordinator",
                "verification": "locally_verified_with_multi_symbol_complete_dossiers",
                "ready": True,
                "portable_boundary_credentials_required": False,
                "host_tool_auth": "host_owned_unknown",
                "execution_owner": "host_harness",
                "event_delivery": "live_cursor_receipts",
                "checkpoint": "durable_portable_stage_boundaries",
                "cancellation": "cooperative_request_and_host_acknowledgement",
                "decision_memory": "optional_when_a_host_configures_a_portable_memory_store",
                "publication": "strict_conformance_gated_completed_dossier_only",
            },
            "company_analytics_v1": {
                "implementation": "durable_twenty_six_stage_outer_profile_plus_completed_sidecars",
                "verification": "locally_verified_with_checkpoint_resume_and_crash_recoverable_publication",
                "ready": True,
                "portable_boundary_credentials_required": False,
                "execution_owner": "host_harness",
                "capability_modes": ["full", "compatible", "tools_only"],
                "capability_mode_readiness": {
                    "full": "adapter_required",
                    "compatible": "locally_ready",
                    "tools_only": "partial_adapter_required",
                },
                "event_delivery": "live_cursor_receipts",
                "checkpoint": "durable_portable_stage_boundaries",
                "cancellation": "cooperative_request_and_host_acknowledgement",
                "decision_memory": "optional_publication_gated_recall_and_outcomes",
                "publication": "single_atomic_completed_result",
                "presentation": "automatic_shared_completed_only_viewer_with_path_only_fallback",
                "live_provider_coverage": "host_owned_and_not_implied",
            },
            "research_data_adapters": {
                "implementation": "isolated_sourcebatch_v1_mcp_with_six_default_public_tools",
                "verification": "locally_verified_public_adapter_and_registration_contracts",
                "ready": False,
                "ready_for_default_public_tools": True,
                "ready_for_full_live_company_research": False,
                "tools_only_live_company_research": "partial",
                "surface_exposed": True,
                "server": "tradingagents-research-data",
                "coordination_mcp_exposed": False,
                "default_capabilities": [
                    "regulatory_filings",
                    "fundamentals",
                    "financial_statements",
                    "company_news",
                    "global_news",
                    "macro",
                ],
                "host_gated_capabilities": ["prices", "indicators", "reddit"],
                "denied_unregistered_capabilities": ["stocktwits"],
                "auth_owner": "host",
                "provider_selection_owner": "host",
                "contract": transition_contracts["research_data_tools"],
            },
            "legacy_transition": {
                "implementation": "authoritative_transition_metadata",
                "verification": "all_removal_gates_unverified",
                "ready_for_removal": False,
                "current_phase": transition_contracts["legacy_transition"]["current_phase"],
                "contract": transition_contracts["legacy_transition"],
            },
        },
    )


def discovery(legacy_path: str | None = None, *, include_legacy: bool = True) -> dict[str, object]:
    matrix = feature_matrix(legacy_path, include_legacy=include_legacy)
    transition_contracts = transition_contract_catalog()
    tools = [
        "discover_capability",
        "get_feature_matrix",
        "prepare_fixture",
        "run_fixture",
        "prepare_host_run",
        "import_host_run",
        "prepare_company_research",
        "import_company_research",
        "prepare_company_analytics",
        "import_company_analytics",
        "record_research_outcome",
        "get_research_quality",
        "create_company_research_run",
        "create_company_analytics_run",
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
        "get_run_semantics",
        "get_run_view",
        "launch_research_report",
        "get_research_report_summary",
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
        "workflow_profiles": workflow_profile_catalog(),
        "transition_contracts": transition_contracts,
        "tools": tuple(tools),
        "safety_notice": matrix.safety_notice,
    }
