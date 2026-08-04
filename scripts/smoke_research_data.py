#!/usr/bin/env python3
"""Bounded live smoke evidence for the credential-free public research adapter.

This probes adapter contracts and public-provider availability. It does not claim
full company-research parity and never emits provider response bodies.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from tradingagents_host.adapters.public import PublicResearchDataAdapter, UrllibHTTPTransport
from tradingagents_host.contracts import (
    CompanyNewsQuery,
    FinancialStatementsQuery,
    FundamentalsQuery,
    GlobalNewsQuery,
    IndicatorsQuery,
    MacroQuery,
    PredictionMarketsQuery,
    PricesQuery,
    RedditQuery,
    RegulatoryFilingsQuery,
    SourceBatch,
    SourceQuery,
    StockTwitsQuery,
)

PUBLIC_CAPABILITIES = (
    "regulatory_filings",
    "fundamentals",
    "financial_statements",
    "company_news",
    "global_news",
    "macro",
    "prediction_markets",
)
FAIL_CLOSED_CAPABILITIES = ("prices", "indicators", "stocktwits", "reddit")
PROVIDER_FAILURE_STATUSES = frozenset({"unavailable", "denied", "rate_limited"})
EXIT_OK = 0
EXIT_CONTRACT_FAILURE = 2
EXIT_PROVIDER_FAILURE = 3


class ResearchAdapter(Protocol):
    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch: ...


def _utc(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        raise ValueError("cutoff must include a UTC offset")
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _query_id(symbol: str, capability: str) -> str:
    return f"smoke:{symbol.lower()}:{capability}"


def _public_query(symbol: str, capability: str, cutoff: datetime) -> SourceQuery:
    cutoff_at = _timestamp(cutoff)
    year_ago = _timestamp(cutoff - timedelta(days=365))
    news_start = _timestamp(cutoff - timedelta(days=30))
    query_id = _query_id(symbol, capability)
    if capability == "regulatory_filings":
        return RegulatoryFilingsQuery(query_id, symbol, "US", ("10-K", "10-Q", "8-K"), year_ago, cutoff_at)
    if capability == "fundamentals":
        return FundamentalsQuery(
            query_id,
            symbol,
            ("Assets", "Revenues", "NetIncomeLoss", "OperatingIncomeLoss"),
            cutoff_at,
        )
    if capability == "financial_statements":
        return FinancialStatementsQuery(
            query_id,
            symbol,
            ("balance_sheet", "income_statement", "cash_flow"),
            ("FY", "Q1", "Q2", "Q3"),
            cutoff_at,
        )
    if capability == "company_news":
        return CompanyNewsQuery(query_id, symbol, news_start, cutoff_at, 10)
    if capability == "global_news":
        return GlobalNewsQuery(query_id, (symbol, "technology"), news_start, cutoff_at, 10)
    if capability == "macro":
        return MacroQuery(
            query_id,
            ("NY.GDP.MKTP.CD", "FP.CPI.TOTL.ZG"),
            ("US",),
            _timestamp(cutoff - timedelta(days=5 * 365)),
            cutoff_at,
            cutoff_at,
        )
    if capability == "prediction_markets":
        return PredictionMarketsQuery(query_id, (symbol, "company"), cutoff_at, 10)
    raise ValueError(f"unsupported public smoke capability: {capability}")


def _fail_closed_query(symbol: str, capability: str, cutoff: datetime) -> SourceQuery:
    cutoff_at = _timestamp(cutoff)
    week_ago = _timestamp(cutoff - timedelta(days=7))
    query_id = _query_id(symbol, capability)
    if capability == "prices":
        return PricesQuery(query_id, symbol, week_ago, cutoff_at, "1d")
    if capability == "indicators":
        return IndicatorsQuery(query_id, symbol, "rsi", week_ago, cutoff_at, {"period": 14})
    if capability == "stocktwits":
        return StockTwitsQuery(query_id, symbol, week_ago, cutoff_at, 30)
    if capability == "reddit":
        return RedditQuery(query_id, symbol, week_ago, cutoff_at, 30)
    raise ValueError(f"unsupported fail-closed smoke capability: {capability}")


def _contract_failure(symbol: str, capability: str, cutoff: str, exc: Exception) -> dict[str, object]:
    exception_name = type(exc).__name__
    return {
        "symbol": symbol,
        "capability": capability,
        "provider": "unknown",
        "status": "contract_failure",
        "count": 0,
        "limitations": [f"Adapter contract failed with {exception_name}."],
        "timestamps": {"cutoff": cutoff, "retrieved_at": None},
        "failure_kind": "contract",
    }


def _evidence(symbol: str, capability: str, batch: SourceBatch) -> dict[str, object]:
    failure_kind = "provider_availability" if batch.status in PROVIDER_FAILURE_STATUSES else None
    return {
        "symbol": symbol,
        "capability": capability,
        "provider": batch.provenance.provider,
        "status": batch.status,
        "count": len(batch.items),
        "limitations": list(batch.limitations),
        "timestamps": {"cutoff": batch.cutoff, "retrieved_at": batch.provenance.retrieved_at},
        "failure_kind": failure_kind,
    }


def _probe(
    adapter: ResearchAdapter,
    symbol: str,
    capability: str,
    query: SourceQuery,
    cutoff: str,
) -> dict[str, object]:
    try:
        batch = adapter.fetch(capability, query)
        if not isinstance(batch, SourceBatch):
            raise TypeError("adapter returned a non-SourceBatch response")
        if batch.capability != capability or batch.query != query or batch.cutoff != query.cutoff_at:
            raise ValueError("adapter response does not match the requested capability, query, and cutoff")
        return _evidence(symbol, capability, batch)
    except Exception as exc:  # A smoke run must preserve evidence for every planned probe.
        return _contract_failure(symbol, capability, cutoff, exc)


def run_smoke(
    adapter: ResearchAdapter,
    symbols: tuple[str, ...],
    cutoff: str,
    *,
    strict_public: bool,
) -> tuple[dict[str, object], int]:
    cutoff_time = _utc(cutoff)
    normalized_cutoff = _timestamp(cutoff_time)
    normalized_symbols = tuple(symbol.strip().upper() for symbol in symbols if symbol.strip())
    if not normalized_symbols:
        raise ValueError("at least one symbol is required")

    public_calls = [
        _probe(adapter, symbol, capability, _public_query(symbol, capability, cutoff_time), normalized_cutoff)
        for symbol in normalized_symbols
        for capability in PUBLIC_CAPABILITIES
    ]
    fail_closed_checks = [
        _probe(adapter, symbol, capability, _fail_closed_query(symbol, capability, cutoff_time), normalized_cutoff)
        for symbol in normalized_symbols
        for capability in FAIL_CLOSED_CAPABILITIES
    ]
    contract_failures = sum(call["failure_kind"] == "contract" for call in public_calls + fail_closed_checks)
    provider_failures = sum(call["failure_kind"] == "provider_availability" for call in public_calls)
    fail_closed_violations = sum(
        call["status"] not in PROVIDER_FAILURE_STATUSES
        for call in fail_closed_checks
        if call["failure_kind"] != "contract"
    )
    evidence: dict[str, object] = {
        "schema_version": "1.0.0",
        "kind": "credential_free_public_research_data_smoke",
        "scope": {
            "claim": "bounded_adapter_contract_and_provider_availability_only",
            "limitations": [
                "This smoke does not claim full company-research parity.",
                "Prices and indicators require a licensed host source; social sources require approved host access.",
            ],
        },
        "request": {
            "symbols": list(normalized_symbols),
            "cutoff": normalized_cutoff,
            "strictness": "strict-public" if strict_public else "contract",
        },
        "public_calls": public_calls,
        "fail_closed_checks": fail_closed_checks,
        "summary": {
            "public_calls": len(public_calls),
            "provider_failures": provider_failures,
            "contract_failures": contract_failures,
            "fail_closed_violations": fail_closed_violations,
        },
    }
    if contract_failures or fail_closed_violations:
        return evidence, EXIT_CONTRACT_FAILURE
    if strict_public and provider_failures:
        return evidence, EXIT_PROVIDER_FAILURE
    return evidence, EXIT_OK


def create_adapter() -> PublicResearchDataAdapter:
    """Create the live adapter with a real retrieval clock.

    The research cutoff and retrieval receipt are different timestamps.  A
    provider that cannot reconstruct the requested historical vintage must
    therefore fail closed instead of backdating the receipt to the cutoff.
    """
    return PublicResearchDataAdapter(UrllibHTTPTransport())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["ORCL", "META"], help="Symbols to probe (default: ORCL META).")
    parser.add_argument("--cutoff", help="UTC ISO-8601 cutoff (default: current UTC time).")
    parser.add_argument("--output", default="-", help="JSON output path, or - for stdout (default: -).")
    parser.add_argument(
        "--strictness",
        choices=("contract", "strict-public"),
        default="contract",
        help="contract tolerates provider failures; strict-public requires all seven public probes per symbol.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cutoff = _timestamp(_utc(args.cutoff)) if args.cutoff else _timestamp(datetime.now(UTC))
    evidence, exit_code = run_smoke(
        create_adapter(),
        tuple(args.symbols),
        cutoff,
        strict_public=args.strictness == "strict-public",
    )
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        Path(args.output).write_text(rendered, encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
