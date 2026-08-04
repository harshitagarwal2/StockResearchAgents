"""Shared immutable value objects for analytics v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from tradingagents_portable.research_contracts import StrictModel, _bounded_text, _utc_timestamp, _validate_id


def validate_decimal(value: str, path: str) -> None:
    from decimal import Decimal, InvalidOperation

    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{path} must be a finite decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{path} must be a finite decimal string")


def validate_digest(value: str, path: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class FiscalPeriod(StrictModel):
    period_id: str
    fiscal_year: int
    fiscal_quarter: int | None
    start_date: str
    end_date: str
    period_type: Literal["instant", "quarter", "year_to_date", "annual", "trailing_twelve_months"]

    def __post_init__(self) -> None:
        _validate_id(self.period_id, "period_id")
        if not 1900 <= self.fiscal_year <= 2200:
            raise ValueError("fiscal_year is outside the supported range")
        if self.fiscal_quarter is not None and self.fiscal_quarter not in {1, 2, 3, 4}:
            raise ValueError("fiscal_quarter must be between one and four")
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        if end < start:
            raise ValueError("fiscal period end_date must not precede start_date")
        if self.period_type == "quarter" and self.fiscal_quarter is None:
            raise ValueError("quarter periods require fiscal_quarter")


@dataclass(frozen=True, slots=True)
class SourceReference(StrictModel):
    source_id: str
    fact_ids: tuple[str, ...]
    available_at: str
    content_sha256: str

    def __post_init__(self) -> None:
        _validate_id(self.source_id, "source_id")
        if not self.fact_ids:
            raise ValueError("source reference requires fact_ids")
        for fact_id in self.fact_ids:
            _validate_id(fact_id, "fact_ids")
        _utc_timestamp(self.available_at, "available_at")
        validate_digest(self.content_sha256, "content_sha256")


@dataclass(frozen=True, slots=True)
class CalculationReceipt(StrictModel):
    calculation_id: str
    operation: str
    formula_version: str
    input_ids: tuple[str, ...]
    input_values: tuple[str, ...]
    output_value: str
    output_unit: str
    calculated_at: str
    calculation_sha256: str

    def __post_init__(self) -> None:
        _validate_id(self.calculation_id, "calculation_id")
        _validate_id(self.operation, "operation")
        _bounded_text(self.formula_version, "formula_version", 64)
        if not self.input_ids or len(self.input_ids) != len(self.input_values):
            raise ValueError("calculation input IDs and values must be non-empty and aligned")
        for input_id in self.input_ids:
            _validate_id(input_id, "input_ids")
        for index, value in enumerate(self.input_values):
            validate_decimal(value, f"input_values[{index}]")
        validate_decimal(self.output_value, "output_value")
        _bounded_text(self.output_unit, "output_unit", 64)
        _utc_timestamp(self.calculated_at, "calculated_at")
        validate_digest(self.calculation_sha256, "calculation_sha256")
