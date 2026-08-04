"""Deterministic, host-owned collection across explicit source providers."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, cast

from .contracts import (
    SourceBatch,
    SourceObservation,
    SourceQuery,
    source_query_from_dict,
    validate_source_response,
)
from .ports import SourcePort

SOURCE_PORTFOLIO_RECEIPT_VERSION = "1.0.0"
MAX_SOURCE_PORTFOLIO_PROVIDERS = 64
MAX_SOURCE_PORTFOLIO_OBSERVATIONS = 50_000
PortfolioStatus = Literal["complete", "partial", "unavailable"]
AttemptStatus = Literal[
    "complete",
    "partial",
    "unavailable",
    "denied",
    "rate_limited",
    "stale",
    "error",
    "invalid_response",
]
DuplicateBasis = Literal["content_digest", "canonical_uri", "provider_native_identity"]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_GAP_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _identifier(value: object, path: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{path} must be a bounded identifier")
    return value


def _sha256_digest(value: object, path: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")
    return value


def _failure_type(exc: Exception) -> str:
    categories: tuple[tuple[type[Exception], str], ...] = (
        (TimeoutError, "TimeoutError"),
        (PermissionError, "PermissionError"),
        (ConnectionError, "ConnectionError"),
        (LookupError, "LookupError"),
        (ValueError, "ValueError"),
        (TypeError, "TypeError"),
        (RuntimeError, "RuntimeError"),
        (OSError, "OSError"),
    )
    return next((category for kind, category in categories if isinstance(exc, kind)), "ProviderError")


def _strict_object(value: object, fields: set[str], path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{path} must be an object")
    unknown = sorted(set(value) - fields)
    if unknown:
        raise ValueError(f"{path} has unknown fields: {unknown}")
    missing = sorted(fields - set(value))
    if missing:
        raise ValueError(f"{path} is missing required fields: {missing}")
    return cast(Mapping[str, object], value)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(encoded).hexdigest()


def _batch_sha256(batch: SourceBatch) -> str:
    return _canonical_sha256(batch.to_dict())


def _source_batch_id(route_id: str, batch_sha256: str) -> str:
    digest = _canonical_sha256({"route_id": route_id, "batch_sha256": batch_sha256})
    return f"batch-{digest}"


@dataclass(frozen=True, slots=True)
class SourceProviderAttempt:
    """Terminal outcome for one explicitly registered provider route."""

    route_id: str
    provider_family: str
    required: bool
    status: AttemptStatus
    batch_id: str | None = None
    batch_sha256: str | None = None
    failure_type: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.route_id, "attempt.route_id")
        _identifier(self.provider_family, "attempt.provider_family")
        if not isinstance(self.required, bool):
            raise ValueError("attempt.required must be a boolean")
        if self.status not in {
            "complete",
            "partial",
            "unavailable",
            "denied",
            "rate_limited",
            "stale",
            "error",
            "invalid_response",
        }:
            raise ValueError("attempt.status is invalid")
        failed_without_batch = self.status in {"error", "invalid_response"}
        if failed_without_batch != (self.batch_id is None) or failed_without_batch != (self.batch_sha256 is None):
            raise ValueError("attempt batch identity must be present exactly for retained batches")
        if self.batch_id is not None:
            _identifier(self.batch_id, "attempt.batch_id")
        if self.batch_sha256 is not None:
            _sha256_digest(self.batch_sha256, "attempt.batch_sha256")
            if self.batch_id != _source_batch_id(self.route_id, self.batch_sha256):
                raise ValueError("attempt.batch_id must bind its route and batch digest")
        if failed_without_batch != (self.failure_type is not None):
            raise ValueError("attempt failure type must be present exactly for adapter failures")
        if self.failure_type is not None:
            _identifier(self.failure_type, "attempt.failure_type")

    def to_dict(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "provider_family": self.provider_family,
            "required": self.required,
            "status": self.status,
            "batch_id": self.batch_id,
            "batch_sha256": self.batch_sha256,
            "failure_type": self.failure_type,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceProviderAttempt:
        raw = _strict_object(
            value,
            {"route_id", "provider_family", "required", "status", "batch_id", "batch_sha256", "failure_type"},
            "source provider attempt",
        )
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True, order=True)
class SourceObservationRef:
    """Stable portfolio-local identity for an observation."""

    route_id: str
    provider_family: str
    source_id: str
    batch_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.route_id, "observation reference.route_id")
        _identifier(self.provider_family, "observation reference.provider_family")
        _identifier(self.source_id, "observation reference.source_id")
        _sha256_digest(self.batch_sha256, "observation reference.batch_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "provider_family": self.provider_family,
            "source_id": self.source_id,
            "batch_sha256": self.batch_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceObservationRef:
        raw = _strict_object(
            value,
            {"route_id", "provider_family", "source_id", "batch_sha256"},
            "source observation reference",
        )
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ExactDuplicateCluster:
    """An exact-match decision; observations remain retained in their batches."""

    cluster_id: str
    match_basis: DuplicateBasis
    representative: SourceObservationRef
    members: tuple[SourceObservationRef, ...]

    def __post_init__(self) -> None:
        _identifier(self.cluster_id, "duplicate cluster.cluster_id")
        if self.match_basis not in {"content_digest", "canonical_uri", "provider_native_identity"}:
            raise ValueError("duplicate cluster.match_basis is invalid")
        if len(self.members) < 2 or tuple(sorted(self.members)) != self.members:
            raise ValueError("duplicate cluster members must be sorted and contain at least two observations")
        if len(set(self.members)) != len(self.members):
            raise ValueError("duplicate cluster members must be unique")
        if self.representative != self.members[0]:
            raise ValueError("duplicate cluster representative must be the first deterministic member")

    def to_dict(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "match_basis": self.match_basis,
            "representative": self.representative.to_dict(),
            "members": [member.to_dict() for member in self.members],
        }

    @classmethod
    def from_dict(cls, value: object) -> ExactDuplicateCluster:
        raw = _strict_object(
            value,
            {"cluster_id", "match_basis", "representative", "members"},
            "exact duplicate cluster",
        )
        members = raw["members"]
        if not isinstance(members, list):
            raise ValueError("exact duplicate cluster members must be an array")
        if len(members) > MAX_SOURCE_PORTFOLIO_OBSERVATIONS:
            raise ValueError("exact duplicate cluster exceeds the observation bound")
        return cls(
            cluster_id=cast(str, raw["cluster_id"]),
            match_basis=cast(DuplicateBasis, raw["match_basis"]),
            representative=SourceObservationRef.from_dict(raw["representative"]),
            members=tuple(SourceObservationRef.from_dict(member) for member in members),
        )


@dataclass(frozen=True, slots=True)
class SourcePortfolioReceipt:
    """Versioned record of collection attempts, retained batches, and dedup decisions."""

    capability: str
    query: SourceQuery
    status: PortfolioStatus
    attempts: tuple[SourceProviderAttempt, ...]
    batches: tuple[SourceBatch, ...]
    coverage_gaps: tuple[str, ...]
    exact_duplicate_clusters: tuple[ExactDuplicateCluster, ...]
    portfolio_sha256: str = ""

    version = SOURCE_PORTFOLIO_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _identifier(self.capability, "source portfolio capability")
        normalized_query = source_query_from_dict(self.query.to_dict())
        if normalized_query != self.query:
            raise ValueError("source portfolio query is not canonical")
        if self.status not in {"complete", "partial", "unavailable"}:
            raise ValueError("source portfolio status is invalid")
        if not self.attempts:
            raise ValueError("source portfolio requires at least one provider attempt")
        if len(self.attempts) > MAX_SOURCE_PORTFOLIO_PROVIDERS:
            raise ValueError("source portfolio exceeds the provider bound")
        if tuple(sorted(self.attempts, key=lambda item: item.route_id)) != self.attempts:
            raise ValueError("source portfolio attempts must use deterministic route ordering")
        if len({item.route_id for item in self.attempts}) != len(self.attempts):
            raise ValueError("source portfolio route attempts must be unique")
        retained_attempts = tuple(item for item in self.attempts if item.batch_sha256 is not None)
        if len(retained_attempts) != len(self.batches):
            raise ValueError("source portfolio retained attempts and batches must align")
        if len({item.batch_id for item in retained_attempts}) != len(retained_attempts):
            raise ValueError("source portfolio batch IDs must be unique")
        observation_count = sum(len(batch.items) for batch in self.batches)
        if observation_count > MAX_SOURCE_PORTFOLIO_OBSERVATIONS:
            raise ValueError("source portfolio exceeds the observation bound")
        if (
            len(self.exact_duplicate_clusters) > observation_count
            or sum(len(cluster.members) for cluster in self.exact_duplicate_clusters) > observation_count
        ):
            raise ValueError("source portfolio duplicate clusters exceed the observation bound")
        for attempt, batch in zip(retained_attempts, self.batches, strict=True):
            validate_source_response(self.capability, self.query, batch)
            if (
                attempt.batch_sha256 != _batch_sha256(batch)
                or attempt.batch_id != _source_batch_id(attempt.route_id, attempt.batch_sha256)
                or attempt.status != batch.status
            ):
                raise ValueError("source portfolio attempt does not match its retained batch")
        if (
            not isinstance(self.coverage_gaps, tuple)
            or not all(isinstance(item, str) for item in self.coverage_gaps)
            or tuple(sorted(set(self.coverage_gaps))) != self.coverage_gaps
        ):
            raise ValueError("source portfolio coverage gaps must be unique and sorted")
        for gap in self.coverage_gaps:
            if not _GAP_CODE.fullmatch(gap):
                raise ValueError("source portfolio coverage gap must be a bounded machine-readable code")
        expected_gaps = _coverage_gaps(self.attempts, self.batches)
        if self.coverage_gaps != expected_gaps:
            raise ValueError("source portfolio coverage gaps do not match required provider outcomes")
        expected_status = _portfolio_status(self.attempts, self.batches, self.coverage_gaps)
        if self.status != expected_status:
            raise ValueError("source portfolio status does not match provider outcomes")
        expected_clusters = _exact_duplicate_clusters(retained_attempts, self.batches)
        if self.exact_duplicate_clusters != expected_clusters:
            raise ValueError("source portfolio exact duplicate clusters are not canonical")
        expected_digest = _canonical_sha256(self._unsigned_dict())
        if self.portfolio_sha256 == "":
            object.__setattr__(self, "portfolio_sha256", expected_digest)
        else:
            _sha256_digest(self.portfolio_sha256, "source portfolio portfolio_sha256")
            if self.portfolio_sha256 != expected_digest:
                raise ValueError("source portfolio receipt digest does not match its content")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "capability": self.capability,
            "query": self.query.to_dict(),
            "status": self.status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "batches": [batch.to_dict() for batch in self.batches],
            "coverage_gaps": list(self.coverage_gaps),
            "exact_duplicate_clusters": [cluster.to_dict() for cluster in self.exact_duplicate_clusters],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "portfolio_sha256": self.portfolio_sha256}

    @property
    def source_batch_ids(self) -> tuple[str, ...]:
        return tuple(cast(str, attempt.batch_id) for attempt in self.attempts if attempt.batch_id is not None)

    @classmethod
    def from_dict(cls, value: object) -> SourcePortfolioReceipt:
        fields = {
            "version",
            "capability",
            "query",
            "status",
            "attempts",
            "batches",
            "coverage_gaps",
            "exact_duplicate_clusters",
            "portfolio_sha256",
        }
        raw = _strict_object(value, fields, "source portfolio receipt")
        if raw["version"] != SOURCE_PORTFOLIO_RECEIPT_VERSION:
            raise ValueError("unsupported source portfolio receipt version")
        attempts = raw["attempts"]
        batches = raw["batches"]
        coverage_gaps = raw["coverage_gaps"]
        clusters = raw["exact_duplicate_clusters"]
        if not isinstance(attempts, list):
            raise ValueError("source portfolio attempts must be an array")
        if len(attempts) > MAX_SOURCE_PORTFOLIO_PROVIDERS:
            raise ValueError("source portfolio exceeds the provider bound")
        if not isinstance(batches, list):
            raise ValueError("source portfolio batches must be an array")
        if len(batches) > MAX_SOURCE_PORTFOLIO_PROVIDERS:
            raise ValueError("source portfolio exceeds the provider bound")
        if not isinstance(coverage_gaps, list) or not all(isinstance(item, str) for item in coverage_gaps):
            raise ValueError("source portfolio coverage gaps must be an array of strings")
        if len(coverage_gaps) > MAX_SOURCE_PORTFOLIO_PROVIDERS + 1:
            raise ValueError("source portfolio exceeds the coverage-gap bound")
        if not isinstance(clusters, list):
            raise ValueError("source portfolio exact duplicate clusters must be an array")
        if len(clusters) > MAX_SOURCE_PORTFOLIO_OBSERVATIONS:
            raise ValueError("source portfolio exceeds the duplicate-cluster bound")
        _sha256_digest(raw["portfolio_sha256"], "source portfolio portfolio_sha256")
        raw_observation_count = 0
        for batch in batches:
            if isinstance(batch, Mapping) and isinstance(batch.get("items"), list):
                raw_observation_count += len(cast(list[object], batch["items"]))
                if raw_observation_count > MAX_SOURCE_PORTFOLIO_OBSERVATIONS:
                    raise ValueError("source portfolio exceeds the observation bound")
        raw_cluster_members = 0
        for cluster in clusters:
            if isinstance(cluster, Mapping) and isinstance(cluster.get("members"), list):
                raw_cluster_members += len(cast(list[object], cluster["members"]))
                if raw_cluster_members > MAX_SOURCE_PORTFOLIO_OBSERVATIONS:
                    raise ValueError("source portfolio duplicate clusters exceed the observation bound")
        return cls(
            capability=cast(str, raw["capability"]),
            query=source_query_from_dict(raw["query"]),
            status=cast(PortfolioStatus, raw["status"]),
            attempts=tuple(SourceProviderAttempt.from_dict(item) for item in attempts),
            batches=tuple(SourceBatch.from_dict(item) for item in batches),
            coverage_gaps=tuple(coverage_gaps),
            exact_duplicate_clusters=tuple(ExactDuplicateCluster.from_dict(item) for item in clusters),
            portfolio_sha256=cast(str, raw["portfolio_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class _ProviderRoute:
    route_id: str
    provider_family: str
    port: SourcePort
    required: bool


class SourcePortfolioCollector:
    """Attempt all registered providers without merging their typed batches."""

    def __init__(self) -> None:
        self._routes: dict[str, dict[str, _ProviderRoute]] = {}

    def register(
        self,
        capability: str,
        route_id: str,
        provider_family: str,
        port: SourcePort,
        *,
        required: bool = False,
    ) -> None:
        _identifier(capability, "source portfolio capability")
        _identifier(route_id, "source portfolio route_id")
        _identifier(provider_family, "source portfolio provider_family")
        if not isinstance(port, SourcePort):
            raise ValueError("source portfolio routes require a SourcePort")
        if not isinstance(required, bool):
            raise ValueError("source portfolio route required must be a boolean")
        routes = self._routes.setdefault(capability, {})
        if route_id in routes:
            raise ValueError(f"source portfolio route is already registered: {route_id}")
        if len(routes) >= MAX_SOURCE_PORTFOLIO_PROVIDERS:
            raise ValueError("source portfolio exceeds the provider bound")
        routes[route_id] = _ProviderRoute(route_id, provider_family, port, required)

    def route_ids(self, capability: str) -> tuple[str, ...]:
        return tuple(sorted(self._routes.get(capability, {})))

    def collect(self, capability: str, query: SourceQuery) -> SourcePortfolioReceipt:
        _identifier(capability, "source portfolio capability")
        routes = self._routes.get(capability)
        if not routes:
            raise KeyError(f"no source portfolio providers registered for capability: {capability}")
        attempts: list[SourceProviderAttempt] = []
        batches: list[SourceBatch] = []
        retained_observations = 0
        for route in sorted(routes.values(), key=lambda item: item.route_id):
            try:
                response = route.port.fetch(capability, query)
            except Exception as exc:  # Provider failures are isolated and sanitized.
                attempts.append(
                    SourceProviderAttempt(
                        route.route_id,
                        route.provider_family,
                        route.required,
                        "error",
                        failure_type=_failure_type(exc),
                    )
                )
                continue
            try:
                batch = validate_source_response(capability, query, response)
            except (TypeError, ValueError) as exc:
                attempts.append(
                    SourceProviderAttempt(
                        route.route_id,
                        route.provider_family,
                        route.required,
                        "invalid_response",
                        failure_type=_failure_type(exc),
                    )
                )
                continue
            if retained_observations + len(batch.items) > MAX_SOURCE_PORTFOLIO_OBSERVATIONS:
                attempts.append(
                    SourceProviderAttempt(
                        route.route_id,
                        route.provider_family,
                        route.required,
                        "invalid_response",
                        failure_type="ObservationBoundExceeded",
                    )
                )
                continue
            digest = _batch_sha256(batch)
            attempts.append(
                SourceProviderAttempt(
                    route.route_id,
                    route.provider_family,
                    route.required,
                    batch.status,
                    batch_id=_source_batch_id(route.route_id, digest),
                    batch_sha256=digest,
                )
            )
            batches.append(batch)
            retained_observations += len(batch.items)
        attempt_tuple = tuple(attempts)
        batch_tuple = tuple(batches)
        coverage_gaps = _coverage_gaps(attempt_tuple, batch_tuple)
        return SourcePortfolioReceipt(
            capability=capability,
            query=query,
            status=_portfolio_status(attempt_tuple, batch_tuple, coverage_gaps),
            attempts=attempt_tuple,
            batches=batch_tuple,
            coverage_gaps=coverage_gaps,
            exact_duplicate_clusters=_exact_duplicate_clusters(
                tuple(item for item in attempt_tuple if item.batch_sha256 is not None), batch_tuple
            ),
        )


def _coverage_gaps(attempts: tuple[SourceProviderAttempt, ...], batches: tuple[SourceBatch, ...]) -> tuple[str, ...]:
    retained = iter(batches)
    batch_by_route: dict[str, SourceBatch] = {}
    for attempt in attempts:
        if attempt.batch_sha256 is not None:
            batch_by_route[attempt.route_id] = next(retained)
    gaps: list[str] = []
    for attempt in attempts:
        if not attempt.required:
            continue
        batch = batch_by_route.get(attempt.route_id)
        if attempt.status != "complete":
            gaps.append(f"required_route:{attempt.route_id}:{attempt.status}")
        elif batch is None or not batch.items:
            gaps.append(f"required_route:{attempt.route_id}:empty")
    if not gaps and not any(batch.items for batch in batches):
        gaps.append("portfolio:no_observations")
    return tuple(sorted(gaps))


def _portfolio_status(
    attempts: tuple[SourceProviderAttempt, ...],
    batches: tuple[SourceBatch, ...],
    coverage_gaps: tuple[str, ...],
) -> PortfolioStatus:
    if not any(batch.items for batch in batches):
        return "unavailable"
    if coverage_gaps:
        return "partial"
    if not any(attempt.required for attempt in attempts) and any(attempt.status != "complete" for attempt in attempts):
        return "partial"
    return "complete"


def _exact_duplicate_clusters(
    attempts: tuple[SourceProviderAttempt, ...], batches: tuple[SourceBatch, ...]
) -> tuple[ExactDuplicateCluster, ...]:
    records: list[tuple[SourceObservationRef, SourceObservation]] = []
    for attempt, batch in zip(attempts, batches, strict=True):
        assert attempt.batch_sha256 is not None
        for observation in batch.items:
            records.append(
                (
                    SourceObservationRef(
                        attempt.route_id,
                        attempt.provider_family,
                        observation.source_id,
                        attempt.batch_sha256,
                    ),
                    observation,
                )
            )
    records.sort(key=lambda item: item[0])
    parents = list(range(len(records)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        parents[max(left_root, right_root)] = min(left_root, right_root)

    matching_edges: list[tuple[int, DuplicateBasis, int, int]] = []
    criteria: tuple[tuple[DuplicateBasis, Callable[[SourceObservation], object] | None], ...] = (
        ("content_digest", lambda item: (item.content_sha256_scope, item.content_sha256)),
        ("canonical_uri", lambda item: item.canonical_uri),
        ("provider_native_identity", None),
    )
    for priority, (basis, key_function) in enumerate(criteria):
        grouped: dict[object, list[int]] = {}
        for index in range(len(records)):
            ref, observation = records[index]
            key = (
                (ref.provider_family, observation.source_id)
                if basis == "provider_native_identity"
                else cast(Callable[[SourceObservation], object], key_function)(observation)
            )
            grouped.setdefault(key, []).append(index)
        for key in sorted(grouped, key=lambda item: repr(item)):
            indices = grouped[key]
            if len(indices) < 2:
                continue
            anchor = indices[0]
            for index in indices[1:]:
                union(anchor, index)
                matching_edges.append((priority, basis, anchor, index))
    grouped_components: dict[int, list[int]] = {}
    for index in range(len(records)):
        grouped_components.setdefault(find(index), []).append(index)
    component_basis: dict[int, tuple[int, DuplicateBasis]] = {}
    for priority, basis, left, _right in matching_edges:
        root = find(left)
        current = component_basis.get(root)
        if current is None or priority < current[0]:
            component_basis[root] = (priority, basis)
    clusters: list[ExactDuplicateCluster] = []
    for root, indices in grouped_components.items():
        if len(indices) < 2:
            continue
        basis = component_basis[root][1]
        members = tuple(records[index][0] for index in indices)
        cluster_payload = {"basis": basis, "members": [item.to_dict() for item in members]}
        cluster_id = f"dup-{_canonical_sha256(cluster_payload)[:24]}"
        clusters.append(ExactDuplicateCluster(cluster_id, basis, members[0], members))
    basis_priority = {basis: priority for priority, (basis, _) in enumerate(criteria)}
    return tuple(sorted(clusters, key=lambda cluster: (basis_priority[cluster.match_basis], cluster.members)))


__all__ = [
    "ExactDuplicateCluster",
    "MAX_SOURCE_PORTFOLIO_OBSERVATIONS",
    "MAX_SOURCE_PORTFOLIO_PROVIDERS",
    "SOURCE_PORTFOLIO_RECEIPT_VERSION",
    "SourceObservationRef",
    "SourcePortfolioCollector",
    "SourcePortfolioReceipt",
    "SourceProviderAttempt",
]
