"""Transparent ratio definitions and observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tradingagents_portable.research_contracts import StrictModel, _bounded_text, _validate_id

from .common import CalculationReceipt, FiscalPeriod, validate_decimal


@dataclass(frozen=True, slots=True)
class RatioDefinition(StrictModel):
    ratio_id: str
    name: str
    category: Literal["growth", "profitability", "liquidity", "leverage", "efficiency", "cash_flow", "valuation"]
    operation: Literal["divide", "growth", "return_on_average", "multiple"]
    numerator_concept: str
    denominator_concept: str
    output_unit: Literal["ratio", "percent", "turns"]
    formula_version: str

    def __post_init__(self) -> None:
        _validate_id(self.ratio_id, "ratio_id")
        _bounded_text(self.name, "name", 128)
        _validate_id(self.numerator_concept, "numerator_concept")
        _validate_id(self.denominator_concept, "denominator_concept")
        _bounded_text(self.formula_version, "formula_version", 64)


@dataclass(frozen=True, slots=True)
class RatioObservation(StrictModel):
    observation_id: str
    definition: RatioDefinition
    period: FiscalPeriod
    value: str
    output_unit: Literal["ratio", "percent", "turns"]
    numerator_fact_ids: tuple[str, ...]
    denominator_fact_ids: tuple[str, ...]
    receipt: CalculationReceipt

    def __post_init__(self) -> None:
        _validate_id(self.observation_id, "observation_id")
        validate_decimal(self.value, "value")
        if self.output_unit != self.definition.output_unit:
            raise ValueError("ratio output unit must match its definition")
        if self.value != self.receipt.output_value or self.output_unit != self.receipt.output_unit:
            raise ValueError("ratio observation must match its calculation receipt")
        for fact_id in (*self.numerator_fact_ids, *self.denominator_fact_ids):
            _validate_id(fact_id, "ratio fact ID")
        expected = (*self.numerator_fact_ids, *self.denominator_fact_ids)
        if self.receipt.input_ids != expected:
            raise ValueError("ratio receipt inputs must match the declared fact IDs")
