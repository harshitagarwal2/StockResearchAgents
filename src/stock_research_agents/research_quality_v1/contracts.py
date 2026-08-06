"""Strict immutable contracts for Research Quality v1.

This module is deliberately a sidecar: it references completed research through
content digests and identifiers, and never carries provider configuration, raw
source bodies, credentials, or execution authority.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from stock_research_agents.contracts import reject_secret_shaped_keys

QUALITY_SCHEMA_VERSION = "research-quality.v1"
_ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_DIRECTIONS = frozenset({"up", "down", "flat"})
_FORECAST_KINDS = frozenset(
    {"binary_event", "numeric_metric", "interval", "directional_return", "benchmark_relative_return"}
)


def _object(value: object, required: set[str], path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    candidate = dict(value)
    reject_secret_shaped_keys(candidate)
    unknown = sorted(set(candidate) - required)
    missing = sorted(required - set(candidate))
    if unknown or missing:
        raise ValueError(f"{path} fields mismatch; missing={missing}, unknown={unknown}")
    return candidate


def _id(value: object, path: str) -> str:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{path} must be a safe identifier")
    return value


def _text(value: object, path: str, limit: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{path} must be non-empty text no longer than {limit} characters")
    return value


def _timestamp(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{path} must include an explicit UTC offset")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _digest(value: object, path: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")
    return value


def _finite(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{path} must be a finite number")
    return float(value)


def _nullable_finite(value: object, path: str) -> float | None:
    return None if value is None else _finite(value, path)


def _nullable_text(value: object, path: str, limit: int) -> str | None:
    return None if value is None else _text(value, path, limit)


def _nullable_id(value: object, path: str) -> str | None:
    return None if value is None else _id(value, path)


def _tuple_of_strings(value: object, path: str, *, limit: int = 128) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or len(value) > limit:
        raise ValueError(f"{path} must be an array of at most {limit} values")
    result = tuple(_id(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise ValueError(f"{path} values must be unique")
    return result


def canonical_json(value: object) -> str:
    """Encode only finite, canonical JSON for persistence and digesting."""
    serialized = value.to_dict() if hasattr(value, "to_dict") else value
    reject_secret_shaped_keys(serialized)
    return json.dumps(serialized, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    policy_id: str
    policy_version: str
    policy_sha256: str

    def __post_init__(self) -> None:
        _id(self.policy_id, "policy_id")
        _text(self.policy_version, "policy_version", 128)
        _digest(self.policy_sha256, "policy_sha256")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> QualityPolicy:
        item = _object(value, {"policy_id", "policy_version", "policy_sha256"}, "policy")
        return cls(
            _id(item["policy_id"], "policy.policy_id"),
            _text(item["policy_version"], "policy.policy_version", 128),
            _digest(item["policy_sha256"], "policy.policy_sha256"),
        )


@dataclass(frozen=True, slots=True)
class QualityRuleResult:
    rule_id: str
    status: Literal["pass", "fail", "skipped", "unverified"]
    detail: str

    def __post_init__(self) -> None:
        _id(self.rule_id, "rule_id")
        if self.status not in {"pass", "fail", "skipped", "unverified"}:
            raise ValueError("rule status is invalid")
        _text(self.detail, "rule detail")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> QualityRuleResult:
        item = _object(value, {"rule_id", "status", "detail"}, "rule")
        return cls(_id(item["rule_id"], "rule.rule_id"), item["status"], _text(item["detail"], "rule.detail"))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ResearchQualityReceipt:
    schema_version: Literal["research-quality.v1"]
    receipt_id: str
    run_id: str
    issued_at: str
    policy: QualityPolicy
    workflow_sha256: str
    request_sha256: str
    dossier_sha256: str
    package_identifier: str
    package_version: str
    stage_digests: tuple[tuple[str, str], ...]
    rules: tuple[QualityRuleResult, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != QUALITY_SCHEMA_VERSION:
            raise ValueError("unsupported Research Quality schema version")
        _id(self.receipt_id, "receipt_id")
        _id(self.run_id, "run_id")
        _timestamp(self.issued_at, "issued_at")
        _digest(self.workflow_sha256, "workflow_sha256")
        _digest(self.request_sha256, "request_sha256")
        _digest(self.dossier_sha256, "dossier_sha256")
        _text(self.package_identifier, "package_identifier", 128)
        _text(self.package_version, "package_version", 128)
        if not self.rules or len({item.rule_id for item in self.rules}) != len(self.rules):
            raise ValueError("rules must be non-empty with unique rule IDs")
        if len({stage_id for stage_id, _ in self.stage_digests}) != len(self.stage_digests):
            raise ValueError("stage digest IDs must be unique")
        for stage_id, digest in self.stage_digests:
            _id(stage_id, "stage_digests.stage_id")
            _digest(digest, "stage_digests.digest")
        for limitation in self.limitations:
            _text(limitation, "limitations item")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "run_id": self.run_id,
            "issued_at": self.issued_at,
            "policy": self.policy.to_dict(),
            "workflow_sha256": self.workflow_sha256,
            "request_sha256": self.request_sha256,
            "dossier_sha256": self.dossier_sha256,
            "package_identifier": self.package_identifier,
            "package_version": self.package_version,
            "stage_digests": [{"stage_id": stage, "sha256": digest} for stage, digest in self.stage_digests],
            "rules": [item.to_dict() for item in self.rules],
            "limitations": list(self.limitations),
        }

    def digest(self) -> str:
        return canonical_digest(self)

    @classmethod
    def from_dict(cls, value: object) -> ResearchQualityReceipt:
        fields = {
            "schema_version",
            "receipt_id",
            "run_id",
            "issued_at",
            "policy",
            "workflow_sha256",
            "request_sha256",
            "dossier_sha256",
            "package_identifier",
            "package_version",
            "stage_digests",
            "rules",
            "limitations",
        }
        item = _object(value, fields, "receipt")
        raw_stages = item["stage_digests"]
        raw_rules = item["rules"]
        raw_limitations = item["limitations"]
        if not isinstance(raw_stages, list | tuple) or not isinstance(raw_rules, list | tuple):
            raise ValueError("receipt stage_digests and rules must be arrays")
        if not isinstance(raw_limitations, list | tuple):
            raise ValueError("receipt limitations must be an array")
        stages: list[tuple[str, str]] = []
        for index, raw_stage in enumerate(raw_stages):
            stage = _object(raw_stage, {"stage_id", "sha256"}, f"receipt.stage_digests[{index}]")
            stages.append(
                (
                    _id(stage["stage_id"], f"receipt.stage_digests[{index}].stage_id"),
                    _digest(stage["sha256"], f"receipt.stage_digests[{index}].sha256"),
                )
            )
        return cls(
            item["schema_version"],  # type: ignore[arg-type]
            _id(item["receipt_id"], "receipt.receipt_id"),
            _id(item["run_id"], "receipt.run_id"),
            _timestamp(item["issued_at"], "receipt.issued_at"),
            QualityPolicy.from_dict(item["policy"]),
            _digest(item["workflow_sha256"], "receipt.workflow_sha256"),
            _digest(item["request_sha256"], "receipt.request_sha256"),
            _digest(item["dossier_sha256"], "receipt.dossier_sha256"),
            _text(item["package_identifier"], "receipt.package_identifier", 128),
            _text(item["package_version"], "receipt.package_version", 128),
            tuple(stages),
            tuple(QualityRuleResult.from_dict(rule) for rule in raw_rules),
            tuple(_text(limitation, "receipt limitation") for limitation in raw_limitations),
        )


@dataclass(frozen=True, slots=True)
class Forecast:
    schema_version: Literal["research-quality.v1"]
    forecast_id: str
    run_id: str
    instrument_id: str
    claim_id: str
    forecast_kind: Literal[
        "binary_event", "numeric_metric", "interval", "directional_return", "benchmark_relative_return"
    ]
    target: str
    forecast_at: str
    information_cutoff_at: str
    resolve_after: str
    horizon: str
    resolution_rule: str
    probability: float | None
    point_estimate: float | None
    interval_lower: float | None
    interval_upper: float | None
    direction: Literal["up", "down", "flat"] | None
    unit: str | None
    benchmark_id: str | None
    evidence_document_ids: tuple[str, ...]
    producer_provenance: str

    def __post_init__(self) -> None:
        if self.schema_version != QUALITY_SCHEMA_VERSION:
            raise ValueError("unsupported Forecast schema version")
        for name in ("forecast_id", "run_id", "instrument_id", "claim_id"):
            _id(getattr(self, name), name)
        if not self.forecast_id.startswith(f"{self.run_id}."):
            raise ValueError("forecast_id must be globally namespaced by run_id")
        if self.forecast_kind not in _FORECAST_KINDS:
            raise ValueError("forecast_kind is invalid")
        _text(self.target, "target")
        forecast_at = _timestamp(self.forecast_at, "forecast_at")
        cutoff = _timestamp(self.information_cutoff_at, "information_cutoff_at")
        resolve_after = _timestamp(self.resolve_after, "resolve_after")
        if _instant(cutoff) > _instant(forecast_at) or _instant(resolve_after) < _instant(forecast_at):
            raise ValueError("forecast cutoff/resolve timestamps are inconsistent")
        _text(self.horizon, "horizon", 256)
        _text(self.resolution_rule, "resolution_rule", 2_000)
        _text(self.producer_provenance, "producer_provenance", 2_000)
        if not self.evidence_document_ids:
            raise ValueError("forecasts require evidence_document_ids")
        for item in self.evidence_document_ids:
            _id(item, "evidence_document_ids item")
        if self.direction is not None and self.direction not in _DIRECTIONS:
            raise ValueError("direction is invalid")
        if self.unit is not None:
            _text(self.unit, "unit", 128)
        if self.benchmark_id is not None:
            _id(self.benchmark_id, "benchmark_id")
        values = (self.probability, self.point_estimate, self.interval_lower, self.interval_upper)
        for name, value in zip(
            ("probability", "point_estimate", "interval_lower", "interval_upper"), values, strict=True
        ):
            if value is not None:
                _finite(value, name)
        if self.forecast_kind == "binary_event":
            if (
                self.probability is None
                or not 0 <= self.probability <= 1
                or any(value is not None for value in values[1:])
                or self.direction is not None
            ):
                raise ValueError("binary events require only probability in [0, 1]")
        elif self.forecast_kind == "numeric_metric":
            if (
                self.point_estimate is None
                or self.unit is None
                or any(value is not None for value in (self.probability, self.interval_lower, self.interval_upper))
                or self.direction is not None
            ):
                raise ValueError("numeric metrics require only point_estimate and unit")
        elif self.forecast_kind == "interval":
            if (
                self.interval_lower is None
                or self.interval_upper is None
                or self.interval_lower > self.interval_upper
                or self.unit is None
                or any(value is not None for value in (self.probability, self.point_estimate))
                or self.direction is not None
            ):
                raise ValueError("interval forecasts require ordered bounds and unit")
        elif self.forecast_kind == "directional_return":
            if (
                self.direction is None
                or any(value is not None for value in values)
                or self.unit is not None
                or self.benchmark_id is not None
            ):
                raise ValueError("directional returns require only direction")
        else:
            if (
                self.direction is None
                or self.benchmark_id is None
                or any(value is not None for value in values)
                or self.unit is not None
            ):
                raise ValueError("benchmark-relative returns require direction and benchmark_id")

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"evidence_document_ids": list(self.evidence_document_ids)}

    def digest(self) -> str:
        return canonical_digest(self)

    @classmethod
    def from_dict(cls, value: object) -> Forecast:
        fields = {
            "schema_version",
            "forecast_id",
            "run_id",
            "instrument_id",
            "claim_id",
            "forecast_kind",
            "target",
            "forecast_at",
            "information_cutoff_at",
            "resolve_after",
            "horizon",
            "resolution_rule",
            "probability",
            "point_estimate",
            "interval_lower",
            "interval_upper",
            "direction",
            "unit",
            "benchmark_id",
            "evidence_document_ids",
            "producer_provenance",
        }
        item = _object(value, fields, "forecast")
        return cls(
            item["schema_version"],  # type: ignore[arg-type]
            _id(item["forecast_id"], "forecast.forecast_id"),
            _id(item["run_id"], "forecast.run_id"),
            _id(item["instrument_id"], "forecast.instrument_id"),
            _id(item["claim_id"], "forecast.claim_id"),
            item["forecast_kind"],  # type: ignore[arg-type]
            _text(item["target"], "forecast.target"),
            _timestamp(item["forecast_at"], "forecast.forecast_at"),
            _timestamp(item["information_cutoff_at"], "forecast.information_cutoff_at"),
            _timestamp(item["resolve_after"], "forecast.resolve_after"),
            _text(item["horizon"], "forecast.horizon", 256),
            _text(item["resolution_rule"], "forecast.resolution_rule", 2_000),
            _nullable_finite(item["probability"], "forecast.probability"),
            _nullable_finite(item["point_estimate"], "forecast.point_estimate"),
            _nullable_finite(item["interval_lower"], "forecast.interval_lower"),
            _nullable_finite(item["interval_upper"], "forecast.interval_upper"),
            item["direction"],  # type: ignore[arg-type]
            _nullable_text(item["unit"], "forecast.unit", 128),
            _nullable_id(item["benchmark_id"], "forecast.benchmark_id"),
            _tuple_of_strings(item["evidence_document_ids"], "forecast.evidence_document_ids"),
            _text(item["producer_provenance"], "forecast.producer_provenance", 2_000),
        )


@dataclass(frozen=True, slots=True)
class OutcomeObservation:
    schema_version: Literal["research-quality.v1"]
    observation_id: str
    forecast_id: str
    observed_at: str
    available_at: str
    resolved_at: str
    resolution_status: Literal["resolved", "unavailable"]
    binary_outcome: bool | None
    numeric_outcome: float | None
    realized_return: float | None
    benchmark_return: float | None
    outcome_document_ids: tuple[str, ...]
    evaluator: str
    supersedes_observation_id: str | None

    def __post_init__(self) -> None:
        if self.schema_version != QUALITY_SCHEMA_VERSION:
            raise ValueError("unsupported OutcomeObservation schema version")
        _id(self.observation_id, "observation_id")
        _id(self.forecast_id, "forecast_id")
        observed = _timestamp(self.observed_at, "observed_at")
        available = _timestamp(self.available_at, "available_at")
        resolved = _timestamp(self.resolved_at, "resolved_at")
        if not (_instant(observed) <= _instant(available) <= _instant(resolved)):
            raise ValueError("outcome timestamps must satisfy observed_at <= available_at <= resolved_at")
        if self.resolution_status not in {"resolved", "unavailable"}:
            raise ValueError("resolution_status is invalid")
        for name in ("numeric_outcome", "realized_return", "benchmark_return"):
            value = getattr(self, name)
            if value is not None:
                _finite(value, name)
        if self.resolution_status == "resolved" and not self.outcome_document_ids:
            raise ValueError("resolved outcomes require outcome_document_ids")
        for item in self.outcome_document_ids:
            _id(item, "outcome_document_ids item")
        _text(self.evaluator, "evaluator", 256)
        if self.supersedes_observation_id is not None:
            _id(self.supersedes_observation_id, "supersedes_observation_id")

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"outcome_document_ids": list(self.outcome_document_ids)}

    @classmethod
    def from_dict(cls, value: object) -> OutcomeObservation:
        fields = {
            "schema_version",
            "observation_id",
            "forecast_id",
            "observed_at",
            "available_at",
            "resolved_at",
            "resolution_status",
            "binary_outcome",
            "numeric_outcome",
            "realized_return",
            "benchmark_return",
            "outcome_document_ids",
            "evaluator",
            "supersedes_observation_id",
        }
        item = _object(value, fields, "outcome")
        binary = item["binary_outcome"]
        if binary is not None and not isinstance(binary, bool):
            raise ValueError("outcome.binary_outcome must be boolean or null")
        return cls(
            item["schema_version"],  # type: ignore[arg-type]
            _id(item["observation_id"], "outcome.observation_id"),
            _id(item["forecast_id"], "outcome.forecast_id"),
            _timestamp(item["observed_at"], "outcome.observed_at"),
            _timestamp(item["available_at"], "outcome.available_at"),
            _timestamp(item["resolved_at"], "outcome.resolved_at"),
            item["resolution_status"],  # type: ignore[arg-type]
            binary,
            _nullable_finite(item["numeric_outcome"], "outcome.numeric_outcome"),
            _nullable_finite(item["realized_return"], "outcome.realized_return"),
            _nullable_finite(item["benchmark_return"], "outcome.benchmark_return"),
            _tuple_of_strings(item["outcome_document_ids"], "outcome.outcome_document_ids"),
            _text(item["evaluator"], "outcome.evaluator", 256),
            _nullable_id(item["supersedes_observation_id"], "outcome.supersedes_observation_id"),
        )


@dataclass(frozen=True, slots=True)
class OutcomeLedger:
    """An immutable linear history; corrections append rather than overwrite."""

    schema_version: Literal["research-quality.v1"]
    forecast_id: str
    observations: tuple[OutcomeObservation, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != QUALITY_SCHEMA_VERSION:
            raise ValueError("unsupported OutcomeLedger schema version")
        _id(self.forecast_id, "forecast_id")
        if len({item.observation_id for item in self.observations}) != len(self.observations):
            raise ValueError("observation IDs must be unique")
        predecessor: str | None = None
        for item in self.observations:
            if item.forecast_id != self.forecast_id:
                raise ValueError("all observations must target the ledger forecast")
            if item.supersedes_observation_id != predecessor:
                raise ValueError("observations must form a linear append-only supersession chain")
            predecessor = item.observation_id

    @property
    def active_observation(self) -> OutcomeObservation | None:
        return self.observations[-1] if self.observations else None

    def append(self, observation: OutcomeObservation) -> OutcomeLedger:
        if observation.forecast_id != self.forecast_id:
            raise ValueError("observation forecast_id does not match ledger")
        expected = self.active_observation.observation_id if self.active_observation else None
        if observation.supersedes_observation_id != expected:
            raise ValueError("observation must supersede exactly the current active observation")
        return OutcomeLedger(self.schema_version, self.forecast_id, (*self.observations, observation))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "forecast_id": self.forecast_id,
            "observations": [item.to_dict() for item in self.observations],
        }

    @classmethod
    def from_dict(cls, value: object) -> OutcomeLedger:
        item = _object(value, {"schema_version", "forecast_id", "observations"}, "outcome ledger")
        observations = item["observations"]
        if not isinstance(observations, list | tuple):
            raise ValueError("outcome ledger observations must be an array")
        return cls(
            item["schema_version"],  # type: ignore[arg-type]
            _id(item["forecast_id"], "outcome ledger.forecast_id"),
            tuple(OutcomeObservation.from_dict(observation) for observation in observations),
        )
