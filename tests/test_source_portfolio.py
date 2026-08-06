from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from stock_research_agents_host.contracts import (
    FilingQuery,
    SourceBatch,
    SourceCompleteness,
    SourceEntitlement,
    SourceObservation,
    SourcePagination,
    SourceProvenance,
)
from stock_research_agents_host.source_portfolio import (
    MAX_SOURCE_PORTFOLIO_PROVIDERS,
    SourcePortfolioCollector,
    SourcePortfolioReceipt,
)

CUTOFF = "2026-08-01T23:59:59+00:00"


def _query() -> FilingQuery:
    return FilingQuery(query_id="meta-2026-08-01", symbol="META", cutoff_at=CUTOFF)


def _observation(source_id: str, **changes: object) -> SourceObservation:
    values: dict[str, object] = {
        "source_id": source_id,
        "source_kind": "filing",
        "canonical_uri": f"https://example.com/{source_id}",
        "content_sha256": sha256(source_id.encode()).hexdigest(),
        "observed_at": "2026-07-31T20:00:00+00:00",
        "published_at": "2026-07-31T20:05:00+00:00",
        "available_at": "2026-07-31T20:06:00+00:00",
        "retrieved_at": "2026-08-01T12:00:00+00:00",
        "provider": "example",
        "provider_version": "v1",
        "license_receipt_id": "license-example",
        "content_sha256_scope": "normalized_source_record",
    }
    values.update(changes)
    return SourceObservation(**values)


def _batch(
    provider: str,
    *items: SourceObservation,
    status: str = "complete",
    redistributable: bool | str = True,
) -> SourceBatch:
    normalized_items = tuple(
        replace(item, provider=provider, license_receipt_id=f"license-{provider}") for item in items
    )
    limitation = None if redistributable is True else "Host use only."
    gaps = () if status == "complete" else ("Provider did not fully cover the query.",)
    limitations = () if status == "complete" else ("Provider response was not complete.",)
    return SourceBatch(
        capability="official_filings",
        query=_query(),
        cutoff=CUTOFF,
        status=status,  # type: ignore[arg-type]
        items=normalized_items,
        provenance=SourceProvenance(provider, "v1", f"{provider}-adapter", "1.0.0", "2026-08-01T12:01:00+00:00"),
        entitlement=SourceEntitlement(
            "allowed",
            redistributable,  # type: ignore[arg-type]
            f"https://example.com/{provider}/terms",
            f"license-{provider}",
            limitation,
        ),
        completeness=SourceCompleteness(status == "complete", gaps),
        pagination=SourcePagination(False, None, len(normalized_items), max(1, len(normalized_items))),
        limitations=limitations,
    )


class _Port:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0

    def fetch(self, capability: str, query: object) -> SourceBatch:
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response  # type: ignore[return-value]


def test_collector_attempts_every_provider_and_is_deterministic() -> None:
    alpha = _Port(_batch("alpha", _observation("alpha-1")))
    beta_batch = _batch(
        "beta",
        _observation(
            "beta-2",
            observed_at="2026-07-31T21:00:00+00:00",
            published_at="2026-07-31T21:05:00+00:00",
            available_at="2026-07-31T21:06:00+00:00",
        ),
        _observation("beta-1"),
        redistributable="unknown",
    )
    beta = _Port(beta_batch)
    collector = SourcePortfolioCollector()
    collector.register("official_filings", "beta", "wire-services", beta)
    collector.register("official_filings", "alpha", "regulators", alpha, required=True)

    receipt = collector.collect("official_filings", _query())

    assert alpha.calls == beta.calls == 1
    assert receipt.status == "complete"
    assert [attempt.route_id for attempt in receipt.attempts] == ["alpha", "beta"]
    assert [batch.provenance.provider for batch in receipt.batches] == ["alpha", "beta"]
    assert receipt.batches[1].entitlement.redistributable == "unknown"
    assert receipt.batches[1].items == beta_batch.items
    assert SourcePortfolioReceipt.from_dict(receipt.to_dict()) == receipt

    repeated = collector.collect("official_filings", _query())
    assert repeated.portfolio_sha256 == receipt.portfolio_sha256
    assert repeated.to_dict() == receipt.to_dict()


def test_failures_are_terminal_sanitized_and_required_failure_makes_partial() -> None:
    good = _Port(_batch("good", _observation("good-1")))
    secret = "token-super-secret"
    broken = _Port(RuntimeError(secret))
    collector = SourcePortfolioCollector()
    collector.register("official_filings", "broken", "licensed", broken, required=True)
    collector.register("official_filings", "good", "regulators", good)

    receipt = collector.collect("official_filings", _query())
    wire = str(receipt.to_dict())

    assert good.calls == broken.calls == 1
    assert receipt.status == "partial"
    assert receipt.attempts[0].status == "error"
    assert receipt.attempts[0].failure_type == "RuntimeError"
    assert receipt.coverage_gaps == ("required_route:broken:error",)
    assert secret not in wire


def test_failure_type_is_sanitized_when_exception_class_name_is_not_an_identifier() -> None:
    unsafe_error = type("token_super_secret", (Exception,), {})
    collector = SourcePortfolioCollector()
    collector.register("official_filings", "broken", "licensed", _Port(unsafe_error("private")))

    receipt = collector.collect("official_filings", _query())

    assert receipt.attempts[0].failure_type == "ProviderError"
    assert "private" not in str(receipt.to_dict())


def test_optional_failure_does_not_downgrade_satisfied_required_coverage() -> None:
    collector = SourcePortfolioCollector()
    collector.register(
        "official_filings", "required", "regulators", _Port(_batch("required", _observation("filing"))), required=True
    )
    collector.register("official_filings", "optional", "social", _Port(TimeoutError("private detail")))

    receipt = collector.collect("official_filings", _query())

    assert receipt.status == "complete"
    assert receipt.coverage_gaps == ()
    assert receipt.attempts[0].status == "error"


@pytest.mark.parametrize("status", ["partial", "stale"])
def test_optional_only_incomplete_evidence_is_not_labeled_complete(status: str) -> None:
    collector = SourcePortfolioCollector()
    collector.register(
        "official_filings",
        "optional",
        "news",
        _Port(_batch("optional", _observation("item"), status=status)),
    )

    receipt = collector.collect("official_filings", _query())

    assert receipt.status == "partial"
    assert receipt.attempts[0].status == status


@pytest.mark.parametrize("failed_response", [TimeoutError("private"), object()])
def test_optional_only_failures_are_not_hidden_by_one_complete_route(failed_response: object) -> None:
    collector = SourcePortfolioCollector()
    collector.register(
        "official_filings",
        "complete",
        "regulator",
        _Port(_batch("complete", _observation("item"))),
    )
    collector.register("official_filings", "failed", "news", _Port(failed_response))

    receipt = collector.collect("official_filings", _query())

    assert receipt.status == "partial"
    assert receipt.attempts[1].status in {"error", "invalid_response"}


def test_required_complete_but_empty_batch_is_not_covered() -> None:
    collector = SourcePortfolioCollector()
    collector.register("official_filings", "empty", "regulators", _Port(_batch("empty")), required=True)
    collector.register("official_filings", "useful", "issuer", _Port(_batch("useful", _observation("release"))))

    receipt = collector.collect("official_filings", _query())

    assert receipt.status == "partial"
    assert receipt.coverage_gaps == ("required_route:empty:empty",)


def test_invalid_responses_are_recorded_and_all_failed_routes_are_unavailable() -> None:
    wrong_query = replace(_query(), query_id="wrong-query")
    invalid = _Port(replace(_batch("invalid"), query=wrong_query))
    exploding = _Port(LookupError("private provider detail"))
    collector = SourcePortfolioCollector()
    collector.register("official_filings", "invalid", "family-a", invalid, required=True)
    collector.register("official_filings", "exploding", "family-b", exploding)

    receipt = collector.collect("official_filings", _query())

    assert receipt.status == "unavailable"
    assert receipt.batches == ()
    assert [(item.route_id, item.status, item.failure_type) for item in receipt.attempts] == [
        ("exploding", "error", "LookupError"),
        ("invalid", "invalid_response", "ValueError"),
    ]


def test_exact_duplicate_clusters_use_declared_precedence() -> None:
    digest = "a" * 64
    collector = SourcePortfolioCollector()
    collector.register(
        "official_filings",
        "alpha",
        "family-one",
        _Port(
            _batch(
                "alpha",
                _observation("digest-a", content_sha256=digest, content_sha256_scope="source_content"),
                _observation("uri-a", canonical_uri="https://example.com/shared"),
                _observation("native-id"),
            )
        ),
    )
    collector.register(
        "official_filings",
        "beta",
        "family-two",
        _Port(
            _batch(
                "beta",
                _observation("digest-b", content_sha256=digest, content_sha256_scope="source_content"),
                _observation("uri-b", canonical_uri="https://example.com/shared"),
            )
        ),
    )
    collector.register(
        "official_filings",
        "gamma",
        "family-one",
        _Port(
            _batch(
                "gamma",
                _observation(
                    "native-id",
                    canonical_uri="https://mirror.example/native-id",
                    content_sha256="b" * 64,
                ),
            )
        ),
    )

    receipt = collector.collect("official_filings", _query())

    assert [cluster.match_basis for cluster in receipt.exact_duplicate_clusters] == [
        "content_digest",
        "canonical_uri",
        "provider_native_identity",
    ]
    assert [cluster.representative.route_id for cluster in receipt.exact_duplicate_clusters] == [
        "alpha",
        "alpha",
        "alpha",
    ]
    assert sum(len(batch.items) for batch in receipt.batches) == 6


def test_exact_duplicate_clustering_is_transitive_across_match_bases() -> None:
    shared_digest = "c" * 64
    collector = SourcePortfolioCollector()
    collector.register(
        "official_filings",
        "alpha",
        "family-a",
        _Port(
            _batch(
                "alpha",
                _observation(
                    "alpha",
                    canonical_uri="https://example.com/alpha",
                    content_sha256=shared_digest,
                    content_sha256_scope="source_content",
                ),
            )
        ),
    )
    collector.register(
        "official_filings",
        "beta",
        "family-b",
        _Port(
            _batch(
                "beta",
                _observation(
                    "beta",
                    canonical_uri="https://example.com/bridge",
                    content_sha256=shared_digest,
                    content_sha256_scope="source_content",
                ),
            )
        ),
    )
    collector.register(
        "official_filings",
        "gamma",
        "family-c",
        _Port(
            _batch(
                "gamma",
                _observation(
                    "gamma",
                    canonical_uri="https://example.com/bridge",
                    content_sha256="d" * 64,
                    content_sha256_scope="source_content",
                ),
            )
        ),
    )

    receipt = collector.collect("official_filings", _query())

    assert len(receipt.exact_duplicate_clusters) == 1
    cluster = receipt.exact_duplicate_clusters[0]
    assert cluster.match_basis == "content_digest"
    assert [member.route_id for member in cluster.members] == ["alpha", "beta", "gamma"]


def test_route_qualified_batch_ids_are_unique_for_identical_batches() -> None:
    shared_batch = _batch("shared", _observation("shared"))
    collector = SourcePortfolioCollector()
    collector.register("official_filings", "route-a", "family", _Port(shared_batch))
    collector.register("official_filings", "route-b", "family", _Port(shared_batch))

    receipt = collector.collect("official_filings", _query())

    assert receipt.attempts[0].batch_sha256 == receipt.attempts[1].batch_sha256
    assert len(receipt.source_batch_ids) == 2
    assert len(set(receipt.source_batch_ids)) == 2
    assert all(batch_id.startswith("batch-") for batch_id in receipt.source_batch_ids)


def test_receipt_wire_model_is_strict_versioned_and_digest_verified() -> None:
    collector = SourcePortfolioCollector()
    collector.register("official_filings", "alpha", "regulators", _Port(_batch("alpha")), required=True)
    receipt = collector.collect("official_filings", _query())
    wire = receipt.to_dict()

    with pytest.raises(ValueError, match="unsupported source portfolio receipt version"):
        SourcePortfolioReceipt.from_dict({**wire, "version": "2.0.0"})
    with pytest.raises(ValueError, match="unknown fields"):
        SourcePortfolioReceipt.from_dict({**wire, "extra": True})
    with pytest.raises(ValueError, match="digest"):
        SourcePortfolioReceipt.from_dict({**wire, "portfolio_sha256": "0" * 64})
    for invalid_digest in ("", None, True, "0" * 63):
        with pytest.raises(ValueError, match="digest"):
            SourcePortfolioReceipt.from_dict({**wire, "portfolio_sha256": invalid_digest})
    with pytest.raises(ValueError, match="digest"):
        replace(receipt, portfolio_sha256=False)  # type: ignore[arg-type]


def test_provider_registration_and_wire_parsing_are_bounded() -> None:
    collector = SourcePortfolioCollector()
    port = _Port(_batch("shared"))
    for index in range(MAX_SOURCE_PORTFOLIO_PROVIDERS):
        collector.register("official_filings", f"provider-{index}", "family", port)
    with pytest.raises(ValueError, match="provider bound"):
        collector.register("official_filings", "one-too-many", "family", port)

    receipt = SourcePortfolioCollector()
    receipt.register("official_filings", "alpha", "family", _Port(_batch("alpha")))
    wire = receipt.collect("official_filings", _query()).to_dict()
    attempts = wire["attempts"]
    assert isinstance(attempts, list)
    with pytest.raises(ValueError, match="provider bound"):
        SourcePortfolioReceipt.from_dict({**wire, "attempts": attempts * (MAX_SOURCE_PORTFOLIO_PROVIDERS + 1)})
