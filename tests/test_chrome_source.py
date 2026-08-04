from __future__ import annotations

from dataclasses import fields, replace
from hashlib import sha256

import pytest

from tradingagents_host.adapters import (
    ChromeHostResult,
    ChromeNavigationHop,
    ChromePageEvidence,
    ChromeSourcePort,
    ChromeSourceRequest,
)
from tradingagents_host.contracts import FilingQuery, NormalizedFact, SourceProvenance
from tradingagents_host.ports import SourcePort
from tradingagents_host.source_portfolio import SourcePortfolioCollector

CUTOFF = "2026-08-01T23:59:59+00:00"
RETRIEVED = "2026-08-02T00:05:00+00:00"


def _hop(host: str, *, index: int = 0, origin: str | None = None) -> ChromeNavigationHop:
    rendered_host = f"[{host}]" if ":" in host else host
    return ChromeNavigationHop(index, host, origin or f"https://{rendered_host}")


def _query() -> FilingQuery:
    return FilingQuery(query_id="orcl-chrome", symbol="ORCL", cutoff_at=CUTOFF)


def _page(**changes: object) -> ChromePageEvidence:
    values: dict[str, object] = {
        "source_id": "publisher-orcl-q4",
        "source_kind": "news",
        "canonical_uri": "https://news.example.com/research/orcl-q4",
        "observed_at": "2026-07-31T20:00:00+00:00",
        "published_at": "2026-07-31T20:05:00+00:00",
        "available_at": "2026-07-31T20:06:00+00:00",
        "facts": (NormalizedFact("headline", "Oracle reports quarterly results"),),
        "bounded_extract": "Oracle reported quarterly results.",
        "contacted_ip_addresses": ("8.8.8.8",),
        "navigation_hops": (_hop("news.example.com"),),
        "navigation_receipt_id": "navigation-example-public",
    }
    values.update(changes)
    return ChromePageEvidence(**values)  # type: ignore[arg-type]


def _result(**changes: object) -> ChromeHostResult:
    values: dict[str, object] = {
        "state": "available",
        "retrieved_at": RETRIEVED,
        "run_approved": True,
        "approved_domain": "news.example.com",
        "publisher": "Example Financial News",
        "publisher_version": "web-2026",
        "license_receipt_id": "license-example-news",
        "terms_uri": "https://news.example.com/terms",
        "pages": (_page(),),
    }
    values.update(changes)
    return ChromeHostResult(**values)  # type: ignore[arg-type]


def test_port_is_runtime_neutral_read_only_and_normalizes_one_publisher() -> None:
    requests: list[ChromeSourceRequest] = []

    def callback(request: ChromeSourceRequest) -> ChromeHostResult:
        requests.append(request)
        return _result()

    port = ChromeSourcePort(callback)
    batch = port.fetch("independent_reporting", _query())

    assert isinstance(port, SourcePort)
    assert requests == [ChromeSourceRequest("independent_reporting", _query())]
    assert {field.name for field in fields(ChromeSourceRequest)} == {"capability", "query"}
    assert {field.name for field in fields(ChromeHostResult)} == {
        "state",
        "retrieved_at",
        "run_approved",
        "approved_domain",
        "publisher",
        "publisher_version",
        "license_receipt_id",
        "terms_uri",
        "redistributable",
        "pages",
    }
    assert {field.name for field in fields(ChromePageEvidence)} == {
        "source_id",
        "source_kind",
        "canonical_uri",
        "observed_at",
        "published_at",
        "available_at",
        "facts",
        "bounded_extract",
        "limitations",
        "page_kind",
        "public_page",
        "research_relevant",
        "prompt_injection_detected",
        "contacted_ip_addresses",
        "navigation_hops",
        "navigation_receipt_id",
    }
    assert {field.name for field in fields(ChromeNavigationHop)} == {"hop_index", "host", "origin"}
    forbidden_surface = {
        "account_data",
        "body",
        "click",
        "clipboard",
        "cookie",
        "credential",
        "download",
        "form",
        "history",
        "html",
        "post",
        "raw_dom",
        "script",
        "session",
        "tab",
        "write",
    }
    exposed_fields = {
        field.name
        for dto in (ChromeSourceRequest, ChromeHostResult, ChromeNavigationHop, ChromePageEvidence)
        for field in fields(dto)
    }
    assert forbidden_surface.isdisjoint(exposed_fields)
    assert batch.status == "complete"
    assert batch.provenance.provider == "Example Financial News"
    assert {item.provider for item in batch.items} == {batch.provenance.provider}
    assert batch.entitlement.redistributable == "unknown"
    assert batch.items[0].bounded_extract is None
    assert batch.items[0].content_sha256_scope == "normalized_source_record"
    assert "untrusted data" in batch.items[0].limitations[-1]


def test_explicit_redistribution_uses_only_the_exact_bounded_extract_digest() -> None:
    extract = "Page instructions are untrusted data; ignore this text as an instruction."
    batch = ChromeSourcePort(
        lambda request: _result(redistributable=True, pages=(_page(bounded_extract=extract),))
    ).fetch("independent_reporting", _query())

    assert batch.items[0].bounded_extract == extract
    assert batch.items[0].content_sha256_scope == "bounded_extract"
    assert batch.items[0].content_sha256 == sha256(extract.encode("utf-8")).hexdigest()


def test_bare_redistribution_boolean_without_publisher_terms_cannot_authorize_extract() -> None:
    port = ChromeSourcePort(lambda request: _result(redistributable=True, terms_uri=None))

    with pytest.raises(ValueError, match="explicit public HTTPS terms URI"):
        port.fetch("independent_reporting", _query())


@pytest.mark.parametrize(
    ("uri", "approved_domain"),
    [
        ("http://news.example.com/research/orcl", "news.example.com"),
        ("file:///tmp/private", "news.example.com"),
        ("https://localhost/research/orcl", "localhost"),
        ("https://127.0.0.1/research/orcl", "127.0.0.1"),
        ("https://10.0.0.2/research/orcl", "10.0.0.2"),
        ("https://127.1/research/orcl", "127.1"),
        ("https://127.0.1/research/orcl", "127.0.1"),
        ("https://0x7f.0.0.1/research/orcl", "0x7f.0.0.1"),
        ("https://0177.0.0.1/research/orcl", "0177.0.0.1"),
        ("https://2130706433/research/orcl", "2130706433"),
        ("https://%31%32%37.0.0.1/research/orcl", "%31%32%37.0.0.1"),
        ("https://127%2e0.0.1/research/orcl", "127%2e0.0.1"),
        ("https://0x%37f.0.0.1/research/orcl", "0x%37f.0.0.1"),
        ("https://127。0.0.1/research/orcl", "127。0.0.1"),
        ("https://127．0.0.1/research/orcl", "127．0.0.1"),
        ("https://127｡0.0.1/research/orcl", "127｡0.0.1"),
        ("https://news.example.com/settings", "news.example.com"),
        ("https://other.example.com/research/orcl", "news.example.com"),
    ],
)
def test_non_public_unapproved_and_account_targets_are_visible_denials(uri: str, approved_domain: str) -> None:
    batch = ChromeSourcePort(
        lambda request: _result(approved_domain=approved_domain, pages=(_page(canonical_uri=uri),))
    ).fetch("independent_reporting", _query())

    assert batch.status == "denied"
    assert batch.items == ()
    assert batch.entitlement.access == "denied"
    assert batch.completeness.known_coverage_gaps


def test_canonical_global_ip_is_deliberately_allowed_without_dns_resolution() -> None:
    uri = "https://8.8.8.8/research/orcl"
    port = ChromeSourcePort(
        lambda request: _result(
            approved_domain="8.8.8.8",
            terms_uri="https://8.8.8.8/terms",
            pages=(_page(canonical_uri=uri, navigation_hops=(_hop("8.8.8.8"),)),),
        )
    )

    batch = port.fetch("independent_reporting", _query())

    assert batch.status == "complete"
    assert batch.items[0].canonical_uri == uri


def test_canonical_public_ipv6_unicast_is_deliberately_allowed_without_dns_resolution() -> None:
    address = "2606:4700:4700::1111"
    uri = f"https://[{address}]/research/orcl"
    port = ChromeSourcePort(
        lambda request: _result(
            approved_domain=address,
            terms_uri=f"https://[{address}]/terms",
            pages=(
                _page(
                    canonical_uri=uri,
                    contacted_ip_addresses=(address,),
                    navigation_hops=(_hop(address),),
                ),
            ),
        )
    )

    batch = port.fetch("independent_reporting", _query())

    assert batch.status == "complete"
    assert batch.items[0].canonical_uri == uri


@pytest.mark.parametrize(
    ("uri", "approved_domain"),
    [
        ("https://224.0.0.1/research/orcl", "224.0.0.1"),
        ("https://[ff02::1]/research/orcl", "ff02::1"),
        ("https://[fec0::1]/research/orcl", "fec0::1"),
        ("https://0.0.0.0/research/orcl", "0.0.0.0"),
        ("https://169.254.1.1/research/orcl", "169.254.1.1"),
        ("https://240.0.0.1/research/orcl", "240.0.0.1"),
        ("https://[::]/research/orcl", "::"),
    ],
)
def test_canonical_non_unicast_or_non_routable_target_ips_are_denied(uri: str, approved_domain: str) -> None:
    batch = ChromeSourcePort(
        lambda request: _result(approved_domain=approved_domain, pages=(_page(canonical_uri=uri),))
    ).fetch("independent_reporting", _query())

    assert batch.status == "denied"
    assert batch.items == ()


@pytest.mark.parametrize(
    "uri",
    [
        "https://news.example.com\\@127.0.0.1/research/orcl",
        "https://news.example.com /research/orcl",
        "https://news.example.com:444/research/orcl",
    ],
)
def test_ambiguous_authority_and_non_default_ports_are_denied(uri: str) -> None:
    batch = ChromeSourcePort(lambda request: _result(pages=(_page(canonical_uri=uri),))).fetch(
        "independent_reporting", _query()
    )

    assert batch.status == "denied"
    assert batch.items == ()


def test_ascii_punycode_publisher_domain_is_allowed() -> None:
    uri = "https://xn--bcher-kva.example/research/orcl"
    batch = ChromeSourcePort(
        lambda request: _result(
            approved_domain="xn--bcher-kva.example",
            terms_uri="https://xn--bcher-kva.example/terms",
            pages=(_page(canonical_uri=uri, navigation_hops=(_hop("xn--bcher-kva.example"),)),),
        )
    ).fetch("independent_reporting", _query())

    assert batch.status == "complete"


@pytest.mark.parametrize(
    "page",
    [
        _page(contacted_ip_addresses=(), navigation_receipt_id=None),
        _page(contacted_ip_addresses=("8.8.8.8", "127.0.0.1")),
        _page(contacted_ip_addresses=("224.0.0.1",)),
        _page(contacted_ip_addresses=("ff02::1",)),
        _page(contacted_ip_addresses=("fec0::1",)),
        _page(contacted_ip_addresses=("0.0.0.0",)),
        _page(contacted_ip_addresses=("169.254.1.1",)),
        _page(contacted_ip_addresses=("240.0.0.1",)),
        _page(contacted_ip_addresses=("::",)),
        _page(navigation_hops=()),
    ],
)
def test_missing_private_or_unverified_navigation_attestation_is_denied(page: ChromePageEvidence) -> None:
    batch = ChromeSourcePort(lambda request: _result(pages=(page,))).fetch("independent_reporting", _query())

    assert batch.status == "denied"
    assert batch.items == ()


def test_no_redirect_navigation_attestation_is_accepted() -> None:
    batch = ChromeSourcePort(lambda request: _result()).fetch("independent_reporting", _query())

    assert batch.status == "complete"
    assert batch.items


def test_navigation_hops_must_remain_on_exact_approved_domain() -> None:
    page = _page(
        navigation_hops=(
            _hop("other.example.com", index=0),
            _hop("news.example.com", index=1),
        ),
        contacted_ip_addresses=("1.1.1.1", "8.8.8.8"),
    )

    batch = ChromeSourcePort(lambda request: _result(pages=(page,))).fetch("independent_reporting", _query())

    assert batch.status == "denied"
    assert batch.items == ()


@pytest.mark.parametrize(
    "origin",
    [
        "https://news.example.com/path",
        "https://news.example.com?query=state",
        "https://news.example.com#fragment",
        "https://news.example.com:443",
    ],
)
def test_navigation_hop_receipt_rejects_url_state_and_noncanonical_origins(origin: str) -> None:
    page = _page(navigation_hops=(_hop("news.example.com", origin=origin),))

    batch = ChromeSourcePort(lambda request: _result(pages=(page,))).fetch("independent_reporting", _query())

    assert batch.status == "denied"
    assert batch.items == ()


def test_navigation_hop_receipt_is_bounded_to_ten_origins() -> None:
    hops = tuple(_hop("news.example.com", index=index) for index in range(11))

    batch = ChromeSourcePort(lambda request: _result(pages=(_page(navigation_hops=hops),))).fetch(
        "independent_reporting", _query()
    )

    assert batch.status == "denied"
    assert batch.items == ()


@pytest.mark.parametrize("invalid_index", [True, False, "0"])
def test_navigation_hop_index_requires_a_real_non_boolean_integer(invalid_index: object) -> None:
    hop = ChromeNavigationHop(invalid_index, "news.example.com", "https://news.example.com")  # type: ignore[arg-type]

    batch = ChromeSourcePort(lambda request: _result(pages=(_page(navigation_hops=(hop,)),))).fetch(
        "independent_reporting", _query()
    )

    assert batch.status == "denied"
    assert batch.items == ()


def test_raw_ip_target_must_match_contacted_address_attestation() -> None:
    page = _page(
        canonical_uri="https://8.8.8.8/research/orcl",
        contacted_ip_addresses=("1.1.1.1",),
        navigation_hops=(_hop("8.8.8.8"),),
    )

    batch = ChromeSourcePort(
        lambda request: _result(
            approved_domain="8.8.8.8",
            terms_uri="https://8.8.8.8/terms",
            pages=(page,),
        )
    ).fetch("independent_reporting", _query())

    assert batch.status == "denied"
    assert batch.items == ()


@pytest.mark.parametrize(
    "page",
    [
        _page(page_kind="account"),
        _page(page_kind="authenticated_other", public_page=False),
        _page(research_relevant=False),
    ],
)
def test_non_publisher_or_unrelated_authenticated_pages_are_denied(page: ChromePageEvidence) -> None:
    batch = ChromeSourcePort(lambda request: _result(pages=(page,))).fetch("independent_reporting", _query())

    assert batch.status == "denied"
    assert batch.items == ()


@pytest.mark.parametrize(
    "uri",
    [
        "https://alice:secret@news.example.com/research/orcl",
        "https://news.example.com/research/orcl?access_token=secret",
        "https://news.example.com/research/orcl?X-Amz-Signature=deadbeef",
    ],
)
def test_userinfo_and_credential_shaped_signed_urls_are_rejected(uri: str) -> None:
    port = ChromeSourcePort(lambda request: _result(pages=(_page(canonical_uri=uri),)))

    with pytest.raises(ValueError, match="userinfo|credential-shaped"):
        port.fetch("independent_reporting", _query())


def test_missing_temporal_metadata_is_not_fabricated_and_creates_visible_gap() -> None:
    port = ChromeSourcePort(
        lambda request: _result(pages=(_page(published_at=None), _page(source_id="unknown-history", available_at=None)))
    )

    batch = port.fetch("independent_reporting", _query())

    assert batch.status == "unavailable"
    assert batch.items == ()
    assert batch.completeness.known_coverage_gaps == (
        "Publisher publication time was not established; evidence was omitted.",
        "Historical availability was not established; evidence was omitted.",
    )
    assert batch.limitations == batch.completeness.known_coverage_gaps


def test_evidence_available_after_cutoff_is_rejected_by_source_contract() -> None:
    page = _page(available_at="2026-08-02T00:01:00+00:00")
    port = ChromeSourcePort(lambda request: _result(pages=(page,)))

    batch = port.fetch("independent_reporting", _query())

    assert batch.status == "unavailable"
    assert batch.items == ()
    assert "unavailable at the requested cutoff" in batch.limitations[0]


def test_post_cutoff_page_is_omitted_from_otherwise_partial_batch() -> None:
    valid = _page()
    late = replace(
        _page(),
        source_id="publisher-late",
        canonical_uri="https://news.example.com/research/late",
        available_at="2026-08-02T00:01:00+00:00",
    )

    batch = ChromeSourcePort(lambda request: _result(pages=(valid, late))).fetch("independent_reporting", _query())

    assert batch.status == "partial"
    assert tuple(item.source_id for item in batch.items) == (valid.source_id,)
    assert batch.completeness.known_coverage_gaps == (
        "Evidence was unavailable at the requested cutoff and was omitted.",
    )


def test_prompt_injection_detection_fails_closed_and_remains_visible_in_portfolio() -> None:
    port = ChromeSourcePort(lambda request: _result(pages=(_page(prompt_injection_detected=True),)))
    collector = SourcePortfolioCollector()
    collector.register("independent_reporting", "chrome", "publisher-pages", port, required=True)

    receipt = collector.collect("independent_reporting", _query())

    assert receipt.attempts[0].status == "unavailable"
    assert receipt.batches[0].items == ()
    assert "prompt injection" in receipt.batches[0].limitations[0].lower()
    assert receipt.coverage_gaps == ("required_route:chrome:unavailable",)


def test_private_target_denial_takes_precedence_over_prompt_injection_classification() -> None:
    page = _page(
        canonical_uri="https://127.0.0.1/research/orcl",
        prompt_injection_detected=True,
    )

    batch = ChromeSourcePort(lambda request: _result(approved_domain="127.0.0.1", pages=(page,))).fetch(
        "independent_reporting", _query()
    )

    assert batch.status == "denied"
    assert batch.items == ()
    assert "public publisher boundary" in batch.limitations[0]


@pytest.mark.parametrize("publisher", ["Chrome", "browser", "Unresolved publisher", "unknown"])
def test_browser_and_placeholder_publisher_identities_are_rejected(publisher: str) -> None:
    port = ChromeSourcePort(lambda request: _result(publisher=publisher))

    with pytest.raises(ValueError, match="attributable publisher"):
        port.fetch("independent_reporting", _query())


def test_terms_and_pages_cannot_mix_publisher_domains() -> None:
    port = ChromeSourcePort(lambda request: _result(terms_uri="https://other.example.com/terms"))

    with pytest.raises(ValueError, match="single approved publisher domain"):
        port.fetch("independent_reporting", _query())


@pytest.mark.parametrize(
    "terms_uri",
    [
        "https://news.example.com\\@127.0.0.1/terms",
        "https://news.example.com:444/terms",
        "https://news.example.com /terms",
    ],
)
def test_terms_uri_rejects_ambiguous_authority_and_non_default_ports(terms_uri: str) -> None:
    batch = ChromeSourcePort(lambda request: _result(terms_uri=terms_uri)).fetch("independent_reporting", _query())

    assert batch.status == "denied"
    assert batch.items == ()


@pytest.mark.parametrize("state", ["disconnected", "unavailable", "denied"])
def test_host_terminal_states_emit_visible_batches_and_required_portfolio_gaps(state: str) -> None:
    port = ChromeSourcePort(lambda request: _result(state=state, pages=()))  # type: ignore[arg-type]
    collector = SourcePortfolioCollector()
    collector.register("independent_reporting", "chrome", "publisher-pages", port, required=True)

    receipt = collector.collect("independent_reporting", _query())

    expected = "denied" if state == "denied" else "unavailable"
    assert receipt.attempts[0].status == expected
    assert receipt.source_batch_ids == (receipt.attempts[0].batch_id,)
    assert receipt.batches[0].items == ()
    assert receipt.coverage_gaps == (f"required_route:chrome:{expected}",)
    assert receipt.status == "unavailable"


def test_host_callback_exception_classification_preserves_permission_and_provider_errors() -> None:
    def denied_callback(request: ChromeSourceRequest) -> ChromeHostResult:
        raise PermissionError("host denied")

    def disconnected_callback(request: ChromeSourceRequest) -> ChromeHostResult:
        raise ConnectionError("host disconnected")

    def provider_error_callback(request: ChromeSourceRequest) -> ChromeHostResult:
        raise OSError("unrelated host failure")

    assert ChromeSourcePort(denied_callback).fetch("independent_reporting", _query()).status == "denied"
    assert ChromeSourcePort(disconnected_callback).fetch("independent_reporting", _query()).status == "unavailable"
    with pytest.raises(OSError, match="unrelated host failure"):
        ChromeSourcePort(provider_error_callback).fetch("independent_reporting", _query())

    collector = SourcePortfolioCollector()
    collector.register("independent_reporting", "chrome", "publisher-pages", ChromeSourcePort(provider_error_callback))
    receipt = collector.collect("independent_reporting", _query())
    assert receipt.attempts[0].status == "error"
    assert receipt.attempts[0].failure_type == "OSError"


def test_multiple_pages_stay_in_one_batch_only_under_the_single_declared_publisher() -> None:
    second = replace(
        _page(),
        source_id="publisher-orcl-guidance",
        canonical_uri="https://news.example.com/research/orcl-guidance",
    )
    batch = ChromeSourcePort(lambda request: _result(pages=(_page(), second))).fetch("independent_reporting", _query())

    assert len(batch.items) == 2
    assert {item.provider for item in batch.items} == {"Example Financial News"}


def test_optional_failed_chrome_route_does_not_replace_valid_required_structured_evidence() -> None:
    structured_batch = ChromeSourcePort(lambda request: _result()).fetch("independent_reporting", _query())
    structured_batch = replace(
        structured_batch,
        provenance=SourceProvenance(
            provider=structured_batch.provenance.provider,
            provider_version=structured_batch.provenance.provider_version,
            adapter="structured-api",
            adapter_version="1.0.0",
            retrieved_at=structured_batch.provenance.retrieved_at,
        ),
    )

    class StructuredPort:
        def fetch(self, capability: str, query: object) -> object:
            return structured_batch

    collector = SourcePortfolioCollector()
    collector.register("independent_reporting", "structured", "publisher-api", StructuredPort(), required=True)  # type: ignore[arg-type]
    collector.register(
        "independent_reporting",
        "chrome",
        "publisher-pages",
        ChromeSourcePort(lambda request: _result(state="disconnected", pages=())),
    )

    receipt = collector.collect("independent_reporting", _query())

    assert receipt.status == "complete"
    assert [(attempt.route_id, attempt.status) for attempt in receipt.attempts] == [
        ("chrome", "unavailable"),
        ("structured", "complete"),
    ]
    assert len(receipt.batches) == 2
    assert receipt.batches[0].items == ()
    assert receipt.batches[1].items == structured_batch.items
    assert receipt.coverage_gaps == ()
