"""Deterministic Decimal valuation functions with auditable receipts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation, localcontext
from statistics import median

from stock_research_agents.analytics_v1.common import CalculationReceipt
from stock_research_agents.analytics_v1.valuation import (
    CapitalBridge,
    ComparableObservation,
    ComparableValuation,
    DcfModelSpec,
    DcfValuation,
    ReverseDcfResult,
    SensitivityPoint,
)


def _text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _equity_value(enterprise_value: Decimal, bridge: CapitalBridge) -> Decimal:
    return (
        enterprise_value
        + Decimal(bridge.cash)
        + Decimal(bridge.non_operating_assets)
        - Decimal(bridge.debt)
        - Decimal(bridge.preferred_equity)
        - Decimal(bridge.minority_interest)
    )


def _receipt(
    *,
    calculation_id: str,
    operation: str,
    version: str,
    input_ids: tuple[str, ...],
    input_values: tuple[str, ...],
    output: Decimal,
    unit: str,
    calculated_at: str,
) -> CalculationReceipt:
    payload = {
        "operation": operation,
        "formula_version": version,
        "input_ids": input_ids,
        "input_values": input_values,
        "output": _text(output),
        "unit": unit,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return CalculationReceipt(
        calculation_id=calculation_id,
        operation=operation,
        formula_version=version,
        input_ids=input_ids,
        input_values=input_values,
        output_value=_text(output),
        output_unit=unit,
        calculated_at=calculated_at,
        calculation_sha256=digest,
    )


def _dcf_values(
    spec: DcfModelSpec,
    discount_rate: Decimal,
    terminal_growth: Decimal,
) -> tuple[tuple[Decimal, ...], Decimal, Decimal, Decimal, Decimal]:
    if discount_rate <= terminal_growth:
        raise ValueError("DCF discount_rate must exceed terminal_growth_rate")
    shares = Decimal(spec.capital_bridge.diluted_shares)
    if shares <= 0:
        raise ValueError("DCF diluted_shares must be positive")
    cash_flows = tuple(Decimal(value) for value in spec.free_cash_flows)
    present_values = tuple(
        value / ((Decimal("1") + discount_rate) ** index) for index, value in enumerate(cash_flows, 1)
    )
    terminal_value = cash_flows[-1] * (Decimal("1") + terminal_growth) / (discount_rate - terminal_growth)
    present_terminal = terminal_value / ((Decimal("1") + discount_rate) ** len(cash_flows))
    enterprise = sum(present_values, Decimal("0")) + present_terminal
    equity = _equity_value(enterprise, spec.capital_bridge)
    fair_value = equity / shares
    return present_values, present_terminal, enterprise, equity, fair_value


def calculate_dcf(
    spec: DcfModelSpec,
    *,
    valuation_id: str,
    calculated_at: str,
    discount_rate_sensitivities: tuple[str, ...] = (),
    terminal_growth_sensitivities: tuple[str, ...] = (),
) -> DcfValuation:
    try:
        with localcontext() as context:
            context.prec = 34
            discount_rate = Decimal(spec.discount_rate)
            terminal_growth = Decimal(spec.terminal_growth_rate)
            present_values, present_terminal, enterprise, equity, fair_value = _dcf_values(
                spec, discount_rate, terminal_growth
            )
            rates = discount_rate_sensitivities or (spec.discount_rate,)
            growths = terminal_growth_sensitivities or (spec.terminal_growth_rate,)
            sensitivity = tuple(
                SensitivityPoint(
                    discount_rate=rate,
                    terminal_growth_rate=growth,
                    enterprise_value=_text(point[2]),
                    equity_value=_text(point[3]),
                    fair_value_per_share=_text(point[4]),
                )
                for rate in rates
                for growth in growths
                for point in (_dcf_values(spec, Decimal(rate), Decimal(growth)),)
            )
    except InvalidOperation as exc:
        raise ValueError("DCF inputs must be valid decimal strings") from exc
    input_ids = (*spec.forecast_period_ids, "discount_rate", "terminal_growth_rate", "diluted_shares")
    input_values = (
        *spec.free_cash_flows,
        spec.discount_rate,
        spec.terminal_growth_rate,
        spec.capital_bridge.diluted_shares,
    )
    receipt = _receipt(
        calculation_id=f"calculation.{valuation_id}",
        operation="dcf",
        version=spec.formula_version,
        input_ids=input_ids,
        input_values=input_values,
        output=fair_value,
        unit=f"{spec.currency}/share",
        calculated_at=calculated_at,
    )
    return DcfValuation(
        valuation_id=valuation_id,
        model_id=spec.model_id,
        present_value_cash_flows=tuple(_text(value) for value in present_values),
        present_value_terminal=_text(present_terminal),
        enterprise_value=_text(enterprise),
        equity_value=_text(equity),
        fair_value_per_share=_text(fair_value),
        currency=spec.currency,
        sensitivity=sensitivity,
        receipt=receipt,
    )


def calculate_reverse_dcf(
    spec: DcfModelSpec,
    *,
    result_id: str,
    target_price: str,
    calculated_at: str,
) -> ReverseDcfResult:
    with localcontext() as context:
        context.prec = 34
        target = Decimal(target_price)
        shares = Decimal(spec.capital_bridge.diluted_shares)
        discount = Decimal(spec.discount_rate)
        cash_flows = tuple(Decimal(value) for value in spec.free_cash_flows)
        present_values = sum(
            (value / ((Decimal("1") + discount) ** index) for index, value in enumerate(cash_flows, 1)),
            Decimal("0"),
        )
        target_equity = target * shares
        target_enterprise = (
            target_equity
            - Decimal(spec.capital_bridge.cash)
            - Decimal(spec.capital_bridge.non_operating_assets)
            + Decimal(spec.capital_bridge.debt)
            + Decimal(spec.capital_bridge.preferred_equity)
            + Decimal(spec.capital_bridge.minority_interest)
        )
        required_present_terminal = target_enterprise - present_values
        terminal_value = required_present_terminal * ((Decimal("1") + discount) ** len(cash_flows))
        last_cash_flow = cash_flows[-1]
        denominator = terminal_value + last_cash_flow
        feasible = required_present_terminal > 0 and last_cash_flow > 0 and denominator != 0
        implied = (terminal_value * discount - last_cash_flow) / denominator if feasible else Decimal("0")
        feasible = feasible and implied < discount and implied > Decimal("-1")
        limitation = None if feasible else "Target price does not imply a finite terminal growth rate below WACC."
    receipt = _receipt(
        calculation_id=f"calculation.{result_id}",
        operation="reverse_dcf",
        version="reverse-dcf.standard.v1",
        input_ids=("target_price", *spec.forecast_period_ids, "discount_rate", "diluted_shares"),
        input_values=(target_price, *spec.free_cash_flows, spec.discount_rate, spec.capital_bridge.diluted_shares),
        output=implied,
        unit="rate",
        calculated_at=calculated_at,
    )
    return ReverseDcfResult(
        result_id=result_id,
        model_id=spec.model_id,
        target_price=target_price,
        implied_terminal_growth_rate=_text(implied),
        feasible=feasible,
        limitation=limitation,
        receipt=receipt,
    )


def calculate_comparable_valuation(
    observations: tuple[ComparableObservation, ...],
    *,
    valuation_id: str,
    target_metric_value: str,
    bridge: CapitalBridge,
    calculated_at: str,
) -> ComparableValuation:
    if not observations:
        raise ValueError("comparable valuation requires peer observations")
    metric_names = {observation.metric_name for observation in observations}
    if len(metric_names) != 1:
        raise ValueError("comparable observations must use one metric")
    with localcontext() as context:
        context.prec = 34
        selected = Decimal(str(median(Decimal(item.multiple) for item in observations)))
        metric = Decimal(target_metric_value)
        enterprise = metric * selected
        equity = _equity_value(enterprise, bridge)
        shares = Decimal(bridge.diluted_shares)
        if shares <= 0:
            raise ValueError("comparable valuation diluted_shares must be positive")
        fair_value = equity / shares
    input_ids = tuple(item.observation_id for item in observations) + ("target_metric_value", "diluted_shares")
    input_values = tuple(item.multiple for item in observations) + (target_metric_value, bridge.diluted_shares)
    receipt = _receipt(
        calculation_id=f"calculation.{valuation_id}",
        operation="comparable_median",
        version="comparables.median.v1",
        input_ids=input_ids,
        input_values=input_values,
        output=fair_value,
        unit=f"{bridge.currency}/share",
        calculated_at=calculated_at,
    )
    return ComparableValuation(
        valuation_id=valuation_id,
        metric_name=next(iter(metric_names)),
        selected_multiple=_text(selected),
        target_metric_value=target_metric_value,
        enterprise_value=_text(enterprise),
        equity_value=_text(equity),
        fair_value_per_share=_text(fair_value),
        capital_bridge=bridge,
        peer_observation_ids=tuple(item.observation_id for item in observations),
        receipt=receipt,
    )
