"""Standalone StockResearchAgents contracts and analytics runtime."""

from .capabilities import discovery, feature_matrix
from .company_analytics import prepare_company_analytics, submit_company_analytics
from .company_analytics_v1 import CompanyAnalyticsResultV1
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
from .lifecycle import LifecycleStore
from .memory import DecisionMemoryStore
from .presentation import PresentationLink, ViewerDaemonPresenter
from .report_server import (
    create_report_server,
    ensure_report_viewer,
    launch_report,
    present_completed_run,
    report_summary,
)
from .research_contracts import CompanyResearchRequest, ResearchDossierV1

__all__ = [
    "Artifact",
    "CapabilityFeature",
    "CapabilitySetupError",
    "CompanyResearchRequest",
    "CompanyAnalyticsCoordinator",
    "CompanyAnalyticsResultV1",
    "FeatureCapabilityMatrix",
    "PresentationLink",
    "PROTOTYPE_NOTICE",
    "ResearchDossierV1",
    "LifecycleStore",
    "LifecycleStageExecutor",
    "DecisionMemoryStore",
    "RunEvent",
    "SCHEMA_VERSION",
    "SetupGuidance",
    "ViewerDaemonPresenter",
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
