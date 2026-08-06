"""Standalone StockResearchAgents contracts and analytics runtime."""

from .application import CompletedPublicationService, CompletedRunQueryService, StockResearchApplication
from .bootstrap import ApplicationRuntime, create_company_analytics_coordinator
from .capabilities import discovery, feature_matrix
from .company_analytics import prepare_company_analytics, submit_company_analytics
from .company_analytics_v1 import CompanyAnalyticsResultV1, CompanyAnalyticsWorkflowDefinition
from .company_lifecycle import CompanyAnalyticsCoordinator
from .conformance import evaluate_validation
from .contracts import (
    PROTOTYPE_NOTICE,
    SCHEMA_VERSION,
    Artifact,
    CapabilityFeature,
    FeatureCapabilityMatrix,
    RunEvent,
    SetupGuidance,
)
from .errors import CapabilitySetupError
from .export import export_run_bundle
from .harness import LifecycleStageExecutor, run_sequential_company_lifecycle
from .instruments import normalize_instrument_symbol
from .lifecycle import LifecycleRecordV1, LifecycleStore
from .memory import DecisionMemoryStore, ResearchHistoryRepository
from .presentation import PresentationLink, ViewerDaemonPresenter
from .report_server import (
    create_report_server,
    ensure_report_viewer,
    launch_report,
    present_completed_run,
    report_summary,
)
from .research_contracts import CompanyResearchRequest, ResearchDossierV1
from .state import StateLayout

__all__ = [
    "ApplicationRuntime",
    "Artifact",
    "CapabilityFeature",
    "CapabilitySetupError",
    "CompanyResearchRequest",
    "CompanyAnalyticsCoordinator",
    "CompanyAnalyticsResultV1",
    "CompanyAnalyticsWorkflowDefinition",
    "CompletedPublicationService",
    "CompletedRunQueryService",
    "FeatureCapabilityMatrix",
    "PresentationLink",
    "PROTOTYPE_NOTICE",
    "ResearchDossierV1",
    "LifecycleStore",
    "LifecycleRecordV1",
    "LifecycleStageExecutor",
    "DecisionMemoryStore",
    "ResearchHistoryRepository",
    "RunEvent",
    "SCHEMA_VERSION",
    "SetupGuidance",
    "StateLayout",
    "StockResearchApplication",
    "ViewerDaemonPresenter",
    "create_company_analytics_coordinator",
    "create_report_server",
    "discovery",
    "feature_matrix",
    "evaluate_validation",
    "ensure_report_viewer",
    "export_run_bundle",
    "prepare_company_analytics",
    "present_completed_run",
    "run_sequential_company_lifecycle",
    "launch_report",
    "normalize_instrument_symbol",
    "report_summary",
    "submit_company_analytics",
]
