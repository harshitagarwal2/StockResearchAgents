"""Standalone capability discovery for StockResearchAgents."""

from __future__ import annotations

from .contracts import CapabilityFeature, FeatureCapabilityMatrix, SupportLevel
from .workflow import integration_contract_catalog, workflow_profile_catalog


def feature_matrix() -> FeatureCapabilityMatrix:
    """Describe only capabilities implemented by this repository."""

    integration_contracts = integration_contract_catalog()
    return FeatureCapabilityMatrix(
        features=(
            CapabilityFeature(
                "typed_contracts",
                SupportLevel.SUPPORTED,
                "Strict credential-free contracts validate every StockResearchAgents boundary.",
            ),
            CapabilityFeature(
                "company_analytics_v1",
                SupportLevel.SUPPORTED,
                "A standalone 26-stage evidence, analytics, evaluation, and completed-publication workflow.",
            ),
            CapabilityFeature(
                "durable_lifecycle",
                SupportLevel.SUPPORTED,
                "Ordered optimistic commits, pause and crash recovery, terminal cancellation, "
                "and recoverable publication.",
            ),
            CapabilityFeature(
                "source_lineage",
                SupportLevel.SUPPORTED,
                "Provider-neutral source batches bind identity, digest scope, entitlement, and point-in-time evidence.",
            ),
            CapabilityFeature(
                "research_quality",
                SupportLevel.SUPPORTED,
                "Forecasts, outcomes, scorecards, and quality receipts are versioned standalone sidecars.",
            ),
            CapabilityFeature(
                "research_data_adapter_contracts",
                SupportLevel.PARTIAL,
                "Seven public research-data tools are implemented; entitled providers remain host-owned adapters.",
            ),
            CapabilityFeature(
                "mcp_stdio",
                SupportLevel.SUPPORTED,
                "Coordination and research-data MCP servers expose StockResearchAgents-owned tools and identities.",
            ),
            CapabilityFeature(
                "completed_only_presentation",
                SupportLevel.SUPPORTED,
                "The viewer, exports, CLI, and MCP expose only atomically completed research results.",
            ),
            CapabilityFeature(
                "decision_memory",
                SupportLevel.SUPPORTED,
                "Publication-gated bounded recall and later external outcomes preserve point-in-time constraints.",
            ),
            CapabilityFeature(
                "broker_order_execution",
                SupportLevel.PROHIBITED,
                "StockResearchAgents never submits orders, mutates portfolios, or grants execution authority.",
            ),
        ),
        runtime_readiness={
            "company_analytics_v1": {
                "implementation": "durable_twenty_six_stage_workflow",
                "verification": "locally_verified_with_recovery_and_atomic_publication",
                "ready": True,
                "core_boundary_credentials_required": False,
                "execution_owner": "caller",
                "execution_modes": ["native", "sequential", "import"],
                "event_delivery": "live_cursor_receipts",
                "checkpoint": "durable_ordered_stage_boundaries",
                "cancellation": "cooperative_request_and_execution_acknowledgement",
                "publication": "single_atomic_completed_result",
            },
            "research_data_adapters": {
                "implementation": "isolated_sourcebatch_v1_mcp_with_seven_default_public_tools",
                "verification": "locally_verified_contracts",
                "ready_for_default_public_tools": True,
                "ready_for_full_live_company_research": False,
                "execution_owner": "host",
                "contract": integration_contracts["research_data_tools"],
            },
        },
    )


def discovery() -> dict[str, object]:
    """Return the standalone public capability surface."""

    matrix = feature_matrix()
    return {
        "name": "stock-research-agents",
        "schema_version": matrix.schema_version,
        "prototype": True,
        "active_profile": "company-analytics.v1",
        "executor_states": matrix.runtime_readiness,
        "workflow_profiles": workflow_profile_catalog(),
        "integration_contracts": integration_contract_catalog(),
        "tools": (
            "discover_capability",
            "get_feature_matrix",
            "prepare_company_analytics",
            "import_company_analytics",
            "record_research_outcome",
            "get_research_quality",
            "create_company_analytics_run",
            "start_run",
            "append_run_receipts",
            "commit_run_stage",
            "pause_run",
            "resume_run",
            "get_run_control",
            "poll_run_events",
            "request_run_cancellation",
            "acknowledge_run_cancellation",
            "finalize_run",
            "export_completed_run",
            "query_decision_memory",
            "record_decision_outcome",
            "get_validation_report",
            "get_run",
            "get_run_events",
            "get_run_result",
            "get_run_semantics",
            "get_run_view",
            "launch_research_report",
            "get_research_report_summary",
        ),
        "safety_notice": matrix.safety_notice,
    }
