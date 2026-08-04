"""Strategy-based, Decimal ratio calculation with lineage receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from typing import Protocol

from tradingagents_portable.analytics_v1.common import CalculationReceipt, FiscalPeriod
from tradingagents_portable.analytics_v1.ratios import RatioDefinition, RatioObservation


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = value.normalize()
    return format(normalized, "f")


class RatioStrategy(Protocol):
    def calculate(self, numerator: Decimal, denominator: Decimal) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class DivideStrategy:
    multiplier: Decimal = Decimal("1")

    def calculate(self, numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == 0:
            raise ValueError("ratio denominator cannot be zero")
        return (numerator / denominator) * self.multiplier


@dataclass(frozen=True, slots=True)
class GrowthStrategy:
    def calculate(self, numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == 0:
            raise ValueError("growth baseline cannot be zero")
        return ((numerator / denominator) - Decimal("1")) * Decimal("100")


class RatioCalculator:
    """Open registry of pure ratio strategies."""

    def __init__(self) -> None:
        self._strategies: dict[str, RatioStrategy] = {}

    def register(self, operation: str, strategy: RatioStrategy) -> None:
        if operation in self._strategies:
            raise ValueError(f"ratio strategy is already registered: {operation}")
        self._strategies[operation] = strategy

    def calculate(
        self,
        *,
        observation_id: str,
        definition: RatioDefinition,
        period: FiscalPeriod,
        numerator: str,
        denominator: str,
        numerator_fact_ids: tuple[str, ...],
        denominator_fact_ids: tuple[str, ...],
        calculated_at: str,
    ) -> RatioObservation:
        try:
            strategy = self._strategies[definition.operation]
        except KeyError as exc:
            raise KeyError(f"no ratio strategy registered for operation: {definition.operation}") from exc
        try:
            with localcontext() as context:
                context.prec = 34
                result = strategy.calculate(Decimal(numerator), Decimal(denominator))
        except (InvalidOperation, DivisionByZero) as exc:
            raise ValueError("ratio inputs must be valid finite decimal strings") from exc
        if not result.is_finite():
            raise ValueError("ratio result must be finite")
        output = _canonical_decimal(result)
        input_ids = (*numerator_fact_ids, *denominator_fact_ids)
        input_values = tuple(numerator for _ in numerator_fact_ids) + tuple(denominator for _ in denominator_fact_ids)
        lineage = {
            "operation": definition.operation,
            "formula_version": definition.formula_version,
            "input_ids": input_ids,
            "input_values": input_values,
            "output": output,
            "unit": definition.output_unit,
        }
        digest = hashlib.sha256(json.dumps(lineage, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        receipt = CalculationReceipt(
            calculation_id=f"calculation.{observation_id}",
            operation=definition.operation,
            formula_version=definition.formula_version,
            input_ids=input_ids,
            input_values=input_values,
            output_value=output,
            output_unit=definition.output_unit,
            calculated_at=calculated_at,
            calculation_sha256=digest,
        )
        return RatioObservation(
            observation_id=observation_id,
            definition=definition,
            period=period,
            value=output,
            output_unit=definition.output_unit,
            numerator_fact_ids=numerator_fact_ids,
            denominator_fact_ids=denominator_fact_ids,
            receipt=receipt,
        )


def standard_ratio_calculator() -> RatioCalculator:
    calculator = RatioCalculator()
    calculator.register("divide", DivideStrategy())
    calculator.register("multiple", DivideStrategy())
    calculator.register("return_on_average", DivideStrategy(Decimal("100")))
    calculator.register("growth", GrowthStrategy())
    return calculator
