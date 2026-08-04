"""Deterministic, provider-free fixtures for complete v3 research submissions."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256

_CUTOFF = "2026-07-31T20:00:00Z"

_PROFILES: dict[str, dict[str, object]] = {
    "ORCL": {
        "instrument_id": "equity:US68389X1054",
        "issuer_name": "Oracle Corporation",
        "asset_type": "equity",
        "exchange": "NYSE",
        "cik": "0001341439",
        "peer_instrument_id": "equity:US5949181045",
        "peer_name": "Microsoft Corporation",
        "eps": 6.0,
        "multiple": 25.0,
    },
    "META": {
        "instrument_id": "equity:US30303M1027",
        "issuer_name": "Meta Platforms, Inc.",
        "asset_type": "equity",
        "exchange": "NASDAQ",
        "cik": "0001326801",
        "peer_instrument_id": "equity:US02079K3059",
        "peer_name": "Alphabet Inc.",
        "eps": 24.0,
        "multiple": 28.0,
    },
    "QQQ": {
        "instrument_id": "fund:US46090E1038",
        "issuer_name": "Invesco QQQ Trust",
        "asset_type": "fund",
        "exchange": "NASDAQ",
        "cik": "0001067839",
        "peer_instrument_id": "fund:US92204A7028",
        "peer_name": "Vanguard Information Technology ETF",
        "eps": 19.0,
        "multiple": 27.0,
    },
}


def _document(
    slug: str,
    suffix: str,
    kind: str,
    *,
    access: str = "public",
    redistributable: bool = True,
    extract: str | None = "Bounded synthetic extract retained for deterministic conformance testing.",
) -> dict[str, object]:
    document_id = f"{slug}-doc-{suffix}"
    limitation = "Host entitlement was unavailable at the research cutoff." if access == "entitlement_blocked" else None
    title = f"{slug.upper()} synthetic {suffix.replace('-', ' ')} evidence"
    publisher = "Deterministic fixture publisher"
    retained_content = json.dumps(
        {"extract": extract, "kind": kind, "publisher": publisher, "title": title},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "id": document_id,
        "kind": kind,
        "title": title,
        "publisher": publisher,
        "locator": {
            "canonical_uri": f"https://fixtures.example.test/{slug}/{suffix}",
            "document_id": document_id,
            "accession_number": f"0000000000-26-{len(suffix):06d}" if kind == "filing" else None,
            "content_sha256": sha256(retained_content.encode()).hexdigest(),
        },
        "entitlement": {
            "access": access,
            "redistributable": redistributable,
            "terms_uri": "https://fixtures.example.test/terms",
            "limitation": limitation,
        },
        "temporal": {
            "observed_at": "2026-07-29T12:00:00Z",
            "published_at": "2026-07-29T13:00:00Z",
            "available_at": "2026-07-29T13:05:00Z",
            "retrieved_at": "2026-07-30T10:00:00Z",
            "cutoff_at": _CUTOFF,
        },
        "extract": extract,
    }


def complete_v3_submission(symbol: str) -> dict[str, object]:
    """Return a fresh, fully linked host submission for one supported identity."""
    profile = _PROFILES.get(
        symbol,
        {
            "instrument_id": f"equity:fixture:{symbol}",
            "issuer_name": f"{symbol} Fixture Company",
            "asset_type": "equity",
            "exchange": "NASDAQ",
            "cik": "0000000001",
            "peer_instrument_id": "equity:fixture:PEER",
            "peer_name": "Fixture Peer Company",
            "eps": 5.0,
            "multiple": 20.0,
        },
    )
    slug = symbol.lower()
    is_fund = profile["asset_type"] == "fund"
    identity = {
        "instrument_id": profile["instrument_id"],
        "symbol": symbol,
        "issuer_name": profile["issuer_name"],
        "asset_type": profile["asset_type"],
        "exchange": profile["exchange"],
        "currency": "USD",
        "country": "US",
        "cik": profile["cik"],
    }
    filing = _document(slug, "filing", "filing")
    narrative = _document(slug, "narrative", "company")
    market = _document(slug, "market", "market")
    blocked = _document(
        slug,
        "licensed-consensus",
        "other",
        access="entitlement_blocked",
        redistributable=False,
        extract=None,
    )
    transcript = None if is_fund else _document(slug, "transcript", "transcript")
    documents = [filing, narrative, market, blocked] + ([] if transcript is None else [transcript])
    eps_id = f"{slug}-metric-eps"
    multiple_id = f"{slug}-metric-multiple"
    value_id = f"{slug}-metric-fair-value"
    calc_id = f"{slug}-calc-fair-value"
    bull_claim = f"{slug}-claim-bull"
    bear_claim = f"{slug}-claim-bear"
    guide_claim = f"{slug}-claim-guidance"
    valuation_id = f"{slug}-valuation-base"
    fair_value = float(profile["eps"]) * float(profile["multiple"])
    portfolio_context = {
        "objective": "Evaluate long-horizon risk-adjusted fit.",
        "horizon": "3-5 years",
        "risk_tolerance": "moderate",
        "sector_exposure_percent": 20.0,
        "issuer_exposure_percent": 0.0,
        "constraints": ["No leverage", "Research output is non-executable"],
        "non_executable": True,
    }
    coverage_areas = ("financials", "narrative", "market", "transcripts", "licensed_consensus")
    request = {
        "schema_version": "2026-08-03.v3",
        "request_id": f"request-{slug}-20260731",
        "requested_at": "2026-08-01T00:00:00Z",
        "cutoff_at": _CUTOFF,
        "research_mode": "fixture",
        "identity": deepcopy(identity),
        "research_plan": {
            "objectives": [
                {
                    "id": f"objective-{slug}",
                    "question": f"What is the evidence-grounded risk/reward for {symbol}?",
                    "decision_relevance": "Supports a non-executable portfolio research decision.",
                    "required_claim_kinds": ["fact", "thesis"],
                }
            ],
            "coverage_dimensions": [
                {
                    "area": area,
                    "required": area not in {"licensed_consensus", "transcripts"} or not is_fund,
                    "minimum_source_count": 0 if area == "transcripts" and is_fund else 1,
                    "preferred_source_kinds": [
                        "filing"
                        if area == "financials"
                        else "company"
                        if area == "narrative"
                        else "market"
                        if area == "market"
                        else "transcript"
                        if area == "transcripts"
                        else "other"
                    ],
                    "entitlement_policy": "host_entitled_allowed" if area == "licensed_consensus" else "public_only",
                }
                for area in coverage_areas
            ],
            "history_windows": [
                {
                    "area": "financials",
                    "start_at": "2024-01-01T00:00:00Z",
                    "end_at": _CUTOFF,
                    "minimum_periods": 3,
                    "expansion_reasons": ["Detect trend breaks"],
                    "latest_data_checks": ["Confirm latest filing availability"],
                    "stop_conditions": ["Three comparable periods retained"],
                }
            ],
            "latest_data_checks": ["Reconcile sources available by cutoff"],
            "stop_conditions": ["Required dimensions resolved or limitations declared"],
        },
        "output_language": "en-US",
        "portfolio_context": deepcopy(portfolio_context),
        "non_executable": True,
    }
    dossier = {
        "schema_version": "2026-08-03.v3",
        "dossier_id": f"dossier-{slug}-20260731",
        "status": "completed",
        "as_of_at": _CUTOFF,
        "completed_at": "2026-08-01T00:30:00Z",
        "identity": deepcopy(identity),
        "documents": documents,
        "calculations": [
            {
                "id": calc_id,
                "formula": f"{eps_id} * {multiple_id}",
                "operation": "multiply",
                "input_metric_ids": [eps_id, multiple_id],
                "constants": [],
                "result": fair_value,
                "unit": "USD/share",
                "engine": "fixture-arithmetic.v1",
                "rounding_digits": 2,
                "tolerance": 1e-9,
                "deterministic": True,
            }
        ],
        "metrics": [
            {
                "id": eps_id,
                "label": "Normalized earnings per share",
                "value": float(profile["eps"]),
                "unit": "USD/share",
                "period_start": "2025-08-01T00:00:00Z",
                "period_end": "2026-07-29T12:00:00Z",
                "as_of_at": "2026-07-29T13:05:00Z",
                "basis": "reported",
                "source_document_ids": [filing["id"]],
                "calculation_id": None,
            },
            {
                "id": multiple_id,
                "label": "Selected earnings multiple",
                "value": float(profile["multiple"]),
                "unit": "x",
                "period_start": None,
                "period_end": "2026-07-29T12:00:00Z",
                "as_of_at": "2026-07-29T13:05:00Z",
                "basis": "assumption",
                "source_document_ids": [market["id"]],
                "calculation_id": None,
            },
            {
                "id": value_id,
                "label": "Recomputed fair value",
                "value": fair_value,
                "unit": "USD/share",
                "period_start": None,
                "period_end": "2026-07-29T12:00:00Z",
                "as_of_at": "2026-07-29T13:05:00Z",
                "basis": "calculated",
                "source_document_ids": [market["id"]],
                "calculation_id": calc_id,
            },
        ],
        "claims": [
            {
                "id": bull_claim,
                "statement": f"{symbol} has a supported constructive scenario.",
                "kind": "thesis",
                "stance": "bull",
                "evidence_document_ids": [filing["id"]],
                "metric_ids": [eps_id],
                "counterevidence_document_ids": [market["id"]],
                "counterclaim_ids": [bear_claim],
                "confidence": 0.72,
            },
            {
                "id": bear_claim,
                "statement": f"{symbol} remains exposed to valuation compression.",
                "kind": "thesis",
                "stance": "bear",
                "evidence_document_ids": [market["id"]],
                "metric_ids": [multiple_id],
                "counterevidence_document_ids": [filing["id"]],
                "counterclaim_ids": [bull_claim],
                "confidence": 0.64,
            },
            {
                "id": guide_claim,
                "statement": "The retained issuer evidence supports the declared forward range.",
                "kind": "guidance",
                "stance": "neutral",
                "evidence_document_ids": [narrative["id"]],
                "metric_ids": [eps_id],
                "counterevidence_document_ids": [],
                "counterclaim_ids": [],
                "confidence": 0.7,
            },
        ],
        "arguments": [
            {
                "argument_id": f"{slug}-argument-bull",
                "debate": "research",
                "round": 1,
                "turn": 1,
                "role": "bull_researcher",
                "claim_ids": [bull_claim],
                "assumption_ids": [guide_claim],
                "rebuttal_of": None,
                "concessions": [],
                "unresolved": ["Licensed consensus unavailable"],
            },
            {
                "argument_id": f"{slug}-argument-bear",
                "debate": "research",
                "round": 1,
                "turn": 2,
                "role": "bear_researcher",
                "claim_ids": [bear_claim],
                "assumption_ids": [],
                "rebuttal_of": f"{slug}-argument-bull",
                "concessions": ["Reported earnings evidence is retained"],
                "unresolved": [],
            },
        ],
        "filings": [
            {
                "id": f"{slug}-filing-record",
                "form": "10-Q",
                "accession_number": filing["locator"]["accession_number"],
                "filed_at": "2026-07-29T13:00:00Z",
                "period_end": "2026-06-30T00:00:00Z",
                "document_id": filing["id"],
                "amendment": False,
            }
        ],
        "filing_changes": [
            {
                "id": f"{slug}-filing-change",
                "prior_document_id": None,
                "current_document_id": filing["id"],
                "change_kind": "mda",
                "summary": "Current-period discussion was evaluated against the declared history window.",
                "metric_ids": [eps_id],
                "claim_ids": [bull_claim],
            }
        ],
        "transcripts": []
        if transcript is None
        else [
            {
                "id": f"{slug}-transcript-record",
                "event_at": "2026-07-29T12:00:00Z",
                "document_id": transcript["id"],
                "speaker_summary": "Management discussed the supported forward range.",
                "guidance_claim_ids": [guide_claim],
                "segments": [
                    {
                        "id": f"{slug}-segment-1",
                        "section": "qa",
                        "speaker": "Chief Financial Officer",
                        "extract": "A bounded synthetic statement about the declared range.",
                        "claim_ids": [guide_claim],
                    }
                ],
                "themes": [
                    {
                        "id": f"{slug}-theme-1",
                        "title": "Forward range",
                        "segment_ids": [f"{slug}-segment-1"],
                        "claim_ids": [guide_claim],
                    }
                ],
            }
        ],
        "guidance": [
            {
                "id": f"{slug}-guidance-1",
                "metric": "Normalized earnings per share",
                "period": "FY2027",
                "low": float(profile["eps"]) * 0.95,
                "high": float(profile["eps"]) * 1.10,
                "unit": "USD/share",
                "status": "introduced",
                "claim_id": guide_claim,
            }
        ],
        "peers": [
            {
                "id": f"{slug}-peer-1",
                "peer_instrument_id": profile["peer_instrument_id"],
                "rationale": f"{profile['peer_name']} is a structurally relevant comparison.",
                "methodology": "Normalize currency to USD and compare the same forward period.",
                "metric_ids": [multiple_id],
                "evidence_document_ids": [market["id"]],
            }
        ],
        "factors": [
            {
                "id": f"{slug}-factor-quality",
                "factor": "quality",
                "direction": "positive",
                "magnitude": "moderate",
                "value": 0.65,
                "unit": "score",
                "methodology": "Deterministic normalization of retained reported metrics.",
                "methodology_version": "fixture-factor.v1",
                "as_of_at": "2026-07-29T13:05:00Z",
                "prior_snapshot_id": None,
                "delta": None,
                "history_document_ids": [filing["id"]],
                "evidence_document_ids": [filing["id"]],
            }
        ],
        "valuations": [
            {
                "id": valuation_id,
                "name": "base",
                "methodology": "Normalized earnings multiplied by a selected comparable multiple.",
                "currency": "USD",
                "fair_value": fair_value,
                "horizon": "12 months",
                "input_metric_ids": [eps_id, multiple_id],
                "calculation_ids": [calc_id],
                "assumption_claim_ids": [guide_claim],
                "assumptions": [
                    {
                        "id": f"{slug}-assumption-eps",
                        "label": "EPS",
                        "value": float(profile["eps"]),
                        "unit": "USD/share",
                        "metric_ids": [eps_id],
                        "claim_ids": [guide_claim],
                    },
                    {
                        "id": f"{slug}-assumption-multiple",
                        "label": "Multiple",
                        "value": float(profile["multiple"]),
                        "unit": "x",
                        "metric_ids": [multiple_id],
                        "claim_ids": [bear_claim],
                    },
                ],
                "sensitivity_cells": [
                    {
                        "id": f"{slug}-sensitivity-base",
                        "row_assumption_id": f"{slug}-assumption-eps",
                        "column_assumption_id": f"{slug}-assumption-multiple",
                        "fair_value": fair_value,
                        "calculation_ids": [calc_id],
                    }
                ],
            }
        ],
        "entities": [
            {"id": f"{slug}-entity-issuer", "name": profile["issuer_name"], "kind": "issuer"},
            {"id": f"{slug}-entity-peer", "name": profile["peer_name"], "kind": "peer"},
        ],
        "events": [
            {
                "id": f"{slug}-event-filing",
                "occurred_at": "2026-07-29T13:00:00Z",
                "title": "Latest filing became available",
                "status": "historical",
                "evidence_document_ids": [filing["id"]],
                "claim_ids": [bull_claim],
                "entity_ids": [f"{slug}-entity-issuer"],
                "ripple_event_ids": [],
            }
        ],
        "risks": [
            {
                "id": f"{slug}-risk-valuation",
                "name": "Valuation compression",
                "probability": 0.35,
                "impact": "high",
                "thesis": "The selected multiple may contract.",
                "evidence_document_ids": [market["id"]],
                "claim_ids": [bear_claim],
                "trigger_metric_ids": [multiple_id],
            }
        ],
        "monitoring": [
            {
                "id": f"{slug}-monitor-valuation",
                "description": "Monitor the selected valuation multiple.",
                "cadence": "quarterly",
                "trigger": "Multiple moves by more than 20 percent.",
                "consequence": "Recompute all valuation cases.",
                "related_ids": [multiple_id],
            }
        ],
        "prior_outcomes": [
            {
                "id": f"{slug}-outcome-1",
                "forecast_claim_id": bull_claim,
                "forecast_at": "2026-01-15T12:00:00Z",
                "evaluated_at": "2026-07-29T13:05:00Z",
                "result": "partially_confirmed",
                "outcome_document_ids": [filing["id"]],
                "calibration_score": 0.7,
                "notes": "Outcome uses only evidence available by the declared cutoff.",
            }
        ],
        "evaluation": {
            "evaluator": "deterministic-fixture-evaluator",
            "evaluator_provenance": "Portable deterministic rules; no model arithmetic.",
            "rubric_version": "research-quality.v1",
            "checks": [
                {
                    "id": f"{slug}-evaluation-grounding",
                    "status": "pass",
                    "rubric": "Decision-relevant claims retain evidence and calculation links.",
                    "evaluator": "deterministic-fixture-evaluator",
                    "evaluated_at": "2026-07-31T19:00:00Z",
                    "document_ids": [filing["id"]],
                    "claim_ids": [bull_claim, bear_claim],
                    "calculation_ids": [calc_id],
                    "notes": "All referenced identifiers resolve.",
                }
            ],
            "limitations": ["Licensed consensus was entitlement-blocked."],
        },
        "research_delta": {
            "previous_dossier_sha256": "a" * 64,
            "added_document_ids": [filing["id"]],
            "changed_claim_ids": [bull_claim],
            "changed_valuation_ids": [valuation_id],
            "summary": "Latest retained filing changed the earnings evidence and base valuation.",
        },
        "portfolio_context": deepcopy(portfolio_context),
        "portfolio_impact": {
            "thesis": "The security adds measured exposure without granting execution authority.",
            "issuer_exposure_delta_percent": 2.0,
            "sector_exposure_delta_percent": 1.0,
            "diversification_effect": "neutral",
            "risk_contribution": "similar",
            "metric_ids": [value_id],
            "claim_ids": [bull_claim, bear_claim],
            "non_executable": True,
        },
        "coverage": [
            {"area": "financials", "status": "complete", "source_document_ids": [filing["id"]], "limitation": None},
            {"area": "narrative", "status": "complete", "source_document_ids": [narrative["id"]], "limitation": None},
            {"area": "market", "status": "complete", "source_document_ids": [market["id"]], "limitation": None},
            {
                "area": "transcripts",
                "status": "not_applicable" if transcript is None else "complete",
                "source_document_ids": [narrative["id"]] if transcript is None else [transcript["id"]],
                "limitation": (
                    "The fund identity has no issuer earnings-call transcript." if transcript is None else None
                ),
            },
            {
                "area": "licensed_consensus",
                "status": "entitlement_blocked",
                "source_document_ids": [blocked["id"]],
                "limitation": "The host lacked entitlement; no consensus claim was made.",
            },
        ],
        "recommendation": "hold",
        "executive_summary": f"Synthetic, point-in-time-safe research dossier for {symbol}.",
        "limitations": ["Fixture values are deterministic and not investment advice."],
    }
    return {
        "schema_version": "2026-08-03.v3",
        "workflow_id": "tradingagents.company-research.v2",
        "request": request,
        "dossier": dossier,
    }
