from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest

from tradingagents_host.adapters.public import HTTPResponse, PublicResearchDataAdapter, UrllibHTTPTransport
from tradingagents_host.contracts import (
    CompanyNewsQuery,
    FinancialStatementsQuery,
    FundamentalsQuery,
    GlobalNewsQuery,
    IndicatorsQuery,
    MacroQuery,
    PricesQuery,
    RedditQuery,
    RegulatoryFilingsQuery,
    SourceBatch,
    SourceCompleteness,
    SourceEntitlement,
    SourcePagination,
    SourceProvenance,
    SourceQuery,
    StockTwitsQuery,
    source_query_from_dict,
)
from tradingagents_host.research_data_mcp import (
    PUBLIC_ADAPTER_RECEIPT,
    TOOL_NAMES,
    AdapterConformanceReceipt,
    ResearchDataService,
    create_server,
)

NOW = "2026-08-03T12:00:00+00:00"


class FakeTransport:
    def __init__(self, responses: dict[str, HTTPResponse | list[HTTPResponse]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, object, object]] = []

    def get_json(self, url: str, *, params: object = None, headers: object = None) -> HTTPResponse:
        self.calls.append((url, params, headers))
        response = next(response for fragment, response in self.responses.items() if fragment in url)
        return response.pop(0) if isinstance(response, list) else response


class FakeSourcePort:
    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        return _empty_batch(capability, query)


def _empty_batch(capability: str, query: SourceQuery) -> SourceBatch:
    return SourceBatch(
        capability=capability,
        query=query,
        cutoff=query.cutoff_at,
        status="complete",
        items=(),
        provenance=SourceProvenance("licensed-host", "1", "fake", "1", NOW),
        entitlement=SourceEntitlement("allowed", True, "https://example.com/terms", "licensed-host-v1", None),
        completeness=SourceCompleteness(True),
        pagination=SourcePagination(False, None, 0, 1),
    )


def _adapter(responses: dict[str, HTTPResponse | list[HTTPResponse]], **kwargs: object) -> PublicResearchDataAdapter:
    return PublicResearchDataAdapter(
        FakeTransport(responses),
        clock=lambda: NOW,
        **kwargs,  # type: ignore[arg-type]
    )


def test_all_manifest_queries_are_exact_typed_round_trips() -> None:
    payloads = (
        PricesQuery("q1", "ORCL", "2026-07-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00", "1d"),
        IndicatorsQuery(
            "q-indicators",
            "ORCL",
            "rsi",
            "2026-07-01T00:00:00+00:00",
            "2026-08-01T00:00:00+00:00",
            {"period": 14},
        ),
        RegulatoryFilingsQuery(
            "q2",
            "ORCL",
            "US",
            ("10-Q",),
            "2026-07-01T00:00:00+00:00",
            "2026-08-01T23:59:59+00:00",
        ),
        FundamentalsQuery("q-fundamentals", "ORCL", ("Assets",), "2026-08-01T23:59:59+00:00"),
        FinancialStatementsQuery("q-statements", "ORCL", ("balance_sheet",), ("2025",), "2026-08-01T23:59:59+00:00"),
        CompanyNewsQuery("q3", "ORCL", "2026-07-01T00:00:00+00:00", "2026-08-01T23:59:59+00:00", 10),
        GlobalNewsQuery("q-global", ("inflation",), "2026-07-01T00:00:00+00:00", "2026-08-01T23:59:59+00:00", 10),
        MacroQuery(
            "q4",
            ("NY.GDP.MKTP.CD",),
            ("US",),
            "2024-01-01T00:00:00+00:00",
            "2025-12-31T00:00:00+00:00",
            "2026-08-04T23:59:59+00:00",
        ),
        StockTwitsQuery("q-stocktwits", "ORCL", "2026-07-28T00:00:00+00:00", "2026-08-01T00:00:00+00:00", 30),
        RedditQuery("q-reddit", "ORCL", "2026-07-28T00:00:00+00:00", "2026-08-01T00:00:00+00:00", 30),
    )
    for query in payloads:
        assert source_query_from_dict(query.to_dict()) == query


def test_sec_filings_require_descriptive_user_agent_filter_cutoff_and_never_return_bodies() -> None:
    transport = FakeTransport(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "submissions": HTTPResponse(
                200,
                {
                    "filings": {
                        "recent": {
                            "form": ["10-Q", "10-Q"],
                            "filingDate": ["2026-07-31", "2026-08-02"],
                            "acceptanceDateTime": ["2026-07-31T12:00:00Z", "2026-08-02T12:00:00Z"],
                            "accessionNumber": ["0001-26-000001", "0001-26-000002"],
                            "primaryDocument": ["q2.htm", "future.htm"],
                        }
                    }
                },
            ),
        }
    )
    adapter = PublicResearchDataAdapter(transport, clock=lambda: NOW)
    query = RegulatoryFilingsQuery(
        "orcl-filings",
        "ORCL",
        "US",
        ("10-Q",),
        "2026-07-01T00:00:00+00:00",
        "2026-08-01T23:59:59+00:00",
    )

    result = adapter.fetch("regulatory_filings", query)

    assert result.status == "complete"
    assert len(result.items) == 1
    assert result.items[0].bounded_extract is None
    assert "raw" not in json.dumps(result.to_dict()).lower()
    sec_headers = [cast(dict[str, str], headers) for url, _, headers in transport.calls if "sec.gov" in url]
    assert sec_headers and all("StockResearchAgents" in headers["User-Agent"] for headers in sec_headers)


def test_provider_windows_compare_timezone_offsets_as_instants_and_gdelt_receives_utc_bounds() -> None:
    sec = _adapter(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "submissions": HTTPResponse(
                200,
                {
                    "filings": {
                        "recent": {
                            "form": ["10-Q"],
                            "filingDate": ["2026-07-31"],
                            "acceptanceDateTime": ["2026-07-31T12:00:00Z"],
                            "accessionNumber": ["0001-26-000001"],
                            "primaryDocument": ["q2.htm"],
                        }
                    }
                },
            ),
        }
    )
    filing = sec.fetch(
        "regulatory_filings",
        RegulatoryFilingsQuery(
            "offset-filing",
            "ORCL",
            "US",
            ("10-Q",),
            "2026-07-01T00:00:00-07:00",
            "2026-07-31T08:00:00-07:00",
        ),
    )

    assert filing.status == "complete"
    assert len(filing.items) == 1

    transport = FakeTransport(
        {
            "gdeltproject": HTTPResponse(
                200,
                {
                    "articles": [
                        {
                            "url": "https://example.com/orcl",
                            "title": "Oracle update",
                            "seendate": "20260801T120000Z",
                        }
                    ]
                },
            )
        }
    )
    news = PublicResearchDataAdapter(transport, clock=lambda: NOW).fetch(
        "company_news",
        CompanyNewsQuery(
            "offset-news",
            "ORCL",
            "2026-08-01T04:00:00-07:00",
            "2026-08-01T06:00:00-07:00",
            10,
        ),
    )

    assert len(news.items) == 1
    params = cast(dict[str, object], transport.calls[0][1])
    assert params["startdatetime"] == "20260801110000"
    assert params["enddatetime"] == "20260801130000"


def test_malformed_sec_historical_file_metadata_fails_closed() -> None:
    adapter = _adapter(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "submissions": HTTPResponse(
                200,
                {
                    "filings": {
                        "recent": {"form": []},
                        "files": "malformed",
                    }
                },
            ),
        }
    )

    result = adapter.fetch(
        "regulatory_filings",
        RegulatoryFilingsQuery(
            "malformed-history",
            "ORCL",
            "US",
            ("10-K",),
            "2025-01-01T00:00:00+00:00",
            "2026-08-01T23:59:59+00:00",
        ),
    )

    assert result.status == "unavailable"
    assert result.items == ()
    assert result.limitations == ("Provider response unavailable: ProviderPayloadError.",)


@pytest.mark.parametrize(
    "filings",
    [
        {"recent": {"form": []}, "files": ["malformed-entry"]},
        {
            "recent": {"form": []},
            "files": [
                {
                    "name": "../submissions.json",
                    "filingFrom": "2025-01-01",
                    "filingTo": "2025-12-31",
                }
            ],
        },
        {
            "recent": {"form": []},
            "files": [
                {
                    "name": "CIK0001341439-submissions-001.json",
                    "filingFrom": "not-a-date",
                    "filingTo": "2025-12-31",
                }
            ],
        },
        {"recent": {"form": 17}, "files": []},
        {
            "recent": {
                "form": ["10-K"],
                "filingDate": "2025-06-30",
                "acceptanceDateTime": ["20250630183000"],
                "accessionNumber": ["0001-25-000001"],
                "primaryDocument": ["annual.htm"],
            },
            "files": [],
        },
        {
            "recent": {
                "form": ["10-K"],
                "filingDate": ["not-a-date"],
                "acceptanceDateTime": ["20250630183000"],
                "accessionNumber": ["0001-25-000001"],
                "primaryDocument": ["annual.htm"],
            },
            "files": [],
        },
    ],
    ids=(
        "non-object-history-entry",
        "invalid-history-name",
        "invalid-history-date",
        "non-array-form-column",
        "non-array-filing-column",
        "invalid-row-date",
    ),
)
def test_malformed_sec_nested_payloads_fail_closed(filings: object) -> None:
    adapter = _adapter(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "submissions": HTTPResponse(200, {"filings": filings}),
        }
    )

    result = adapter.fetch(
        "regulatory_filings",
        RegulatoryFilingsQuery(
            "malformed-nested-sec",
            "ORCL",
            "US",
            ("10-K",),
            "2025-01-01T00:00:00+00:00",
            "2026-08-01T23:59:59+00:00",
        ),
    )

    assert result.status == "unavailable"
    assert result.items == ()
    assert result.limitations == ("Provider response unavailable: ProviderPayloadError.",)


def test_sec_filings_consumes_relevant_historical_submission_files() -> None:
    transport = FakeTransport(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "submissions": [
                HTTPResponse(
                    200,
                    {
                        "filings": {
                            "recent": {"form": []},
                            "files": [
                                {
                                    "name": "CIK0001341439-submissions-001.json",
                                    "filingFrom": "2020-01-01",
                                    "filingTo": "2025-12-31",
                                }
                            ],
                        }
                    },
                ),
                HTTPResponse(
                    200,
                    {
                        "form": ["10-K"],
                        "filingDate": ["2025-06-30"],
                        "acceptanceDateTime": ["2025-06-30T18:30:00Z"],
                        "accessionNumber": ["0001-25-000001"],
                        "primaryDocument": ["annual.htm"],
                    },
                ),
            ],
        }
    )
    adapter = PublicResearchDataAdapter(transport, clock=lambda: NOW)
    query = RegulatoryFilingsQuery(
        "orcl-history",
        "ORCL",
        "US",
        ("10-K",),
        "2025-01-01T00:00:00+00:00",
        "2026-08-01T23:59:59+00:00",
    )

    result = adapter.fetch("regulatory_filings", query)

    assert result.status == "complete"
    assert [item.source_id for item in result.items] == ["sec-0001-25-000001"]
    assert len([url for url, _, _ in transport.calls if "submissions" in url]) == 2


def test_sec_history_metadata_uses_inclusive_calendar_date_overlap() -> None:
    transport = FakeTransport(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "submissions": [
                HTTPResponse(
                    200,
                    {
                        "filings": {
                            "recent": {"form": []},
                            "files": [
                                {
                                    "name": "CIK0001341439-submissions-001.json",
                                    "filingFrom": "2025-01-01",
                                    "filingTo": "2025-12-31",
                                }
                            ],
                        }
                    },
                ),
                HTTPResponse(
                    200,
                    {
                        "form": ["10-K"],
                        "filingDate": ["2025-12-31"],
                        "acceptanceDateTime": ["2025-12-31T18:00:00Z"],
                        "accessionNumber": ["0001-25-000002"],
                        "primaryDocument": ["annual.htm"],
                    },
                ),
            ],
        }
    )
    adapter = PublicResearchDataAdapter(transport, clock=lambda: NOW)

    result = adapter.fetch(
        "regulatory_filings",
        RegulatoryFilingsQuery(
            "same-day-history",
            "ORCL",
            "US",
            ("10-K",),
            "2025-12-31T12:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
        ),
    )

    assert result.status == "complete"
    assert [item.source_id for item in result.items] == ["sec-0001-25-000002"]
    assert len([url for url, _, _ in transport.calls if "submissions" in url]) == 2


def test_sec_companyfacts_normalizes_fundamentals_and_requested_statement_types() -> None:
    facts = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                                "filed": "2026-02-15",
                                "accn": "0001-26-000003",
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2025,
                                "val": 100,
                            }
                        ]
                    }
                }
            }
        }
    }
    adapter = _adapter(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "companyfacts": HTTPResponse(200, facts),
        }
    )
    as_of = "2026-08-01T23:59:59+00:00"

    fundamentals = adapter.fetch("fundamentals", FundamentalsQuery("fund", "ORCL", ("Assets",), as_of))
    statements = adapter.fetch(
        "financial_statements",
        FinancialStatementsQuery("stmt", "1341439", ("balance_sheet",), ("annual",), as_of),
    )

    assert fundamentals.status == statements.status == "complete"
    assert fundamentals.items[0].facts[0].value == "Assets"
    assert any(fact.value == "balance_sheet" for fact in statements.items[0].facts)


def test_sec_companyfacts_reports_missing_metric_statement_type_and_period_coverage() -> None:
    facts = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                                "filed": "2026-02-15",
                                "accn": "0001-26-000003",
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2025,
                                "val": 100,
                            }
                        ]
                    }
                }
            }
        }
    }
    adapter = _adapter(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "companyfacts": HTTPResponse(200, facts),
        }
    )
    as_of = "2026-08-01T23:59:59+00:00"

    fundamentals = adapter.fetch(
        "fundamentals",
        FundamentalsQuery("fund-coverage", "ORCL", ("Assets", "Revenue"), as_of),
    )
    statements = adapter.fetch(
        "financial_statements",
        FinancialStatementsQuery(
            "stmt-coverage",
            "1341439",
            ("balance_sheet", "income_statement"),
            ("annual", "quarterly"),
            as_of,
        ),
    )

    assert fundamentals.status == statements.status == "partial"
    assert fundamentals.completeness.known_coverage_gaps == (
        "SEC company facts did not return requested metric: Revenue.",
    )
    assert any("statement_type=balance_sheet, period=quarterly" in gap for gap in statements.limitations)
    assert any("statement_type=income_statement, period=annual" in gap for gap in statements.limitations)
    assert any("statement_type=income_statement, period=quarterly" in gap for gap in statements.limitations)


def test_sec_companyfacts_is_unavailable_when_no_requested_coverage_is_returned() -> None:
    adapter = _adapter(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "companyfacts": HTTPResponse(200, {"facts": {"us-gaap": {}}}),
        }
    )

    result = adapter.fetch(
        "fundamentals",
        FundamentalsQuery("fund-none", "ORCL", ("Revenue",), "2026-08-01T23:59:59+00:00"),
    )

    assert result.status == "unavailable"
    assert result.items == ()
    assert result.completeness.known_coverage_gaps == ("SEC company facts did not return requested metric: Revenue.",)


def test_sec_companyfacts_ids_are_stable_when_provider_rows_are_reordered() -> None:
    rows = [
        {
            "end": "2024-12-31",
            "filed": "2025-02-15",
            "accn": "0001-25-000001",
            "val": 100,
        },
        {
            "end": "2025-12-31",
            "filed": "2026-02-15",
            "accn": "0001-26-000001",
            "val": 200,
        },
    ]

    def fetch(provider_rows: list[dict[str, object]]) -> SourceBatch:
        adapter = _adapter(
            {
                "companyfacts": HTTPResponse(
                    200,
                    {"facts": {"us-gaap": {"Assets": {"units": {"USD": provider_rows}}}}},
                )
            }
        )
        return adapter.fetch(
            "fundamentals",
            FundamentalsQuery("stable-facts", "1341439", ("Assets",), "2026-08-01T23:59:59+00:00"),
        )

    first = fetch(rows)
    reordered = fetch(list(reversed(rows)))

    first_ids = {item.facts[1].value: item.source_id for item in first.items}
    reordered_ids = {item.facts[1].value: item.source_id for item in reordered.items}
    assert first_ids == reordered_ids


def test_sec_companyfacts_enforces_hard_item_cap_and_reports_partial_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tradingagents_host.adapters.public.MAX_SEC_COMPANY_FACT_ITEMS", 2)
    rows = [
        {
            "end": f"{year}-12-31",
            "filed": f"{year + 1}-02-15",
            "accn": f"0001-{str(year + 1)[-2:]}-{index:06d}",
            "val": index,
        }
        for index, year in enumerate((2023, 2024, 2025), start=1)
    ]
    adapter = _adapter(
        {
            "companyfacts": HTTPResponse(
                200,
                {"facts": {"us-gaap": {"Assets": {"units": {"USD": rows}}}}},
            )
        }
    )

    result = adapter.fetch(
        "fundamentals",
        FundamentalsQuery("bounded-facts", "1341439", ("Assets",), "2026-08-01T23:59:59+00:00"),
    )

    assert result.status == "partial"
    assert len(result.items) == 2
    assert result.completeness.known_coverage_gaps == (
        "SEC company facts exceeded the adapter limit of 2 items; additional matching facts were omitted.",
    )


def test_sec_date_only_companyfact_is_not_available_at_intraday_midnight() -> None:
    adapter = _adapter(
        {
            "company_tickers": HTTPResponse(200, {"0": {"ticker": "ORCL", "cik_str": 1341439}}),
            "companyfacts": HTTPResponse(
                200,
                {
                    "facts": {
                        "us-gaap": {
                            "Assets": {
                                "units": {
                                    "USD": [
                                        {
                                            "end": "2025-12-31",
                                            "filed": "2026-02-15",
                                            "accn": "0001-26-000003",
                                            "val": 100,
                                        }
                                    ]
                                }
                            }
                        }
                    }
                },
            ),
        }
    )

    result = adapter.fetch(
        "fundamentals",
        FundamentalsQuery("intraday-fund", "ORCL", ("Assets",), "2026-02-15T12:00:00+00:00"),
    )

    assert result.items == ()
    assert any("end-of-day UTC" in limitation for limitation in result.limitations)


@pytest.mark.parametrize(
    ("status_code", "expected"),
    ((429, "rate_limited"), (403, "denied"), (503, "unavailable")),
)
def test_provider_failures_are_typed_and_credential_free(status_code: int, expected: str) -> None:
    adapter = _adapter({"gdeltproject": HTTPResponse(status_code, {"authorization": "never-returned"})})
    query = CompanyNewsQuery("news", "ORCL", "2026-07-01T00:00:00+00:00", "2026-08-01T23:59:59+00:00", 10)

    result = adapter.fetch("company_news", query)

    assert result.status == expected
    assert result.items == ()
    assert "authorization" not in json.dumps(result.to_dict()).lower()


def test_malformed_provider_payload_is_sanitized_but_adapter_contract_failure_is_not_masked() -> None:
    query = CompanyNewsQuery(
        "malformed-news",
        "ORCL",
        "2026-07-01T00:00:00+00:00",
        "2026-08-01T23:59:59+00:00",
        10,
    )
    malformed = _adapter({"gdeltproject": HTTPResponse(200, {"articles": {}})})

    unavailable = malformed.fetch("company_news", query)

    assert unavailable.status == "unavailable"
    assert unavailable.limitations == ("Provider response unavailable: ProviderPayloadError.",)

    invalid_adapter = PublicResearchDataAdapter(
        FakeTransport(
            {
                "gdeltproject": HTTPResponse(
                    200,
                    {
                        "articles": [
                            {
                                "url": "https://example.com/article",
                                "title": "Oracle update",
                                "seendate": "20260731T120000Z",
                            }
                        ]
                    },
                )
            }
        ),
        clock=lambda: "not-a-timestamp",
    )
    with pytest.raises(ValueError, match="retrieved_at"):
        invalid_adapter.fetch("company_news", query)


def test_gdelt_ids_dedup_and_saturation_are_source_correct() -> None:
    articles = [
        {
            "url": "https://example.com/article?campaign=one",
            "title": "First rendering",
            "seendate": "20260731T120000Z",
        },
        {
            "url": "https://example.com/other",
            "title": "Other article",
            "seendate": "20260731T130000Z",
        },
        {
            "url": "https://example.com/article?campaign=two",
            "title": "Duplicate rendering",
            "seendate": "20260731T140000Z",
        },
    ]
    query = CompanyNewsQuery(
        "gdelt-correctness",
        "ORCL",
        "2026-07-01T00:00:00+00:00",
        "2026-08-01T23:59:59+00:00",
        3,
    )

    def fetch(provider_articles: list[dict[str, str]]) -> SourceBatch:
        return _adapter({"gdeltproject": HTTPResponse(200, {"articles": provider_articles})}).fetch(
            "company_news", query
        )

    first = fetch(articles)
    reordered = fetch(list(reversed(articles)))

    assert first.status == reordered.status == "partial"
    assert len(first.items) == len(reordered.items) == 2
    assert {item.canonical_uri for item in first.items} == {
        "https://example.com/article",
        "https://example.com/other",
    }
    assert {item.canonical_uri: item.source_id for item in first.items} == {
        item.canonical_uri: item.source_id for item in reordered.items
    }
    assert first.completeness.known_coverage_gaps == (
        "GDELT returned the requested max_items limit; additional matching articles may exist.",
    )
    assert any("seen/discovery timestamp" in limitation for limitation in first.limitations)
    assert any("not a publisher publication timestamp" in limitation for limitation in first.limitations)


def test_default_transport_has_bounded_retry_and_configurable_operator_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = iter((503, 429, 200))
    requests: list[object] = []
    sleeps: list[float] = []

    class Response:
        def __init__(self, status: int) -> None:
            self.status = status
            self.headers: dict[str, str] = {}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request: object, timeout: int) -> Response:
        requests.append(request)
        assert timeout == 20
        return Response(next(statuses))

    monkeypatch.setattr("tradingagents_host.adapters.public.urlopen", fake_urlopen)
    transport = UrllibHTTPTransport(
        operator_identity="Acme Research Adapter/1.0 (ops@example.com)",
        max_attempts=3,
        backoff_seconds=0.05,
        sleep=sleeps.append,
    )

    result = transport.get_json("https://example.com/data", params={"page": 1})

    assert result.status == 200
    assert sleeps == [0.05, 0.1]
    assert len(requests) == 3
    assert requests[0].get_header("User-agent") == "Acme Research Adapter/1.0 (ops@example.com)"  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="credential fields"):
        transport.get_json("https://example.com/data", params={"access_token": "must-not-be-sent"})
    with pytest.raises(ValueError, match="credential fields"):
        transport.get_json("https://example.com/data", headers={"Authorization": "must-not-be-sent"})


def test_world_bank_pagination_is_fully_consumed_without_unusable_cursor() -> None:
    adapter = _adapter(
        {
            "worldbank": [
                HTTPResponse(
                    200,
                    [
                        {"page": 1, "pages": 2},
                        [{"date": "2025", "value": 123, "countryiso3code": "USA"}],
                    ],
                ),
                HTTPResponse(
                    200,
                    [
                        {"page": 2, "pages": 2},
                        [{"date": "2024", "value": 120, "countryiso3code": "USA"}],
                    ],
                ),
            ]
        }
    )
    query = MacroQuery(
        "macro",
        ("NY.GDP.MKTP.CD",),
        ("US",),
        "2024-01-01T00:00:00+00:00",
        "2025-12-31T00:00:00+00:00",
        "2026-08-04T23:59:59+00:00",
    )

    result = adapter.fetch("macro", query)

    assert result.status == "complete"
    assert len(result.items) == 2
    assert result.pagination.has_more is False
    assert result.pagination.next_cursor is None


def test_world_bank_current_vintage_uses_stable_retrieval_availability() -> None:
    timestamps = iter(
        (
            "2026-08-03T12:00:00+00:00",
            "2026-08-03T12:01:00+00:00",
            "2026-08-03T12:02:00+00:00",
        )
    )
    adapter = PublicResearchDataAdapter(
        FakeTransport(
            {
                "worldbank": HTTPResponse(
                    200,
                    [{"page": 1, "pages": 1}, [{"date": "2025", "value": 123}]],
                )
            }
        ),
        clock=lambda: next(timestamps),
    )
    query = MacroQuery(
        "macro-current-vintage",
        ("NY.GDP.MKTP.CD",),
        ("US",),
        "2025-01-01T00:00:00+00:00",
        "2025-12-31T23:59:59+00:00",
        "2026-08-04T23:59:59+00:00",
    )

    result = adapter.fetch("macro", query)

    observation = result.items[0]
    assert observation.observed_at == "2025-01-01T00:00:00+00:00"
    assert observation.facts[1].period == "2025"
    assert observation.published_at == "2026-08-03T12:01:00+00:00"
    assert observation.available_at == observation.published_at
    assert observation.retrieved_at == observation.available_at


def test_world_bank_historical_vintage_remains_fail_closed() -> None:
    transport = FakeTransport({})
    adapter = PublicResearchDataAdapter(transport, clock=lambda: NOW)
    query = MacroQuery(
        "macro-historical-vintage",
        ("NY.GDP.MKTP.CD",),
        ("US",),
        "2024-01-01T00:00:00+00:00",
        "2025-12-31T23:59:59+00:00",
        "2026-08-01T23:59:59+00:00",
    )

    result = adapter.fetch("macro", query)

    assert result.status == "unavailable"
    assert result.items == ()
    assert transport.calls == []
    assert "historical vintage" in result.limitations[0]


def test_gdelt_and_world_bank_send_descriptive_credential_free_user_agent() -> None:
    transport = FakeTransport(
        {
            "gdeltproject": HTTPResponse(200, {"articles": []}),
            "worldbank": HTTPResponse(200, [{"page": 1, "pages": 1}, []]),
        }
    )
    adapter = PublicResearchDataAdapter(transport, clock=lambda: NOW)
    adapter.fetch(
        "company_news",
        CompanyNewsQuery(
            "news-headers",
            "ORCL",
            "2026-07-01T00:00:00+00:00",
            "2026-08-01T23:59:59+00:00",
            10,
        ),
    )
    adapter.fetch(
        "macro",
        MacroQuery(
            "macro-headers",
            ("NY.GDP.MKTP.CD",),
            ("US",),
            "2025-01-01T00:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
            "2026-08-04T23:59:59+00:00",
        ),
    )

    public_calls = [call for call in transport.calls if "gdeltproject" in call[0] or "worldbank" in call[0]]
    assert len(public_calls) == 2
    for _, _, raw_headers in public_calls:
        headers = cast(dict[str, str], raw_headers)
        assert "StockResearchAgents" in headers["User-Agent"]
        assert not {key.lower() for key in headers}.intersection(
            {"authorization", "proxy-authorization", "x-api-key", "api-key"}
        )


def test_prices_social_and_reddit_fail_closed_without_host_entitlements() -> None:
    adapter = _adapter({})
    prices = PricesQuery("prices", "ORCL", "2026-07-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00", "1d")

    assert adapter.fetch("prices", prices).status == "unavailable"

    social_args = ("social", "ORCL", "2026-07-28T00:00:00+00:00", "2026-08-01T00:00:00+00:00", 30)
    assert adapter.fetch("stocktwits", StockTwitsQuery(*social_args)).status == "denied"
    assert adapter.fetch("reddit", RedditQuery(*social_args)).status == "denied"


def test_licensed_market_and_host_oauth_ports_are_used_when_injected() -> None:
    source = FakeSourcePort()
    adapter = _adapter({}, licensed_source=source, reddit_oauth_source=source)
    prices = PricesQuery("prices", "ORCL", "2026-07-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00", "1d")
    reddit = RedditQuery("reddit", "ORCL", "2026-07-28T00:00:00+00:00", "2026-08-01T00:00:00+00:00", 30)

    assert adapter.fetch("prices", prices).status == "complete"
    assert adapter.fetch("reddit", reddit).status == "complete"


def test_mcp_registration_requires_matching_source_batch_v1_receipt() -> None:
    adapter = _adapter({})
    empty = create_server(adapter)
    wrong_adapter = replace(PUBLIC_ADAPTER_RECEIPT, adapter_id="DifferentAdapter")
    wrong = create_server(adapter, (wrong_adapter,))
    gated = create_server(adapter, (PUBLIC_ADAPTER_RECEIPT,))

    assert empty._tool_manager.list_tools() == []
    assert wrong._tool_manager.list_tools() == []
    assert {tool.name for tool in gated._tool_manager.list_tools()} == {
        TOOL_NAMES[capability] for capability in PUBLIC_ADAPTER_RECEIPT.capabilities
    }
    with pytest.raises(ValueError, match="SourceBatch v1"):
        AdapterConformanceReceipt("bad", "PublicResearchDataAdapter", "2.0.0", ("macro",))


def test_conformant_host_can_register_all_exact_manifest_tool_schemas() -> None:
    adapter = _adapter({})
    receipt = AdapterConformanceReceipt(
        "all-source-batch-v1",
        "PublicResearchDataAdapter",
        "1.0.0",
        tuple(TOOL_NAMES),
    )
    tools = {tool.name: tool for tool in create_server(adapter, (receipt,))._tool_manager.list_tools()}
    required = {
        "prices": ["symbol", "start_time", "end_time", "interval"],
        "indicators": ["symbol", "indicator", "start_time", "end_time", "parameters"],
        "regulatory_filings": ["issuer", "jurisdiction", "form_types", "filed_after", "filed_before"],
        "fundamentals": ["symbol", "metrics", "as_of"],
        "financial_statements": ["issuer", "statement_types", "periods", "as_of"],
        "company_news": ["symbol", "published_after", "published_before", "max_items"],
        "global_news": ["topics", "published_after", "published_before", "max_items"],
        "macro": ["series", "regions", "start_time", "end_time", "vintage_as_of"],
        "stocktwits": ["symbol", "start_time", "end_time", "max_items"],
        "reddit": ["symbol", "start_time", "end_time", "max_items"],
    }

    assert set(tools) == set(TOOL_NAMES.values())
    for capability, fields in required.items():
        schema = tools[TOOL_NAMES[capability]].parameters
        assert schema["required"] == fields
        assert list(schema["properties"]) == fields


def test_mcp_and_direct_python_share_the_same_canonical_response() -> None:
    adapter = _adapter({"gdeltproject": HTTPResponse(200, {"articles": []})})
    service = ResearchDataService(adapter)
    server = create_server(adapter, (PUBLIC_ADAPTER_RECEIPT,))
    fields: dict[str, object] = {
        "symbol": "ORCL",
        "published_after": "2026-07-01T00:00:00+00:00",
        "published_before": "2026-08-01T23:59:59+00:00",
        "max_items": 10,
    }
    tool = next(tool for tool in server._tool_manager.list_tools() if tool.name == "research_data_get_company_news")

    direct = service.execute("company_news", fields)
    via_mcp_function = tool.fn(**fields)

    assert via_mcp_function == direct
    assert set(tool.parameters["properties"]) == set(fields)
    assert not {"api_key", "token", "authorization", "password"}.intersection(tool.parameters["properties"])
