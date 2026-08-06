"""Strict, versioned contracts for evidence-first company research.

The StockResearchAgents boundary accepts bounded facts, extracts, references, and deterministic
calculation receipts. It intentionally rejects credentials, execution instructions,
and bulk source content before constructing any model.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import MISSING, asdict, dataclass, fields
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import UnionType
from typing import Any, ClassVar, Literal, TypeVar, Union, cast, get_args, get_origin, get_type_hints
from urllib.parse import parse_qsl, urlsplit

RESEARCH_SCHEMA_VERSION = "company-research.v1"
COMPANY_RESEARCH_WORKFLOW_ID = "stockresearchagents.company-research.v1"
WORKFLOW_DIRECTORY = Path(__file__).resolve().parent / "workflow"
COMPANY_RESEARCH_V2_PATH = WORKFLOW_DIRECTORY / "company-research.v1.json"
COMPANY_RESEARCH_SUBMISSION_V1_SCHEMA_PATH = WORKFLOW_DIRECTORY / "company-research-submission.v1.schema.json"
MAX_DOSSIER_BYTES = 1_000_000
MAX_DOCUMENTS = 256
MAX_COLLECTION_ITEMS = 512

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_TIMESTAMP_OFFSET_PATTERN = re.compile(r"T.*(?:Z|[+-][0-9]{2}:[0-9]{2})$")
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "authorization_header",
    "bearer",
    "cookie",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
}
_SENSITIVE_URI_PARAMETER_KEYS = {
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
_EXECUTION_KEYS = {
    "broker",
    "broker_account",
    "broker_order",
    "execution_authority",
    "order",
    "order_id",
    "order_payload",
    "submitted",
    "trade_execution",
}
_RAW_CONTENT_KEYS = {
    "body_html",
    "full_text",
    "raw_content",
    "raw_document",
    "raw_filing",
    "raw_html",
    "raw_transcript",
    "source_blob",
}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)


def _utc_timestamp(value: str, path: str) -> datetime:
    if not isinstance(value, str) or not value or _TIMESTAMP_OFFSET_PATTERN.search(value) is None:
        raise ValueError(f"{path} must be an exact timezone-aware date-time")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{path} must be an exact timezone-aware date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{path} must include a timezone offset")
    return parsed


def _validate_id(value: str, path: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"{path} must be a bounded stable identifier")


def _bounded_text(value: str, path: str, limit: int = 8_000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{path} must be non-empty and at most {limit} characters")


def _bounded_tuple(value: tuple[Any, ...], path: str, limit: int = MAX_COLLECTION_ITEMS) -> None:
    if len(value) > limit:
        raise ValueError(f"{path} exceeds the {limit}-item bound")


def _reject_forbidden_material(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            location = ".".join((*path, str(raw_key)))
            if key in _SECRET_KEYS or any(part in _SECRET_KEYS for part in key.split("_")):
                raise ValueError(f"credential material is forbidden: {location}")
            if key in _EXECUTION_KEYS:
                raise ValueError(f"execution material is forbidden: {location}")
            if key in _RAW_CONTENT_KEYS:
                raise ValueError(f"raw source content is forbidden: {location}")
            _reject_forbidden_material(nested, (*path, str(raw_key)))
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _reject_forbidden_material(nested, (*path, str(index)))
    elif isinstance(value, str):
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"credential material is forbidden: {'.'.join(path)}")


T = TypeVar("T", bound="StrictModel")


class StrictModel:
    """Dataclass mixin with unknown-field rejection and JSON-safe serialization."""

    @classmethod
    def from_dict(cls: type[T], value: object) -> T:
        _reject_forbidden_material(value)
        return _decode_model(cls, value, cls.__name__)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(cast(Any, self))
        _reject_forbidden_material(payload)
        return payload


def _decode_model(cls: type[T], value: object, path: str) -> T:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    model_fields = {item.name: item for item in fields(cast(Any, cls))}
    unknown = sorted(set(value) - set(model_fields))
    if unknown:
        raise ValueError(f"{path} has unknown fields: {unknown}")
    hints = get_type_hints(cls)
    decoded: dict[str, Any] = {}
    for name, model_field in model_fields.items():
        if name not in value:
            if model_field.default is not MISSING or model_field.default_factory is not MISSING:
                continue
            raise ValueError(f"{path}.{name} is required")
        decoded[name] = _decode_value(hints[name], value[name], f"{path}.{name}")
    return cls(**decoded)


def _decode_value(expected: Any, value: object, path: str) -> Any:
    origin = get_origin(expected)
    args = get_args(expected)
    if origin is Literal:
        if value not in args:
            raise ValueError(f"{path} must be one of {list(args)!r}")
        return value
    if origin is tuple:
        if not isinstance(value, list | tuple):
            raise ValueError(f"{path} must be an array")
        item_type = args[0]
        decoded = tuple(_decode_value(item_type, item, f"{path}[{index}]") for index, item in enumerate(value))
        _bounded_tuple(decoded, path)
        field_name = path.rsplit(".", 1)[-1]
        if field_name.endswith("_ids"):
            if len(set(decoded)) != len(decoded):
                raise ValueError(f"{path} must contain unique identifiers")
            for index, identifier in enumerate(decoded):
                _validate_id(identifier, f"{path}[{index}]")
        return decoded
    if origin in {Union, UnionType}:
        if value is None and type(None) in args:
            return None
        failures: list[str] = []
        for candidate in args:
            if candidate is type(None):
                continue
            try:
                return _decode_value(candidate, value, path)
            except ValueError as exc:
                failures.append(str(exc))
        raise ValueError(f"{path} does not match its declared type: {'; '.join(failures)}")
    if isinstance(expected, type) and issubclass(expected, StrictModel):
        return _decode_model(expected, value, path)
    if expected is float:
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
            raise ValueError(f"{path} must be a finite number")
        return float(value)
    if expected is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} must be an integer")
        return value
    if expected is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be a boolean")
        return value
    if expected is str:
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        return value
    raise TypeError(f"unsupported contract type at {path}: {expected!r}")


@dataclass(frozen=True, slots=True)
class ResearchIdentity(StrictModel):
    instrument_id: str
    symbol: str
    issuer_name: str
    asset_type: Literal["equity", "fund", "crypto"]
    exchange: str | None
    currency: str
    country: str | None
    cik: str | None

    def __post_init__(self) -> None:
        _validate_id(self.instrument_id, "identity.instrument_id")
        _bounded_text(self.symbol, "identity.symbol", 32)
        if not re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9._^=/\-]{0,31}", self.symbol):
            raise ValueError("identity.symbol must be a bounded ASCII market identifier")
        _bounded_text(self.issuer_name, "identity.issuer_name", 256)
        _bounded_text(self.currency, "identity.currency", 32)
        if self.cik is not None and not re.fullmatch(r"\d{10}", self.cik):
            raise ValueError("identity.cik must contain exactly 10 digits")


@dataclass(frozen=True, slots=True)
class TemporalProvenance(StrictModel):
    observed_at: str
    published_at: str
    available_at: str
    retrieved_at: str
    cutoff_at: str

    def __post_init__(self) -> None:
        observed = _utc_timestamp(self.observed_at, "temporal.observed_at")
        published = _utc_timestamp(self.published_at, "temporal.published_at")
        available = _utc_timestamp(self.available_at, "temporal.available_at")
        retrieved = _utc_timestamp(self.retrieved_at, "temporal.retrieved_at")
        cutoff = _utc_timestamp(self.cutoff_at, "temporal.cutoff_at")
        if observed > published or published > available:
            raise ValueError("temporal timestamps must satisfy observed_at <= published_at <= available_at")
        if available > cutoff or retrieved < available:
            raise ValueError("source must be available by cutoff and retrieved no earlier than availability")


@dataclass(frozen=True, slots=True)
class SourceEntitlement(StrictModel):
    access: Literal["public", "licensed", "entitlement_blocked"]
    redistributable: bool
    terms_uri: str | None
    limitation: str | None

    def __post_init__(self) -> None:
        if self.access == "entitlement_blocked" and self.redistributable:
            raise ValueError("blocked sources cannot be redistributable")
        if self.access == "entitlement_blocked" and not self.limitation:
            raise ValueError("blocked sources require an entitlement limitation")
        if self.terms_uri is not None:
            _validate_public_uri(self.terms_uri, "entitlement.terms_uri")


@dataclass(frozen=True, slots=True)
class SourceLocator(StrictModel):
    canonical_uri: str
    document_id: str | None
    accession_number: str | None
    content_sha256: str

    def __post_init__(self) -> None:
        _validate_public_uri(self.canonical_uri, "locator.canonical_uri")
        if not _SHA256_PATTERN.fullmatch(self.content_sha256):
            raise ValueError("locator.content_sha256 must be a lowercase SHA-256 digest")


def _validate_public_uri(value: str, path: str) -> None:
    _bounded_text(value, path, 2_048)
    parsed = urlsplit(value)
    if (
        not value.startswith("https://")
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"{path} must be a credential-free https URI")
    parameter_keys = [key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)] + [
        key for key, _ in parse_qsl(parsed.fragment, keep_blank_values=True)
    ]

    def credential_shaped(key: str) -> bool:
        normalized = key.strip().lower().replace("-", "_")
        parts = normalized.split("_")
        return (
            normalized in _SECRET_KEYS
            or normalized in _SENSITIVE_URI_PARAMETER_KEYS
            or any(part in _SECRET_KEYS for part in parts)
            or normalized.startswith(("x_amz_", "x_goog_"))
        )

    sensitive = any(credential_shaped(key) for key in parameter_keys)
    if sensitive:
        raise ValueError(f"{path} contains credential-shaped query parameters")


@dataclass(frozen=True, slots=True)
class SourceDocument(StrictModel):
    id: str
    kind: Literal["filing", "earnings_release", "transcript", "company", "regulatory", "market", "news", "other"]
    title: str
    publisher: str
    locator: SourceLocator
    entitlement: SourceEntitlement
    temporal: TemporalProvenance
    extract: str | None

    def __post_init__(self) -> None:
        _validate_id(self.id, "document.id")
        _bounded_text(self.title, "document.title", 512)
        _bounded_text(self.publisher, "document.publisher", 256)
        if self.extract is not None and (not self.extract.strip() or len(self.extract) > 2_000):
            raise ValueError("document.extract must be a non-empty extract of at most 2000 characters")
        if not self.entitlement.redistributable and self.extract is not None:
            raise ValueError("non-redistributable documents cannot include extracts")


@dataclass(frozen=True, slots=True)
class CalculationConstant(StrictModel):
    name: str
    value: float

    def __post_init__(self) -> None:
        _validate_id(self.name, "calculation_constant.name")


@dataclass(frozen=True, slots=True)
class CalculationLineage(StrictModel):
    id: str
    formula: str
    operation: Literal["add", "subtract", "multiply", "divide", "sum", "average", "identity", "discounted_cash_flow"]
    input_metric_ids: tuple[str, ...]
    constants: tuple[CalculationConstant, ...]
    result: float
    unit: str
    engine: str
    rounding_digits: int | None
    tolerance: float
    deterministic: Literal[True]

    def __post_init__(self) -> None:
        _validate_id(self.id, "calculation.id")
        _bounded_text(self.formula, "calculation.formula", 2_000)
        if not self.input_metric_ids:
            raise ValueError("calculation.input_metric_ids cannot be empty")
        if len(set(self.input_metric_ids)) != len(self.input_metric_ids):
            raise ValueError("calculation.input_metric_ids must be unique")
        if len({item.name for item in self.constants}) != len(self.constants):
            raise ValueError("calculation constant names must be unique")
        _bounded_tuple(self.constants, "calculation.constants", 64)
        minimum_inputs = {"identity": 1, "subtract": 2, "divide": 2, "add": 2, "multiply": 2}
        if self.operation in minimum_inputs and len(self.input_metric_ids) != minimum_inputs[self.operation]:
            raise ValueError(
                f"calculation operation {self.operation!r} requires exactly {minimum_inputs[self.operation]} inputs"
            )
        if self.operation in {"sum", "average", "discounted_cash_flow"} and not self.input_metric_ids:
            raise ValueError(f"calculation operation {self.operation!r} requires inputs")
        if self.rounding_digits is not None and not 0 <= self.rounding_digits <= 12:
            raise ValueError("calculation.rounding_digits must be between 0 and 12")
        if not 0 <= self.tolerance <= 1:
            raise ValueError("calculation.tolerance must be between 0 and 1")
        _bounded_text(self.engine, "calculation.engine", 128)


@dataclass(frozen=True, slots=True)
class Metric(StrictModel):
    id: str
    label: str
    value: float
    unit: str
    period_start: str | None
    period_end: str
    as_of_at: str
    basis: Literal["reported", "calculated", "estimated", "assumption"]
    source_document_ids: tuple[str, ...]
    calculation_id: str | None

    def __post_init__(self) -> None:
        _validate_id(self.id, "metric.id")
        _bounded_text(self.label, "metric.label")
        period_end = _utc_timestamp(self.period_end, "metric.period_end")
        as_of = _utc_timestamp(self.as_of_at, "metric.as_of_at")
        if self.period_start is not None and _utc_timestamp(self.period_start, "metric.period_start") > _utc_timestamp(
            self.period_end, "metric.period_end"
        ):
            raise ValueError("metric.period_start cannot follow period_end")
        if self.basis == "reported" and period_end > as_of:
            raise ValueError("reported metric.period_end cannot follow metric.as_of_at")
        if self.basis == "calculated" and self.calculation_id is None:
            raise ValueError("calculated metrics require calculation_id")
        if self.basis != "calculated" and self.calculation_id is not None:
            raise ValueError("only calculated metrics may reference calculation_id")
        if not self.source_document_ids and self.basis != "assumption":
            raise ValueError("non-assumption metrics require source documents")


@dataclass(frozen=True, slots=True)
class Claim(StrictModel):
    id: str
    statement: str
    kind: Literal["fact", "guidance", "estimate", "inference", "thesis"]
    stance: Literal["bull", "bear", "neutral"]
    evidence_document_ids: tuple[str, ...]
    metric_ids: tuple[str, ...]
    counterevidence_document_ids: tuple[str, ...]
    counterclaim_ids: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        _validate_id(self.id, "claim.id")
        _bounded_text(self.statement, "claim.statement")
        if not 0 <= self.confidence <= 1:
            raise ValueError("claim.confidence must be between 0 and 1")
        if not self.evidence_document_ids and not self.metric_ids:
            raise ValueError("every claim requires retained evidence")


@dataclass(frozen=True, slots=True)
class ArgumentTurn(StrictModel):
    argument_id: str
    debate: Literal["research", "risk"]
    round: int
    turn: int
    role: str
    claim_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    rebuttal_of: str | None
    concessions: tuple[str, ...]
    unresolved: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.argument_id, "argument.argument_id")
        if self.round < 1 or self.turn < 1:
            raise ValueError("argument round and turn must be positive")
        _bounded_text(self.role, "argument.role", 128)
        if not self.claim_ids:
            raise ValueError("arguments require claim_ids")

    @property
    def id(self) -> str:
        return self.argument_id


@dataclass(frozen=True, slots=True)
class FilingRecord(StrictModel):
    id: str
    form: str
    accession_number: str
    filed_at: str
    period_end: str
    document_id: str
    amendment: bool

    def __post_init__(self) -> None:
        _validate_id(self.id, "filing.id")
        _utc_timestamp(self.filed_at, "filing.filed_at")
        _utc_timestamp(self.period_end, "filing.period_end")


@dataclass(frozen=True, slots=True)
class FilingChange(StrictModel):
    id: str
    prior_document_id: str | None
    current_document_id: str
    change_kind: Literal["narrative", "table", "risk", "mda", "accounting"]
    summary: str
    metric_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "filing_change.id")
        _bounded_text(self.summary, "filing_change.summary", 4_000)
        if not self.metric_ids and not self.claim_ids:
            raise ValueError("filing changes require metric_ids or claim_ids")


@dataclass(frozen=True, slots=True)
class TranscriptSegment(StrictModel):
    id: str
    section: Literal["prepared", "qa"]
    speaker: str
    extract: str
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "transcript_segment.id")
        _bounded_text(self.speaker, "transcript_segment.speaker", 256)
        _bounded_text(self.extract, "transcript_segment.extract", 2_000)


@dataclass(frozen=True, slots=True)
class TranscriptTheme(StrictModel):
    id: str
    title: str
    segment_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "transcript_theme.id")
        if not self.segment_ids:
            raise ValueError("transcript themes require segment_ids")


@dataclass(frozen=True, slots=True)
class TranscriptRecord(StrictModel):
    id: str
    event_at: str
    document_id: str
    speaker_summary: str
    guidance_claim_ids: tuple[str, ...]
    segments: tuple[TranscriptSegment, ...]
    themes: tuple[TranscriptTheme, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "transcript.id")
        _utc_timestamp(self.event_at, "transcript.event_at")
        _bounded_text(self.speaker_summary, "transcript.speaker_summary", 4_000)
        segment_ids = {item.id for item in self.segments}
        if len(segment_ids) != len(self.segments):
            raise ValueError("transcript segment IDs must be unique")
        if len({item.id for item in self.themes}) != len(self.themes):
            raise ValueError("transcript theme IDs must be unique")
        for theme in self.themes:
            if missing := set(theme.segment_ids) - segment_ids:
                raise ValueError(f"transcript theme {theme.id!r} references unknown segments: {sorted(missing)}")


@dataclass(frozen=True, slots=True)
class GuidanceRecord(StrictModel):
    id: str
    metric: str
    period: str
    low: float | None
    high: float | None
    unit: str
    status: Literal["introduced", "reaffirmed", "raised", "lowered", "withdrawn", "superseded"]
    claim_id: str

    def __post_init__(self) -> None:
        _validate_id(self.id, "guidance.id")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("guidance.low cannot exceed guidance.high")


@dataclass(frozen=True, slots=True)
class PeerComparison(StrictModel):
    id: str
    peer_instrument_id: str
    rationale: str
    methodology: str
    metric_ids: tuple[str, ...]
    evidence_document_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "peer.id")
        _validate_id(self.peer_instrument_id, "peer.peer_instrument_id")
        _bounded_text(self.methodology, "peer.methodology", 2_000)
        if not self.metric_ids or not self.evidence_document_ids:
            raise ValueError("peer comparisons require metrics and evidence")


@dataclass(frozen=True, slots=True)
class FactorSnapshot(StrictModel):
    id: str
    factor: str
    direction: Literal["positive", "negative", "mixed", "neutral"]
    magnitude: Literal["low", "moderate", "high", "unknown"]
    value: float | None
    unit: str | None
    methodology: str
    methodology_version: str
    as_of_at: str
    prior_snapshot_id: str | None
    delta: float | None
    history_document_ids: tuple[str, ...]
    evidence_document_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "factor.id")
        _utc_timestamp(self.as_of_at, "factor.as_of_at")
        _bounded_text(self.methodology, "factor.methodology", 2_000)
        _bounded_text(self.methodology_version, "factor.methodology_version", 128)
        if not self.evidence_document_ids:
            raise ValueError("factor snapshots require evidence")


@dataclass(frozen=True, slots=True)
class ValuationAssumption(StrictModel):
    id: str
    label: str
    value: float
    unit: str
    metric_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "valuation_assumption.id")
        if not self.metric_ids and not self.claim_ids:
            raise ValueError("valuation assumptions require metric_ids or claim_ids")


@dataclass(frozen=True, slots=True)
class ValuationSensitivityCell(StrictModel):
    id: str
    row_assumption_id: str
    column_assumption_id: str
    fair_value: float
    calculation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "valuation_sensitivity.id")
        if not self.calculation_ids:
            raise ValueError("valuation sensitivity cells require calculation_ids")


@dataclass(frozen=True, slots=True)
class ValuationCase(StrictModel):
    id: str
    name: Literal["bear", "base", "bull"]
    methodology: str
    currency: str
    fair_value: float
    horizon: str
    input_metric_ids: tuple[str, ...]
    calculation_ids: tuple[str, ...]
    assumption_claim_ids: tuple[str, ...]
    assumptions: tuple[ValuationAssumption, ...]
    sensitivity_cells: tuple[ValuationSensitivityCell, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "valuation.id")
        if not self.input_metric_ids or not self.calculation_ids:
            raise ValueError("valuation cases require metric inputs and reproducible calculations")
        assumption_ids = {item.id for item in self.assumptions}
        if len(assumption_ids) != len(self.assumptions):
            raise ValueError("valuation assumption IDs must be unique")
        for cell in self.sensitivity_cells:
            if {cell.row_assumption_id, cell.column_assumption_id} - assumption_ids:
                raise ValueError(f"valuation sensitivity {cell.id!r} references unknown assumptions")


@dataclass(frozen=True, slots=True)
class ResearchEntity(StrictModel):
    id: str
    name: str
    kind: Literal["issuer", "peer", "customer", "supplier", "partner", "regulator", "market", "other"]

    def __post_init__(self) -> None:
        _validate_id(self.id, "entity.id")
        _bounded_text(self.name, "entity.name", 256)


@dataclass(frozen=True, slots=True)
class ResearchEvent(StrictModel):
    id: str
    occurred_at: str
    title: str
    status: Literal["historical", "active", "scheduled", "cancelled"]
    evidence_document_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    ripple_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "event.id")
        _utc_timestamp(self.occurred_at, "event.occurred_at")
        if not self.evidence_document_ids:
            raise ValueError("events require evidence")


@dataclass(frozen=True, slots=True)
class RiskScenario(StrictModel):
    id: str
    name: str
    probability: float | None
    impact: Literal["low", "moderate", "high", "severe", "unknown"]
    thesis: str
    evidence_document_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    trigger_metric_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "risk.id")
        if self.probability is not None and not 0 <= self.probability <= 1:
            raise ValueError("risk.probability must be between 0 and 1")
        if not self.evidence_document_ids:
            raise ValueError("risk scenarios require evidence")


@dataclass(frozen=True, slots=True)
class MonitoringCondition(StrictModel):
    id: str
    description: str
    cadence: str
    trigger: str
    consequence: str
    related_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "monitoring.id")
        if not self.related_ids:
            raise ValueError("monitoring conditions require related research IDs")


@dataclass(frozen=True, slots=True)
class PriorOutcome(StrictModel):
    id: str
    forecast_claim_id: str
    forecast_at: str
    evaluated_at: str
    result: Literal["confirmed", "partially_confirmed", "disconfirmed", "unresolved"]
    outcome_document_ids: tuple[str, ...]
    calibration_score: float | None
    notes: str

    def __post_init__(self) -> None:
        _validate_id(self.id, "prior_outcome.id")
        if _utc_timestamp(self.forecast_at, "prior_outcome.forecast_at") > _utc_timestamp(
            self.evaluated_at, "prior_outcome.evaluated_at"
        ):
            raise ValueError("prior outcome cannot be evaluated before its forecast")
        if self.calibration_score is not None and not 0 <= self.calibration_score <= 1:
            raise ValueError("prior_outcome.calibration_score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PortfolioImpactAnalysis(StrictModel):
    thesis: str
    issuer_exposure_delta_percent: float | None
    sector_exposure_delta_percent: float | None
    diversification_effect: Literal["improves", "reduces", "neutral", "unknown"]
    risk_contribution: Literal["lower", "similar", "higher", "unknown"]
    metric_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    non_executable: Literal[True]

    def __post_init__(self) -> None:
        for value in (self.issuer_exposure_delta_percent, self.sector_exposure_delta_percent):
            if value is not None and not -100 <= value <= 100:
                raise ValueError("portfolio impact deltas must be between -100 and 100 percent")


@dataclass(frozen=True, slots=True)
class EvaluationCheck(StrictModel):
    id: str
    status: Literal["pass", "fail", "skipped", "unverified", "not_applicable"]
    rubric: str
    evaluator: str
    evaluated_at: str
    document_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    calculation_ids: tuple[str, ...]
    notes: str

    def __post_init__(self) -> None:
        _validate_id(self.id, "evaluation_check.id")
        _utc_timestamp(self.evaluated_at, "evaluation_check.evaluated_at")
        _bounded_text(self.rubric, "evaluation_check.rubric", 2_000)
        _bounded_text(self.evaluator, "evaluation_check.evaluator", 256)


@dataclass(frozen=True, slots=True)
class EvaluationReceipt(StrictModel):
    evaluator: str
    evaluator_provenance: str
    rubric_version: str
    checks: tuple[EvaluationCheck, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _bounded_text(self.evaluator, "evaluation.evaluator", 256)
        _bounded_text(self.evaluator_provenance, "evaluation.evaluator_provenance", 2_000)
        _bounded_text(self.rubric_version, "evaluation.rubric_version", 128)
        if not self.checks or len({item.id for item in self.checks}) != len(self.checks):
            raise ValueError("evaluation checks must be non-empty with unique IDs")


@dataclass(frozen=True, slots=True)
class ResearchDelta(StrictModel):
    previous_dossier_sha256: str | None
    added_document_ids: tuple[str, ...]
    changed_claim_ids: tuple[str, ...]
    changed_valuation_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if self.previous_dossier_sha256 is not None and not _SHA256_PATTERN.fullmatch(self.previous_dossier_sha256):
            raise ValueError("research_delta.previous_dossier_sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class SanitizedPortfolioContext(StrictModel):
    objective: str
    horizon: str
    risk_tolerance: Literal["low", "moderate", "high", "unspecified"]
    sector_exposure_percent: float | None
    issuer_exposure_percent: float | None
    constraints: tuple[str, ...]
    non_executable: Literal[True]

    def __post_init__(self) -> None:
        _bounded_text(self.objective, "portfolio_context.objective")
        _bounded_text(self.horizon, "portfolio_context.horizon")
        for value in (self.sector_exposure_percent, self.issuer_exposure_percent):
            if value is not None and not 0 <= value <= 100:
                raise ValueError("portfolio exposure percentages must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class CoverageItem(StrictModel):
    area: str
    status: Literal["complete", "partial", "missing", "stale", "conflicting", "entitlement_blocked", "not_applicable"]
    source_document_ids: tuple[str, ...]
    limitation: str | None

    def __post_init__(self) -> None:
        _bounded_text(self.area, "coverage.area", 128)
        if self.status != "complete" and not self.limitation:
            raise ValueError("non-complete coverage requires an explicit limitation")
        if self.status == "complete" and not self.source_document_ids:
            raise ValueError("complete coverage requires retained source documents")


@dataclass(frozen=True, slots=True)
class ResearchObjective(StrictModel):
    id: str
    question: str
    decision_relevance: str
    required_claim_kinds: tuple[Literal["fact", "guidance", "estimate", "inference", "thesis"], ...]

    def __post_init__(self) -> None:
        _validate_id(self.id, "objective.id")
        _bounded_text(self.question, "objective.question", 2_000)
        _bounded_text(self.decision_relevance, "objective.decision_relevance", 2_000)
        if not self.required_claim_kinds:
            raise ValueError("objective.required_claim_kinds cannot be empty")
        if len(set(self.required_claim_kinds)) != len(self.required_claim_kinds):
            raise ValueError("objective.required_claim_kinds must be unique")


@dataclass(frozen=True, slots=True)
class CoverageDimension(StrictModel):
    area: str
    required: bool
    minimum_source_count: int
    preferred_source_kinds: tuple[
        Literal["filing", "earnings_release", "transcript", "company", "regulatory", "market", "news", "other"], ...
    ]
    entitlement_policy: Literal["public_only", "caller_entitled_allowed"]

    def __post_init__(self) -> None:
        _bounded_text(self.area, "coverage_dimension.area", 128)
        if not 0 <= self.minimum_source_count <= MAX_DOCUMENTS:
            raise ValueError(f"coverage_dimension.minimum_source_count must be between 0 and {MAX_DOCUMENTS}")
        if len(set(self.preferred_source_kinds)) != len(self.preferred_source_kinds):
            raise ValueError("coverage_dimension.preferred_source_kinds must be unique")


@dataclass(frozen=True, slots=True)
class PlannedHistoryWindow(StrictModel):
    area: str
    start_at: str
    end_at: str
    minimum_periods: int
    expansion_reasons: tuple[str, ...]
    latest_data_checks: tuple[str, ...]
    stop_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        start = _utc_timestamp(self.start_at, "history_window.start_at")
        end = _utc_timestamp(self.end_at, "history_window.end_at")
        if start > end:
            raise ValueError("history_window.start_at cannot follow end_at")
        if not 1 <= self.minimum_periods <= 120:
            raise ValueError("history_window.minimum_periods must be between 1 and 120")
        if not self.expansion_reasons or not self.latest_data_checks or not self.stop_conditions:
            raise ValueError("history windows require expansion reasons, latest-data checks, and stop conditions")
        for field_name, values in (
            ("expansion_reasons", self.expansion_reasons),
            ("latest_data_checks", self.latest_data_checks),
            ("stop_conditions", self.stop_conditions),
        ):
            for index, item in enumerate(values):
                _bounded_text(item, f"history_window.{field_name}[{index}]")


@dataclass(frozen=True, slots=True)
class ResearchPlan(StrictModel):
    objectives: tuple[ResearchObjective, ...]
    coverage_dimensions: tuple[CoverageDimension, ...]
    history_windows: tuple[PlannedHistoryWindow, ...]
    latest_data_checks: tuple[str, ...]
    stop_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.objectives or not self.coverage_dimensions or not self.history_windows:
            raise ValueError("research plan requires objectives, coverage dimensions, and history windows")
        _bounded_tuple(self.objectives, "research_plan.objectives", 64)
        _bounded_tuple(self.coverage_dimensions, "research_plan.coverage_dimensions", 64)
        _bounded_tuple(self.history_windows, "research_plan.history_windows", 64)
        if len({item.id for item in self.objectives}) != len(self.objectives):
            raise ValueError("research objective IDs must be unique")
        areas = [item.area for item in self.coverage_dimensions]
        if len(set(areas)) != len(areas):
            raise ValueError("research plan coverage dimensions must be unique")
        window_areas = {item.area for item in self.history_windows}
        if not window_areas.issubset(set(areas)):
            raise ValueError("history windows must reference declared coverage dimensions")
        if not self.latest_data_checks or not self.stop_conditions:
            raise ValueError("research plan requires global latest-data checks and stop conditions")
        for field_name, values in (
            ("latest_data_checks", self.latest_data_checks),
            ("stop_conditions", self.stop_conditions),
        ):
            for index, item in enumerate(values):
                _bounded_text(item, f"research_plan.{field_name}[{index}]")


@dataclass(frozen=True, slots=True)
class CompanyResearchRequest(StrictModel):
    schema_version: Literal["company-research.v1"]
    request_id: str
    requested_at: str
    cutoff_at: str
    research_mode: Literal["live", "fixture", "historical_replay"]
    identity: ResearchIdentity
    research_plan: ResearchPlan
    output_language: str
    portfolio_context: SanitizedPortfolioContext | None
    non_executable: Literal[True]

    def __post_init__(self) -> None:
        _validate_id(self.request_id, "request.request_id")
        requested = _utc_timestamp(self.requested_at, "request.requested_at")
        cutoff = _utc_timestamp(self.cutoff_at, "request.cutoff_at")
        if cutoff > requested:
            raise ValueError("request.cutoff_at cannot follow requested_at")
        for window in self.research_plan.history_windows:
            if _utc_timestamp(window.end_at, f"request.history_windows.{window.area}.end_at") > cutoff:
                raise ValueError(f"history window {window.area!r} extends beyond request.cutoff_at")
        _bounded_text(self.output_language, "request.output_language", 64)


@dataclass(frozen=True, slots=True)
class ResearchDossierV1(StrictModel):
    schema_version: Literal["company-research.v1"]
    dossier_id: str
    status: Literal["completed"]
    as_of_at: str
    completed_at: str
    identity: ResearchIdentity
    documents: tuple[SourceDocument, ...]
    calculations: tuple[CalculationLineage, ...]
    metrics: tuple[Metric, ...]
    claims: tuple[Claim, ...]
    arguments: tuple[ArgumentTurn, ...]
    filings: tuple[FilingRecord, ...]
    filing_changes: tuple[FilingChange, ...]
    transcripts: tuple[TranscriptRecord, ...]
    guidance: tuple[GuidanceRecord, ...]
    peers: tuple[PeerComparison, ...]
    factors: tuple[FactorSnapshot, ...]
    valuations: tuple[ValuationCase, ...]
    entities: tuple[ResearchEntity, ...]
    events: tuple[ResearchEvent, ...]
    risks: tuple[RiskScenario, ...]
    monitoring: tuple[MonitoringCondition, ...]
    prior_outcomes: tuple[PriorOutcome, ...]
    evaluation: EvaluationReceipt
    research_delta: ResearchDelta | None
    portfolio_context: SanitizedPortfolioContext | None
    portfolio_impact: PortfolioImpactAnalysis | None
    coverage: tuple[CoverageItem, ...]
    recommendation: Literal["buy", "overweight", "hold", "underweight", "sell"]
    executive_summary: str
    limitations: tuple[str, ...]
    _REFERENCE_GROUPS: ClassVar[tuple[str, ...]] = (
        "documents",
        "calculations",
        "metrics",
        "claims",
        "arguments",
        "filings",
        "filing_changes",
        "transcripts",
        "guidance",
        "peers",
        "factors",
        "valuations",
        "entities",
        "events",
        "risks",
        "monitoring",
        "prior_outcomes",
    )

    def __post_init__(self) -> None:
        _validate_id(self.dossier_id, "dossier_id")
        cutoff = _utc_timestamp(self.as_of_at, "as_of_at")
        completed = _utc_timestamp(self.completed_at, "completed_at")
        if completed < cutoff:
            raise ValueError("completed_at cannot precede as_of_at")
        for document in self.documents:
            if _utc_timestamp(document.temporal.retrieved_at, f"documents.{document.id}.retrieved_at") > completed:
                raise ValueError(f"document {document.id!r} was retrieved after dossier completion")
        for check in self.evaluation.checks:
            if _utc_timestamp(check.evaluated_at, f"evaluation.{check.id}.evaluated_at") > completed:
                raise ValueError(f"evaluation check {check.id!r} occurred after dossier completion")
        _bounded_text(self.executive_summary, "executive_summary", 12_000)
        if not self.documents or not self.claims:
            raise ValueError("completed dossiers require non-empty documents and claims")
        if len(self.arguments) < 2 or len({item.role for item in self.arguments}) < 2:
            raise ValueError("completed dossiers require a structured challenge with at least two argument roles")
        if not any(item.rebuttal_of is not None for item in self.arguments):
            raise ValueError("completed dossiers require at least one explicit argument rebuttal")
        if len(self.documents) > MAX_DOCUMENTS:
            raise ValueError(f"documents exceeds the {MAX_DOCUMENTS}-item terminal bound")
        for group_name in self._REFERENCE_GROUPS:
            _bounded_tuple(getattr(self, group_name), group_name)
        _bounded_tuple(self.coverage, "coverage", 64)
        self._validate_temporal_cutoff(cutoff)
        self._validate_references()
        if len(self.coverage) == 0 or len({item.area for item in self.coverage}) != len(self.coverage):
            raise ValueError("coverage must contain unique declared areas")
        coverage_by_area = {item.area: item for item in self.coverage}
        optional_collections = {
            "filings": self.filings,
            "transcripts": self.transcripts,
            "guidance": self.guidance,
            "peers": self.peers,
            "factors": self.factors,
            "valuations": self.valuations,
            "events": self.events,
            "risks": self.risks,
            "monitoring": self.monitoring,
        }
        for area, values in optional_collections.items():
            receipt = coverage_by_area.get(area)
            if not values and (
                receipt is None or receipt.status not in {"not_applicable", "partial", "missing", "entitlement_blocked"}
            ):
                raise ValueError(f"empty {area} requires explicit limited or not-applicable coverage")
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > MAX_DOSSIER_BYTES:
            raise ValueError(f"terminal dossier exceeds the {MAX_DOSSIER_BYTES}-byte bound")

    def _validate_temporal_cutoff(self, cutoff: datetime) -> None:
        for document in self.documents:
            if _utc_timestamp(document.temporal.cutoff_at, f"documents.{document.id}.cutoff_at") != cutoff:
                raise ValueError(f"document {document.id!r} uses a different research cutoff")
        for metric in self.metrics:
            if _utc_timestamp(metric.as_of_at, f"metrics.{metric.id}.as_of_at") > cutoff:
                raise ValueError(f"metric {metric.id!r} was unavailable at the research cutoff")
            if (
                metric.basis == "reported"
                and _utc_timestamp(metric.period_end, f"metrics.{metric.id}.period_end") > cutoff
            ):
                raise ValueError(f"reported metric {metric.id!r} leaks beyond the research cutoff")
        for filing in self.filings:
            if _utc_timestamp(filing.filed_at, f"filings.{filing.id}.filed_at") > cutoff:
                raise ValueError(f"filing {filing.id!r} was unavailable at the research cutoff")
        for transcript in self.transcripts:
            if _utc_timestamp(transcript.event_at, f"transcripts.{transcript.id}.event_at") > cutoff:
                raise ValueError(f"transcript {transcript.id!r} occurs after the research cutoff")
        for factor in self.factors:
            if _utc_timestamp(factor.as_of_at, f"factors.{factor.id}.as_of_at") > cutoff:
                raise ValueError(f"factor {factor.id!r} leaks beyond the research cutoff")
        for event in self.events:
            if (
                event.status == "historical"
                and _utc_timestamp(event.occurred_at, f"events.{event.id}.occurred_at") > cutoff
            ):
                raise ValueError(f"historical event {event.id!r} occurs after the research cutoff")
        for outcome in self.prior_outcomes:
            if _utc_timestamp(outcome.evaluated_at, f"prior_outcomes.{outcome.id}.evaluated_at") > cutoff:
                raise ValueError(f"prior outcome {outcome.id!r} was unavailable at the research cutoff")

    def _validate_references(self) -> None:
        id_sets: dict[str, set[str]] = {}
        for group_name in self._REFERENCE_GROUPS:
            identifiers = [item.id for item in getattr(self, group_name)]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{group_name} IDs must be unique")
            id_sets[group_name] = set(identifiers)

        def require(values: tuple[str, ...], group: str, owner: str) -> None:
            missing = set(values) - id_sets[group]
            if missing:
                raise ValueError(f"{owner} references unknown {group}: {sorted(missing)}")

        document_by_id = {item.id: item for item in self.documents}
        accessible_document_ids = {
            item.id for item in self.documents if item.entitlement.access != "entitlement_blocked"
        }
        for transcript in self.transcripts:
            require((transcript.document_id,), "documents", f"transcript {transcript.id}")
            transcript_document = document_by_id[transcript.document_id]
            if transcript_document.kind != "transcript":
                raise ValueError(f"transcript {transcript.id!r} must reference a transcript document")
            if transcript.segments and (
                transcript_document.entitlement.access == "entitlement_blocked"
                or not transcript_document.entitlement.redistributable
            ):
                raise ValueError(
                    f"transcript {transcript.id!r} cannot include segment extracts from a "
                    "non-redistributable or entitlement-blocked document"
                )
        metric_by_id = {item.id: item for item in self.metrics}
        calculation_by_id = {item.id: item for item in self.calculations}
        for calculation in self.calculations:
            require(calculation.input_metric_ids, "metrics", f"calculation {calculation.id}")
        for metric in self.metrics:
            require(metric.source_document_ids, "documents", f"metric {metric.id}")
            metric_as_of = _utc_timestamp(metric.as_of_at, f"metrics.{metric.id}.as_of_at")
            for document_id in metric.source_document_ids:
                available_at = _utc_timestamp(
                    document_by_id[document_id].temporal.available_at,
                    f"documents.{document_id}.available_at",
                )
                if available_at > metric_as_of:
                    raise ValueError(
                        f"metric {metric.id!r} predates the availability of source document {document_id!r}"
                    )
            if metric.basis != "assumption" and not set(metric.source_document_ids) & accessible_document_ids:
                raise ValueError(f"metric {metric.id!r} requires at least one accessible source document")
            if metric.calculation_id is not None:
                require((metric.calculation_id,), "calculations", f"metric {metric.id}")
                calculation = calculation_by_id[metric.calculation_id]
                if metric.id in calculation.input_metric_ids:
                    raise ValueError(f"calculated metric {metric.id!r} cannot depend on itself")
                for input_metric_id in calculation.input_metric_ids:
                    input_as_of = _utc_timestamp(
                        metric_by_id[input_metric_id].as_of_at,
                        f"metrics.{input_metric_id}.as_of_at",
                    )
                    if input_as_of > metric_as_of:
                        raise ValueError(f"calculated metric {metric.id!r} predates input metric {input_metric_id!r}")
                expected = (
                    round(calculation.result, calculation.rounding_digits)
                    if calculation.rounding_digits is not None
                    else calculation.result
                )
                if abs(metric.value - expected) > calculation.tolerance or metric.unit != calculation.unit:
                    raise ValueError(f"calculated metric {metric.id!r} must match calculation result and unit")
        metric_document_ids = {item.id: set(item.source_document_ids) for item in self.metrics}
        for claim in self.claims:
            require(claim.evidence_document_ids, "documents", f"claim {claim.id}")
            require(claim.counterevidence_document_ids, "documents", f"claim {claim.id}")
            require(claim.metric_ids, "metrics", f"claim {claim.id}")
            require(claim.counterclaim_ids, "claims", f"claim {claim.id}")
            claim_documents = set(claim.evidence_document_ids)
            for metric_id in claim.metric_ids:
                claim_documents.update(metric_document_ids[metric_id])
            if not claim_documents & accessible_document_ids:
                raise ValueError(f"claim {claim.id!r} requires at least one accessible source document")
            if claim.id in claim.counterclaim_ids:
                raise ValueError(f"claim {claim.id!r} cannot counter itself")
        for argument in self.arguments:
            require(argument.claim_ids, "claims", f"argument {argument.id}")
            require(argument.assumption_ids, "claims", f"argument {argument.id}")
            if argument.rebuttal_of is not None:
                require((argument.rebuttal_of,), "arguments", f"argument {argument.id}")
                if argument.rebuttal_of == argument.id:
                    raise ValueError(f"argument {argument.id!r} cannot rebut itself")
        for filing in self.filings:
            require((filing.document_id,), "documents", f"filing {filing.id}")
            if document_by_id[filing.document_id].kind != "filing":
                raise ValueError(f"filing {filing.id!r} must reference a filing document")
        for change in self.filing_changes:
            require((change.current_document_id,), "documents", f"filing change {change.id}")
            if change.prior_document_id is not None:
                require((change.prior_document_id,), "documents", f"filing change {change.id}")
                if change.prior_document_id == change.current_document_id:
                    raise ValueError(f"filing change {change.id!r} requires different prior and current documents")
            require(change.metric_ids, "metrics", f"filing change {change.id}")
            require(change.claim_ids, "claims", f"filing change {change.id}")
        for transcript in self.transcripts:
            require(transcript.guidance_claim_ids, "claims", f"transcript {transcript.id}")
            for segment in transcript.segments:
                require(segment.claim_ids, "claims", f"transcript segment {segment.id}")
            for theme in transcript.themes:
                require(theme.claim_ids, "claims", f"transcript theme {theme.id}")
        for guidance in self.guidance:
            require((guidance.claim_id,), "claims", f"guidance {guidance.id}")
        for peer in self.peers:
            require(peer.metric_ids, "metrics", f"peer {peer.id}")
            require(peer.evidence_document_ids, "documents", f"peer {peer.id}")
            if peer.peer_instrument_id == self.identity.instrument_id:
                raise ValueError(f"peer {peer.id!r} cannot reference the researched instrument")
        for factor in self.factors:
            require(factor.evidence_document_ids, "documents", f"factor {factor.id}")
            require(factor.history_document_ids, "documents", f"factor {factor.id}")
            if factor.prior_snapshot_id is not None:
                require((factor.prior_snapshot_id,), "factors", f"factor {factor.id}")
                if factor.prior_snapshot_id == factor.id:
                    raise ValueError(f"factor {factor.id!r} cannot be its own prior snapshot")
        for valuation in self.valuations:
            require(valuation.input_metric_ids, "metrics", f"valuation {valuation.id}")
            require(valuation.calculation_ids, "calculations", f"valuation {valuation.id}")
            require(valuation.assumption_claim_ids, "claims", f"valuation {valuation.id}")
            for assumption in valuation.assumptions:
                require(assumption.metric_ids, "metrics", f"valuation assumption {assumption.id}")
                require(assumption.claim_ids, "claims", f"valuation assumption {assumption.id}")
            for cell in valuation.sensitivity_cells:
                require(cell.calculation_ids, "calculations", f"valuation sensitivity {cell.id}")
        for event in self.events:
            require(event.evidence_document_ids, "documents", f"event {event.id}")
            require(event.claim_ids, "claims", f"event {event.id}")
            require(event.entity_ids, "entities", f"event {event.id}")
            require(event.ripple_event_ids, "events", f"event {event.id}")
            if event.id in event.ripple_event_ids:
                raise ValueError(f"event {event.id!r} cannot ripple to itself")
        for risk in self.risks:
            require(risk.evidence_document_ids, "documents", f"risk {risk.id}")
            require(risk.claim_ids, "claims", f"risk {risk.id}")
            require(risk.trigger_metric_ids, "metrics", f"risk {risk.id}")
        monitorable_ids = set().union(
            id_sets["claims"], id_sets["events"], id_sets["risks"], id_sets["guidance"], id_sets["metrics"]
        )
        for condition in self.monitoring:
            missing = set(condition.related_ids) - monitorable_ids
            if missing:
                raise ValueError(f"monitoring {condition.id!r} references unknown research IDs: {sorted(missing)}")
        for outcome in self.prior_outcomes:
            require((outcome.forecast_claim_id,), "claims", f"prior outcome {outcome.id}")
            require(outcome.outcome_document_ids, "documents", f"prior outcome {outcome.id}")
        if self.portfolio_impact is not None:
            require(self.portfolio_impact.metric_ids, "metrics", "portfolio impact")
            require(self.portfolio_impact.claim_ids, "claims", "portfolio impact")
        for check in self.evaluation.checks:
            require(check.document_ids, "documents", f"evaluation check {check.id}")
            require(check.claim_ids, "claims", f"evaluation check {check.id}")
            require(check.calculation_ids, "calculations", f"evaluation check {check.id}")
        for item in self.coverage:
            require(item.source_document_ids, "documents", f"coverage {item.area}")
        if self.research_delta is not None:
            require(self.research_delta.added_document_ids, "documents", "research_delta")
            require(self.research_delta.changed_claim_ids, "claims", "research_delta")
            require(self.research_delta.changed_valuation_ids, "valuations", "research_delta")

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, value: str) -> ResearchDossierV1:
        try:
            raw = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("research dossier must be valid JSON") from exc
        return cls.from_dict(raw)

    def digest(self) -> str:
        return sha256(self.to_json().encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CompanyResearchSubmissionV1(StrictModel):
    schema_version: Literal["company-research.v1"]
    workflow_id: Literal["stockresearchagents.company-research.v1"]
    request: CompanyResearchRequest
    dossier: ResearchDossierV1

    def __post_init__(self) -> None:
        if self.request.cutoff_at != self.dossier.as_of_at:
            raise ValueError("request.cutoff_at must exactly match dossier.as_of_at")
        if self.request.identity != self.dossier.identity:
            raise ValueError("request.identity must exactly match dossier.identity")
        if self.request.portfolio_context != self.dossier.portfolio_context:
            raise ValueError("request and dossier portfolio_context must exactly match")
        if _utc_timestamp(self.dossier.completed_at, "dossier.completed_at") < _utc_timestamp(
            self.request.requested_at, "request.requested_at"
        ):
            raise ValueError("dossier.completed_at cannot precede request.requested_at")
        planned = {item.area for item in self.request.research_plan.coverage_dimensions}
        reported = {item.area for item in self.dossier.coverage}
        missing = planned - reported
        if missing:
            raise ValueError(f"dossier coverage omits planned dimensions: {sorted(missing)}")
        coverage_by_area = {item.area: item for item in self.dossier.coverage}
        documents_by_id = {item.id: item for item in self.dossier.documents}
        for dimension in self.request.research_plan.coverage_dimensions:
            receipt = coverage_by_area[dimension.area]
            documents = tuple(documents_by_id[item] for item in receipt.source_document_ids)
            if dimension.required and receipt.status == "not_applicable":
                raise ValueError(f"required coverage dimension {dimension.area!r} cannot be not_applicable")
            if dimension.entitlement_policy == "public_only" and any(
                item.entitlement.access != "public" for item in documents
            ):
                raise ValueError(f"coverage dimension {dimension.area!r} permits only public sources")
            if receipt.status != "complete":
                continue
            if len(set(receipt.source_document_ids)) < dimension.minimum_source_count:
                raise ValueError(
                    f"complete coverage dimension {dimension.area!r} requires at least "
                    f"{dimension.minimum_source_count} sources"
                )
            if any(item.entitlement.access == "entitlement_blocked" for item in documents):
                raise ValueError(f"complete coverage dimension {dimension.area!r} cannot use blocked sources")
            if dimension.preferred_source_kinds and not any(
                item.kind in dimension.preferred_source_kinds for item in documents
            ):
                raise ValueError(
                    f"complete coverage dimension {dimension.area!r} lacks its planned preferred source kinds"
                )


def parse_research_dossier(value: object) -> ResearchDossierV1:
    """Parse and fully validate one completed ``company-research-submission.v1`` dossier."""
    return ResearchDossierV1.from_dict(value)


def serialize_research_dossier(value: ResearchDossierV1) -> str:
    """Serialize a validated dossier using stable, bounded canonical JSON."""
    if not isinstance(value, ResearchDossierV1):
        raise TypeError("value must be ResearchDossierV1")
    return value.to_json()


def validate_research_dossier(dossier: ResearchDossierV1, cutoff: str) -> None:
    """Re-run whole-dossier invariants against an explicit host cutoff."""
    if not isinstance(dossier, ResearchDossierV1):
        raise TypeError("dossier must be ResearchDossierV1")
    if dossier.as_of_at != cutoff:
        raise ValueError("dossier.as_of_at must exactly match the requested cutoff")
    ResearchDossierV1.from_dict(dossier.to_dict())


def parse_company_research_submission_v1(payload: object) -> CompanyResearchSubmissionV1:
    """Parse one strict company research request-plus-terminal-dossier submission."""
    if isinstance(payload, Mapping):
        request = payload.get("request")
        dossier = payload.get("dossier")
        if isinstance(request, Mapping) and isinstance(dossier, Mapping):
            requested_at = request.get("requested_at")
            completed_at = dossier.get("completed_at")
            if (
                completed_at is not None
                and requested_at is not None
                and _utc_timestamp(completed_at, "dossier.completed_at")
                < _utc_timestamp(requested_at, "request.requested_at")
            ):
                raise ValueError("dossier.completed_at cannot precede request.requested_at")
    return CompanyResearchSubmissionV1.from_dict(payload)
