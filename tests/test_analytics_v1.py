from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from tradingagents_portable.analytics_v1 import (
    AnalyticsBundleV1,
    CapitalBridge,
    ComparableObservation,
    DatasetManifest,
    DcfModelSpec,
    FinancialFact,
    FiscalPeriod,
    RatioDefinition,
    SourceLicenseReceipt,
    SplitManifest,
)
from tradingagents_portable.analytics_v1.calculators import (
    calculate_comparable_valuation,
    calculate_dcf,
    calculate_reverse_dcf,
    standard_ratio_calculator,
)
from tradingagents_portable.analytics_v1.validators import evaluate_analytics_bundle

NOW = "2026-08-01T12:00:00+00:00"


def _period() -> FiscalPeriod:
    return FiscalPeriod("2026-q2", 2026, 2, "2026-04-01", "2026-06-30", "quarter")


def _fact(fact_id: str, concept: str, value: str) -> FinancialFact:
    return FinancialFact(
        fact_id=fact_id,
        concept=concept,
        value=value,
        unit="USD",
        currency="USD",
        scale=0,
        period=_period(),
        filed_at="2026-07-30T20:00:00+00:00",
        available_at="2026-07-30T20:05:00+00:00",
        source_id="sec.10q",
        accession_number="0000000000-26-000001",
        amendment_of_fact_id=None,
    )


def _license(machine_use: str = "allowed") -> SourceLicenseReceipt:
    return SourceLicenseReceipt(
        receipt_id="license.sec",
        source_id="sec.10q",
        access="public",
        permitted_purpose="research",
        machine_use=machine_use,  # type: ignore[arg-type]
        retention_days=None,
        derived_data_rights="allowed",
        redistribution="bounded_extract",
        terms_uri="https://www.sec.gov/privacy.htm",
        checked_at=NOW,
        policy_sha256="a" * 64,
        limitation=None if machine_use == "allowed" else "Machine use is not permitted.",
    )


def _bridge() -> CapitalBridge:
    return CapitalBridge("50", "100", "0", "0", "0", "10", "USD")


def _bundle(**changes: object) -> AnalyticsBundleV1:
    values: dict[str, object] = {
        "run_id": "host-meta-analytics",
        "base_submission_digest": "a" * 64,
        "base_dossier_digest": "b" * 64,
        "cutoff_at": "2026-08-01T00:00:00+00:00",
        "completed_at": NOW,
        "facts": (_fact("fact.revenue", "revenue", "100"), _fact("fact.gross_profit", "gross_profit", "40")),
        "statement_snapshots": (),
        "restatements": (),
        "ratios": (),
        "calculation_receipts": (),
        "dcf_models": (),
        "dcf_valuations": (),
        "reverse_dcf_results": (),
        "comparable_observations": (),
        "comparable_valuations": (),
        "analyst_opinions": (),
        "estimates": (),
        "consensus": (),
        "ownership": (),
        "insider_transactions": (),
        "short_interest": (),
        "datasets": (),
        "splits": (),
        "factors": (),
        "experiment_specs": (),
        "experiments": (),
        "catalysts": (),
        "event_clusters": (),
        "source_licenses": (_license(),),
        "coverage_decision": "supported",
        "limitations": (),
        "complete": True,
    }
    values.update(changes)
    return AnalyticsBundleV1(**values)


def test_ratio_strategy_produces_decimal_value_and_lineage() -> None:
    definition = RatioDefinition(
        ratio_id="ratio.gross_margin",
        name="Gross margin",
        category="profitability",
        operation="divide",
        numerator_concept="gross_profit",
        denominator_concept="revenue",
        output_unit="ratio",
        formula_version="gross-margin.v1",
    )

    ratio = standard_ratio_calculator().calculate(
        observation_id="ratio.gross_margin.2026q2",
        definition=definition,
        period=_period(),
        numerator="40",
        denominator="100",
        numerator_fact_ids=("fact.gross_profit",),
        denominator_fact_ids=("fact.revenue",),
        calculated_at=NOW,
    )

    assert Decimal(ratio.value) == Decimal("0.4")
    assert len(ratio.receipt.calculation_sha256) == 64
    with pytest.raises(ValueError, match="denominator"):
        standard_ratio_calculator().calculate(
            observation_id="ratio.invalid",
            definition=definition,
            period=_period(),
            numerator="1",
            denominator="0",
            numerator_fact_ids=("fact.gross_profit",),
            denominator_fact_ids=("fact.revenue",),
            calculated_at=NOW,
        )


def test_dcf_reverse_dcf_and_comparables_reproduce() -> None:
    spec = DcfModelSpec(
        model_id="dcf.base",
        currency="USD",
        forecast_period_ids=("fy1", "fy2", "fy3"),
        free_cash_flows=("100", "110", "120"),
        discount_rate="0.10",
        terminal_growth_rate="0.03",
        capital_bridge=_bridge(),
    )
    valuation = calculate_dcf(
        spec,
        valuation_id="valuation.dcf.base",
        calculated_at=NOW,
        discount_rate_sensitivities=("0.09", "0.10", "0.11"),
        terminal_growth_sensitivities=("0.02", "0.03", "0.04"),
    )
    reverse = calculate_reverse_dcf(
        spec,
        result_id="reverse.base",
        target_price=valuation.fair_value_per_share,
        calculated_at=NOW,
    )

    assert len(valuation.sensitivity) == 9
    assert abs(Decimal(reverse.implied_terminal_growth_rate) - Decimal("0.03")) < Decimal("1e-30")

    peers = (
        ComparableObservation("peer.1", "peer-a", "ebitda", "100", "1000", "10", ("peer-source.1",)),
        ComparableObservation("peer.2", "peer-b", "ebitda", "100", "1200", "12", ("peer-source.2",)),
        ComparableObservation("peer.3", "peer-c", "ebitda", "100", "1400", "14", ("peer-source.3",)),
    )
    comparable = calculate_comparable_valuation(
        peers,
        valuation_id="valuation.comps",
        target_metric_value="200",
        bridge=_bridge(),
        calculated_at=NOW,
    )
    assert comparable.selected_multiple == "12"
    assert comparable.enterprise_value == "2400"


def test_split_manifest_rejects_leakage_and_shuffling() -> None:
    with pytest.raises(ValueError, match="purge"):
        SplitManifest(
            "split.1",
            "purged_walk_forward",
            "2024-01-01T00:00:00+00:00",
            "2025-12-31T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
            "2026-06-30T00:00:00+00:00",
            5,
            1,
            False,
            "a" * 64,
        )
    with pytest.raises(ValueError, match="shuffled"):
        SplitManifest(
            "split.2",
            "walk_forward",
            "2024-01-01T00:00:00+00:00",
            "2025-12-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            "2026-06-30T00:00:00+00:00",
            0,
            0,
            True,  # type: ignore[arg-type]
            "a" * 64,
        )


def test_bundle_conformance_enforces_machine_use_rights() -> None:
    bundle = _bundle()
    assert evaluate_analytics_bundle(bundle).conformant is True

    denied = _bundle(
        source_licenses=(_license("denied"),),
        coverage_decision="policy_blocked",
        limitations=("SEC facts were excluded by a simulated policy denial.",),
    )
    report = evaluate_analytics_bundle(denied)
    assert report.conformant is False
    assert "not permitted for machine use" in report.errors[0]


def test_dataset_manifest_separates_features_from_future_targets() -> None:
    manifest = DatasetManifest(
        dataset_id="dataset.meta.daily",
        symbol="META",
        content_sha256="a" * 64,
        start_at="2020-01-01T00:00:00+00:00",
        cutoff_at="2026-07-31T00:00:00+00:00",
        feature_available_through="2026-07-31T00:00:00+00:00",
        target_starts_at="2026-08-01T00:00:00+00:00",
        target_ends_at="2026-08-31T00:00:00+00:00",
        fields=("close", "volume", "revenue_revision"),
        source_ids=("market.meta", "fundamentals.meta"),
        point_in_time=True,
        limitations=(),
    )
    assert manifest.point_in_time is True
    with pytest.raises(ValueError, match="separate"):
        replace(manifest, target_starts_at="2026-07-30T00:00:00+00:00")
