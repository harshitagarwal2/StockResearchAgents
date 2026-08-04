"""Credential-free, versioned records produced by host source adapters."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from typing import ClassVar, Literal, TypeAlias, cast
from urllib.parse import parse_qsl, urlsplit

SOURCE_BATCH_VERSION = "1.0.0"
SOURCE_QUERY_VERSION = "1.0.0"
BatchStatus: TypeAlias = Literal["complete", "partial", "unavailable", "denied", "rate_limited", "stale"]
Redistributable: TypeAlias = bool | Literal["unknown"]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CREDENTIAL_VALUE = re.compile(
    r"(?:"
    r"\b(?:api[_-]?key|authorization|client[_-]?secret|cookie|credential|password|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|secret|token)\b\s*[:=]\s*\S+"
    r"|\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"
    r")",
    re.I,
)
_SENSITIVE_URI_KEYS = {
    "access_key",
    "access_key_id",
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "awsaccesskeyid",
    "client_id",
    "client_secret",
    "credential",
    "credentials",
    "googleaccessid",
    "key",
    "key_pair_id",
    "oauth_token",
    "refresh_token",
    "secret",
    "security_token",
    "sig",
    "signature",
    "signed",
    "token",
}
_SENSITIVE_URI_PARTS = {"credential", "key", "secret", "sig", "signature", "token"}
_RAW_NAMES = {"body_html", "full_text", "raw_content", "raw_document", "raw_filing", "raw_html", "source_blob"}


def _timestamp(value: str, path: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError(f"{path} must be a timezone-aware date-time")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{path} must be a timezone-aware date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{path} must be a timezone-aware date-time")
    return parsed


def _identifier(value: str, path: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{path} must be a bounded stable identifier")


def _text(value: str, path: str, limit: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{path} must be non-empty and at most {limit} characters")
    if _CREDENTIAL_VALUE.search(value):
        raise ValueError(f"{path} contains credential-shaped material")


def _optional_text(value: str | None, path: str, limit: int) -> None:
    if value is not None:
        _text(value, path, limit)


def _string_tuple(value: tuple[str, ...], path: str, *, maximum: int = 64) -> None:
    if not isinstance(value, tuple) or len(value) > maximum:
        raise ValueError(f"{path} must be a tuple with at most {maximum} items")
    for item in value:
        _text(item, path, 512)


def _required_string_tuple(value: tuple[str, ...], path: str, *, maximum: int = 64) -> None:
    _string_tuple(value, path, maximum=maximum)
    if not value:
        raise ValueError(f"{path} must contain at least one item")


def _window(start: str, end: str, *, start_path: str, end_path: str) -> None:
    if _timestamp(start, start_path) > _timestamp(end, end_path):
        raise ValueError(f"{start_path} must not be later than {end_path}")


def _max_items(value: int, path: str, maximum: int = 250) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ValueError(f"{path} must be between 1 and {maximum}")


def _parameters(value: Mapping[str, object]) -> None:
    if not isinstance(value, Mapping) or len(value) > 32:
        raise ValueError("parameters must be an object with at most 32 entries")
    for key, item in value.items():
        _identifier(key, "parameters key")
        if _credential_shaped_field(key):
            raise ValueError("parameters cannot contain credential-shaped fields")
        if not isinstance(item, str | int | float | bool) or isinstance(item, float) and not (-1e308 < item < 1e308):
            raise ValueError("parameters values must be bounded JSON scalars")
        if isinstance(item, str):
            _text(item, f"parameters.{key}", 256)


def _credential_shaped_uri_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    parts = tuple(part for part in normalized.split("_") if part)
    return (
        normalized in _SENSITIVE_URI_KEYS
        or any(part in _SENSITIVE_URI_PARTS for part in parts)
        or normalized.startswith(("x_amz_", "x_goog_"))
    )


def _credential_shaped_field(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    parts = tuple(part for part in normalized.split("_") if part)
    return normalized in _SENSITIVE_URI_KEYS or any(
        part in {"authorization", "cookie", "credential", "credentials", "password", "secret", "token"}
        for part in parts
    )


def _uri(value: str, path: str = "canonical_uri") -> None:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a credential-free https URI")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{path} must be a credential-free https URI")
    keys = [key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    keys.extend(key for key, _ in parse_qsl(parsed.fragment, keep_blank_values=True))
    if any(_credential_shaped_uri_key(key) for key in keys):
        raise ValueError(f"{path} contains credential-shaped parameters")


def _strict_object(value: object, fields: set[str], path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    unknown = sorted(set(value) - fields)
    if unknown:
        raise ValueError(f"{path} has unknown fields: {unknown}")
    return value


@dataclass(frozen=True, slots=True)
class NormalizedFact:
    """One bounded source fact; numeric values use decimal strings."""

    name: str
    value: str
    unit: str | None = None
    period: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.name, "fact.name")
        if self.name.lower() in _RAW_NAMES or _credential_shaped_field(self.name):
            raise ValueError("fact.name cannot request raw or credential material")
        _text(self.value, "fact.value", 2_000)
        _optional_text(self.unit, "fact.unit", 64)
        _optional_text(self.period, "fact.period", 64)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """Bounded, licensed observation returned by a host adapter.

    ``content_sha256_scope`` says exactly what bytes ``content_sha256`` covers:
    authoritative source bytes, the UTF-8 bounded extract, or an adapter's
    canonical normalized source record. The normalized-record default preserves
    existing safe adapters that hash parsed provider rows without retaining raw
    source content.
    """

    source_id: str
    source_kind: Literal[
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
    canonical_uri: str
    content_sha256: str
    observed_at: str
    published_at: str
    available_at: str
    retrieved_at: str
    provider: str
    provider_version: str
    license_receipt_id: str
    facts: tuple[NormalizedFact, ...] = ()
    bounded_extract: str | None = None
    limitations: tuple[str, ...] = ()
    content_sha256_scope: Literal["source_content", "bounded_extract", "normalized_source_record"] = (
        "normalized_source_record"
    )

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _identifier(self.license_receipt_id, "license_receipt_id")
        _uri(self.canonical_uri)
        if not isinstance(self.content_sha256, str) or not _SHA256.fullmatch(self.content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        if self.content_sha256_scope not in {"source_content", "bounded_extract", "normalized_source_record"}:
            raise ValueError("content_sha256_scope is invalid")
        observed = _timestamp(self.observed_at, "observed_at")
        published = _timestamp(self.published_at, "published_at")
        available = _timestamp(self.available_at, "available_at")
        retrieved = _timestamp(self.retrieved_at, "retrieved_at")
        if observed > published or published > available or available > retrieved:
            raise ValueError("source timestamps must satisfy observed <= published <= available <= retrieved")
        _text(self.provider, "provider", 128)
        _text(self.provider_version, "provider_version", 128)
        _optional_text(self.bounded_extract, "bounded_extract", 4_000)
        if self.content_sha256_scope == "bounded_extract":
            if self.bounded_extract is None:
                raise ValueError("bounded_extract digest scope requires a bounded extract")
            if sha256(self.bounded_extract.encode("utf-8")).hexdigest() != self.content_sha256:
                raise ValueError("content_sha256 must digest the exact UTF-8 bounded extract")
        if not isinstance(self.facts, tuple) or not all(isinstance(fact, NormalizedFact) for fact in self.facts):
            raise ValueError("source observation facts must be NormalizedFact records")
        if len(self.facts) > 512:
            raise ValueError("source observation exceeds fact bounds")
        _string_tuple(self.limitations, "limitations")
        if len({fact.name for fact in self.facts}) != len(self.facts):
            raise ValueError("source observation facts must have unique names")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "canonical_uri": self.canonical_uri,
            "content_sha256": self.content_sha256,
            "observed_at": self.observed_at,
            "published_at": self.published_at,
            "available_at": self.available_at,
            "retrieved_at": self.retrieved_at,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "license_receipt_id": self.license_receipt_id,
            "facts": [fact.to_dict() for fact in self.facts],
            "bounded_extract": self.bounded_extract,
            "limitations": list(self.limitations),
            "content_sha256_scope": self.content_sha256_scope,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceObservation:
        raw = _strict_object(value, set(cls.__dataclass_fields__), "source observation")
        payload = dict(raw)
        facts = payload.get("facts", [])
        limitations = payload.get("limitations", [])
        if not isinstance(facts, list) or not all(isinstance(fact, Mapping) for fact in facts):
            raise ValueError("source observation facts must be an array of objects")
        if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
            raise ValueError("source observation limitations must be an array of strings")
        payload["facts"] = tuple(
            NormalizedFact(**_strict_object(fact, set(NormalizedFact.__dataclass_fields__), "fact"))  # type: ignore[arg-type]
            for fact in facts
        )
        payload["limitations"] = tuple(limitations)
        return cls(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    provider: str
    provider_version: str
    adapter: str
    adapter_version: str
    retrieved_at: str

    def __post_init__(self) -> None:
        _text(self.provider, "provenance.provider", 128)
        _text(self.provider_version, "provenance.provider_version", 128)
        _text(self.adapter, "provenance.adapter", 128)
        _text(self.adapter_version, "provenance.adapter_version", 128)
        _timestamp(self.retrieved_at, "provenance.retrieved_at")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceEntitlement:
    access: Literal["allowed", "denied", "unknown"]
    redistributable: Redistributable
    terms_uri: str | None
    license_receipt_id: str
    limitation: str | None

    def __post_init__(self) -> None:
        if self.access not in {"allowed", "denied", "unknown"}:
            raise ValueError("entitlement.access is invalid")
        if not isinstance(self.redistributable, bool) and self.redistributable != "unknown":
            raise ValueError("entitlement.redistributable is invalid")
        if self.terms_uri is not None:
            _uri(self.terms_uri, "entitlement.terms_uri")
        _identifier(self.license_receipt_id, "entitlement.license_receipt_id")
        _optional_text(self.limitation, "entitlement.limitation", 512)
        if (self.access != "allowed" or self.redistributable is not True) and self.limitation is None:
            raise ValueError("restricted or unknown entitlement requires a limitation")
        if self.access == "denied" and self.redistributable is not False:
            raise ValueError("denied entitlement must be non-redistributable")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceCompleteness:
    complete: bool
    known_coverage_gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.complete, bool):
            raise ValueError("completeness.complete must be a boolean")
        _string_tuple(self.known_coverage_gaps, "completeness.known_coverage_gaps")
        if self.complete and self.known_coverage_gaps:
            raise ValueError("complete coverage cannot declare known coverage gaps")

    def to_dict(self) -> dict[str, object]:
        return {"complete": self.complete, "known_coverage_gaps": list(self.known_coverage_gaps)}


@dataclass(frozen=True, slots=True)
class SourcePagination:
    has_more: bool
    next_cursor: str | None
    returned_items: int
    bounded_items: int

    def __post_init__(self) -> None:
        if not isinstance(self.has_more, bool):
            raise ValueError("pagination.has_more must be a boolean")
        _optional_text(self.next_cursor, "pagination.next_cursor", 1_024)
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("pagination.next_cursor must be present exactly when has_more is true")
        if not isinstance(self.returned_items, int) or isinstance(self.returned_items, bool) or self.returned_items < 0:
            raise ValueError("pagination.returned_items must be a non-negative integer")
        if (
            not isinstance(self.bounded_items, int)
            or isinstance(self.bounded_items, bool)
            or not 1 <= self.bounded_items <= 10_000
        ):
            raise ValueError("pagination.bounded_items must be between 1 and 10000")
        if self.returned_items > self.bounded_items:
            raise ValueError("pagination.returned_items cannot exceed bounded_items")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FilingQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "filing"
    query_id: str
    symbol: str
    cutoff_at: str
    form_types: tuple[str, ...] = ("10-K", "10-Q", "8-K")
    start_at: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        _timestamp(self.cutoff_at, "cutoff_at")
        if not isinstance(self.form_types, tuple) or not self.form_types or len(self.form_types) > 32:
            raise ValueError("form_types must contain between 1 and 32 items")
        for form_type in self.form_types:
            _text(form_type, "form_type", 32)
        if self.start_at is not None and _timestamp(self.start_at, "start_at") > _timestamp(
            self.cutoff_at, "cutoff_at"
        ):
            raise ValueError("start_at must not be later than cutoff_at")

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self), "form_types": list(self.form_types)}


@dataclass(frozen=True, slots=True)
class FundamentalQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "fundamental"
    query_id: str
    symbol: str
    cutoff_at: str
    periods: int = 12

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        _timestamp(self.cutoff_at, "cutoff_at")
        if not isinstance(self.periods, int) or isinstance(self.periods, bool) or not 1 <= self.periods <= 80:
            raise ValueError("periods must be between 1 and 80")

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self)}


@dataclass(frozen=True, slots=True)
class MarketSeriesQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "market_series"
    query_id: str
    symbol: str
    start_at: str
    cutoff_at: str
    interval: Literal["1d", "1wk", "1mo"] = "1d"

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        if self.interval not in {"1d", "1wk", "1mo"}:
            raise ValueError("interval is invalid")
        if _timestamp(self.start_at, "start_at") > _timestamp(self.cutoff_at, "cutoff_at"):
            raise ValueError("start_at must not be later than cutoff_at")

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self)}


@dataclass(frozen=True, slots=True)
class ResearchQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "research"
    query_id: str
    symbol: str
    cutoff_at: str
    topics: tuple[str, ...]
    start_at: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        cutoff = _timestamp(self.cutoff_at, "cutoff_at")
        if not isinstance(self.topics, tuple) or not self.topics or len(self.topics) > 32:
            raise ValueError("topics must contain between 1 and 32 items")
        for topic in self.topics:
            _text(topic, "topic", 128)
        if self.start_at is not None and _timestamp(self.start_at, "start_at") > cutoff:
            raise ValueError("start_at must not be later than cutoff_at")

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self), "topics": list(self.topics)}


@dataclass(frozen=True, slots=True)
class PricesQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "prices"
    query_id: str
    symbol: str
    start_time: str
    end_time: str
    interval: str

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        _window(self.start_time, self.end_time, start_path="start_time", end_path="end_time")
        _text(self.interval, "interval", 32)

    @property
    def cutoff_at(self) -> str:
        return self.end_time

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self)}


@dataclass(frozen=True, slots=True)
class IndicatorsQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "indicators"
    query_id: str
    symbol: str
    indicator: str
    start_time: str
    end_time: str
    parameters: Mapping[str, object]

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        _text(self.indicator, "indicator", 64)
        _window(self.start_time, self.end_time, start_path="start_time", end_path="end_time")
        _parameters(self.parameters)
        object.__setattr__(self, "parameters", dict(sorted(self.parameters.items())))

    @property
    def cutoff_at(self) -> str:
        return self.end_time

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self)}


@dataclass(frozen=True, slots=True)
class RegulatoryFilingsQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "regulatory_filings"
    query_id: str
    issuer: str
    jurisdiction: str
    form_types: tuple[str, ...]
    filed_after: str
    filed_before: str

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.issuer, "issuer", 64)
        _text(self.jurisdiction, "jurisdiction", 32)
        _required_string_tuple(self.form_types, "form_types", maximum=32)
        _window(self.filed_after, self.filed_before, start_path="filed_after", end_path="filed_before")

    @property
    def cutoff_at(self) -> str:
        return self.filed_before

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self), "form_types": list(self.form_types)}


@dataclass(frozen=True, slots=True)
class FundamentalsQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "fundamentals"
    query_id: str
    symbol: str
    metrics: tuple[str, ...]
    as_of: str

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        _required_string_tuple(self.metrics, "metrics", maximum=64)
        _timestamp(self.as_of, "as_of")

    @property
    def cutoff_at(self) -> str:
        return self.as_of

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self), "metrics": list(self.metrics)}


@dataclass(frozen=True, slots=True)
class FinancialStatementsQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "financial_statements"
    query_id: str
    issuer: str
    statement_types: tuple[str, ...]
    periods: tuple[str, ...]
    as_of: str

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.issuer, "issuer", 64)
        _required_string_tuple(self.statement_types, "statement_types", maximum=8)
        _required_string_tuple(self.periods, "periods", maximum=80)
        _timestamp(self.as_of, "as_of")

    @property
    def cutoff_at(self) -> str:
        return self.as_of

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "type": self.query_type,
            **asdict(self),
            "statement_types": list(self.statement_types),
            "periods": list(self.periods),
        }


@dataclass(frozen=True, slots=True)
class CompanyNewsQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "company_news"
    query_id: str
    symbol: str
    published_after: str
    published_before: str
    max_items: int

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        _window(self.published_after, self.published_before, start_path="published_after", end_path="published_before")
        _max_items(self.max_items, "max_items")

    @property
    def cutoff_at(self) -> str:
        return self.published_before

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self)}


@dataclass(frozen=True, slots=True)
class GlobalNewsQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "global_news"
    query_id: str
    topics: tuple[str, ...]
    published_after: str
    published_before: str
    max_items: int

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _required_string_tuple(self.topics, "topics", maximum=32)
        _window(self.published_after, self.published_before, start_path="published_after", end_path="published_before")
        _max_items(self.max_items, "max_items")

    @property
    def cutoff_at(self) -> str:
        return self.published_before

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self), "topics": list(self.topics)}


@dataclass(frozen=True, slots=True)
class MacroQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "macro"
    query_id: str
    series: tuple[str, ...]
    regions: tuple[str, ...]
    start_time: str
    end_time: str
    vintage_as_of: str

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _required_string_tuple(self.series, "series", maximum=32)
        _required_string_tuple(self.regions, "regions", maximum=32)
        _window(self.start_time, self.end_time, start_path="start_time", end_path="end_time")
        if _timestamp(self.end_time, "end_time") > _timestamp(self.vintage_as_of, "vintage_as_of"):
            raise ValueError("end_time must not be later than vintage_as_of")

    @property
    def cutoff_at(self) -> str:
        return self.vintage_as_of

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "type": self.query_type,
            **asdict(self),
            "series": list(self.series),
            "regions": list(self.regions),
        }


@dataclass(frozen=True, slots=True)
class StockTwitsQuery:
    version: ClassVar[str] = SOURCE_QUERY_VERSION
    query_type: ClassVar[str] = "stocktwits"
    query_id: str
    symbol: str
    start_time: str
    end_time: str
    max_items: int

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _text(self.symbol, "symbol", 32)
        _window(self.start_time, self.end_time, start_path="start_time", end_path="end_time")
        _max_items(self.max_items, "max_items", 30)
        window = _timestamp(self.end_time, "end_time") - _timestamp(self.start_time, "start_time")
        if window.total_seconds() > 7 * 24 * 60 * 60:
            raise ValueError("social query window cannot exceed 7 days")

    @property
    def cutoff_at(self) -> str:
        return self.end_time

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "type": self.query_type, **asdict(self)}


@dataclass(frozen=True, slots=True)
class RedditQuery(StockTwitsQuery):
    query_type: ClassVar[str] = "reddit"


SourceQuery: TypeAlias = (
    FilingQuery
    | FundamentalQuery
    | MarketSeriesQuery
    | ResearchQuery
    | PricesQuery
    | IndicatorsQuery
    | RegulatoryFilingsQuery
    | FundamentalsQuery
    | FinancialStatementsQuery
    | CompanyNewsQuery
    | GlobalNewsQuery
    | MacroQuery
    | StockTwitsQuery
    | RedditQuery
)
_SOURCE_QUERY_CLASSES = (
    FilingQuery,
    FundamentalQuery,
    MarketSeriesQuery,
    ResearchQuery,
    PricesQuery,
    IndicatorsQuery,
    RegulatoryFilingsQuery,
    FundamentalsQuery,
    FinancialStatementsQuery,
    CompanyNewsQuery,
    GlobalNewsQuery,
    MacroQuery,
    StockTwitsQuery,
    RedditQuery,
)
_QUERY_TYPES: dict[str, type[SourceQuery]] = {
    FilingQuery.query_type: FilingQuery,
    FundamentalQuery.query_type: FundamentalQuery,
    MarketSeriesQuery.query_type: MarketSeriesQuery,
    ResearchQuery.query_type: ResearchQuery,
    PricesQuery.query_type: PricesQuery,
    IndicatorsQuery.query_type: IndicatorsQuery,
    RegulatoryFilingsQuery.query_type: RegulatoryFilingsQuery,
    FundamentalsQuery.query_type: FundamentalsQuery,
    FinancialStatementsQuery.query_type: FinancialStatementsQuery,
    CompanyNewsQuery.query_type: CompanyNewsQuery,
    GlobalNewsQuery.query_type: GlobalNewsQuery,
    MacroQuery.query_type: MacroQuery,
    StockTwitsQuery.query_type: StockTwitsQuery,
    RedditQuery.query_type: RedditQuery,
}


def source_query_from_dict(value: object) -> SourceQuery:
    raw = _strict_object(
        value,
        {"version", "type", "query_id"}
        | {field for query_cls in _SOURCE_QUERY_CLASSES for field in query_cls.__dataclass_fields__},
        "source query",
    )
    if raw.get("version") != SOURCE_QUERY_VERSION:
        raise ValueError("unsupported source query version")
    query_type = raw.get("type")
    query_cls = _QUERY_TYPES.get(query_type) if isinstance(query_type, str) else None
    if query_cls is None:
        raise ValueError("unsupported source query type")
    allowed = set(query_cls.__dataclass_fields__)
    payload = {key: item for key, item in raw.items() if key not in {"version", "type"}}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"source query has fields invalid for {query_type}: {unknown}")
    for collection in ("form_types", "topics", "metrics", "statement_types", "periods", "series", "regions"):
        if collection in payload:
            collection_value = payload[collection]
            if collection == "periods" and isinstance(collection_value, int):
                continue
            if not isinstance(collection_value, list) or not all(isinstance(item, str) for item in collection_value):
                raise ValueError(f"source query {collection} must be an array of strings")
            payload[collection] = tuple(cast(list[str], collection_value))
    return query_cls(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SourceBatch:
    capability: str
    query: SourceQuery
    cutoff: str
    status: BatchStatus
    items: tuple[SourceObservation, ...]
    provenance: SourceProvenance
    entitlement: SourceEntitlement
    completeness: SourceCompleteness
    pagination: SourcePagination
    limitations: tuple[str, ...] = ()

    version: ClassVar[str] = SOURCE_BATCH_VERSION

    def __post_init__(self) -> None:
        _identifier(self.capability, "capability")
        if not isinstance(self.query, _SOURCE_QUERY_CLASSES):
            raise TypeError("SourceBatch.query must use a tradingagents_host query contract")
        if self.query.cutoff_at != self.cutoff:
            raise ValueError("source batch cutoff must exactly match the query cutoff")
        cutoff = _timestamp(self.cutoff, "cutoff")
        if self.status not in {"complete", "partial", "unavailable", "denied", "rate_limited", "stale"}:
            raise ValueError("source batch status is invalid")
        if not isinstance(self.items, tuple) or not all(isinstance(item, SourceObservation) for item in self.items):
            raise ValueError("source batch items must be SourceObservation records")
        object.__setattr__(
            self,
            "items",
            tuple(sorted(self.items, key=lambda item: (_timestamp(item.observed_at, "observed_at"), item.source_id))),
        )
        provenance_retrieved = _timestamp(self.provenance.retrieved_at, "provenance.retrieved_at")
        for observation in self.items:
            if (
                observation.provider != self.provenance.provider
                or observation.provider_version != self.provenance.provider_version
            ):
                raise ValueError("source observation provider must match the batch provenance")
            if observation.license_receipt_id != self.entitlement.license_receipt_id:
                raise ValueError("source observation license receipt must match the batch entitlement receipt")
            if _timestamp(observation.available_at, "available_at") > cutoff:
                raise ValueError("source observation was unavailable at the requested cutoff")
            if _timestamp(observation.retrieved_at, "retrieved_at") > provenance_retrieved:
                raise ValueError("batch provenance retrieval time cannot precede an item retrieval")
        if len({item.source_id for item in self.items}) != len(self.items):
            raise ValueError("source batch items must have unique source IDs")
        _string_tuple(self.limitations, "limitations")
        if self.pagination.returned_items != len(self.items):
            raise ValueError("pagination.returned_items must equal the number of items")
        status_complete = self.status == "complete"
        if self.completeness.complete != status_complete:
            raise ValueError("status and completeness.complete must agree")
        if not status_complete and not self.completeness.known_coverage_gaps:
            raise ValueError("non-complete source batches require known coverage gaps")
        if status_complete and self.pagination.has_more:
            raise ValueError("complete source batches cannot have more pages")
        if self.pagination.has_more and self.status != "partial":
            raise ValueError("paginated source batches must have partial status")
        if not status_complete and not self.limitations:
            raise ValueError("non-complete source batches require limitations")
        if self.status in {"unavailable", "denied", "rate_limited"} and self.items:
            raise ValueError(f"{self.status} source batches cannot contain items")
        if self.status in {"partial", "stale"} and not self.items:
            raise ValueError(f"{self.status} source batches require at least one item")
        if self.status == "denied" and self.entitlement.access != "denied":
            raise ValueError("denied source batches require denied entitlement")
        if self.entitlement.access == "denied" and self.status != "denied":
            raise ValueError("denied entitlement requires denied batch status")
        if self.status == "complete" and self.entitlement.access != "allowed":
            raise ValueError("complete source batches require allowed entitlement")
        if self.entitlement.redistributable is not True and any(
            item.bounded_extract is not None for item in self.items
        ):
            raise ValueError("non-redistributable or unknown entitlement cannot include extracts")

    @property
    def query_id(self) -> str:
        return self.query.query_id

    @property
    def cutoff_at(self) -> str:
        return self.cutoff

    @property
    def observations(self) -> tuple[SourceObservation, ...]:
        return self.items

    @property
    def complete(self) -> bool:
        return self.completeness.complete

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "capability": self.capability,
            "query": self.query.to_dict(),
            "cutoff": self.cutoff,
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
            "provenance": self.provenance.to_dict(),
            "entitlement": self.entitlement.to_dict(),
            "completeness": self.completeness.to_dict(),
            "pagination": self.pagination.to_dict(),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceBatch:
        fields = {
            "version",
            "capability",
            "query",
            "cutoff",
            "status",
            "items",
            "provenance",
            "entitlement",
            "completeness",
            "pagination",
            "limitations",
        }
        raw = _strict_object(value, fields, "source batch")
        if raw.get("version") != SOURCE_BATCH_VERSION:
            raise ValueError("unsupported SourceBatch version")
        missing = sorted((fields - {"version"}) - set(raw))
        if missing:
            raise ValueError(f"source batch is missing required fields: {missing}")
        items = raw["items"]
        limitations = raw["limitations"]
        if not isinstance(items, list):
            raise ValueError("source batch items must be an array")
        if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
            raise ValueError("source batch limitations must be an array of strings")
        provenance = _strict_object(raw["provenance"], set(SourceProvenance.__dataclass_fields__), "provenance")
        entitlement = _strict_object(raw["entitlement"], set(SourceEntitlement.__dataclass_fields__), "entitlement")
        completeness = _strict_object(raw["completeness"], set(SourceCompleteness.__dataclass_fields__), "completeness")
        pagination = _strict_object(raw["pagination"], set(SourcePagination.__dataclass_fields__), "pagination")
        gaps = completeness.get("known_coverage_gaps")
        if not isinstance(gaps, list) or not all(isinstance(item, str) for item in gaps):
            raise ValueError("completeness.known_coverage_gaps must be an array of strings")
        return cls(
            capability=cast(str, raw["capability"]),
            query=source_query_from_dict(raw["query"]),
            cutoff=cast(str, raw["cutoff"]),
            status=cast(BatchStatus, raw["status"]),
            items=tuple(SourceObservation.from_dict(item) for item in items),
            provenance=SourceProvenance(**provenance),  # type: ignore[arg-type]
            entitlement=SourceEntitlement(**entitlement),  # type: ignore[arg-type]
            completeness=SourceCompleteness(  # type: ignore[arg-type]
                complete=cast(bool, completeness.get("complete")), known_coverage_gaps=tuple(gaps)
            ),
            pagination=SourcePagination(**pagination),  # type: ignore[arg-type]
            limitations=tuple(limitations),
        )


def validate_source_response(capability: str, query: SourceQuery, batch: SourceBatch) -> SourceBatch:
    """Validate the invariant every source-port implementation must satisfy."""

    if not isinstance(query, _SOURCE_QUERY_CLASSES):
        raise TypeError("source queries must use a tradingagents_host query contract")
    if not isinstance(batch, SourceBatch):
        raise TypeError("source adapters must return a SourceBatch")
    if batch.capability != capability:
        raise ValueError("source adapter returned a batch for a different capability")
    if batch.query != query:
        raise ValueError("source adapter returned a batch for a different query")
    if batch.cutoff != query.cutoff_at:
        raise ValueError("source adapter returned a batch for a different cutoff")
    return batch
