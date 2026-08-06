"""Runtime-neutral normalization boundary for host-owned Chrome retrieval."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, TypeAlias
from urllib.parse import SplitResult, urlsplit

from stock_research_agents_host.contracts import (
    NormalizedFact,
    SourceBatch,
    SourceCompleteness,
    SourceEntitlement,
    SourceObservation,
    SourcePagination,
    SourceProvenance,
    SourceQuery,
)

CHROME_SOURCE_ADAPTER_VERSION = "1.0.0"

ChromeHostState: TypeAlias = Literal["available", "disconnected", "denied", "unavailable"]
ChromePageKind: TypeAlias = Literal["publisher", "account", "settings", "messages", "authenticated_other"]
ChromeSourceKind: TypeAlias = Literal[
    "filing",
    "fundamental",
    "market_series",
    "news",
    "transcript",
    "analyst_research",
    "ownership",
    "positioning",
    "other",
]

_SPECIAL_HOSTS = {"localhost", "localhost.localdomain"}
_SPECIAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_ATTESTATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DENIED_PATH_SEGMENTS = {
    "account",
    "accounts",
    "inbox",
    "login",
    "messages",
    "oauth",
    "profile",
    "settings",
    "signin",
}
_UNTRUSTED_CONTENT_LIMITATION = (
    "Chrome page content was treated as untrusted data; page-supplied instructions were not followed."
)
_RESERVED_PUBLISHER_IDENTITIES = {
    "browser",
    "chrome",
    "google chrome",
    "unknown",
    "unknown publisher",
    "unresolved",
    "unresolved publisher",
    "web browser",
}


@dataclass(frozen=True, slots=True)
class ChromeSourceRequest:
    """Read-only request passed to the injected host callback.

    The request deliberately exposes no browser action, form, download, script,
    or clipboard surface. The host owns Chrome and its approval flow.
    """

    capability: str
    query: SourceQuery


@dataclass(frozen=True, slots=True)
class ChromeNavigationHop:
    """Browser-canonical redirect attestation without path, query, or page state."""

    hop_index: int
    host: str
    origin: str


@dataclass(frozen=True, slots=True)
class ChromePageEvidence:
    """Bounded normalized data extracted by the host from one untrusted page."""

    source_id: str
    source_kind: ChromeSourceKind
    canonical_uri: str
    observed_at: str
    published_at: str | None
    available_at: str | None
    facts: tuple[NormalizedFact, ...] = ()
    bounded_extract: str | None = None
    limitations: tuple[str, ...] = ()
    page_kind: ChromePageKind = "publisher"
    public_page: bool = True
    research_relevant: bool = True
    prompt_injection_detected: bool = False
    contacted_ip_addresses: tuple[str, ...] = ()
    navigation_hops: tuple[ChromeNavigationHop, ...] = ()
    navigation_receipt_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChromeHostResult:
    """Host callback result containing normalized evidence, never browser state."""

    state: ChromeHostState
    retrieved_at: str
    run_approved: bool = False
    approved_domain: str | None = None
    publisher: str | None = None
    publisher_version: str | None = None
    license_receipt_id: str | None = None
    terms_uri: str | None = None
    redistributable: bool | Literal["unknown"] = "unknown"
    pages: tuple[ChromePageEvidence, ...] = ()


ChromeHostCallback: TypeAlias = Callable[[ChromeSourceRequest], ChromeHostResult]


class _DeniedTarget(ValueError):
    pass


class ChromeSourcePort:
    """Normalize a host-owned Chrome callback into the canonical ``SourcePort``.

    This adapter never imports, launches, or controls Chrome. It accepts only an
    injected callback whose DTO is intentionally read-only and browser-neutral.
    """

    def __init__(self, callback: ChromeHostCallback, *, clock: Callable[[], str] | None = None) -> None:
        if not callable(callback):
            raise TypeError("Chrome source callback must be callable")
        self._callback = callback
        self._clock = clock

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        try:
            result = self._callback(ChromeSourceRequest(capability=capability, query=query))
        except PermissionError:
            return self._terminal(capability, query, "denied", "Chrome host permission was denied.")
        except (ConnectionError, TimeoutError):
            return self._terminal(capability, query, "unavailable", "Chrome host is disconnected.")
        if not isinstance(result, ChromeHostResult):
            raise TypeError("Chrome host callback must return ChromeHostResult")
        if result.state not in {"available", "disconnected", "denied", "unavailable"}:
            raise ValueError("Chrome host result state is invalid")
        if not isinstance(result.run_approved, bool):
            raise ValueError("Chrome run approval must be a boolean")
        if not isinstance(result.pages, tuple):
            raise ValueError("Chrome pages must be a tuple")
        if not all(isinstance(page, ChromePageEvidence) for page in result.pages):
            raise TypeError("Chrome pages must be ChromePageEvidence records")
        if result.state == "disconnected":
            return self._terminal(
                capability,
                query,
                "unavailable",
                "Chrome host is disconnected.",
                retrieved_at=result.retrieved_at,
            )
        if result.state == "unavailable":
            return self._terminal(
                capability,
                query,
                "unavailable",
                "Chrome host is unavailable.",
                retrieved_at=result.retrieved_at,
            )
        if result.state == "denied" or not result.run_approved or result.approved_domain is None:
            return self._terminal(
                capability,
                query,
                "denied",
                "Chrome access was not explicitly approved for this run and domain.",
                retrieved_at=result.retrieved_at,
            )
        if not result.pages:
            return self._terminal(
                capability,
                query,
                "unavailable",
                "Chrome returned no attributable publisher evidence.",
                retrieved_at=result.retrieved_at,
            )
        if not result.publisher or not result.publisher_version or not result.license_receipt_id:
            raise ValueError("available Chrome evidence requires one publisher and entitlement receipt")
        _validate_publisher_identity(result.publisher)

        try:
            approved_domain = _normalize_approved_domain(result.approved_domain)
            for page in result.pages:
                _validate_approved_publisher_page(page, approved_domain)
            _validate_terms_domain(result.terms_uri, approved_domain)
            if result.redistributable is True and result.terms_uri is None:
                raise ValueError(
                    "Chrome redistribution requires an explicit public HTTPS terms URI on the approved publisher domain"
                )
        except _DeniedTarget:
            return self._terminal(
                capability,
                query,
                "denied",
                "Chrome target is outside the approved public publisher boundary.",
                retrieved_at=result.retrieved_at,
            )
        if any(page.prompt_injection_detected is True for page in result.pages):
            return self._terminal(
                capability,
                query,
                "unavailable",
                "Potential prompt injection was detected in Chrome page content; evidence was omitted.",
                retrieved_at=result.retrieved_at,
                provider=result.publisher,
                provider_version=result.publisher_version,
                license_receipt_id=result.license_receipt_id,
            )

        gaps: list[str] = []
        observations: list[SourceObservation] = []
        for page in result.pages:
            if page.published_at is None:
                gaps.append("Publisher publication time was not established; evidence was omitted.")
                continue
            if page.available_at is None:
                gaps.append("Historical availability was not established; evidence was omitted.")
                continue
            if _parse_timestamp(page.available_at) > _parse_timestamp(query.cutoff_at):
                gaps.append("Evidence was unavailable at the requested cutoff and was omitted.")
                continue
            extract = page.bounded_extract if result.redistributable is True else None
            digest_scope: Literal["bounded_extract", "normalized_source_record"]
            if extract is not None:
                digest_scope = "bounded_extract"
                digest = sha256(extract.encode("utf-8")).hexdigest()
            else:
                digest_scope = "normalized_source_record"
                digest = _normalized_record_digest(page, result.publisher, result.publisher_version)
            observations.append(
                SourceObservation(
                    source_id=page.source_id,
                    source_kind=page.source_kind,
                    canonical_uri=page.canonical_uri,
                    content_sha256=digest,
                    observed_at=page.observed_at,
                    published_at=page.published_at,
                    available_at=page.available_at,
                    retrieved_at=result.retrieved_at,
                    provider=result.publisher,
                    provider_version=result.publisher_version,
                    license_receipt_id=result.license_receipt_id,
                    facts=page.facts,
                    bounded_extract=extract,
                    limitations=(*page.limitations, _UNTRUSTED_CONTENT_LIMITATION),
                    content_sha256_scope=digest_scope,
                )
            )

        if not observations:
            unique_gaps = _unique_strings(gaps)
            return self._terminal(
                capability,
                query,
                "unavailable",
                unique_gaps[0] if unique_gaps else "Chrome returned no usable publisher evidence.",
                retrieved_at=result.retrieved_at,
                provider=result.publisher,
                provider_version=result.publisher_version,
                license_receipt_id=result.license_receipt_id,
                gaps=unique_gaps or None,
            )

        unique_gaps = _unique_strings(gaps)
        complete = not unique_gaps
        redistribution_limitation = (
            None
            if result.redistributable is True
            else "Redistribution permission was not established; extracts were omitted."
        )
        limitations = unique_gaps
        if not complete:
            limitations += ("Chrome evidence did not completely cover the requested page set.",)
        return SourceBatch(
            capability=capability,
            query=query,
            cutoff=query.cutoff_at,
            status="complete" if complete else "partial",
            items=tuple(observations),
            provenance=SourceProvenance(
                provider=result.publisher,
                provider_version=result.publisher_version,
                adapter="chrome-host-callback",
                adapter_version=CHROME_SOURCE_ADAPTER_VERSION,
                retrieved_at=result.retrieved_at,
            ),
            entitlement=SourceEntitlement(
                access="allowed",
                redistributable=result.redistributable,
                terms_uri=result.terms_uri,
                license_receipt_id=result.license_receipt_id,
                limitation=redistribution_limitation,
            ),
            completeness=SourceCompleteness(complete=complete, known_coverage_gaps=unique_gaps),
            pagination=SourcePagination(
                has_more=False,
                next_cursor=None,
                returned_items=len(observations),
                bounded_items=max(1, len(result.pages)),
            ),
            limitations=limitations,
        )

    def _terminal(
        self,
        capability: str,
        query: SourceQuery,
        status: Literal["unavailable", "denied"],
        limitation: str,
        *,
        retrieved_at: str | None = None,
        provider: str = "Unresolved publisher",
        provider_version: str = "unavailable",
        license_receipt_id: str | None = None,
        gaps: tuple[str, ...] | None = None,
    ) -> SourceBatch:
        timestamp = retrieved_at or (self._clock() if self._clock is not None else _now())
        receipt_id = license_receipt_id or f"chrome-{status}"
        visible_gaps = _unique_strings(gaps or (limitation,))
        visible_limitations = _unique_strings((limitation, *visible_gaps))
        return SourceBatch(
            capability=capability,
            query=query,
            cutoff=query.cutoff_at,
            status=status,
            items=(),
            provenance=SourceProvenance(
                provider=provider,
                provider_version=provider_version,
                adapter="chrome-host-callback",
                adapter_version=CHROME_SOURCE_ADAPTER_VERSION,
                retrieved_at=timestamp,
            ),
            entitlement=SourceEntitlement(
                access="denied" if status == "denied" else "unknown",
                redistributable=False if status == "denied" else "unknown",
                terms_uri=None,
                license_receipt_id=receipt_id,
                limitation=limitation,
            ),
            completeness=SourceCompleteness(complete=False, known_coverage_gaps=visible_gaps),
            pagination=SourcePagination(has_more=False, next_cursor=None, returned_items=0, bounded_items=1),
            limitations=visible_limitations,
        )


def _normalize_approved_domain(value: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise _DeniedTarget("approved domain is invalid")
    candidate = value.rstrip(".").lower()
    if not candidate or "://" in candidate or "/" in candidate or "@" in candidate:
        raise _DeniedTarget("approved domain is invalid")
    _ensure_public_host(candidate)
    return candidate


def _validate_approved_publisher_page(page: ChromePageEvidence, approved_domain: str) -> None:
    if not isinstance(page, ChromePageEvidence):
        raise TypeError("Chrome pages must be ChromePageEvidence records")
    if not isinstance(page.prompt_injection_detected, bool):
        raise ValueError("Chrome prompt-injection status must be a boolean")
    parsed = _parse_public_https_uri(page.canonical_uri, "Chrome target")
    assert parsed.hostname is not None
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname != approved_domain:
        raise _DeniedTarget("Chrome target domain was not explicitly approved")
    path_segments = {segment.casefold() for segment in parsed.path.split("/") if segment}
    if path_segments & _DENIED_PATH_SEGMENTS:
        raise _DeniedTarget("Chrome account, settings, and message pages are denied")
    if page.page_kind != "publisher" or page.public_page is not True or page.research_relevant is not True:
        raise _DeniedTarget("Chrome page is not a public research-relevant publisher page")
    _validate_navigation_attestation(page, approved_domain, hostname)


def _ensure_public_host(hostname: str) -> None:
    if "%" in hostname or any(ord(character) > 0x7F for character in hostname):
        raise _DeniedTarget("Chrome target host must use strict ASCII or punycode syntax")
    if hostname in _SPECIAL_HOSTS or hostname.endswith(_SPECIAL_SUFFIXES):
        raise _DeniedTarget("Chrome target is not on the public internet")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            # ``inet_aton`` recognizes alternative numeric IPv4 spellings (short,
            # integer, octal, and hexadecimal) without performing DNS. Reject
            # all such ambiguous forms; canonical IPs were handled above.
            socket.inet_aton(hostname)
        except OSError:
            pass
        else:
            raise _DeniedTarget("Chrome target uses an ambiguous numeric internet address") from None
        _validate_ascii_domain(hostname)
        return
    if str(address) != hostname:
        raise _DeniedTarget("Chrome target IP must use its canonical string representation")
    if not _is_globally_routable_unicast(address):
        raise _DeniedTarget("Chrome target is not a globally routable unicast address")


def _validate_publisher_identity(publisher: str) -> None:
    if publisher.strip().casefold() in _RESERVED_PUBLISHER_IDENTITIES:
        raise ValueError("Chrome publisher must identify the attributable publisher, not the browser")


def _validate_terms_domain(terms_uri: str | None, approved_domain: str) -> None:
    if terms_uri is None:
        return
    parsed = _parse_public_https_uri(terms_uri, "Chrome terms URI")
    assert parsed.hostname is not None
    if parsed.hostname.rstrip(".").casefold() != approved_domain:
        raise ValueError("Chrome terms URI and publisher pages must use the single approved publisher domain")


def _parse_public_https_uri(value: str, label: str) -> SplitResult:
    if not isinstance(value, str):
        raise _DeniedTarget(f"{label} must be an HTTPS URI")
    if "\\" in value or any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in value
    ):
        raise _DeniedTarget(f"{label} contains ambiguous URI syntax")
    authority = value.partition("://")[2].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "%" in authority or any(ord(character) > 0x7F for character in authority):
        raise _DeniedTarget(f"{label} authority must use strict ASCII syntax")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise _DeniedTarget(f"{label} authority is invalid") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise _DeniedTarget(f"{label} must be an HTTPS URI")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain userinfo")
    if port is not None and port != 443:
        raise _DeniedTarget(f"{label} may use only the default HTTPS port")
    _ensure_public_host(parsed.hostname.rstrip(".").lower())
    return parsed


def _validate_ascii_domain(hostname: str) -> None:
    try:
        hostname.encode("ascii")
    except UnicodeEncodeError:
        raise _DeniedTarget("Chrome target host must use ASCII or punycode syntax") from None
    if len(hostname) > 253:
        raise _DeniedTarget("Chrome target host exceeds the public domain bound")
    labels = hostname.split(".")
    if len(labels) < 2 or all(label.isdigit() for label in labels):
        raise _DeniedTarget("Chrome target is not an unambiguous public publisher domain")
    if not all(_DOMAIN_LABEL.fullmatch(label) for label in labels):
        raise _DeniedTarget("Chrome target host must use strict ASCII or punycode syntax")


def _validate_navigation_attestation(page: ChromePageEvidence, approved_domain: str, canonical_hostname: str) -> None:
    if (
        not isinstance(page.contacted_ip_addresses, tuple)
        or not page.contacted_ip_addresses
        or len(page.contacted_ip_addresses) > 64
    ):
        raise _DeniedTarget("Chrome navigation requires contacted-address attestation")
    if not isinstance(page.navigation_hops, tuple) or not page.navigation_hops or len(page.navigation_hops) > 10:
        raise _DeniedTarget("Chrome navigation requires a bounded canonical-origin attestation")
    if not isinstance(page.navigation_receipt_id, str) or not _ATTESTATION_ID.fullmatch(page.navigation_receipt_id):
        raise _DeniedTarget("Chrome navigation requires a bounded public-address verification receipt")
    final_hostname: str | None = None
    for expected_index, hop in enumerate(page.navigation_hops):
        if (
            not isinstance(hop, ChromeNavigationHop)
            or not isinstance(hop.hop_index, int)
            or isinstance(hop.hop_index, bool)
            or hop.hop_index != expected_index
        ):
            raise _DeniedTarget("Chrome navigation hops must use contiguous bounded indexes")
        if not isinstance(hop.host, str):
            raise _DeniedTarget("Chrome navigation hop host is invalid")
        host = hop.host.rstrip(".").lower()
        _ensure_public_host(host)
        if hop.host != host:
            raise _DeniedTarget("Chrome navigation hop host must use canonical syntax")
        parsed = _parse_public_https_uri(hop.origin, "Chrome navigation origin")
        assert parsed.hostname is not None
        if parsed.path or parsed.query or parsed.fragment or parsed.port is not None:
            raise _DeniedTarget("Chrome navigation origins must be browser-canonical origins without URL state")
        hostname = parsed.hostname.rstrip(".").lower()
        if hop.origin != _canonical_https_origin(hostname) or hostname != host:
            raise _DeniedTarget("Chrome navigation origins must use browser-canonical HTTPS origin syntax")
        if hostname != approved_domain:
            raise _DeniedTarget("Chrome navigation crossed outside the explicitly approved publisher domain")
        final_hostname = hostname
    if final_hostname != canonical_hostname:
        raise _DeniedTarget("Chrome final navigation origin must match the canonical publisher URI")
    for raw_address in page.contacted_ip_addresses:
        if not isinstance(raw_address, str):
            raise _DeniedTarget("Chrome contacted addresses must be canonical public IP strings")
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError:
            raise _DeniedTarget("Chrome contacted addresses must be canonical public IP strings") from None
        if str(address) != raw_address or not _is_globally_routable_unicast(address):
            raise _DeniedTarget("Chrome contacted addresses must be canonical globally routable unicast IPs")
    try:
        canonical_address = ipaddress.ip_address(canonical_hostname)
    except ValueError:
        pass
    else:
        if str(canonical_address) not in page.contacted_ip_addresses:
            raise _DeniedTarget("Chrome raw-IP target must appear in the contacted-address attestation")


def _canonical_https_origin(hostname: str) -> str:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        authority = hostname
    else:
        authority = f"[{address}]" if isinstance(address, ipaddress.IPv6Address) else str(address)
    return f"https://{authority}"


def _is_globally_routable_unicast(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_reserved
        and not address.is_unspecified
        and not getattr(address, "is_site_local", False)
    )


def _parse_timestamp(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError("Chrome evidence timestamps must be timezone-aware date-times") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Chrome evidence timestamps must be timezone-aware date-times")
    return parsed


def _unique_strings(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _normalized_record_digest(page: ChromePageEvidence, publisher: str, publisher_version: str) -> str:
    payload = {
        "available_at": page.available_at,
        "canonical_uri": page.canonical_uri,
        "facts": [fact.to_dict() for fact in page.facts],
        "observed_at": page.observed_at,
        "published_at": page.published_at,
        "publisher": publisher,
        "publisher_version": publisher_version,
        "source_id": page.source_id,
        "source_kind": page.source_kind,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(encoded).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "CHROME_SOURCE_ADAPTER_VERSION",
    "ChromeHostCallback",
    "ChromeHostResult",
    "ChromeNavigationHop",
    "ChromePageEvidence",
    "ChromeSourcePort",
    "ChromeSourceRequest",
]
