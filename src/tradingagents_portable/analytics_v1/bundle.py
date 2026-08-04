"""Completed analytics sidecar that leaves research_dossier.v3 unchanged."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from tradingagents_portable.research_contracts import StrictModel, _bounded_text, _utc_timestamp, _validate_id

from .common import CalculationReceipt
from .consensus import AnalystOpinion, ConsensusSnapshot, EstimateObservation
from .events import Catalyst, EventCluster
from .fundamentals import FinancialFact, RestatementLink, StatementSnapshot
from .market_experiments import DatasetManifest, ExperimentReceipt, ExperimentSpec, FactorObservation, SplitManifest
from .positioning import InsiderTransaction, OwnershipSnapshot, ShortInterestSnapshot
from .ratios import RatioObservation
from .source_policy import SourceLicenseReceipt
from .valuation import ComparableObservation, ComparableValuation, DcfModelSpec, DcfValuation, ReverseDcfResult


@dataclass(frozen=True, slots=True)
class AnalyticsBundleV1(StrictModel):
    run_id: str
    base_submission_digest: str
    base_dossier_digest: str
    cutoff_at: str
    completed_at: str
    facts: tuple[FinancialFact, ...]
    statement_snapshots: tuple[StatementSnapshot, ...]
    restatements: tuple[RestatementLink, ...]
    ratios: tuple[RatioObservation, ...]
    calculation_receipts: tuple[CalculationReceipt, ...]
    dcf_models: tuple[DcfModelSpec, ...]
    dcf_valuations: tuple[DcfValuation, ...]
    reverse_dcf_results: tuple[ReverseDcfResult, ...]
    comparable_observations: tuple[ComparableObservation, ...]
    comparable_valuations: tuple[ComparableValuation, ...]
    analyst_opinions: tuple[AnalystOpinion, ...]
    estimates: tuple[EstimateObservation, ...]
    consensus: tuple[ConsensusSnapshot, ...]
    ownership: tuple[OwnershipSnapshot, ...]
    insider_transactions: tuple[InsiderTransaction, ...]
    short_interest: tuple[ShortInterestSnapshot, ...]
    datasets: tuple[DatasetManifest, ...]
    splits: tuple[SplitManifest, ...]
    factors: tuple[FactorObservation, ...]
    experiment_specs: tuple[ExperimentSpec, ...]
    experiments: tuple[ExperimentReceipt, ...]
    catalysts: tuple[Catalyst, ...]
    event_clusters: tuple[EventCluster, ...]
    source_licenses: tuple[SourceLicenseReceipt, ...]
    coverage_decision: Literal["supported", "insufficient_evidence", "conflicted", "policy_blocked"]
    limitations: tuple[str, ...]
    complete: Literal[True]

    def __post_init__(self) -> None:
        _validate_id(self.run_id, "run_id")
        for path, value in (
            ("base_submission_digest", self.base_submission_digest),
            ("base_dossier_digest", self.base_dossier_digest),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{path} must be a lowercase SHA-256 digest")
        cutoff = _utc_timestamp(self.cutoff_at, "cutoff_at")
        completed = _utc_timestamp(self.completed_at, "completed_at")
        if completed < cutoff:
            raise ValueError("analytics completed_at must not precede cutoff_at")
        collections = (
            self.facts,
            self.statement_snapshots,
            self.ratios,
            self.dcf_valuations,
            self.consensus,
            self.datasets,
            self.experiments,
            self.catalysts,
            self.source_licenses,
        )
        if not any(collections):
            raise ValueError("analytics bundle cannot be empty")
        if self.coverage_decision != "supported" and not self.limitations:
            raise ValueError("non-supported analytics coverage requires limitations")
        for limitation in self.limitations:
            _bounded_text(limitation, "limitations", 1_000)
        self._validate_unique_ids()
        self._validate_references(cutoff)

    def _validate_unique_ids(self) -> None:
        groups = (
            ("facts", self.facts, "fact_id"),
            ("statements", self.statement_snapshots, "snapshot_id"),
            ("ratios", self.ratios, "observation_id"),
            ("dcf_models", self.dcf_models, "model_id"),
            ("dcf", self.dcf_valuations, "valuation_id"),
            ("reverse_dcf", self.reverse_dcf_results, "result_id"),
            ("comparables", self.comparable_valuations, "valuation_id"),
            ("comparable_observations", self.comparable_observations, "observation_id"),
            ("opinions", self.analyst_opinions, "opinion_id"),
            ("estimates", self.estimates, "estimate_id"),
            ("consensus", self.consensus, "snapshot_id"),
            ("datasets", self.datasets, "dataset_id"),
            ("experiment_specs", self.experiment_specs, "experiment_id"),
            ("experiments", self.experiments, "receipt_id"),
            ("catalysts", self.catalysts, "catalyst_id"),
            ("licenses", self.source_licenses, "receipt_id"),
        )
        for name, values, attribute in groups:
            identifiers = [getattr(value, attribute) for value in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"analytics {name} IDs must be unique")

    def _validate_references(self, cutoff: datetime) -> None:
        fact_ids = {fact.fact_id for fact in self.facts}
        source_ids = {license_receipt.source_id for license_receipt in self.source_licenses}
        for fact in self.facts:
            if _utc_timestamp(fact.available_at, "fact.available_at") > cutoff:
                raise ValueError("analytics fact was unavailable at cutoff")
            if fact.source_id not in source_ids:
                raise ValueError(f"financial fact references an unlicensed source: {fact.source_id}")
        for snapshot in self.statement_snapshots:
            missing = set(snapshot.fact_ids) - fact_ids
            if missing:
                raise ValueError(f"statement snapshot references unknown facts: {sorted(missing)}")
        estimate_ids = {estimate.estimate_id for estimate in self.estimates}
        for consensus_snapshot in self.consensus:
            missing = set(consensus_snapshot.estimate_ids) - estimate_ids
            if missing:
                raise ValueError(f"consensus snapshot references unknown estimates: {sorted(missing)}")

    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode()).hexdigest()
