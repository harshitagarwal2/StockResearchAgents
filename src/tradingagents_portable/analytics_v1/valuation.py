"""Typed DCF, reverse-DCF, comparable, and capital-bridge results."""

from __future__ import annotations

from dataclasses import dataclass

from tradingagents_portable.research_contracts import StrictModel, _bounded_text, _validate_id

from .common import CalculationReceipt, validate_decimal


@dataclass(frozen=True, slots=True)
class CapitalBridge(StrictModel):
    cash: str
    debt: str
    preferred_equity: str
    minority_interest: str
    non_operating_assets: str
    diluted_shares: str
    currency: str

    def __post_init__(self) -> None:
        for name in (
            "cash",
            "debt",
            "preferred_equity",
            "minority_interest",
            "non_operating_assets",
            "diluted_shares",
        ):
            validate_decimal(getattr(self, name), name)
        _bounded_text(self.currency, "currency", 16)


@dataclass(frozen=True, slots=True)
class DcfModelSpec(StrictModel):
    model_id: str
    currency: str
    forecast_period_ids: tuple[str, ...]
    free_cash_flows: tuple[str, ...]
    discount_rate: str
    terminal_growth_rate: str
    capital_bridge: CapitalBridge
    formula_version: str = "dcf.standard.v1"

    def __post_init__(self) -> None:
        _validate_id(self.model_id, "model_id")
        _bounded_text(self.currency, "currency", 16)
        if not self.forecast_period_ids or len(self.forecast_period_ids) != len(self.free_cash_flows):
            raise ValueError("DCF forecast periods and free cash flows must be non-empty and aligned")
        for period_id in self.forecast_period_ids:
            _validate_id(period_id, "forecast_period_ids")
        for index, cash_flow in enumerate(self.free_cash_flows):
            validate_decimal(cash_flow, f"free_cash_flows[{index}]")
        validate_decimal(self.discount_rate, "discount_rate")
        validate_decimal(self.terminal_growth_rate, "terminal_growth_rate")
        _bounded_text(self.formula_version, "formula_version", 64)
        if self.currency != self.capital_bridge.currency:
            raise ValueError("DCF and capital bridge currencies must match")


@dataclass(frozen=True, slots=True)
class SensitivityPoint(StrictModel):
    discount_rate: str
    terminal_growth_rate: str
    enterprise_value: str
    equity_value: str
    fair_value_per_share: str

    def __post_init__(self) -> None:
        for name in (
            "discount_rate",
            "terminal_growth_rate",
            "enterprise_value",
            "equity_value",
            "fair_value_per_share",
        ):
            validate_decimal(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class DcfValuation(StrictModel):
    valuation_id: str
    model_id: str
    present_value_cash_flows: tuple[str, ...]
    present_value_terminal: str
    enterprise_value: str
    equity_value: str
    fair_value_per_share: str
    currency: str
    sensitivity: tuple[SensitivityPoint, ...]
    receipt: CalculationReceipt

    def __post_init__(self) -> None:
        _validate_id(self.valuation_id, "valuation_id")
        _validate_id(self.model_id, "model_id")
        if not self.present_value_cash_flows:
            raise ValueError("DCF valuation requires forecast present values")
        for index, value in enumerate(self.present_value_cash_flows):
            validate_decimal(value, f"present_value_cash_flows[{index}]")
        for name in ("present_value_terminal", "enterprise_value", "equity_value", "fair_value_per_share"):
            validate_decimal(getattr(self, name), name)
        _bounded_text(self.currency, "currency", 16)
        if self.receipt.output_value != self.fair_value_per_share:
            raise ValueError("DCF receipt must reproduce fair_value_per_share")


@dataclass(frozen=True, slots=True)
class ReverseDcfResult(StrictModel):
    result_id: str
    model_id: str
    target_price: str
    implied_terminal_growth_rate: str
    feasible: bool
    limitation: str | None
    receipt: CalculationReceipt

    def __post_init__(self) -> None:
        _validate_id(self.result_id, "result_id")
        _validate_id(self.model_id, "model_id")
        validate_decimal(self.target_price, "target_price")
        validate_decimal(self.implied_terminal_growth_rate, "implied_terminal_growth_rate")
        if not self.feasible and not self.limitation:
            raise ValueError("infeasible reverse DCF results require a limitation")


@dataclass(frozen=True, slots=True)
class ComparableObservation(StrictModel):
    observation_id: str
    company_id: str
    metric_name: str
    metric_value: str
    enterprise_value: str
    multiple: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.observation_id, "observation_id")
        _validate_id(self.company_id, "company_id")
        _validate_id(self.metric_name, "metric_name")
        for name in ("metric_value", "enterprise_value", "multiple"):
            validate_decimal(getattr(self, name), name)
        if not self.source_ids:
            raise ValueError("comparable observation requires source IDs")
        for source_id in self.source_ids:
            _validate_id(source_id, "source_ids")


@dataclass(frozen=True, slots=True)
class ComparableValuation(StrictModel):
    valuation_id: str
    metric_name: str
    selected_multiple: str
    target_metric_value: str
    enterprise_value: str
    equity_value: str
    fair_value_per_share: str
    capital_bridge: CapitalBridge
    peer_observation_ids: tuple[str, ...]
    receipt: CalculationReceipt

    def __post_init__(self) -> None:
        _validate_id(self.valuation_id, "valuation_id")
        _validate_id(self.metric_name, "metric_name")
        for name in (
            "selected_multiple",
            "target_metric_value",
            "enterprise_value",
            "equity_value",
            "fair_value_per_share",
        ):
            validate_decimal(getattr(self, name), name)
        if not self.peer_observation_ids:
            raise ValueError("comparable valuation requires peer observations")
        if self.receipt.output_value != self.fair_value_per_share:
            raise ValueError("comparable receipt must reproduce fair_value_per_share")
