"""SEC provider, including issuer resolution, validation, and normalization."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, cast

from stock_research_agents_host.adapters.providers._base import (
    ProviderPayloadError,
    ProviderSupport,
    digest,
    instant,
    iso,
    query_instant,
)
from stock_research_agents_host.adapters.providers.catalog import provider_specs
from stock_research_agents_host.contracts import (
    FinancialStatementsQuery,
    FundamentalsQuery,
    NormalizedFact,
    RegulatoryFilingsQuery,
    SourceBatch,
    SourceObservation,
    SourceQuery,
)

MAX_SEC_SUBMISSION_FILES = 32
MAX_SEC_COMPANY_FACT_ITEMS = 1_000


def _available_at(filed: object, accepted: object = None) -> tuple[str | None, bool]:
    accepted_at = iso(accepted)
    if accepted_at is not None:
        return accepted_at, False
    filed_at = iso(filed)
    if filed_at is None:
        return None, False
    if isinstance(filed, str) and len(filed.strip()) in {8, 10}:
        return filed_at.replace("T00:00:00+00:00", "T23:59:59.999999+00:00"), True
    return filed_at, False


def _history_files(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise ProviderPayloadError("SEC submissions historical files must be an array")
    validated: list[Mapping[str, object]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise ProviderPayloadError("SEC historical submission metadata entries must be objects")
        name = entry.get("name")
        start = instant(entry.get("filingFrom"))
        end = instant(entry.get("filingTo"))
        if not isinstance(name, str) or not re.fullmatch(r"CIK\d+-submissions-\d+\.json", name):
            raise ProviderPayloadError("SEC historical submission metadata contains an invalid name")
        if start is None or end is None or start > end:
            raise ProviderPayloadError("SEC historical submission metadata contains an invalid date range")
        validated.append(cast(Mapping[str, object], entry))
    return validated


def _filing_table(value: Mapping[str, object], table_name: str) -> Mapping[str, list[object]]:
    forms = value.get("form")
    if not isinstance(forms, list):
        raise ProviderPayloadError(f"SEC filing table {table_name} must contain a form array")
    columns: dict[str, list[object]] = {"form": forms}
    for key in ("filingDate", "acceptanceDateTime", "accessionNumber", "primaryDocument"):
        column = value.get(key)
        if column is None and not forms:
            columns[key] = []
            continue
        if not isinstance(column, list) or len(column) != len(forms):
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid {key} column")
        columns[key] = column
    for index, form in enumerate(forms):
        if not isinstance(form, str) or not form.strip():
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid form value")
        if instant(columns["filingDate"][index]) is None:
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid filing date")
        accepted = columns["acceptanceDateTime"][index]
        if accepted not in {None, ""} and instant(accepted) is None:
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid acceptance timestamp")
        accession = columns["accessionNumber"][index]
        if not isinstance(accession, str) or not re.fullmatch(r"\d+-\d{2}-\d+", accession):
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid accession number")
        primary_document = columns["primaryDocument"][index]
        if not isinstance(primary_document, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", primary_document):
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid primary document")
    return columns


def _at(rows: Mapping[str, list[object]], key: str, index: int) -> object | None:
    values = rows.get(key, [])
    return values[index] if index < len(values) else None


def _statement_alias(value: str) -> str:
    normalized = value.lower().replace("-", "_").replace(" ", "_")
    return {
        "balance": "balance_sheet",
        "income": "income_statement",
        "operations": "income_statement",
        "cashflow": "cash_flow",
        "cash_flow_statement": "cash_flow",
    }.get(normalized, normalized)


def _statement_kind(metric: str) -> str | None:
    lowered = metric.lower()
    if any(token in lowered for token in ("cashprovided", "cashused", "cashflow", "payments", "proceeds")):
        return "cash_flow"
    if any(token in lowered for token in ("revenue", "income", "earnings", "expense", "profit", "loss")):
        return "income_statement"
    if any(token in lowered for token in ("assets", "liabilities", "equity", "inventory", "receivable")):
        return "balance_sheet"
    return None


def _period_matches(row: Mapping[str, object], periods: set[str]) -> bool:
    normalized = {item.lower() for item in periods}
    candidates = {
        str(row.get("end", "")).lower(),
        str(row.get("fy", "")).lower(),
        str(row.get("fp", "")).lower(),
        str(row.get("frame", "")).lower(),
    }
    if normalized.intersection(candidates):
        return True
    form = str(row.get("form", "")).upper()
    fp = str(row.get("fp", "")).upper()
    return ("annual" in normalized and (form == "10-K" or fp == "FY")) or (
        "quarterly" in normalized and (form == "10-Q" or fp in {"Q1", "Q2", "Q3"})
    )


@dataclass(frozen=True, slots=True)
class SecProvider:
    support: ProviderSupport
    max_company_fact_items: int = MAX_SEC_COMPANY_FACT_ITEMS

    provider_id: ClassVar[str] = "sec"
    specs: ClassVar = provider_specs(provider_id)

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        if capability == "regulatory_filings":
            if not isinstance(query, RegulatoryFilingsQuery):
                raise ValueError(f"{capability} requires its matching typed query")
            return self._filings(query)
        if capability == "fundamentals":
            if not isinstance(query, FundamentalsQuery):
                raise ValueError(f"{capability} requires its matching typed query")
            return self._facts(query, statements=False)
        if not isinstance(query, FinancialStatementsQuery):
            raise ValueError(f"{capability} requires its matching typed query")
        return self._facts(query, statements=True)

    def _resolve_cik(self, capability: str, query: SourceQuery, issuer: str) -> str | SourceBatch:
        digits = issuer.removeprefix("CIK").strip()
        if digits.isdigit():
            return digits.zfill(10)
        response = self.support.request(
            capability,
            query,
            "https://www.sec.gov/files/company_tickers.json",
            headers=self.support.headers,
        )
        if isinstance(response, SourceBatch):
            return response
        if not isinstance(response.payload, Mapping):
            raise ProviderPayloadError("SEC ticker directory must be an object")
        for row in response.payload.values():
            if isinstance(row, Mapping) and str(row.get("ticker", "")).upper() == issuer.upper():
                cik = str(row.get("cik_str", ""))
                if not cik.isdigit():
                    raise ProviderPayloadError("SEC ticker directory returned an invalid CIK")
                return cik.zfill(10)
        return self.support.terminal(capability, query, "unavailable", "SEC issuer identity could not be resolved.")

    def _filings(self, query: RegulatoryFilingsQuery) -> SourceBatch:
        capability = "regulatory_filings"
        if query.jurisdiction.upper() not in {"US", "USA", "SEC"}:
            return self.support.terminal(
                capability, query, "unavailable", "SEC adapter supports United States filings only."
            )
        cik = self._resolve_cik(capability, query, query.issuer)
        if isinstance(cik, SourceBatch):
            return cik
        response = self.support.request(
            capability,
            query,
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=self.support.headers,
        )
        if isinstance(response, SourceBatch):
            return response
        if not isinstance(response.payload, Mapping):
            raise ProviderPayloadError("SEC submissions response must be an object")
        filings_value = response.payload.get("filings")
        if not isinstance(filings_value, Mapping):
            raise ProviderPayloadError("SEC submissions response must contain filings")
        filings = cast(Mapping[str, object], filings_value)
        recent_value = filings.get("recent")
        if not isinstance(recent_value, Mapping):
            raise ProviderPayloadError("SEC submissions response must contain recent filings")
        filing_tables: list[tuple[str, Mapping[str, list[object]]]] = [
            ("recent", _filing_table(cast(Mapping[str, object], recent_value), "recent"))
        ]
        gaps: list[str] = []
        filed_after = query_instant(query.filed_after)
        filed_before = query_instant(query.filed_before)
        cutoff = query_instant(query.cutoff_at)
        historical_files = [
            entry
            for entry in _history_files(filings.get("files", []))
            if query_instant(cast(str, entry["filingTo"])).date() >= filed_after.date()
            and query_instant(cast(str, entry["filingFrom"])).date() <= filed_before.date()
        ]
        if len(historical_files) > MAX_SEC_SUBMISSION_FILES:
            gaps.append(
                f"SEC listed more than the bounded {MAX_SEC_SUBMISSION_FILES} relevant historical submission files."
            )
        for entry in historical_files[:MAX_SEC_SUBMISSION_FILES]:
            name = cast(str, entry["name"])
            historical = self.support.request(
                capability,
                query,
                f"https://data.sec.gov/submissions/{name}",
                headers=self.support.headers,
            )
            if isinstance(historical, SourceBatch):
                gaps.append(f"SEC historical submission file {name} could not be retrieved.")
                continue
            if not isinstance(historical.payload, Mapping):
                gaps.append(f"SEC historical submission file {name} had an invalid response shape.")
                continue
            filing_tables.append((name, _filing_table(cast(Mapping[str, object], historical.payload), name)))
        rows: list[SourceObservation] = []
        conservative_dates = False
        for table_name, table in filing_tables:
            for index, form in enumerate(table.get("form", [])):
                if str(form) not in query.form_types:
                    continue
                filed_raw = _at(table, "filingDate", index)
                filed = iso(filed_raw)
                available, conservative = _available_at(filed_raw, _at(table, "acceptanceDateTime", index))
                conservative_dates = conservative_dates or conservative
                filed_instant = instant(filed)
                available_instant = instant(available)
                if (
                    filed is None
                    or available is None
                    or filed_instant is None
                    or available_instant is None
                    or not filed_after.date() <= filed_instant.date() <= filed_before.date()
                    or available_instant > cutoff
                ):
                    continue
                accession = str(_at(table, "accessionNumber", index) or f"{table_name}-row-{index}")
                primary = str(_at(table, "primaryDocument", index) or "")
                uri = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary}"
                metadata = {"accession": accession, "form": form, "filed": filed, "available": available}
                rows.append(
                    self.support.observation(
                        source_id=f"sec-{accession}",
                        source_kind="filing",
                        uri=uri,
                        observed=filed,
                        published=available,
                        available=available,
                        provider="SEC EDGAR",
                        provider_version="submissions-v1",
                        license_id="sec-public-data-v1",
                        facts=(
                            NormalizedFact("form_type", str(form)),
                            NormalizedFact("accession_number", accession),
                        ),
                        digest_value=metadata,
                    )
                )
        limitations = (
            ("SEC date-only filing availability is conservatively represented as end-of-day UTC.",)
            if conservative_dates
            else ()
        )
        return self.support.batch(
            capability,
            query,
            tuple(rows),
            "SEC EDGAR",
            "submissions-v1",
            "sec-public-data-v1",
            "https://www.sec.gov/os/accessing-edgar-data",
            status="partial" if gaps else "complete",
            limitations=tuple(gaps) + limitations,
            gaps=tuple(gaps),
        )

    def _facts(
        self,
        query: FundamentalsQuery | FinancialStatementsQuery,
        *,
        statements: bool,
    ) -> SourceBatch:
        capability = "financial_statements" if statements else "fundamentals"
        issuer = query.issuer if isinstance(query, FinancialStatementsQuery) else query.symbol
        cik = self._resolve_cik(capability, query, issuer)
        if isinstance(cik, SourceBatch):
            return cik
        response = self.support.request(
            capability,
            query,
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=self.support.headers,
        )
        if isinstance(response, SourceBatch):
            return response
        if not isinstance(response.payload, Mapping):
            raise ProviderPayloadError("SEC company facts response must be an object")
        facts_value = response.payload.get("facts")
        if not isinstance(facts_value, Mapping):
            raise ProviderPayloadError("SEC company facts response must contain a facts object")
        taxonomies = cast(Mapping[str, object], facts_value)
        requested = None if statements else {item.lower() for item in cast(FundamentalsQuery, query).metrics}
        statement_query = cast(FinancialStatementsQuery, query) if statements else None
        periods = set(statement_query.periods) if statement_query else set()
        statement_types = (
            {_statement_alias(item) for item in statement_query.statement_types} if statement_query else set()
        )
        rows: list[SourceObservation] = []
        returned_metrics: set[str] = set()
        returned_statement_periods: set[tuple[str, str]] = set()
        conservative_dates = False
        capped = False
        cutoff = query_instant(query.as_of)
        for taxonomy, taxonomy_facts in taxonomies.items():
            if not isinstance(taxonomy_facts, Mapping):
                continue
            for metric, fact_payload in taxonomy_facts.items():
                if requested is not None and metric.lower() not in requested:
                    continue
                statement_kind = _statement_kind(metric)
                if statements and statement_kind not in statement_types:
                    continue
                if not isinstance(fact_payload, Mapping) or not isinstance(fact_payload.get("units"), Mapping):
                    continue
                for unit, observations in cast(Mapping[str, object], fact_payload["units"]).items():
                    if not isinstance(observations, list):
                        continue
                    for row in observations:
                        if not isinstance(row, Mapping):
                            continue
                        filed_raw = row.get("filed")
                        filed = iso(filed_raw)
                        available, conservative = _available_at(filed_raw)
                        conservative_dates = conservative_dates or conservative
                        end = str(row.get("end", ""))
                        available_instant = instant(available)
                        if (
                            filed is None
                            or available is None
                            or available_instant is None
                            or available_instant > cutoff
                        ):
                            continue
                        if statements and periods and not _period_matches(row, periods):
                            continue
                        accession = str(row.get("accn", f"fact-{digest(row)[:16]}"))
                        value = str(row.get("val", ""))
                        if not value:
                            continue
                        if len(rows) >= self.max_company_fact_items:
                            capped = True
                            continue
                        facts = [
                            NormalizedFact("metric", metric),
                            NormalizedFact("value", value, str(unit), end or None),
                        ]
                        if statements:
                            facts.extend(
                                (
                                    NormalizedFact("taxonomy", taxonomy),
                                    NormalizedFact("statement_type", cast(str, statement_kind)),
                                )
                            )
                        rows.append(
                            self.support.observation(
                                source_id=f"sec-{accession}-{digest((taxonomy, metric, unit, row))[:16]}",
                                source_kind="fundamental",
                                uri=(
                                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
                                ),
                                observed=iso(row.get("start")) or filed,
                                published=available,
                                available=available,
                                provider="SEC EDGAR",
                                provider_version="companyfacts-v1",
                                license_id="sec-public-data-v1",
                                facts=tuple(facts),
                                digest_value=row,
                            )
                        )
                        returned_metrics.add(metric.lower())
                        if statements:
                            returned_statement_periods.update(
                                (cast(str, statement_kind), period)
                                for period in periods
                                if _period_matches(row, {period})
                            )
        gaps: list[str] = []
        if capped:
            gaps.append(
                f"SEC company facts exceeded the adapter limit of {self.max_company_fact_items} items; "
                "additional matching facts were omitted."
            )
        if requested is not None:
            requested_names = {item.lower(): item for item in cast(FundamentalsQuery, query).metrics}
            gaps.extend(
                f"SEC company facts did not return requested metric: {requested_names[metric]}."
                for metric in sorted(requested - returned_metrics)
            )
        else:
            expected = {(statement_type, period) for statement_type in statement_types for period in periods}
            gaps.extend(
                "SEC company facts did not return requested coverage for "
                f"statement_type={statement_type}, period={period}."
                for statement_type, period in sorted(expected - returned_statement_periods)
            )
        status = "complete" if not gaps else ("partial" if rows else "unavailable")
        limitations = list(gaps)
        if conservative_dates:
            limitations.append("SEC company facts expose filing dates without times; availability uses end-of-day UTC.")
        return self.support.batch(
            capability,
            query,
            tuple(rows),
            "SEC EDGAR",
            "companyfacts-v1",
            "sec-public-data-v1",
            "https://www.sec.gov/os/accessing-edgar-data",
            status=status,
            limitations=tuple(limitations),
            gaps=tuple(gaps),
        )
