"""Cross-artifact conformance for analytics_bundle.v1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from stock_research_agents.analytics_v1.bundle import AnalyticsBundleV1
from stock_research_agents.analytics_v1.calculators.ratios import standard_ratio_calculator
from stock_research_agents.analytics_v1.calculators.valuation import (
    calculate_comparable_valuation,
    calculate_dcf,
    calculate_reverse_dcf,
)
from stock_research_agents.analytics_v1.common import CalculationReceipt
from stock_research_agents.analytics_v1.market_experiments import split_gap_days


@dataclass(frozen=True, slots=True)
class AnalyticsConformanceReport:
    conformant: bool
    checks: tuple[str, ...]
    errors: tuple[str, ...]


def _receipt_digest(receipt: CalculationReceipt) -> str:
    payload = {
        "operation": receipt.operation,
        "formula_version": receipt.formula_version,
        "input_ids": receipt.input_ids,
        "input_values": receipt.input_values,
        "output": receipt.output_value,
        "unit": receipt.output_unit,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evaluate_analytics_bundle(bundle: AnalyticsBundleV1) -> AnalyticsConformanceReport:
    errors: list[str] = []
    checks: list[str] = []

    license_by_source = {receipt.source_id: receipt for receipt in bundle.source_licenses}
    referenced_sources = {fact.source_id for fact in bundle.facts}
    referenced_sources.update(opinion.source_id for opinion in bundle.analyst_opinions)
    referenced_sources.update(estimate.source_id for estimate in bundle.estimates)
    referenced_sources.update(transaction.source_id for transaction in bundle.insider_transactions)
    for source_id in sorted(referenced_sources):
        receipt = license_by_source.get(source_id)
        if receipt is None:
            errors.append(f"referenced source has no license receipt: {source_id}")
        elif receipt.machine_use != "allowed":
            errors.append(f"referenced source is not permitted for machine use: {source_id}")
    checks.append("source_licensing")

    facts = {fact.fact_id: fact for fact in bundle.facts}
    for link in bundle.restatements:
        original = facts.get(link.original_fact_id)
        amended = facts.get(link.amended_fact_id)
        if original is None or amended is None:
            errors.append(f"restatement references unknown facts: {link.original_fact_id}->{link.amended_fact_id}")
            continue
        if amended.amendment_of_fact_id != original.fact_id:
            errors.append(f"amended fact does not declare its original: {amended.fact_id}")
        if amended.available_at != link.amendment_available_at:
            errors.append(f"restatement availability mismatch: {amended.fact_id}")
    checks.append("restatement_lineage")

    all_receipts = (
        *bundle.calculation_receipts,
        *(ratio.receipt for ratio in bundle.ratios),
        *(valuation.receipt for valuation in bundle.dcf_valuations),
        *(result.receipt for result in bundle.reverse_dcf_results),
        *(valuation.receipt for valuation in bundle.comparable_valuations),
        *(factor.receipt for factor in bundle.factors),
    )
    receipt_ids = [receipt.calculation_id for receipt in all_receipts]
    if len(receipt_ids) != len(set(receipt_ids)):
        errors.append("calculation receipt IDs must be unique")
    for calculation_receipt in all_receipts:
        if _receipt_digest(calculation_receipt) != calculation_receipt.calculation_sha256:
            errors.append(f"calculation receipt digest mismatch: {calculation_receipt.calculation_id}")
    checks.append("calculation_lineage")

    for ratio in bundle.ratios:
        fact_references = (*ratio.numerator_fact_ids, *ratio.denominator_fact_ids)
        missing = set(fact_references) - set(facts)
        if missing:
            errors.append(f"ratio references unknown facts: {sorted(missing)}")
            continue
        numerator_count = len(ratio.numerator_fact_ids)
        if numerator_count == 0 or not ratio.denominator_fact_ids:
            errors.append(f"ratio requires numerator and denominator facts: {ratio.observation_id}")
            continue
        reproduced_ratio = standard_ratio_calculator().calculate(
            observation_id=ratio.observation_id,
            definition=ratio.definition,
            period=ratio.period,
            numerator=ratio.receipt.input_values[0],
            denominator=ratio.receipt.input_values[numerator_count],
            numerator_fact_ids=ratio.numerator_fact_ids,
            denominator_fact_ids=ratio.denominator_fact_ids,
            calculated_at=ratio.receipt.calculated_at,
        )
        if reproduced_ratio.value != ratio.value:
            errors.append(f"ratio did not reproduce: {ratio.observation_id}")
    checks.append("ratio_reproduction")

    model_by_id = {model.model_id: model for model in bundle.dcf_models}
    for valuation in bundle.dcf_valuations:
        model = model_by_id.get(valuation.model_id)
        if model is None:
            errors.append(f"DCF valuation references unknown model: {valuation.model_id}")
            continue
        reproduced_dcf = calculate_dcf(
            model,
            valuation_id=valuation.valuation_id,
            calculated_at=valuation.receipt.calculated_at,
        )
        if reproduced_dcf.fair_value_per_share != valuation.fair_value_per_share:
            errors.append(f"DCF valuation did not reproduce: {valuation.valuation_id}")
    for result in bundle.reverse_dcf_results:
        model = model_by_id.get(result.model_id)
        if model is None:
            errors.append(f"reverse DCF references unknown model: {result.model_id}")
            continue
        reproduced_reverse_dcf = calculate_reverse_dcf(
            model,
            result_id=result.result_id,
            target_price=result.target_price,
            calculated_at=result.receipt.calculated_at,
        )
        if reproduced_reverse_dcf.implied_terminal_growth_rate != result.implied_terminal_growth_rate:
            errors.append(f"reverse DCF did not reproduce: {result.result_id}")
    checks.append("valuation_reproduction")

    observation_by_id = {item.observation_id: item for item in bundle.comparable_observations}
    for comparable_valuation in bundle.comparable_valuations:
        observations = tuple(
            observation_by_id[item_id]
            for item_id in comparable_valuation.peer_observation_ids
            if item_id in observation_by_id
        )
        if len(observations) != len(comparable_valuation.peer_observation_ids):
            errors.append(f"comparable valuation references unknown peers: {comparable_valuation.valuation_id}")
            continue
        reproduced_comparable = calculate_comparable_valuation(
            observations,
            valuation_id=comparable_valuation.valuation_id,
            target_metric_value=comparable_valuation.target_metric_value,
            bridge=comparable_valuation.capital_bridge,
            calculated_at=comparable_valuation.receipt.calculated_at,
        )
        if reproduced_comparable.fair_value_per_share != comparable_valuation.fair_value_per_share:
            errors.append(f"comparable valuation did not reproduce: {comparable_valuation.valuation_id}")
    checks.append("comparable_reproduction")

    dataset_by_id = {dataset.dataset_id: dataset for dataset in bundle.datasets}
    spec_by_id = {spec.experiment_id: spec for spec in bundle.experiment_specs}
    experiment_by_id = {receipt.experiment_id: receipt for receipt in bundle.experiments}
    if len(experiment_by_id) != len(bundle.experiments):
        errors.append("experiment receipts must use unique experiment IDs")
    for split in bundle.splits:
        if split_gap_days(split) < split.purge_days:
            errors.append(f"split violates declared purge: {split.split_id}")
    for experiment_receipt in bundle.experiments:
        spec = spec_by_id.get(experiment_receipt.experiment_id)
        if spec is None:
            errors.append(f"experiment receipt has no declared spec: {experiment_receipt.experiment_id}")
            continue
        if experiment_receipt.dataset_sha256 not in {dataset.content_sha256 for dataset in dataset_by_id.values()}:
            errors.append(f"experiment references an unknown dataset digest: {experiment_receipt.experiment_id}")
        if experiment_receipt.dataset_sha256 != spec.dataset_sha256:
            errors.append(f"experiment dataset digest differs from its spec: {experiment_receipt.experiment_id}")
    checks.append("leakage_safe_experiments")

    return AnalyticsConformanceReport(not errors, tuple(checks), tuple(errors))


def assert_analytics_bundle_conformant(bundle: AnalyticsBundleV1) -> None:
    report = evaluate_analytics_bundle(bundle)
    if not report.conformant:
        raise ValueError("analytics bundle is not conformant: " + "; ".join(report.errors))
