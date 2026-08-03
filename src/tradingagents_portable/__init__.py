"""Portable, harness-neutral contracts and executors for TradingAgents."""

from typing import TYPE_CHECKING, Any

from .capabilities import discovery, feature_matrix
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
from .harness import run_sequential_host_workflow
from .host_native import prepare_host_run, submit_host_run
from .lifecycle import HostRunCoordinator, LifecycleStore
from .memory import DecisionMemoryStore
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
    "DebateTurn",
    "EvidenceItem",
    "FeatureCapabilityMatrix",
    "HostRunCoordinator",
    "InstrumentIdentity",
    "LegacyTradingAgentsAdapter",
    "PortfolioDecision",
    "PROTOTYPE_NOTICE",
    "Provenance",
    "ResearchDecision",
    "RiskDecision",
    "LifecycleStore",
    "DecisionMemoryStore",
    "RunEvent",
    "RunRequest",
    "RunResult",
    "SCHEMA_VERSION",
    "SetupGuidance",
    "StageSpec",
    "TraderDecision",
    "WorkflowTopology",
    "build_legacy_topology",
    "discovery",
    "feature_matrix",
    "evaluate_conformance",
    "export_run_bundle",
    "prepare_fixture",
    "prepare_host_run",
    "run_fixture",
    "run_sequential_host_workflow",
    "submit_host_run",
]
