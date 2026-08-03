"""Portable, harness-neutral contracts and executors for TradingAgents."""

from .capabilities import discovery, feature_matrix
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
from .fixture import prepare_fixture, run_fixture
from .legacy import LegacyTradingAgentsAdapter
from .topology import build_legacy_topology

__all__ = [
    "AnalystReport",
    "Artifact",
    "CapabilityFeature",
    "CapabilitySetupError",
    "DebateTurn",
    "EvidenceItem",
    "FeatureCapabilityMatrix",
    "InstrumentIdentity",
    "LegacyTradingAgentsAdapter",
    "PortfolioDecision",
    "PROTOTYPE_NOTICE",
    "Provenance",
    "ResearchDecision",
    "RiskDecision",
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
    "prepare_fixture",
    "run_fixture",
]
