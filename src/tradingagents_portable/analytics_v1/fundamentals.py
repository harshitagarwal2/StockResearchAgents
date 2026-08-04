"""Point-in-time fundamental facts and restatement lineage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tradingagents_portable.research_contracts import StrictModel, _bounded_text, _utc_timestamp, _validate_id

from .common import FiscalPeriod, validate_decimal


@dataclass(frozen=True, slots=True)
class FinancialFact(StrictModel):
    fact_id: str
    concept: str
    value: str
    unit: str
    currency: str | None
    scale: int
    period: FiscalPeriod
    filed_at: str
    available_at: str
    source_id: str
    accession_number: str | None
    amendment_of_fact_id: str | None

    def __post_init__(self) -> None:
        _validate_id(self.fact_id, "fact_id")
        _validate_id(self.concept, "concept")
        validate_decimal(self.value, "value")
        _bounded_text(self.unit, "unit", 64)
        if self.currency is not None:
            _bounded_text(self.currency, "currency", 16)
        if not -18 <= self.scale <= 18:
            raise ValueError("scale must be between -18 and 18")
        filed = _utc_timestamp(self.filed_at, "filed_at")
        available = _utc_timestamp(self.available_at, "available_at")
        if available < filed:
            raise ValueError("available_at must not precede filed_at")
        _validate_id(self.source_id, "source_id")
        if self.accession_number is not None:
            _bounded_text(self.accession_number, "accession_number", 64)
        if self.amendment_of_fact_id is not None:
            _validate_id(self.amendment_of_fact_id, "amendment_of_fact_id")
            if self.amendment_of_fact_id == self.fact_id:
                raise ValueError("a fact cannot amend itself")


@dataclass(frozen=True, slots=True)
class RestatementLink(StrictModel):
    original_fact_id: str
    amended_fact_id: str
    amendment_available_at: str
    reason: str | None

    def __post_init__(self) -> None:
        _validate_id(self.original_fact_id, "original_fact_id")
        _validate_id(self.amended_fact_id, "amended_fact_id")
        if self.original_fact_id == self.amended_fact_id:
            raise ValueError("restatement must link two different facts")
        _utc_timestamp(self.amendment_available_at, "amendment_available_at")
        if self.reason is not None:
            _bounded_text(self.reason, "reason", 1_000)


@dataclass(frozen=True, slots=True)
class StatementSnapshot(StrictModel):
    snapshot_id: str
    statement: Literal["income", "balance_sheet", "cash_flow", "segments", "key_performance_indicators"]
    period: FiscalPeriod
    cutoff_at: str
    fact_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    complete: bool
    limitation: str | None

    def __post_init__(self) -> None:
        _validate_id(self.snapshot_id, "snapshot_id")
        _utc_timestamp(self.cutoff_at, "cutoff_at")
        if not self.fact_ids or len(set(self.fact_ids)) != len(self.fact_ids):
            raise ValueError("statement snapshot requires unique fact IDs")
        if not self.source_ids:
            raise ValueError("statement snapshot requires source IDs")
        for identifier in (*self.fact_ids, *self.source_ids):
            _validate_id(identifier, "snapshot reference")
        if not self.complete and not self.limitation:
            raise ValueError("incomplete statement snapshots require a limitation")
