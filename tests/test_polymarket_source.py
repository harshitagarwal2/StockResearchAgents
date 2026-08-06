from __future__ import annotations

import json
from copy import deepcopy
from typing import cast

import pytest

from stock_research_agents_host import PredictionMarketsQuery
from stock_research_agents_host.adapters.public import (
    MAX_HTTP_RESPONSE_BYTES,
    HTTPResponse,
    ProviderTransportError,
    PublicResearchDataAdapter,
    UrllibHTTPTransport,
)
from stock_research_agents_host.contracts import source_query_from_dict

NOW = "2026-08-04T12:00:00+00:00"
CUTOFF = NOW
SEARCH_URL = "https://gamma-api.polymarket.com/public-search"


class RecordingTransport:
    def __init__(self, response: HTTPResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, object, object]] = []

    def get_json(self, url: str, *, params: object = None, headers: object = None) -> HTTPResponse:
        self.calls.append((url, params, headers))
        return self.response


def _market(
    market_id: str = "101",
    *,
    updated_at: str = "2026-08-04T10:00:00Z",
    active: bool = True,
    closed: bool = False,
) -> dict[str, object]:
    return {
        "id": market_id,
        "slug": f"will-oracle-win-{market_id}",
        "question": f"Will Oracle win contract {market_id}?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.65", "0.35"]',
        "volume": "125000.50",
        "liquidity": "42000",
        "endDate": "2026-12-31T23:59:59Z",
        "resolutionSource": "Official agency announcement",
        "resolvedBy": "UMA",
        "umaResolutionStatus": "proposed",
        "active": active,
        "closed": closed,
        "updatedAt": updated_at,
        # Trading fields from Gamma are intentionally not projected into facts.
        "enableOrderBook": True,
        "clobTokenIds": '["secretly-not-a-secret-token-id"]',
    }


def _event(
    *markets: dict[str, object],
    event_id: str = "event-1",
    active: bool = True,
    closed: bool = False,
) -> dict[str, object]:
    return {
        "id": event_id,
        "slug": f"oracle-contract-{event_id}",
        "active": active,
        "closed": closed,
        "markets": list(markets),
    }


def _query(*, max_items: int = 10) -> PredictionMarketsQuery:
    return PredictionMarketsQuery("pm-oracle", ("Oracle", "cloud contract"), CUTOFF, max_items)


def _adapter(
    payload: object,
    *,
    status: int = 200,
    add_default_pagination: bool = True,
) -> tuple[PublicResearchDataAdapter, RecordingTransport]:
    if add_default_pagination and isinstance(payload, dict) and "events" in payload and "pagination" not in payload:
        events = payload["events"]
        event_count = len(events) if isinstance(events, list) else 0
        payload = {**payload, "pagination": {"hasMore": False, "totalResults": event_count}}
    transport = RecordingTransport(HTTPResponse(status, payload))
    return PublicResearchDataAdapter(transport, clock=lambda: NOW), transport


def test_prediction_market_query_is_strict_round_trip_and_bounded() -> None:
    query = _query(max_items=25)

    assert source_query_from_dict(query.to_dict()) == query
    assert query.cutoff_at == CUTOFF
    with pytest.raises(ValueError, match="between 1 and 25"):
        PredictionMarketsQuery("too-many", ("ORCL",), CUTOFF, 26)
    with pytest.raises(ValueError, match="at least one"):
        PredictionMarketsQuery("no-terms", (), CUTOFF, 1)
    with pytest.raises(ValueError, match="unique after whitespace and case normalization"):
        PredictionMarketsQuery("duplicate-terms", (" Oracle ", "oracle"), CUTOFF, 1)
    with pytest.raises(ValueError, match="invalid for prediction_markets"):
        source_query_from_dict({**query.to_dict(), "symbol": "ORCL"})


def test_success_normalizes_only_bounded_positioning_facts_with_unknown_redistribution() -> None:
    adapter, transport = _adapter(
        {
            "events": [_event(_market())],
            "tags": [],
            "profiles": [],
            "pagination": {"hasMore": False, "totalResults": 1},
        }
    )

    result = adapter.fetch("prediction_markets", _query())

    assert result.status == "complete"
    assert len(result.items) == 1
    observation = result.items[0]
    assert observation.source_kind == "positioning"
    assert observation.canonical_uri == "https://polymarket.com/event/oracle-contract-event-1/will-oracle-win-101"
    assert observation.observed_at == observation.published_at == observation.available_at
    assert observation.observed_at == NOW
    assert observation.retrieved_at == NOW
    assert observation.bounded_extract is None
    assert observation.content_sha256_scope == "normalized_source_record"
    facts = {fact.name: fact.value for fact in observation.facts}
    assert facts == {
        "question": "Will Oracle win contract 101?",
        "outcomes": '["Yes","No"]',
        "outcome_prices": '["0.65","0.35"]',
        "volume": "125000.50",
        "liquidity": "42000",
        "end_date": "2026-12-31T23:59:59+00:00",
        "resolution_source": "Official agency announcement",
        "resolved_by": "UMA",
        "resolution_status": "proposed",
    }
    assert result.entitlement.access == "allowed"
    assert result.entitlement.redistributable == "unknown"
    assert result.entitlement.terms_uri == "https://polymarket.com/tos"
    assert result.entitlement.limitation and "without extracts" in result.entitlement.limitation
    assert any("current market snapshot" in limitation for limitation in result.limitations)
    assert any("not verified outcome facts" in limitation for limitation in result.limitations)

    assert len(transport.calls) == 1
    url, raw_params, raw_headers = transport.calls[0]
    assert url == SEARCH_URL
    assert raw_params == {
        "q": "Oracle cloud contract",
        "events_status": "active",
        "limit_per_type": 10,
        "page": 1,
        "keep_closed_markets": 0,
        "search_tags": "false",
        "search_profiles": "false",
    }
    headers = cast(dict[str, str], raw_headers)
    assert set(headers) == {"User-Agent"}
    assert "StockResearchAgents" in headers["User-Agent"]


def test_null_events_is_a_valid_empty_search_result() -> None:
    adapter, _ = _adapter(
        {
            "events": None,
            "pagination": {"hasMore": False, "totalResults": 0},
        }
    )

    result = adapter.fetch("prediction_markets", _query())

    assert result.status == "complete"
    assert result.items == ()


def test_missing_official_pagination_fails_closed() -> None:
    adapter, _ = _adapter({"events": [_event(_market())]}, add_default_pagination=False)

    result = adapter.fetch("prediction_markets", _query())

    assert result.status == "unavailable"
    assert result.items == ()
    assert result.limitations == ("Provider response unavailable: ProviderPayloadError.",)


def test_closed_and_inactive_snapshots_are_excluded() -> None:
    payload = {
        "events": [
            _event(_market("kept")),
            _event(_market("closed-market", closed=True), event_id="closed-market-event"),
            _event(_market("inactive-market", active=False), event_id="inactive-market-event"),
            _event(_market("closed-event"), event_id="closed-event", closed=True),
            _event(_market("inactive-event"), event_id="inactive-event", active=False),
        ]
    }
    adapter, _ = _adapter(payload)

    result = adapter.fetch("prediction_markets", _query())

    assert result.status == "complete"
    assert [dict((fact.name, fact.value) for fact in item.facts)["question"] for item in result.items] == [
        "Will Oracle win contract kept?"
    ]


def test_updated_at_after_retrieval_fails_closed_before_cutoff_filtering() -> None:
    adapter, _ = _adapter(
        {
            "events": [_event(_market(updated_at="2026-08-04T12:00:01Z"))],
            "pagination": {"hasMore": False, "totalResults": 1},
        }
    )
    future_cutoff = PredictionMarketsQuery(
        "future-cutoff-pm",
        ("Oracle",),
        "2026-08-04T13:00:00+00:00",
        10,
    )

    result = adapter.fetch("prediction_markets", future_cutoff)

    assert result.status == "unavailable"
    assert result.items == ()
    assert result.limitations == ("Provider response unavailable: ProviderPayloadError.",)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"events": {}},
        {"events": ["not-an-event"]},
        {"events": [{"active": True, "closed": False, "markets": {}}]},
        {"events": [_event({**_market(), "outcomePrices": "not-json"})]},
        {"events": [_event({**_market(), "outcomePrices": '["0.65"]'})]},
        {"events": [_event({**_market(), "updatedAt": "not-a-timestamp"})]},
        {"events": [_event({**_market(), "active": "true"})]},
        {"events": [_event(_market())], "pagination": []},
        {"events": [_event(_market())], "pagination": {}},
        {"events": [_event(_market())], "pagination": {"hasMore": "false"}},
        {"events": [_event(_market())], "pagination": {"hasMore": False, "totalResults": -1}},
        {"events": [_event(_market())], "pagination": {"hasMore": False, "totalResults": 1_000_001}},
    ],
)
def test_malformed_gamma_payloads_fail_closed_as_typed_unavailable(payload: object) -> None:
    adapter, _ = _adapter(payload)

    result = adapter.fetch("prediction_markets", _query())

    assert result.status == "unavailable"
    assert result.items == ()
    assert result.completeness.complete is False
    assert result.limitations == ("Provider response unavailable: ProviderPayloadError.",)


def test_saturation_is_deterministically_capped_and_partial() -> None:
    markets = (_market("3"), _market("1"), _market("2"))
    query = _query(max_items=2)
    first_adapter, _ = _adapter({"events": [_event(*markets)]})
    second_adapter, _ = _adapter({"events": [_event(*reversed(markets))]})

    first = first_adapter.fetch("prediction_markets", query)
    second = second_adapter.fetch("prediction_markets", query)

    assert first.status == second.status == "partial"
    assert len(first.items) == len(second.items) == 2
    assert [(item.source_id, item.content_sha256) for item in first.items] == [
        (item.source_id, item.content_sha256) for item in second.items
    ]
    assert first.completeness.known_coverage_gaps == (
        "Polymarket returned more active markets than max_items; the normalized result was capped.",
    )
    assert first.pagination.bounded_items == 2
    assert first.pagination.has_more is False
    assert first.pagination.next_cursor is None


def test_official_pagination_has_more_marks_non_resumable_partial_coverage() -> None:
    adapter, _ = _adapter(
        {
            "events": [_event(_market())],
            "pagination": {"hasMore": True, "totalResults": 3},
        }
    )

    result = adapter.fetch("prediction_markets", _query())

    assert result.status == "partial"
    assert result.pagination.has_more is False
    assert result.pagination.next_cursor is None
    assert result.completeness.known_coverage_gaps == (
        "Polymarket pagination reports additional matching results beyond page 1 of 3.",
    )


def test_event_count_equal_to_limit_is_complete_when_pagination_says_no_more() -> None:
    query = _query(max_items=2)
    adapter, _ = _adapter(
        {
            "events": [
                _event(_market("1"), event_id="one"),
                _event(_market("2"), event_id="two"),
            ],
            "pagination": {"hasMore": False, "totalResults": 2},
        }
    )

    result = adapter.fetch("prediction_markets", query)

    assert result.status == "complete"
    assert len(result.items) == 2


def test_retrieval_after_as_of_fails_closed_without_retaining_current_snapshot_rows() -> None:
    adapter, _ = _adapter({"events": [_event(_market())]})
    historical = PredictionMarketsQuery(
        "historical-pm",
        ("Oracle",),
        "2026-08-04T11:00:00+00:00",
        10,
    )

    result = adapter.fetch("prediction_markets", historical)

    assert result.status == "unavailable"
    assert result.items == ()
    assert result.completeness.known_coverage_gaps == (
        "Polymarket Gamma was retrieved after the requested as_of cutoff; current search cannot reconstruct "
        "the market universe or probabilities at that cutoff.",
    )


def test_retrieval_after_as_of_without_retained_rows_is_terminal_unavailable() -> None:
    adapter, _ = _adapter({"events": [_event(_market(updated_at="2026-08-04T11:30:00Z"))]})
    historical = PredictionMarketsQuery(
        "empty-historical-pm",
        ("Oracle",),
        "2026-08-04T11:00:00+00:00",
        10,
    )

    result = adapter.fetch("prediction_markets", historical)

    assert result.status == "unavailable"
    assert result.items == ()
    assert "cannot reconstruct the market universe" in result.limitations[0]


@pytest.mark.parametrize(
    "payload",
    [
        {"events": [_event(event_id=str(index)) for index in range(26)]},
        {"events": [_event(*(_market(str(index)) for index in range(101)))]},
        {"events": [{**_event(_market()), "slug": "e" * 257}]},
        {"events": [_event({**_market(), "slug": "m" * 257})]},
        {"events": [_event({**_market(), "question": "q" * 2_001})]},
        {"events": [_event({**_market(), "resolutionSource": "r" * 2_001})]},
        {"events": [_event({**_market(), "outcomes": json.dumps(["x" * 4_097])})]},
    ],
)
def test_oversized_gamma_payload_components_fail_closed(payload: object) -> None:
    adapter, _ = _adapter(payload)

    result = adapter.fetch("prediction_markets", _query(max_items=25))

    assert result.status == "unavailable"
    assert result.items == ()
    assert result.limitations == ("Provider response unavailable: ProviderPayloadError.",)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "denied"), (403, "denied"), (429, "rate_limited"), (500, "unavailable")],
)
def test_http_failures_return_typed_terminal_batches(status: int, expected: str) -> None:
    adapter, _ = _adapter(None, status=status)

    result = adapter.fetch("prediction_markets", _query())

    assert result.status == expected
    assert result.items == ()
    assert result.limitations


def test_ids_digests_and_order_ignore_provider_event_order() -> None:
    event_one = _event(_market("late", updated_at="2026-08-04T10:30:00Z"), event_id="one")
    event_two = _event(_market("early", updated_at="2026-08-04T09:30:00Z"), event_id="two")
    first_adapter, _ = _adapter({"events": [event_one, event_two]})
    second_adapter, _ = _adapter({"events": list(reversed(deepcopy([event_one, event_two])))})

    first = first_adapter.fetch("prediction_markets", _query())
    second = second_adapter.fetch("prediction_markets", _query())

    assert [item.source_id for item in first.items] == [item.source_id for item in second.items]
    assert [item.content_sha256 for item in first.items] == [item.content_sha256 for item in second.items]
    assert [item.observed_at for item in first.items] == sorted(item.observed_at for item in first.items)


def test_adapter_exposes_no_auth_or_executable_market_behavior() -> None:
    adapter, transport = _adapter({"events": [_event(_market())]})

    result = adapter.fetch("prediction_markets", _query())

    request_json = json.dumps(transport.calls, sort_keys=True).lower()
    assert "authorization" not in request_json
    assert "cookie" not in request_json
    assert "api_key" not in request_json
    assert "clob" not in request_json
    fact_names = {fact.name for fact in result.items[0].facts}
    assert not fact_names.intersection({"enable_order_book", "clob_token_ids", "token_id", "order"})
    assert result.items[0].bounded_extract is None
    with pytest.raises(ValueError, match="matching typed query"):
        adapter.fetch("prices", _query())


def test_default_transport_bounds_response_body_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_amounts: list[int] = []

    class OversizedResponse:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self) -> OversizedResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, amount: int) -> bytes:
            requested_amounts.append(amount)
            return b"x" * amount

    def fake_urlopen(request: object, timeout: int) -> OversizedResponse:
        assert timeout == 20
        return OversizedResponse()

    monkeypatch.setattr("stock_research_agents_host.adapters.public.urlopen", fake_urlopen)
    transport = UrllibHTTPTransport(max_attempts=1)

    with pytest.raises(ProviderTransportError, match="bounded size limit"):
        transport.get_json(SEARCH_URL)
    assert requested_amounts == [MAX_HTTP_RESPONSE_BYTES + 1]


def test_default_transport_rejects_unbounded_response_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnboundedOnlyResponse:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self) -> UnboundedOnlyResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request: object, timeout: int) -> UnboundedOnlyResponse:
        assert timeout == 20
        return UnboundedOnlyResponse()

    monkeypatch.setattr("stock_research_agents_host.adapters.public.urlopen", fake_urlopen)

    with pytest.raises(ProviderTransportError, match="does not support bounded reads"):
        UrllibHTTPTransport(max_attempts=1).get_json(SEARCH_URL)
