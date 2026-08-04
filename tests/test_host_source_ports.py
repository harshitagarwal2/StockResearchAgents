from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256

import pytest

from tradingagents_host.adapters import FixtureSourceAdapter, ReplaySourceAdapter
from tradingagents_host.contracts import (
    FilingQuery,
    NormalizedFact,
    SourceBatch,
    SourceCompleteness,
    SourceEntitlement,
    SourceObservation,
    SourcePagination,
    SourceProvenance,
)
from tradingagents_host.ports import SourcePort
from tradingagents_host.source_router import SourceRouter

CUTOFF = "2026-08-01T23:59:59+00:00"


def _observation(**changes: object) -> SourceObservation:
    values: dict[str, object] = {
        "source_id": "sec-2026q2",
        "source_kind": "filing",
        "canonical_uri": "https://www.sec.gov/Archives/example.htm",
        "content_sha256": "a" * 64,
        "observed_at": "2026-07-31T20:00:00+00:00",
        "published_at": "2026-07-31T20:05:00+00:00",
        "available_at": "2026-07-31T20:06:00+00:00",
        "retrieved_at": "2026-08-01T12:00:00+00:00",
        "provider": "SEC EDGAR",
        "provider_version": "host-web-v1",
        "license_receipt_id": "license-sec-public",
        "facts": (NormalizedFact("revenue", "15900000000", "USD", "2026-Q2"),),
    }
    values.update(changes)
    return SourceObservation(**values)


def _query(**changes: object) -> FilingQuery:
    values: dict[str, object] = {"query_id": "meta-2026-08-01", "symbol": "META", "cutoff_at": CUTOFF}
    values.update(changes)
    return FilingQuery(**values)


def _entitlement(**changes: object) -> SourceEntitlement:
    values: dict[str, object] = {
        "access": "allowed",
        "redistributable": True,
        "terms_uri": "https://www.sec.gov/os/accessing-edgar-data",
        "license_receipt_id": "license-sec-public",
        "limitation": None,
    }
    values.update(changes)
    return SourceEntitlement(**values)


def _batch(
    *,
    query: FilingQuery | None = None,
    status: str = "complete",
    items: tuple[SourceObservation, ...] | None = None,
    entitlement: SourceEntitlement | None = None,
    limitations: tuple[str, ...] = (),
    gaps: tuple[str, ...] = (),
    has_more: bool = False,
    next_cursor: str | None = None,
) -> SourceBatch:
    resolved_items = (_observation(),) if items is None else items
    resolved_query = query or _query()
    resolved_gaps = gaps or (() if status == "complete" else ("The bounded query was not fully covered.",))
    return SourceBatch(
        capability="official_filings",
        query=resolved_query,
        cutoff=resolved_query.cutoff_at,
        status=status,  # type: ignore[arg-type]
        items=resolved_items,
        provenance=SourceProvenance(
            provider="SEC EDGAR",
            provider_version="host-web-v1",
            adapter="fixture",
            adapter_version="1.0.0",
            retrieved_at="2026-08-01T12:00:01+00:00",
        ),
        entitlement=entitlement or _entitlement(),
        completeness=SourceCompleteness(complete=status == "complete", known_coverage_gaps=resolved_gaps),
        pagination=SourcePagination(
            has_more=has_more,
            next_cursor=next_cursor,
            returned_items=len(resolved_items),
            bounded_items=max(1, len(resolved_items)),
        ),
        limitations=limitations,
    )


def test_source_batch_emits_authoritative_versioned_wire_model() -> None:
    batch = _batch()

    assert batch.to_dict() == {
        "version": "1.0.0",
        "capability": "official_filings",
        "query": {
            "version": "1.0.0",
            "type": "filing",
            "query_id": "meta-2026-08-01",
            "symbol": "META",
            "cutoff_at": CUTOFF,
            "form_types": ["10-K", "10-Q", "8-K"],
            "start_at": None,
        },
        "cutoff": CUTOFF,
        "status": "complete",
        "items": [_observation().to_dict()],
        "provenance": {
            "provider": "SEC EDGAR",
            "provider_version": "host-web-v1",
            "adapter": "fixture",
            "adapter_version": "1.0.0",
            "retrieved_at": "2026-08-01T12:00:01+00:00",
        },
        "entitlement": {
            "access": "allowed",
            "redistributable": True,
            "terms_uri": "https://www.sec.gov/os/accessing-edgar-data",
            "license_receipt_id": "license-sec-public",
            "limitation": None,
        },
        "completeness": {"complete": True, "known_coverage_gaps": []},
        "pagination": {"has_more": False, "next_cursor": None, "returned_items": 1, "bounded_items": 1},
        "limitations": [],
    }
    assert batch.query_id == batch.query.query_id
    assert batch.cutoff_at == batch.cutoff
    assert batch.observations == batch.items
    assert batch.complete is True


def test_source_observation_digest_scope_is_explicit_and_bounded_extract_is_verifiable() -> None:
    assert _observation().content_sha256_scope == "normalized_source_record"
    assert _observation().to_dict()["content_sha256_scope"] == "normalized_source_record"
    legacy_safe_payload = _observation().to_dict()
    del legacy_safe_payload["content_sha256_scope"]
    assert SourceObservation.from_dict(legacy_safe_payload).content_sha256_scope == "normalized_source_record"

    extract = "A bounded licensed extract."
    observation = _observation(
        bounded_extract=extract,
        content_sha256_scope="bounded_extract",
        content_sha256=sha256(extract.encode("utf-8")).hexdigest(),
    )
    assert SourceObservation.from_dict(observation.to_dict()) == observation

    with pytest.raises(ValueError, match="exact UTF-8 bounded extract"):
        _observation(bounded_extract=extract, content_sha256_scope="bounded_extract")


def test_source_router_requires_explicit_capabilities_and_never_falls_back() -> None:
    fixture = FixtureSourceAdapter((_batch(),))
    router = SourceRouter()
    router.register("official_filings", fixture)

    assert router.fetch("official_filings", _query()) == _batch()
    with pytest.raises(KeyError, match="no source adapter"):
        router.fetch("licensed_analyst_research", _query())


def test_source_adapters_are_substitutable_and_replay_round_trips(tmp_path) -> None:
    batch = _batch()
    path = tmp_path / "source-batch.json"
    path.write_text(json.dumps(batch.to_dict()), encoding="utf-8")

    ports: tuple[SourcePort, ...] = (FixtureSourceAdapter((batch,)), ReplaySourceAdapter(path))
    for port in ports:
        result = port.fetch("official_filings", _query())
        assert isinstance(port, SourcePort)
        assert result == batch
        assert result.to_dict() == batch.to_dict()


@pytest.mark.parametrize(
    "query_string",
    (
        "X-Amz-Signature=forbidden",
        "X-Amz-Credential=forbidden",
        "X-Goog-Signature=forbidden",
        "AWSAccessKeyId=forbidden",
        "sig=forbidden",
        "signature=forbidden",
        "access-token=forbidden",
        "download_key=forbidden",
    ),
)
def test_source_contract_rejects_signed_or_credentialed_urls(query_string: str) -> None:
    with pytest.raises(ValueError, match="credential-shaped"):
        _observation(canonical_uri=f"https://example.com/report?{query_string}")
    with pytest.raises(ValueError, match="credential-shaped"):
        _entitlement(terms_uri=f"https://example.com/terms?{query_string}")


def test_source_observation_rejects_future_raw_and_actual_credential_material() -> None:
    with pytest.raises(ValueError, match="timestamps"):
        _observation(available_at="2026-08-02T00:00:00+00:00", retrieved_at="2026-08-01T12:00:00+00:00")
    with pytest.raises(ValueError, match="raw"):
        NormalizedFact("raw_content", "do not cross the boundary")
    for value in ("Authorization: Bearer abcdefghijklmnop", "token=actual-auth-value"):
        with pytest.raises(ValueError, match="credential"):
            NormalizedFact("revenue", value)
    with pytest.raises(ValueError, match="requested cutoff"):
        _batch(
            items=(_observation(available_at="2026-08-02T00:00:00+00:00", retrieved_at="2026-08-02T01:00:00+00:00"),)
        )


@pytest.mark.parametrize(
    "value",
    (
        "Bearer bonds rallied after the auction.",
        "The tokenized-asset market expanded.",
        "Secret sauce is not a financial credential.",
        "Authorization vote scheduled for shareholders.",
    ),
)
def test_benign_financial_text_is_not_misclassified_as_credentials(value: str) -> None:
    assert NormalizedFact("headline", value).value == value


def test_complete_batch_allows_no_matching_observations() -> None:
    batch = _batch(items=())

    assert batch.items == ()
    assert batch.status == "complete"
    assert batch.completeness.complete is True


@pytest.mark.parametrize("status", ("partial", "unavailable", "denied", "rate_limited", "stale"))
def test_non_complete_statuses_require_explicit_limitations(status: str) -> None:
    entitlement = (
        _entitlement(access="denied", redistributable=False, limitation="Access denied.")
        if status == "denied"
        else _entitlement()
    )
    items = () if status in {"unavailable", "denied", "rate_limited"} else (_observation(),)
    with pytest.raises(ValueError, match="require limitations"):
        _batch(status=status, items=items, entitlement=entitlement)


@pytest.mark.parametrize("status", ("unavailable", "denied", "rate_limited"))
def test_terminal_no_data_statuses_reject_observations(status: str) -> None:
    entitlement = (
        _entitlement(access="denied", redistributable=False, limitation="Access denied.")
        if status == "denied"
        else _entitlement()
    )
    with pytest.raises(ValueError, match="cannot contain items"):
        _batch(status=status, entitlement=entitlement, limitations=("No data returned.",))


def test_denied_status_and_entitlement_must_agree() -> None:
    with pytest.raises(ValueError, match="denied entitlement"):
        _batch(status="denied", items=(), limitations=("Access denied.",))
    with pytest.raises(ValueError, match="denied batch status"):
        _batch(
            status="partial",
            entitlement=_entitlement(access="denied", redistributable=False, limitation="Access denied."),
            limitations=("Access denied for part of the query.",),
        )


def test_partial_pagination_and_stale_results_have_explicit_semantics() -> None:
    partial = _batch(
        status="partial",
        limitations=("Provider page bound reached.",),
        gaps=("Additional provider page not retrieved.",),
        has_more=True,
        next_cursor="opaque-page-2",
    )
    stale = _batch(
        status="stale",
        limitations=("Latest available filing predates the requested freshness window.",),
        gaps=("No current-period filing was available.",),
    )

    assert partial.pagination.has_more is True
    assert stale.items
    with pytest.raises(ValueError, match="partial status"):
        replace(stale, pagination=SourcePagination(True, "opaque-page-2", 1, 1))


def test_pagination_counts_cursor_and_complete_coverage_are_consistent() -> None:
    batch = _batch()
    with pytest.raises(ValueError, match="number of items"):
        replace(batch, pagination=SourcePagination(False, None, 0, 1))
    with pytest.raises(ValueError, match="exactly when"):
        SourcePagination(has_more=False, next_cursor="unexpected", returned_items=0, bounded_items=1)
    with pytest.raises(ValueError, match="known coverage gaps"):
        SourceCompleteness(complete=True, known_coverage_gaps=("Unexpected gap.",))
    with pytest.raises(ValueError, match="require known coverage gaps"):
        replace(
            batch,
            status="partial",
            completeness=SourceCompleteness(False),
            limitations=("Coverage was partial.",),
        )


def test_nonredistributable_or_unknown_entitlement_cannot_carry_extracts() -> None:
    item = _observation(bounded_extract="Attributed excerpt.")
    for redistributable in (False, "unknown"):
        with pytest.raises(ValueError, match="cannot include extracts"):
            _batch(
                status="partial",
                items=(item,),
                entitlement=_entitlement(redistributable=redistributable, limitation="Reference only."),
                limitations=("Redistribution is restricted.",),
            )


def test_batch_items_must_share_the_batch_entitlement_receipt() -> None:
    with pytest.raises(ValueError, match="license receipt must match"):
        _batch(items=(_observation(license_receipt_id="license-other-provider"),))


def test_batch_items_must_share_the_batch_provider_provenance() -> None:
    with pytest.raises(ValueError, match="provider must match"):
        _batch(items=(_observation(provider="different-provider"),))
    with pytest.raises(ValueError, match="provider must match"):
        _batch(items=(_observation(provider_version="different-version"),))


def test_items_are_normalized_to_deterministic_order() -> None:
    later = _observation(source_id="later", content_sha256="b" * 64)
    earlier = _observation(
        source_id="earlier",
        content_sha256="c" * 64,
        observed_at="2026-07-30T20:00:00+00:00",
        published_at="2026-07-30T20:05:00+00:00",
        available_at="2026-07-30T20:06:00+00:00",
    )

    assert tuple(item.source_id for item in _batch(items=(later, earlier)).items) == ("earlier", "later")


def test_replay_rejects_unsupported_versions_unknown_fields_and_raw_bodies(tmp_path) -> None:
    payload = _batch().to_dict()
    path = tmp_path / "source-batch.json"

    for mutation, message in (
        (lambda value: value.update(version="2.0.0"), "unsupported SourceBatch version"),
        (lambda value: value.update(authorization="forbidden"), "unknown fields"),
        (lambda value: value["query"].update(version="2.0.0"), "unsupported source query version"),  # type: ignore[union-attr]
        (lambda value: value["items"][0].update(raw_body="forbidden"), "unknown fields"),  # type: ignore[index,union-attr]
    ):
        candidate = json.loads(json.dumps(payload))
        mutation(candidate)
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            ReplaySourceAdapter(path).fetch("official_filings", _query())


def test_source_ports_reject_any_response_for_a_different_request(tmp_path) -> None:
    batch = _batch()
    path = tmp_path / "source-batch.json"
    path.write_text(json.dumps(batch.to_dict()), encoding="utf-8")

    ports: tuple[SourcePort, ...] = (FixtureSourceAdapter((batch,)), ReplaySourceAdapter(path))
    for port in ports:
        with pytest.raises(ValueError, match="different query"):
            port.fetch("official_filings", _query(symbol="GOOG"))
