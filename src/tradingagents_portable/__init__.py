"""Portable, harness-neutral contracts and executors for TradingAgents."""

from typing import TYPE_CHECKING, Any

from .capabilities import discovery, feature_matrix
from .company_analytics import prepare_company_analytics, submit_company_analytics
from .company_lifecycle import CompanyResearchCoordinator
from .company_research import prepare_company_research, submit_company_research
from .conformance import evaluate_conformance
from .contracts import (
    PROTOTYPE_NOTICE,
    SCHEMA_VERSION,
    AnalystReport,
    Artifact,
    CapabilityFeature,
    DebateTurn,
    EvidenceItem,
    FeatureCapabilityMatrix,
    InstrumentIdentity,
    PortfolioDecision,
    Provenance,
    ResearchDecision,
    RiskDecision,
    RunEvent,
    RunRequest,
    RunResult,
    SetupGuidance,
    StageSpec,
    TraderDecision,
    WorkflowTopology,
)
from .errors import CapabilitySetupError
from .export import export_run_bundle
from .fixture import prepare_fixture, run_fixture
from .harness import LifecycleStageExecutor, run_sequential_company_lifecycle, run_sequential_host_workflow
from .host_native import build_host_run, prepare_host_run, submit_host_run
from .instruments import normalize_instrument_symbol
from .lifecycle import HostRunCoordinator, LifecycleStore
from .memory import DecisionMemoryStore
from .presentation import PresentationLink, ViewerDaemonPresenter
from .report_server import (
    create_report_server,
    ensure_report_viewer,
    launch_report,
    present_completed_run,
    report_summary,
)
from .research_contracts import CompanyResearchRequest, HostSubmissionV3, ResearchDossierV3
from .topology import build_legacy_topology

if TYPE_CHECKING:
    from .legacy import LegacyTradingAgentsAdapter


def __getattr__(name: str) -> Any:
    if name == "LegacyTradingAgentsAdapter":
        from .legacy import LegacyTradingAgentsAdapter

        return LegacyTradingAgentsAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AnalystReport",
    "Artifact",
    "CapabilityFeature",
    "CapabilitySetupError",
    "CompanyResearchRequest",
    "CompanyResearchCoordinator",
    "DebateTurn",
    "EvidenceItem",
    "FeatureCapabilityMatrix",
    "HostRunCoordinator",
    "HostSubmissionV3",
    "InstrumentIdentity",
    "LegacyTradingAgentsAdapter",
    "PortfolioDecision",
    "PresentationLink",
    "PROTOTYPE_NOTICE",
    "Provenance",
    "ResearchDecision",
    "ResearchDossierV3",
    "RiskDecision",
    "LifecycleStore",
    "LifecycleStageExecutor",
    "DecisionMemoryStore",
    "RunEvent",
    "RunRequest",
    "RunResult",
    "SCHEMA_VERSION",
    "SetupGuidance",
    "StageSpec",
    "TraderDecision",
    "WorkflowTopology",
    "ViewerDaemonPresenter",
    "build_host_run",
    "build_legacy_topology",
    "create_report_server",
    "discovery",
    "feature_matrix",
    "evaluate_conformance",
    "ensure_report_viewer",
    "export_run_bundle",
    "prepare_fixture",
    "prepare_company_research",
    "prepare_company_analytics",
    "prepare_host_run",
    "present_completed_run",
    "run_fixture",
    "run_sequential_company_lifecycle",
    "run_sequential_host_workflow",
    "launch_report",
    "normalize_instrument_symbol",
    "report_summary",
    "submit_host_run",
    "submit_company_research",
    "submit_company_analytics",
]
