"""Deterministic, provider-neutral company analytics sidecars."""

from .bundle import AnalyticsBundleV1
from .common import CalculationReceipt, FiscalPeriod, SourceReference
from .consensus import AnalystOpinion, ConsensusSnapshot, EstimateObservation, RatingScale
from .events import Catalyst, EventCluster, MaterialityAssessment
from .fundamentals import FinancialFact, RestatementLink, StatementSnapshot
from .market_experiments import DatasetManifest, ExperimentReceipt, ExperimentSpec, FactorObservation, SplitManifest
from .positioning import InsiderTransaction, OwnershipSnapshot, ShortInterestSnapshot
from .ratios import RatioDefinition, RatioObservation
from .source_policy import SourceLicenseReceipt
from .valuation import (
    CapitalBridge,
    ComparableObservation,
    ComparableValuation,
    DcfModelSpec,
    DcfValuation,
    ReverseDcfResult,
    SensitivityPoint,
)

__all__ = [
    "AnalystOpinion",
    "AnalyticsBundleV1",
    "CalculationReceipt",
    "CapitalBridge",
    "Catalyst",
    "ComparableObservation",
    "ComparableValuation",
    "ConsensusSnapshot",
    "DatasetManifest",
    "DcfModelSpec",
    "DcfValuation",
    "EstimateObservation",
    "EventCluster",
    "ExperimentReceipt",
    "ExperimentSpec",
    "FactorObservation",
    "FinancialFact",
    "FiscalPeriod",
    "InsiderTransaction",
    "MaterialityAssessment",
    "OwnershipSnapshot",
    "RatioDefinition",
    "RatioObservation",
    "RatingScale",
    "RestatementLink",
    "ReverseDcfResult",
    "SensitivityPoint",
    "ShortInterestSnapshot",
    "SourceLicenseReceipt",
    "SourceReference",
    "SplitManifest",
    "StatementSnapshot",
]
