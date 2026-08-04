"""Hermetic fixtures for the composed company-analytics.v1 profile."""

from __future__ import annotations

import hashlib
import json

from research_v3_fixtures import complete_v3_submission

from tradingagents_portable.analytics_v1 import AnalyticsBundleV1, FinancialFact, FiscalPeriod, SourceLicenseReceipt
from tradingagents_portable.company_analytics_v1 import (
    SourceLineageBindingV1,
    SourceLineageCrosswalkV1,
    base_request_digest,
    base_submission_digest,
    canonical_workflow_digest,
)
from tradingagents_portable.company_analytics_v1.contracts import analytics_run_id
from tradingagents_portable.company_analytics_v1.provider import CompanyAnalyticsV1Provider
from tradingagents_portable.research_contracts import parse_host_submission_v3
from tradingagents_portable.research_lab_v1 import (
    Hypothesis,
    HypothesisLedger,
    HypothesisTransition,
    ResearchIterationReceipt,
    RunCardV1,
    StageReceipt,
)
from tradingagents_portable.research_quality_v1 import (
    Forecast,
    QualityPolicy,
    QualityRuleResult,
    ResearchQualityReceipt,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def complete_v4_submission(symbol: str = "META", *, execution_mode: str = "compatible") -> dict[str, object]:
    company = parse_host_submission_v3(complete_v3_submission(symbol))
    manifest = CompanyAnalyticsV1Provider().load_manifest()
    workflow_digest = canonical_workflow_digest()
    run_id = analytics_run_id(company, "initiating-coverage.v1", workflow_digest)
    document = company.dossier.documents[0]
    claim = company.dossier.claims[0]
    completed_at = company.dossier.completed_at
    period = FiscalPeriod("2026-q2", 2026, 2, "2026-04-01", "2026-06-30", "quarter")
    facts = (
        FinancialFact(
            fact_id="fact.revenue",
            concept="revenue",
            value="100",
            unit="USD",
            currency="USD",
            scale=0,
            period=period,
            filed_at=document.temporal.published_at,
            available_at=document.temporal.available_at,
            source_id=document.id,
            accession_number=document.locator.accession_number,
            amendment_of_fact_id=None,
        ),
    )
    source_licenses = tuple(
        SourceLicenseReceipt(
            receipt_id=f"analytics-license.{item.id}",
            source_id=item.id,
            access=item.entitlement.access,
            permitted_purpose="none" if item.entitlement.access == "entitlement_blocked" else "research",
            machine_use="denied" if item.entitlement.access == "entitlement_blocked" else "allowed",
            retention_days=None,
            derived_data_rights="denied" if item.entitlement.access == "entitlement_blocked" else "allowed",
            redistribution=(
                "denied"
                if item.entitlement.access == "entitlement_blocked"
                else "bounded_extract"
                if item.entitlement.redistributable
                else "reference_only"
            ),
            terms_uri=item.entitlement.terms_uri,
            checked_at=completed_at,
            policy_sha256=_digest(
                {
                    "access": item.entitlement.access,
                    "redistributable": item.entitlement.redistributable,
                    "terms_uri": item.entitlement.terms_uri,
                }
            ),
            limitation=item.entitlement.limitation,
        )
        for item in company.dossier.documents
    )
    analytics = AnalyticsBundleV1(
        run_id=run_id,
        base_submission_digest=base_submission_digest(company),
        base_dossier_digest=company.dossier.digest(),
        cutoff_at=company.request.cutoff_at,
        completed_at=completed_at,
        facts=facts,
        statement_snapshots=(),
        restatements=(),
        ratios=(),
        calculation_receipts=(),
        dcf_models=(),
        dcf_valuations=(),
        reverse_dcf_results=(),
        comparable_observations=(),
        comparable_valuations=(),
        analyst_opinions=(),
        estimates=(),
        consensus=(),
        ownership=(),
        insider_transactions=(),
        short_interest=(),
        datasets=(),
        splits=(),
        factors=(),
        experiment_specs=(),
        experiments=(),
        catalysts=(),
        event_clusters=(),
        source_licenses=source_licenses,
        coverage_decision="supported",
        limitations=(),
        complete=True,
    )
    stages = tuple(
        StageReceipt(
            stage_id=str(stage["id"]),
            status="completed",
            started_at=company.request.requested_at,
            completed_at=completed_at,
            input_digest=base_submission_digest(company),
            output_digest=_digest({"fixture_stage": stage["id"]}),
            attempts=1,
            limitation=None,
        )
        for stage in manifest["stages"]
    )
    artifact_kinds = CompanyAnalyticsV1Provider.descriptor.artifact_kinds
    run_card = RunCardV1(
        run_id=run_id,
        profile="company-analytics.v1",
        research_pack_id="initiating-coverage.v1",
        submission_digest=base_submission_digest(company),
        workflow_digest=workflow_digest,
        harness="fixture-host",
        execution_mode=execution_mode,  # type: ignore[arg-type]
        started_at=company.request.requested_at,
        completed_at=completed_at,
        stages=stages,
        source_batch_ids=("source-batch.primary",),
        artifact_kinds=artifact_kinds,
        limitations=(),
        complete=True,
    )
    source_lineage = SourceLineageCrosswalkV1(
        schema_version="source-lineage-crosswalk.v1",
        bindings=tuple(
            SourceLineageBindingV1(
                binding_id=f"lineage.{item.id}",
                source_batch_id="source-batch.primary",
                source_observation_id=f"observation.{item.id}",
                content_sha256_scope="normalized_source_record",
                content_sha256=item.locator.content_sha256,
                canonical_uri=item.locator.canonical_uri,
                host_license_receipt_id=f"host-license.{item.id}",
                dossier_document_id=item.id,
                analytics_source_id=item.id,
                analytics_license_receipt_id=f"analytics-license.{item.id}",
                entitlement_access=item.entitlement.access,
                redistributable=item.entitlement.redistributable,
                terms_uri=item.entitlement.terms_uri,
            )
            for item in company.dossier.documents
        ),
    )
    hypothesis = Hypothesis(
        hypothesis_id="hypothesis.primary",
        statement=claim.statement,
        falsification_criteria="A subsequent primary filing contradicts the stated operating driver.",
        expected_observation="The next primary filing reports evidence consistent with the thesis.",
        horizon_at="2027-07-31T20:00:00Z",
        created_at=company.request.requested_at,
        evidence_ids=(document.id,),
        related_hypothesis_ids=(),
    )
    transition = HypothesisTransition(
        transition_id="transition.primary.1",
        hypothesis_id=hypothesis.hypothesis_id,
        from_status=None,
        to_status="proposed",
        changed_at=company.request.requested_at,
        reason="Registered before the completed synthesis.",
        evidence_ids=(document.id,),
    )
    ledger = HypothesisLedger(run_id, hypothesis, (transition,), "proposed")
    iteration = ResearchIterationReceipt(
        iteration_id="iteration.1",
        run_id=run_id,
        hypothesis_ids=(hypothesis.hypothesis_id,),
        started_at=company.request.requested_at,
        completed_at=completed_at,
        budget_units=10,
        consumed_units=6,
        novelty_score=0.8,
        maximum_correlation=0.2,
        decision="stop_sufficient",
        output_digest="e" * 64,
    )
    quality = ResearchQualityReceipt(
        "research-quality.v1",
        "quality.primary",
        run_id,
        completed_at,
        QualityPolicy("quality-policy.default", "1", "f" * 64),
        workflow_digest,
        base_request_digest(company),
        company.dossier.digest(),
        "tradingagents-portable",
        "0.1.0",
        tuple((stage.stage_id, stage.output_digest or "") for stage in stages),
        (QualityRuleResult("rule.analytics-conformance", "pass", "Analytics sidecars reproduced."),),
        (),
    )
    forecast = Forecast(
        "research-quality.v1",
        f"{run_id}.forecast.{symbol.lower()}.primary",
        run_id,
        company.dossier.identity.instrument_id,
        claim.id,
        "binary_event",
        "The primary operating thesis remains supported at the next annual filing.",
        completed_at,
        company.request.cutoff_at,
        "2027-08-01T00:00:00Z",
        "one-year",
        "Resolve true only when a retained primary filing explicitly supports the stated driver.",
        0.65,
        None,
        None,
        None,
        None,
        None,
        None,
        (document.id,),
        "fixture-host explicit forecast; not claim confidence",
    )
    return {
        "schema_version": "company-analytics.v1",
        "workflow_id": "tradingagents.company-analytics.v1",
        "company_research": company.to_dict(),
        "analytics_bundle": analytics.to_dict(),
        "source_lineage": source_lineage.to_dict(),
        "run_card": run_card.to_dict(),
        "hypothesis_ledgers": [ledger.to_dict()],
        "research_iterations": [iteration.to_dict()],
        "quality_receipt": quality.to_dict(),
        "forecasts": [forecast.to_dict()],
    }
