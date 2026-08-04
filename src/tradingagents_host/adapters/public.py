"""Lawful public research-data adapters with host-injected network and licensed ports."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from tradingagents_host.contracts import (
    CompanyNewsQuery,
    FinancialStatementsQuery,
    FundamentalsQuery,
    GlobalNewsQuery,
    IndicatorsQuery,
    MacroQuery,
    NormalizedFact,
    PricesQuery,
    RedditQuery,
    RegulatoryFilingsQuery,
    SourceBatch,
    SourceCompleteness,
    SourceEntitlement,
    SourceObservation,
    SourcePagination,
    SourceProvenance,
    SourceQuery,
    StockTwitsQuery,
    validate_source_response,
)
from tradingagents_host.ports import SourcePort

ADAPTER_VERSION = "1.0.0"
SEC_USER_AGENT = "StockResearchAgents research adapter/0.1 (https://github.com/harshitagarwal2/StockResearchAgents)"
MAX_SEC_SUBMISSION_FILES = 32
MAX_SEC_COMPANY_FACT_ITEMS = 1_000
MAX_WORLD_BANK_PAGES = 100
_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
_CREDENTIAL_PARAM_PARTS = {"authorization", "cookie", "credential", "key", "password", "secret", "sig", "token"}


def _reject_credential_fields(fields: Mapping[str, object] | None, label: str) -> None:
    for key in fields or {}:
        normalized = str(key).lower().replace("-", "_")
        if any(part in _CREDENTIAL_PARAM_PARTS for part in normalized.split("_")):
            raise ValueError(f"public transport {label} cannot contain credential fields")


class ProviderTransportError(RuntimeError):
    """A public provider could not be reached or decoded by the transport."""


class ProviderPayloadError(RuntimeError):
    """A provider returned a successful response with an unusable payload shape."""


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    status: int
    payload: object
    headers: Mapping[str, str] | None = None


class HTTPTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HTTPResponse: ...


class UrllibHTTPTransport:
    """Small default transport; credentials are intentionally unsupported."""

    def __init__(
        self,
        *,
        operator_identity: str = SEC_USER_AGENT,
        max_attempts: int = 3,
        backoff_seconds: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not operator_identity.strip() or "(" not in operator_identity or ")" not in operator_identity:
            raise ValueError("operator_identity must descriptively identify the host and a contact")
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if not 0 <= backoff_seconds <= 1:
            raise ValueError("backoff_seconds must be between 0 and 1 second")
        self._operator_identity = operator_identity
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    @property
    def operator_identity(self) -> str:
        return self._operator_identity

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HTTPResponse:
        _reject_credential_fields(params, "parameters")
        _reject_credential_fields(headers, "headers")
        target = f"{url}?{urlencode(params)}" if params else url
        request_headers = {"User-Agent": self._operator_identity, **dict(headers or {})}
        request = Request(target, headers=request_headers)
        for attempt in range(self._max_attempts):
            try:
                with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS provider URLs
                    result = HTTPResponse(response.status, json.loads(response.read()), dict(response.headers))
            except HTTPError as exc:
                result = HTTPResponse(exc.code, None, dict(exc.headers or {}))
            if result.status not in _RETRYABLE_HTTP_STATUSES or attempt + 1 == self._max_attempts:
                return result
            self._sleep(self._backoff_seconds * (2**attempt))
        raise AssertionError("bounded retry loop did not return")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value.strip()
    if len(candidate) == 8 and candidate.isdigit():
        candidate = f"{candidate[:4]}-{candidate[4:6]}-{candidate[6:]}T00:00:00+00:00"
    elif len(candidate) == 10:
        candidate = f"{candidate}T00:00:00+00:00"
    elif len(candidate.removesuffix("Z")) == 15 and candidate[8] == "T":
        compact = candidate.removesuffix("Z")
        date_part = f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
        time_part = f"{compact[9:11]}:{compact[11:13]}:{compact[13:]}"
        candidate = f"{date_part}T{time_part}+00:00"
    elif candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _instant(value: object) -> datetime | None:
    normalized = _iso(value)
    if normalized is None:
        return None
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _query_instant(value: str) -> datetime:
    parsed = _instant(value)
    if parsed is None:  # Query contracts validate timestamps before adapter dispatch.
        raise ValueError("validated source query contains an invalid timestamp")
    return parsed


def _sec_available_at(filed: object, accepted: object = None) -> tuple[str | None, bool]:
    accepted_at = _iso(accepted)
    if accepted_at is not None:
        return accepted_at, False
    filed_at = _iso(filed)
    if filed_at is None:
        return None, False
    if isinstance(filed, str) and len(filed.strip()) in {8, 10}:
        return filed_at.replace("T00:00:00+00:00", "T23:59:59.999999+00:00"), True
    return filed_at, False


def _validated_sec_history_files(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise ProviderPayloadError("SEC submissions historical files must be an array")
    validated: list[Mapping[str, object]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise ProviderPayloadError("SEC historical submission metadata entries must be objects")
        name = entry.get("name")
        filing_from = entry.get("filingFrom")
        filing_to = entry.get("filingTo")
        if not isinstance(name, str) or not re.fullmatch(r"CIK\d+-submissions-\d+\.json", name):
            raise ProviderPayloadError("SEC historical submission metadata contains an invalid name")
        start = _instant(filing_from)
        end = _instant(filing_to)
        if start is None or end is None or start > end:
            raise ProviderPayloadError("SEC historical submission metadata contains an invalid date range")
        validated.append(cast(Mapping[str, object], entry))
    return validated


def _validated_sec_filing_table(value: Mapping[str, object], table_name: str) -> Mapping[str, list[object]]:
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
        if _instant(columns["filingDate"][index]) is None:
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid filing date")
        accepted = columns["acceptanceDateTime"][index]
        if accepted not in {None, ""} and _instant(accepted) is None:
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid acceptance timestamp")
        accession = columns["accessionNumber"][index]
        if not isinstance(accession, str) or not re.fullmatch(r"\d+-\d{2}-\d+", accession):
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid accession number")
        primary_document = columns["primaryDocument"][index]
        if not isinstance(primary_document, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", primary_document):
            raise ProviderPayloadError(f"SEC filing table {table_name} contains an invalid primary document")
    return columns


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _safe_uri(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        return fallback
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class PublicResearchDataAdapter:
    """One explicit SourcePort covering public providers and fail-closed host integrations."""

    def __init__(
        self,
        transport: HTTPTransport,
        *,
        licensed_source: SourcePort | None = None,
        reddit_oauth_source: SourcePort | None = None,
        sec_user_agent: str | None = None,
        clock: Callable[[], str] = _now,
    ) -> None:
        operator_identity = (
            sec_user_agent if sec_user_agent is not None else getattr(transport, "operator_identity", SEC_USER_AGENT)
        )
        if not operator_identity.strip() or "(" not in operator_identity or ")" not in operator_identity:
            raise ValueError("SEC User-Agent must descriptively identify the host and a contact")
        self._transport = transport
        self._licensed_source = licensed_source
        self._reddit_oauth_source = reddit_oauth_source
        self._sec_headers = {"User-Agent": operator_identity}
        self._public_headers = {"User-Agent": operator_identity}
        self._clock = clock

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        expected = {
            "prices": PricesQuery,
            "indicators": IndicatorsQuery,
            "regulatory_filings": RegulatoryFilingsQuery,
            "fundamentals": FundamentalsQuery,
            "financial_statements": FinancialStatementsQuery,
            "company_news": CompanyNewsQuery,
            "global_news": GlobalNewsQuery,
            "macro": MacroQuery,
            "stocktwits": StockTwitsQuery,
            "reddit": RedditQuery,
        }.get(capability)
        if expected is None or not isinstance(query, expected):
            raise ValueError(f"{capability} requires its matching typed query")
        if capability in {"prices", "indicators"}:
            return self._licensed(capability, query)
        if capability == "stocktwits":
            return self._terminal(capability, query, "denied", "Approved StockTwits API access is not configured.")
        if capability == "reddit":
            if self._reddit_oauth_source is None:
                return self._terminal(capability, query, "denied", "Host Reddit OAuth access is required.")
            return validate_source_response(capability, query, self._reddit_oauth_source.fetch(capability, query))
        try:
            if capability == "regulatory_filings":
                return self._sec_filings(cast(RegulatoryFilingsQuery, query))
            if capability == "fundamentals":
                return self._sec_facts(cast(FundamentalsQuery, query), statements=False)
            if capability == "financial_statements":
                return self._sec_facts(cast(FinancialStatementsQuery, query), statements=True)
            if capability in {"company_news", "global_news"}:
                return self._gdelt(capability, cast(CompanyNewsQuery | GlobalNewsQuery, query))
            return self._world_bank(cast(MacroQuery, query))
        except (ProviderTransportError, ProviderPayloadError) as exc:
            return self._terminal(
                capability, query, "unavailable", f"Provider response unavailable: {type(exc).__name__}."
            )

    def _licensed(self, capability: str, query: SourceQuery) -> SourceBatch:
        if self._licensed_source is None:
            return self._terminal(capability, query, "unavailable", "A licensed host SourcePort is required.")
        return validate_source_response(capability, query, self._licensed_source.fetch(capability, query))

    def _request(
        self,
        capability: str,
        query: SourceQuery,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HTTPResponse | SourceBatch:
        try:
            response = self._transport.get_json(url, params=params, headers=headers)
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderTransportError("public provider transport failed") from exc
        if response.status == 429:
            return self._terminal(capability, query, "rate_limited", "The provider rate limit was reached.")
        if response.status in {401, 403}:
            return self._terminal(capability, query, "denied", "The provider denied host access.")
        if not 200 <= response.status < 300:
            return self._terminal(capability, query, "unavailable", f"Provider returned HTTP {response.status}.")
        return response

    def _resolve_cik(self, capability: str, query: SourceQuery, issuer: str) -> str | SourceBatch:
        digits = issuer.removeprefix("CIK").strip()
        if digits.isdigit():
            return digits.zfill(10)
        response = self._request(
            capability,
            query,
            "https://www.sec.gov/files/company_tickers.json",
            headers=self._sec_headers,
        )
        if isinstance(response, SourceBatch):
            return response
        if not isinstance(response.payload, Mapping):
            raise ProviderPayloadError("SEC ticker directory must be an object")
        rows = response.payload.values()
        for row in rows:
            if isinstance(row, Mapping) and str(row.get("ticker", "")).upper() == issuer.upper():
                cik = str(row.get("cik_str", ""))
                if not cik.isdigit():
                    raise ProviderPayloadError("SEC ticker directory returned an invalid CIK")
                return cik.zfill(10)
        return self._terminal(capability, query, "unavailable", "SEC issuer identity could not be resolved.")

    def _sec_filings(self, query: RegulatoryFilingsQuery) -> SourceBatch:
        capability = "regulatory_filings"
        if query.jurisdiction.upper() not in {"US", "USA", "SEC"}:
            return self._terminal(capability, query, "unavailable", "SEC adapter supports United States filings only.")
        cik = self._resolve_cik(capability, query, query.issuer)
        if isinstance(cik, SourceBatch):
            return cik
        response = self._request(
            capability,
            query,
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=self._sec_headers,
        )
        if isinstance(response, SourceBatch):
            return response
        if not isinstance(response.payload, Mapping):
            raise ProviderPayloadError("SEC submissions response must be an object")
        payload = response.payload
        filings_value = payload.get("filings")
        if not isinstance(filings_value, Mapping):
            raise ProviderPayloadError("SEC submissions response must contain filings")
        filings = cast(Mapping[str, object], filings_value)
        recent_value = filings.get("recent")
        if not isinstance(recent_value, Mapping):
            raise ProviderPayloadError("SEC submissions response must contain recent filings")
        recent = _validated_sec_filing_table(cast(Mapping[str, object], recent_value), "recent")
        filing_tables: list[tuple[str, Mapping[str, list[object]]]] = [("recent", recent)]
        gaps: list[str] = []
        historical_files_value = _validated_sec_history_files(filings.get("files", []))
        filed_after = _query_instant(query.filed_after)
        filed_before = _query_instant(query.filed_before)
        cutoff = _query_instant(query.cutoff_at)
        historical_files = [
            entry
            for entry in historical_files_value
            if _query_instant(cast(str, entry["filingTo"])).date() >= filed_after.date()
            and _query_instant(cast(str, entry["filingFrom"])).date() <= filed_before.date()
        ]
        if len(historical_files) > MAX_SEC_SUBMISSION_FILES:
            gaps.append(
                f"SEC listed more than the bounded {MAX_SEC_SUBMISSION_FILES} relevant historical submission files."
            )
        for entry in historical_files[:MAX_SEC_SUBMISSION_FILES]:
            name = cast(str, entry["name"])
            historical = self._request(
                capability,
                query,
                f"https://data.sec.gov/submissions/{name}",
                headers=self._sec_headers,
            )
            if isinstance(historical, SourceBatch):
                gaps.append(f"SEC historical submission file {name} could not be retrieved.")
                continue
            if not isinstance(historical.payload, Mapping):
                gaps.append(f"SEC historical submission file {name} had an invalid response shape.")
                continue
            filing_tables.append(
                (name, _validated_sec_filing_table(cast(Mapping[str, object], historical.payload), name))
            )
        rows: list[SourceObservation] = []
        conservative_dates = False
        for table_name, table in filing_tables:
            for index, form in enumerate(table.get("form", [])):
                if str(form) not in query.form_types:
                    continue
                filed_raw = _at(table, "filingDate", index)
                filed = _iso(filed_raw)
                available, conservative = _sec_available_at(filed_raw, _at(table, "acceptanceDateTime", index))
                conservative_dates = conservative_dates or conservative
                filed_instant = _instant(filed)
                available_instant = _instant(available)
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
                accession_path = accession.replace("-", "")
                uri = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary}"
                metadata = {"accession": accession, "form": form, "filed": filed, "available": available}
                rows.append(
                    self._observation(
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
        return self._batch(
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

    def _sec_facts(self, query: FundamentalsQuery | FinancialStatementsQuery, *, statements: bool) -> SourceBatch:
        capability = "financial_statements" if statements else "fundamentals"
        issuer = cast(FinancialStatementsQuery, query).issuer if statements else cast(FundamentalsQuery, query).symbol
        cik = self._resolve_cik(capability, query, issuer)
        if isinstance(cik, SourceBatch):
            return cik
        response = self._request(
            capability,
            query,
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=self._sec_headers,
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
        cutoff = _query_instant(query.as_of)
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
                        filed = _iso(filed_raw)
                        available, conservative = _sec_available_at(filed_raw)
                        conservative_dates = conservative_dates or conservative
                        end = str(row.get("end", ""))
                        available_instant = _instant(available)
                        if (
                            filed is None
                            or available is None
                            or available_instant is None
                            or available_instant > cutoff
                        ):
                            continue
                        if statements and periods and not _period_matches(row, periods):
                            continue
                        accession = str(row.get("accn", f"fact-{_digest(row)[:16]}"))
                        value = str(row.get("val", ""))
                        if not value:
                            continue
                        if len(rows) >= MAX_SEC_COMPANY_FACT_ITEMS:
                            capped = True
                            continue
                        uri = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
                        facts = [
                            NormalizedFact("metric", metric),
                            NormalizedFact("value", value, str(unit), end or None),
                        ]
                        if statements:
                            facts.append(NormalizedFact("taxonomy", taxonomy))
                            facts.append(NormalizedFact("statement_type", cast(str, statement_kind)))
                        rows.append(
                            self._observation(
                                source_id=f"sec-{accession}-{_digest((taxonomy, metric, unit, row))[:16]}",
                                source_kind="fundamental",
                                uri=uri,
                                observed=_iso(row.get("start")) or filed,
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
                f"SEC company facts exceeded the adapter limit of {MAX_SEC_COMPANY_FACT_ITEMS} items; "
                "additional matching facts were omitted."
            )
        if requested is not None:
            requested_names = {item.lower(): item for item in cast(FundamentalsQuery, query).metrics}
            gaps.extend(
                f"SEC company facts did not return requested metric: {requested_names[metric]}."
                for metric in sorted(requested - returned_metrics)
            )
        else:
            expected_coverage = {(statement_type, period) for statement_type in statement_types for period in periods}
            gaps.extend(
                "SEC company facts did not return requested coverage for "
                f"statement_type={statement_type}, period={period}."
                for statement_type, period in sorted(expected_coverage - returned_statement_periods)
            )
        status = "complete" if not gaps else ("partial" if rows else "unavailable")
        limitations = list(gaps)
        if conservative_dates:
            limitations.append("SEC company facts expose filing dates without times; availability uses end-of-day UTC.")
        return self._batch(
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

    def _gdelt(self, capability: str, query: CompanyNewsQuery | GlobalNewsQuery) -> SourceBatch:
        terms = query.symbol if isinstance(query, CompanyNewsQuery) else " OR ".join(query.topics)
        published_after = _query_instant(query.published_after)
        published_before = _query_instant(query.published_before)
        response = self._request(
            capability,
            query,
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": terms,
                "mode": "artlist",
                "format": "json",
                "maxrecords": query.max_items,
                "startdatetime": published_after.strftime("%Y%m%d%H%M%S"),
                "enddatetime": published_before.strftime("%Y%m%d%H%M%S"),
            },
            headers=self._public_headers,
        )
        if isinstance(response, SourceBatch):
            return response
        if not isinstance(response.payload, Mapping) or not isinstance(response.payload.get("articles"), list):
            raise ProviderPayloadError("GDELT response must contain an articles array")
        articles = cast(list[object], response.payload["articles"])
        rows: list[SourceObservation] = []
        seen_uris: set[str] = set()
        for article in articles if isinstance(articles, list) else []:
            if not isinstance(article, Mapping):
                continue
            published = _iso(article.get("seendate"))
            published_instant = _instant(published)
            if (
                published is None
                or published_instant is None
                or not published_after <= published_instant <= published_before
            ):
                continue
            uri = _safe_uri(article.get("url"), f"https://api.gdeltproject.org/article/{_digest(article)}")
            if uri in seen_uris:
                continue
            seen_uris.add(uri)
            facts = tuple(
                NormalizedFact(name, str(value))
                for name, value in (
                    ("title", article.get("title")),
                    ("domain", article.get("domain")),
                    ("language", article.get("language")),
                )
                if value
            )
            rows.append(
                self._observation(
                    source_id=f"gdelt-{_digest(uri)[:24]}",
                    source_kind="news",
                    uri=uri,
                    observed=published,
                    published=published,
                    available=published,
                    provider="GDELT",
                    provider_version="DOC-2.0",
                    license_id="gdelt-metadata-links-v1",
                    facts=facts,
                    digest_value=article,
                )
            )
        saturated = len(articles) >= query.max_items
        gap = (
            ("GDELT returned the requested max_items limit; additional matching articles may exist.",)
            if saturated
            else ()
        )
        limitations = (
            "GDELT seendate is a seen/discovery timestamp, not a publisher publication timestamp; "
            "published_at uses it as an availability proxy.",
            *gap,
        )
        return self._batch(
            capability,
            query,
            tuple(rows[: query.max_items]),
            "GDELT",
            "DOC-2.0",
            "gdelt-metadata-links-v1",
            "https://www.gdeltproject.org/about.html",
            status="partial" if saturated else "complete",
            limitations=limitations,
            gaps=gap,
            redistributable="unknown",
            entitlement_limitation=(
                "Only GDELT metadata and publisher links are returned; no article body is redistributed."
            ),
        )

    def _world_bank(self, query: MacroQuery) -> SourceBatch:
        capability = "macro"
        retrieved_at = _iso(self._clock())
        retrieved_instant = _instant(retrieved_at)
        vintage = _query_instant(query.vintage_as_of)
        start = _query_instant(query.start_time)
        end = _query_instant(query.end_time)
        if retrieved_instant is None or retrieved_instant > vintage:
            return self._terminal(
                capability,
                query,
                "unavailable",
                "The World Bank current-data API cannot reconstruct a historical vintage after its cutoff.",
            )
        rows: list[SourceObservation] = []
        for region in query.regions:
            for series in query.series:
                total_pages = 1
                for page in range(1, MAX_WORLD_BANK_PAGES + 1):
                    response = self._request(
                        capability,
                        query,
                        f"https://api.worldbank.org/v2/country/{region}/indicator/{series}",
                        params={
                            "format": "json",
                            "date": f"{start.year}:{end.year}",
                            "page": page,
                            "per_page": 1000,
                        },
                        headers=self._public_headers,
                    )
                    if isinstance(response, SourceBatch):
                        return response
                    response_retrieved_at = _iso(self._clock())
                    response_retrieved_instant = _instant(response_retrieved_at)
                    if (
                        response_retrieved_at is None
                        or response_retrieved_instant is None
                        or response_retrieved_instant > vintage
                    ):
                        return self._terminal(
                            capability,
                            query,
                            "unavailable",
                            "The World Bank current-data API cannot reconstruct a historical vintage after its cutoff.",
                        )
                    if not isinstance(response.payload, list) or len(response.payload) < 2:
                        raise ProviderPayloadError("World Bank response must contain metadata and observations")
                    metadata, observations = response.payload[0], response.payload[1]
                    if page == 1:
                        total_pages = int(metadata.get("pages", 1)) if isinstance(metadata, Mapping) else 1
                        if not 1 <= total_pages <= MAX_WORLD_BANK_PAGES:
                            return self._terminal(
                                capability,
                                query,
                                "unavailable",
                                (
                                    "World Bank pagination exceeds the bounded "
                                    f"{MAX_WORLD_BANK_PAGES}-page retrieval limit."
                                ),
                            )
                    for index, row in enumerate(observations if isinstance(observations, list) else []):
                        if not isinstance(row, Mapping) or row.get("value") is None:
                            continue
                        year = str(row.get("date", ""))
                        observed = f"{year}-01-01T00:00:00+00:00"
                        observed_instant = _instant(observed)
                        if observed_instant is None or not start <= observed_instant <= end:
                            continue
                        uri = f"https://api.worldbank.org/v2/country/{region}/indicator/{series}"
                        rows.append(
                            self._observation(
                                source_id=f"world-bank-{region}-{series}-{year}-{page}-{index}",
                                source_kind="other",
                                uri=uri,
                                observed=observed,
                                published=response_retrieved_at,
                                available=response_retrieved_at,
                                retrieved=response_retrieved_at,
                                provider="World Bank",
                                provider_version="api-v2",
                                license_id="world-bank-cc-by-4.0",
                                facts=(
                                    NormalizedFact("series", series),
                                    NormalizedFact("value", str(row["value"]), period=year),
                                    NormalizedFact("region", region),
                                    NormalizedFact("vintage_as_of", query.vintage_as_of),
                                ),
                                digest_value=row,
                            )
                        )
                    if page >= total_pages:
                        break
        return self._batch(
            capability,
            query,
            tuple(rows),
            "World Bank",
            "api-v2",
            "world-bank-cc-by-4.0",
            "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets",
            limitations=("World Bank API values are the current vintage; historical revision lineage is not exposed.",),
        )

    def _observation(
        self,
        *,
        source_id: str,
        source_kind: str,
        uri: str,
        observed: str,
        published: str,
        available: str,
        retrieved: str | None = None,
        provider: str,
        provider_version: str,
        license_id: str,
        facts: tuple[NormalizedFact, ...],
        digest_value: object,
    ) -> SourceObservation:
        return SourceObservation(
            source_id=source_id,
            source_kind=cast(object, source_kind),  # type: ignore[arg-type]
            canonical_uri=uri,
            content_sha256=_digest(digest_value),
            observed_at=observed,
            published_at=published,
            available_at=available,
            retrieved_at=retrieved or self._clock(),
            provider=provider,
            provider_version=provider_version,
            license_receipt_id=license_id,
            facts=facts,
            bounded_extract=None,
            limitations=(),
        )

    def _complete(
        self,
        capability: str,
        query: SourceQuery,
        items: tuple[SourceObservation, ...],
        provider: str,
        provider_version: str,
        license_id: str,
        terms_uri: str,
        *,
        redistributable: bool | str = True,
        entitlement_limitation: str | None = None,
    ) -> SourceBatch:
        return self._batch(
            capability,
            query,
            items,
            provider,
            provider_version,
            license_id,
            terms_uri,
            redistributable=redistributable,
            entitlement_limitation=entitlement_limitation,
        )

    def _batch(
        self,
        capability: str,
        query: SourceQuery,
        items: tuple[SourceObservation, ...],
        provider: str,
        provider_version: str,
        license_id: str,
        terms_uri: str,
        *,
        status: str = "complete",
        limitations: tuple[str, ...] = (),
        gaps: tuple[str, ...] = (),
        next_cursor: str | None = None,
        redistributable: bool | str = True,
        entitlement_limitation: str | None = None,
    ) -> SourceBatch:
        return SourceBatch(
            capability=capability,
            query=query,
            cutoff=query.cutoff_at,
            status=cast(object, status),  # type: ignore[arg-type]
            items=items,
            provenance=SourceProvenance(
                provider, provider_version, type(self).__name__, ADAPTER_VERSION, self._clock()
            ),
            entitlement=SourceEntitlement(
                access="allowed",
                redistributable=cast(object, redistributable),  # type: ignore[arg-type]
                terms_uri=terms_uri,
                license_receipt_id=license_id,
                limitation=entitlement_limitation,
            ),
            completeness=SourceCompleteness(status == "complete", gaps),
            pagination=SourcePagination(next_cursor is not None, next_cursor, len(items), max(1, len(items))),
            limitations=limitations,
        )

    def _terminal(self, capability: str, query: SourceQuery, status: str, limitation: str) -> SourceBatch:
        denied = status == "denied"
        return SourceBatch(
            capability=capability,
            query=query,
            cutoff=query.cutoff_at,
            status=cast(object, status),  # type: ignore[arg-type]
            items=(),
            provenance=SourceProvenance("host", "1", type(self).__name__, ADAPTER_VERSION, self._clock()),
            entitlement=SourceEntitlement(
                access="denied" if denied else "unknown",
                redistributable=False if denied else "unknown",
                terms_uri=None,
                license_receipt_id="host-access-not-configured",
                limitation=limitation,
            ),
            completeness=SourceCompleteness(False, (limitation,)),
            pagination=SourcePagination(False, None, 0, 1),
            limitations=(limitation,),
        )


def _at(rows: Mapping[str, list[object]], key: str, index: int) -> object | None:
    values = rows.get(key, [])
    return values[index] if index < len(values) else None


def _statement_alias(value: str) -> str:
    normalized = value.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "balance": "balance_sheet",
        "income": "income_statement",
        "operations": "income_statement",
        "cashflow": "cash_flow",
        "cash_flow_statement": "cash_flow",
    }
    return aliases.get(normalized, normalized)


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
