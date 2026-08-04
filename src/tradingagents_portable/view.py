"""Lossless completed-view projection of a portable run."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .contracts import EvidenceItem, RunEvent, RunResult
from .reporting import report_groups
from .semantics import build_completed_run_semantics

SOURCE_QUALITY_VOCABULARY = frozenset(
    {
        "primary_regulatory",
        "primary_company",
        "primary_agency",
        "primary_partner",
        "established_market_data",
        "reputable_journalism",
        "aggregator_discovery",
        "public_discussion",
        "synthetic_fixture",
        "unknown",
    }
)

_ACCESS_ALLOWED = frozenset({"allowed", "licensed", "public"})
_ACCESS_BLOCKED = frozenset({"blocked", "denied", "entitlement_blocked"})
_LINK_VERIFICATION_GROUPS = {
    "opened_attributable": frozenset({"attributable", "opened", "opened_and_verified", "verified"}),
    "primary_confirmed": frozenset({"primary_confirmed"}),
    "multi_source_confirmed": frozenset({"multi_source_confirmed"}),
    "single_source_reported": frozenset({"single_source_reported"}),
    "discovery_only": frozenset({"discovery_only"}),
}
_OPENED_LINK_STATUSES = frozenset().union(
    _LINK_VERIFICATION_GROUPS["opened_attributable"],
    _LINK_VERIFICATION_GROUPS["primary_confirmed"],
    _LINK_VERIFICATION_GROUPS["multi_source_confirmed"],
    _LINK_VERIFICATION_GROUPS["single_source_reported"],
)


@dataclass(frozen=True, slots=True)
class RunView:
    """UI-ready representation that keeps decisions and signal distinct."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload


def _badge(label: str, value: object, tone: str, detail: str) -> dict[str, object]:
    return {"label": label, "value": value, "tone": tone, "detail": detail}


def _safe_web_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    safe = (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and not hostname.endswith(".invalid")
    )
    return value if safe else None


def _timestamp_extreme(values: list[str], *, latest: bool) -> str | None:
    parsed: list[tuple[str, datetime]] = []
    for value in values:
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        parsed.append((value, timestamp.astimezone(UTC)))
    if not parsed:
        return None
    chooser = max if latest else min
    return chooser(parsed, key=lambda item: item[1])[0]


def _date_distance_days(earlier: str | None, later: str | None) -> int | None:
    if earlier is None or later is None:
        return None
    try:
        return (datetime.fromisoformat(later).date() - datetime.fromisoformat(earlier).date()).days
    except ValueError:
        return None


def _evidence_context(item: EvidenceItem) -> dict[str, str]:
    return {"evidence_id": item.id, "category": item.category}


def _normalize_records(item: EvidenceItem, key: str, text_key: str) -> list[dict[str, Any]]:
    value = item.values.get(key)
    if not isinstance(value, list | tuple):
        return []

    records: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, str):
            record: dict[str, Any] = {text_key: entry}
        elif isinstance(entry, Mapping):
            record = {str(field): field_value for field, field_value in entry.items()}
        else:
            continue
        record.update(_evidence_context(item))
        records.append(record)
    return records


def _normalize_metrics(item: EvidenceItem) -> list[dict[str, Any]]:
    value = item.values.get("metrics")
    records: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for name, metric_value in value.items():
            if isinstance(metric_value, Mapping):
                record = {str(field): field_value for field, field_value in metric_value.items()}
                record.setdefault("name", str(name))
            else:
                record = {"name": str(name), "value": metric_value}
            record.update(_evidence_context(item))
            records.append(record)
    elif isinstance(value, list | tuple):
        for metric in value:
            if not isinstance(metric, Mapping):
                continue
            record = {str(field): field_value for field, field_value in metric.items()}
            record.update(_evidence_context(item))
            records.append(record)
    return records


def _source_quality(item: EvidenceItem) -> str:
    value = item.values.get("source_quality")
    if item.provenance.fixture:
        return "synthetic_fixture"
    return value if isinstance(value, str) and value in SOURCE_QUALITY_VOCABULARY else "unknown"


def _has_unrecognized_source_quality(item: EvidenceItem) -> bool:
    value = item.values.get("source_quality")
    return (
        not item.provenance.fixture
        and isinstance(value, str)
        and bool(value.strip())
        and value not in SOURCE_QUALITY_VOCABULARY
    )


def _mapping(value: object) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        serialized = to_dict()
        if isinstance(serialized, Mapping):
            return {str(key): item for key, item in serialized.items()}
    return None


def _completed_research_dossier(result: RunResult) -> dict[str, Any] | None:
    """Return the completed v3 dossier without interpreting its research data."""
    for artifact in result.artifacts:
        if artifact.kind == "research_dossier.v3" or artifact.id == "research_dossier.v3":
            dossier = _mapping(artifact.content)
            if dossier:
                return dossier
    return None


def _completed_research_request(result: RunResult) -> dict[str, Any] | None:
    for artifact in result.artifacts:
        if artifact.kind == "research_request.v3" or artifact.id == "research.request.v3":
            request = _mapping(artifact.content)
            if request:
                return request
    return None


def _completed_artifact_content(result: RunResult, kind: str) -> object | None:
    """Project a declared sidecar only from the terminal completed result."""
    if result.status.value != "completed":
        return None
    for artifact in result.artifacts:
        if artifact.kind != kind:
            continue
        if isinstance(artifact.content, Mapping):
            return {str(key): value for key, value in artifact.content.items()}
        if isinstance(artifact.content, list | tuple):
            return list(artifact.content)
        to_dict = getattr(artifact.content, "to_dict", None)
        if callable(to_dict):
            return to_dict()
    return None


def _declared_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _source_host(value: object) -> str | None:
    uri = _safe_web_url(value)
    if uri is None:
        return None
    hostname = (urlparse(uri).hostname or "").lower()
    return hostname.removeprefix("www.") or None


def _record_sequence(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list | tuple):
        return []
    return [record for item in value if (record := _mapping(item)) is not None]


def _document_source_record(value: Mapping[str, object], ordinal: int) -> dict[str, Any]:
    locator = _mapping(value.get("locator")) or {}
    temporal = _mapping(value.get("temporal")) or {}
    entitlement = _mapping(value.get("entitlement"))
    entitlement_value = value.get("entitlement")
    canonical_uri = _safe_web_url(
        locator.get("canonical_uri") or value.get("canonical_uri") or value.get("url") or value.get("uri")
    )
    access = entitlement.get("access") if entitlement is not None else entitlement_value
    return {
        "id": _declared_text(value.get("id")) or f"source-document-{ordinal + 1}",
        "title": _declared_text(value.get("title") or value.get("name")),
        "kind": _declared_text(value.get("kind") or value.get("source_kind") or value.get("document_kind")),
        "publisher": _declared_text(value.get("publisher") or value.get("declared_publisher")),
        "canonical_uri": canonical_uri,
        "origin_host": _source_host(canonical_uri),
        "content_sha256": _declared_text(locator.get("content_sha256") or value.get("content_sha256")),
        "published_at": _declared_text(temporal.get("published_at") or value.get("published_at")),
        "available_at": _declared_text(temporal.get("available_at") or value.get("available_at")),
        "retrieved_at": _declared_text(temporal.get("retrieved_at") or value.get("retrieved_at")),
        "access": _declared_text(access),
        "redistributable": entitlement.get("redistributable") if entitlement is not None else None,
        "verification_status": _declared_text(value.get("verification_status")),
        "retrieval_provider": _declared_text(value.get("retrieval_provider")),
        "record_type": "document",
    }


def _evidence_source_record(item: EvidenceItem, ordinal: int) -> dict[str, Any]:
    locator = _mapping(item.values.get("locator")) or {}
    temporal = _mapping(item.values.get("temporal")) or {}
    entitlement = _mapping(item.values.get("entitlement")) or {}
    canonical_uri = _safe_web_url(locator.get("canonical_uri") or item.provenance.source_uri)
    return {
        "id": item.id or f"evidence-source-{ordinal + 1}",
        "title": item.title or None,
        "kind": _declared_text(item.values.get("document_kind") or item.provenance.source_type or item.category),
        "publisher": _declared_text(item.values.get("publisher")),
        "canonical_uri": canonical_uri,
        "origin_host": _source_host(canonical_uri),
        "content_sha256": _declared_text(locator.get("content_sha256")),
        "published_at": _declared_text(temporal.get("published_at") or item.provenance.source_date),
        "available_at": _declared_text(temporal.get("available_at") or item.provenance.source_date),
        "retrieved_at": _declared_text(temporal.get("retrieved_at") or item.provenance.retrieved_at),
        "access": _declared_text(entitlement.get("access")),
        "redistributable": entitlement.get("redistributable"),
        "verification_status": _declared_text(item.values.get("verification_status")),
        "retrieval_provider": _declared_text(item.provenance.provider),
        "record_type": "document",
    }


def _linked_source_record(value: Mapping[str, object], ordinal: int) -> dict[str, Any]:
    canonical_uri = _safe_web_url(value.get("url") or value.get("source_url") or value.get("canonical_uri"))
    return {
        "id": _declared_text(value.get("id")) or f"linked-source-{ordinal + 1}",
        "title": _declared_text(value.get("headline") or value.get("title")),
        "kind": _declared_text(value.get("source_kind")) or "news_item",
        "publisher": _declared_text(value.get("publisher")),
        "canonical_uri": canonical_uri,
        "origin_host": _source_host(canonical_uri),
        "content_sha256": _declared_text(value.get("content_sha256")),
        "published_at": _declared_text(value.get("published_at") or value.get("source_date")),
        "available_at": _declared_text(value.get("available_at") or value.get("published_at")),
        "retrieved_at": _declared_text(value.get("retrieved_at")),
        "access": _declared_text(value.get("access")),
        "redistributable": value.get("redistributable"),
        "verification_status": _declared_text(value.get("verification_status")),
        "source_quality": _declared_text(value.get("source_quality")),
        "retrieval_provider": _declared_text(value.get("retrieval_provider") or value.get("discovery_provider")),
        "record_type": "linked_source",
    }


def _normalized_sha256(value: object) -> str | None:
    digest = (_declared_text(value) or "").lower()
    return digest if len(digest) == 64 and all(character in "0123456789abcdef" for character in digest) else None


def _source_access_status(value: Mapping[str, object]) -> str:
    access = (_declared_text(value.get("access")) or "").casefold()
    if access in _ACCESS_ALLOWED:
        return "accessible"
    if access in _ACCESS_BLOCKED:
        return "blocked"
    return "access_unknown"


def _source_traceability_status(value: Mapping[str, object]) -> str:
    has_uri = _declared_text(value.get("canonical_uri")) is not None
    has_digest = _normalized_sha256(value.get("content_sha256")) is not None
    if has_uri and has_digest:
        return "canonical"
    if (
        has_uri
        or has_digest
        or (_declared_text(value.get("publisher")) is not None and _declared_text(value.get("title")) is not None)
    ):
        return "attributable"
    return "unattributable"


def _has_exact_source_identity(value: Mapping[str, object]) -> bool:
    return (
        _declared_text(value.get("canonical_uri")) is not None
        or _normalized_sha256(value.get("content_sha256")) is not None
    )


def _metadata_source_identity(value: Mapping[str, object]) -> str:
    identity = "|".join(
        filter(
            None,
            (
                (_declared_text(value.get("publisher")) or "").casefold(),
                (_declared_text(value.get("title")) or "").casefold(),
                _declared_text(value.get("published_at")) or "",
            ),
        )
    )
    return identity or str(value.get("id", "unknown"))


def _source_group_identity(group: list[dict[str, Any]]) -> str:
    uris = sorted({uri for record in group if (uri := _declared_text(record.get("canonical_uri"))) is not None})
    if uris:
        return f"uri:{uris[0]}"
    hashes = sorted(
        {digest for record in group if (digest := _normalized_sha256(record.get("content_sha256"))) is not None}
    )
    if hashes:
        return f"sha256:{hashes[0]}"
    return f"metadata:{min(_metadata_source_identity(record) for record in group)}"


def _source_record_groups(records: list[dict[str, Any]], *, exact_only: bool) -> list[list[dict[str, Any]]]:
    eligible = [record for record in records if not exact_only or _has_exact_source_identity(record)]
    parents = list(range(len(eligible)))

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
        if left_root < right_root:
            parents[right_root] = left_root
        else:
            parents[left_root] = right_root

    hash_owner: dict[str, int] = {}
    uri_owner: dict[str, int] = {}
    metadata_owner: dict[str, int] = {}
    for index, record in enumerate(eligible):
        content_sha256 = _normalized_sha256(record.get("content_sha256"))
        canonical_uri = _declared_text(record.get("canonical_uri"))
        identities = (
            (hash_owner, content_sha256),
            (uri_owner, canonical_uri),
        )
        for owners, identity in identities:
            if identity is None:
                continue
            if identity in owners:
                union(index, owners[identity])
            else:
                owners[identity] = index
        if content_sha256 is None and canonical_uri is None and not exact_only:
            metadata_identity = _metadata_source_identity(record)
            if metadata_identity in metadata_owner:
                union(index, metadata_owner[metadata_identity])
            else:
                metadata_owner[metadata_identity] = index

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(eligible):
        grouped.setdefault(find(index), []).append(record)
    return sorted(grouped.values(), key=_source_group_identity)


def _metadata_candidates(group: list[dict[str, Any]], field: str) -> list[Any]:
    candidate_groups: dict[tuple[type[object], object], list[Any]] = {}
    case_insensitive_fields = {"access", "kind", "origin_host", "publisher"}
    for record in group:
        value = record.get(field)
        if isinstance(value, str):
            value = _declared_text(value)
            if value is None:
                continue
            if field == "content_sha256":
                value = _normalized_sha256(value) or value
                key: tuple[type[object], object] = (str, value)
            elif field in case_insensitive_fields:
                key = (str, value.casefold())
            else:
                key = (str, value)
        elif isinstance(value, bool):
            key = (bool, value)
        else:
            continue
        candidate_groups.setdefault(key, []).append(value)
    values = [
        min(group_values, key=lambda item: (str(item).casefold(), str(item)))
        for group_values in candidate_groups.values()
    ]
    return sorted(
        values,
        key=lambda item: (type(item).__name__, str(item).casefold(), str(item)),
    )


def _merged_source_records(
    records: list[dict[str, Any]], *, exact_only: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    merge_fields = (
        "title",
        "kind",
        "publisher",
        "canonical_uri",
        "origin_host",
        "content_sha256",
        "access",
        "redistributable",
        "published_at",
        "available_at",
        "retrieved_at",
    )
    for group in _source_record_groups(records, exact_only=exact_only):
        ordered_group = sorted(group, key=lambda record: str(record.get("id", "unknown")))
        representative = dict(ordered_group[0])
        observation_ids = [str(record.get("id", "unknown")) for record in ordered_group]
        representative["id"] = observation_ids[0]
        representative["observation_count"] = len(group)
        representative["observation_ids"] = observation_ids
        for field in merge_fields:
            candidates = _metadata_candidates(group, field)
            if len(candidates) == 1:
                representative[field] = candidates[0]
            elif len(candidates) > 1:
                representative[field] = None
                representative[f"{field}_candidates"] = candidates
                conflicts.append(
                    {
                        "source_identity": _source_group_identity(group),
                        "field": field,
                        "values": candidates,
                        "observation_ids": observation_ids,
                    }
                )
        available_values = [
            value for record in group if (value := _declared_text(record.get("available_at"))) is not None
        ]
        published_values = [
            value for record in group if (value := _declared_text(record.get("published_at"))) is not None
        ]
        retrieved_values = [
            value for record in group if (value := _declared_text(record.get("retrieved_at"))) is not None
        ]
        representative["latest_usable_at"] = _timestamp_extreme(
            available_values or published_values,
            latest=True,
        )
        representative["first_retrieved_at"] = _timestamp_extreme(retrieved_values, latest=False)
        representative["latest_retrieved_at"] = _timestamp_extreme(retrieved_values, latest=True)
        merged.append(representative)
    return merged, sorted(
        conflicts,
        key=lambda item: (str(item["source_identity"]), str(item["field"])),
    )


def _deduplicated_source_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged, _ = _merged_source_records(records)
    return merged


def _unique_exact_source_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged, _ = _merged_source_records(records, exact_only=True)
    return merged


def _declared_counts(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    labels: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for record in records:
        label = _declared_text(record.get(field))
        if label is None:
            continue
        key = label.casefold()
        labels.setdefault(key, label)
        counts[key] += 1
    return {labels[key]: counts[key] for key in sorted(counts, key=lambda item: labels[item].casefold())}


def _source_concentration(records: list[dict[str, Any]]) -> dict[str, Any]:
    publisher_counts = _declared_counts(records, "publisher")
    attributed_count = sum(publisher_counts.values())
    unattributed_count = len(records) - attributed_count
    if not publisher_counts or attributed_count == 0:
        return {
            "status": "not_assessable",
            "top_publisher": None,
            "top_publisher_count": 0,
            "top_publisher_share": None,
            "publisher_attributed_record_count": 0,
            "publisher_unattributed_record_count": unattributed_count,
            "basis": "Exact declared publisher labels; editorial independence is not inferred.",
        }
    top_publisher, top_count = sorted(publisher_counts.items(), key=lambda item: (-item[1], item[0].casefold()))[0]
    share = top_count / attributed_count
    if len(publisher_counts) == 1:
        status = "single_publisher"
    elif share > 0.5:
        status = "concentrated"
    else:
        status = "distributed"
    return {
        "status": status,
        "top_publisher": top_publisher,
        "top_publisher_count": top_count,
        "top_publisher_share": round(share, 4),
        "publisher_attributed_record_count": attributed_count,
        "publisher_unattributed_record_count": unattributed_count,
        "basis": (
            "Share uses only distinct records with exact declared publisher labels; more than 50% is marked "
            "concentrated. Publisher-unattributed records are reported separately, and editorial independence "
            "is not inferred."
        ),
    }


def _document_is_accessible(value: Mapping[str, object]) -> bool:
    return _source_access_status(value) == "accessible"


def _coverage_rows(
    documents: list[dict[str, Any]],
    request: Mapping[str, object],
    dossier: Mapping[str, object],
) -> list[dict[str, Any]]:
    plan = _mapping(request.get("research_plan")) or {}
    dimensions = _record_sequence(plan.get("coverage_dimensions"))
    receipts = _record_sequence(dossier.get("coverage"))
    dimensions_by_area = {area: item for item in dimensions if (area := _declared_text(item.get("area"))) is not None}
    receipts_by_area = {area: item for item in receipts if (area := _declared_text(item.get("area"))) is not None}
    areas = list(dimensions_by_area)
    areas.extend(area for area in receipts_by_area if area not in dimensions_by_area)
    documents_by_id = {str(item["id"]): item for item in documents}
    rows: list[dict[str, Any]] = []
    for area in areas:
        dimension = dimensions_by_area.get(area, {})
        receipt = receipts_by_area.get(area, {})
        source_document_ids = tuple(
            dict.fromkeys(item for item in receipt.get("source_document_ids", ()) if isinstance(item, str) and item)
        )
        retained = [documents_by_id[item] for item in source_document_ids if item in documents_by_id]
        accessible = [item for item in retained if _document_is_accessible(item)]
        unique_retained = _unique_exact_source_records(retained)
        unique_accessible = [item for item in unique_retained if _document_is_accessible(item)]
        minimum = dimension.get("minimum_source_count")
        planned_minimum = minimum if isinstance(minimum, int) and not isinstance(minimum, bool) else None
        preferred_source_kinds = tuple(
            item for item in dimension.get("preferred_source_kinds", ()) if isinstance(item, str) and item
        )
        present_source_kinds = tuple(
            sorted({kind for item in unique_accessible if (kind := _declared_text(item.get("kind"))) is not None})
        )
        minimum_met = len(unique_accessible) >= planned_minimum if planned_minimum is not None else None
        preferred_kind_met = (
            bool(set(preferred_source_kinds).intersection(present_source_kinds)) if preferred_source_kinds else None
        )
        reported_status = _declared_text(receipt.get("status")) or "not_reported"
        verdict = reported_status
        if minimum_met is False:
            verdict = "insufficient"
        elif preferred_kind_met is False:
            verdict = "wrong_source_class"
        usable_timestamps = [
            value
            for item in unique_accessible
            if (
                value := _declared_text(
                    item.get("latest_usable_at") or item.get("available_at") or item.get("published_at")
                )
            )
            is not None
        ]
        latest_usable_at = _timestamp_extreme(usable_timestamps, latest=True)
        rows.append(
            {
                "area": area,
                "required": dimension.get("required") if isinstance(dimension.get("required"), bool) else None,
                "retained_document_count": len(retained),
                "accessible_document_count": len(accessible),
                "unique_accessible_source_count": len(unique_accessible),
                "planned_minimum": planned_minimum,
                "minimum_met": minimum_met,
                "publisher_diversity_count": len(_declared_counts(unique_accessible, "publisher")),
                "origin_host_count": len(_declared_counts(unique_accessible, "origin_host")),
                "preferred_source_kinds": list(preferred_source_kinds),
                "present_source_kinds": list(present_source_kinds),
                "preferred_kind_met": preferred_kind_met,
                "latest_usable_at": latest_usable_at,
                "reported_status": reported_status,
                "verdict": verdict,
                "source_document_ids": list(source_document_ids),
                "limitation": _declared_text(receipt.get("limitation")),
            }
        )
    return rows


def _claim_support(dossier: Mapping[str, object], documents: list[dict[str, Any]]) -> dict[str, Any]:
    claims = _record_sequence(dossier.get("claims"))
    metrics = _record_sequence(dossier.get("metrics"))
    metric_documents = {
        str(item["id"]): tuple(
            source_id for source_id in item.get("source_document_ids", ()) if isinstance(source_id, str)
        )
        for item in metrics
        if _declared_text(item.get("id")) is not None
    }
    documents_by_id = {str(item["id"]): item for item in documents}
    counts: Counter[str] = Counter()
    for claim in claims:
        direct_ids = [item for item in claim.get("evidence_document_ids", ()) if isinstance(item, str)]
        metric_ids = [item for item in claim.get("metric_ids", ()) if isinstance(item, str)]
        document_ids = tuple(
            dict.fromkeys(
                (*direct_ids, *(item for metric_id in metric_ids for item in metric_documents.get(metric_id, ())))
            )
        )
        supporting = [documents_by_id[item] for item in document_ids if item in documents_by_id]
        traceable_supporting = [item for item in supporting if _has_exact_source_identity(item)]
        unique_supporting = _unique_exact_source_records(supporting)
        unique_accessible = [item for item in unique_supporting if _document_is_accessible(item)]
        if document_ids:
            counts["explicitly_linked"] += 1
        else:
            counts["unlinked"] += 1
        if unique_accessible:
            counts["accessible_support"] += 1
        elif document_ids:
            counts["without_accessible_support"] += 1
        if len(traceable_supporting) > len(unique_supporting):
            counts["duplicate_support_references"] += 1
        if len(unique_accessible) == 1:
            counts["single_document"] += 1
        elif len(unique_accessible) >= 2:
            counts["multiple_document"] += 1
        if len(_declared_counts(unique_accessible, "publisher")) >= 2:
            counts["multiple_publishers"] += 1
        if len(_declared_counts(unique_accessible, "origin_host")) >= 2:
            counts["multiple_origin_hosts"] += 1
        if any(isinstance(item, str) and item for item in claim.get("counterevidence_document_ids", ())):
            counts["counterevidenced"] += 1
    return {
        "claim_count": len(claims),
        "explicitly_linked_claim_count": counts["explicitly_linked"],
        "unlinked_claim_count": counts["unlinked"],
        "claims_with_accessible_support": counts["accessible_support"],
        "claims_without_accessible_support": counts["without_accessible_support"],
        "single_document_claim_count": counts["single_document"],
        "multiple_document_claim_count": counts["multiple_document"],
        "claims_with_duplicate_support_references": counts["duplicate_support_references"],
        "multiple_publisher_claim_count": counts["multiple_publishers"],
        "multiple_origin_host_claim_count": counts["multiple_origin_hosts"],
        "counterevidenced_claim_count": counts["counterevidenced"],
    }


def _linked_verification_category(value: Mapping[str, object]) -> str:
    status = (_declared_text(value.get("verification_status")) or "").casefold()
    for category, statuses in _LINK_VERIFICATION_GROUPS.items():
        if status in statuses:
            return category
    return "unverified"


def _opened_attributable_link_count(records: list[dict[str, Any]]) -> int:
    count = 0
    for group in _source_record_groups(records, exact_only=True):
        merged, _ = _merged_source_records(group, exact_only=True)
        source = merged[0]
        has_qualifying_status = any(
            (_declared_text(item.get("verification_status")) or "").casefold() in _OPENED_LINK_STATUSES
            for item in group
        )
        if (
            _source_access_status(source) == "accessible"
            and _declared_text(source.get("canonical_uri")) is not None
            and has_qualifying_status
        ):
            count += 1
    return count


def _source_analysis(result: RunResult, news: list[dict[str, Any]]) -> dict[str, Any]:
    dossier = _completed_research_dossier(result) or {}
    request = _completed_research_request(result) or {}
    raw_documents = next(
        (
            records
            for key in ("documents", "source_documents", "sources")
            if (records := _record_sequence(dossier.get(key)))
        ),
        [],
    )
    if raw_documents:
        documents = [_document_source_record(item, ordinal) for ordinal, item in enumerate(raw_documents)]
        document_basis = "completed_research_dossier"
    else:
        documents = [_evidence_source_record(item, ordinal) for ordinal, item in enumerate(result.evidence)]
        document_basis = "run_evidence"
    linked_sources = [_linked_source_record(item, ordinal) for ordinal, item in enumerate(news)]
    observations = [*documents, *linked_sources]
    unique_records, metadata_conflicts = _merged_source_records(observations)
    unique_traceable_records, _ = _merged_source_records(observations, exact_only=True)
    publisher_counts = _declared_counts(unique_records, "publisher")
    host_counts = _declared_counts(unique_records, "origin_host")
    retrieval_provider_counts = _declared_counts(observations, "retrieval_provider")
    dossier_schema = _declared_text(dossier.get("schema_version"))
    independence_status = "unsupported_by_v3_contract" if dossier_schema == "2026-08-03.v3" else "not_declared"
    canonical_uris = [uri for item in observations if (uri := _declared_text(item.get("canonical_uri"))) is not None]
    content_hashes = [
        digest for item in observations if (digest := _normalized_sha256(item.get("content_sha256"))) is not None
    ]
    coverage_rows = _coverage_rows(documents, request, dossier)
    claim_support = _claim_support(dossier, documents)
    claim_support["independence_note"] = (
        "The strict v3 dossier cannot declare ownership or editorial-control groups. Publisher and host "
        "diversity are separate observable proxies, not independence evidence."
        if independence_status == "unsupported_by_v3_contract"
        else "No versioned ownership or editorial-control receipt was retained; publisher and host diversity "
        "remain separate proxies."
    )
    concentration = _source_concentration(unique_records)
    document_access_counts = Counter(_source_access_status(item) for item in documents)
    document_traceability_counts = Counter(_source_traceability_status(item) for item in documents)
    linked_access_counts = Counter(_source_access_status(item) for item in linked_sources)
    linked_verification_counts = Counter(_linked_verification_category(item) for item in linked_sources)
    opened_attributable_link_count = _opened_attributable_link_count(linked_sources)
    gaps: list[dict[str, str]] = []

    def gap(severity: str, area: str, finding: str, next_source_class: str) -> None:
        candidate = {
            "severity": severity,
            "area": area,
            "finding": finding,
            "next_source_class": next_source_class,
        }
        if candidate not in gaps:
            gaps.append(candidate)

    if not documents:
        gap("critical", "all", "No source-document record was retained.", "Canonical source documents")
    elif document_traceability_counts["canonical"] == 0:
        gap(
            "warning",
            "all",
            (
                "No retained document record carries both a canonical web URI and a valid content digest; "
                "legacy evidence cannot be treated as canonical."
            ),
            "Canonical source documents with URL, digest, and entitlement receipt",
        )
    if document_access_counts["access_unknown"]:
        gap(
            "warning",
            "all",
            (
                f"{document_access_counts['access_unknown']} retained document records have no explicit "
                "access or entitlement receipt."
            ),
            "Explicit public, licensed, or blocked entitlement receipts",
        )
    if metadata_conflicts:
        conflicting_fields = ", ".join(sorted({str(item["field"]) for item in metadata_conflicts}))
        gap(
            "warning",
            "source_metadata",
            (
                f"{len(metadata_conflicts)} conflicting source-metadata declarations were retained across "
                f"these fields: {conflicting_fields}. No conflicting value was selected as authoritative."
            ),
            "A reconciled source-identity and metadata receipt",
        )
    if concentration["status"] in {"single_publisher", "concentrated"} and len(unique_records) > 1:
        share = concentration["top_publisher_share"]
        share_text = f"{round(float(share) * 100)}%" if isinstance(share, float | int) else "most"
        gap(
            "warning",
            "all",
            (
                f"{share_text} of publisher-attributed distinct records use the publisher label "
                f"{concentration['top_publisher']}."
            ),
            "A differently controlled source with a declared ownership or editorial-control group",
        )
    if unique_records:
        gap(
            "information",
            "all",
            (
                "The strict v3 dossier has no ownership or editorial-control field; publisher and hostname "
                "diversity cannot prove independence."
                if independence_status == "unsupported_by_v3_contract"
                else "No versioned ownership or editorial-control receipt was retained."
            ),
            "A versioned source-portfolio ownership/control receipt",
        )
    for row in coverage_rows:
        required = row["required"] is True
        if row["minimum_met"] is False:
            gap(
                "critical" if required else "warning",
                str(row["area"]),
                (
                    f"{row['unique_accessible_source_count']} unique accessible sources were retained against "
                    f"a planned minimum of {row['planned_minimum']} "
                    f"({row['accessible_document_count']} accessible document records before deduplication)."
                ),
                ", ".join(row["preferred_source_kinds"]) or "An additional accessible source document",
            )
        if row["preferred_kind_met"] is False:
            gap(
                "critical" if required else "warning",
                str(row["area"]),
                "The retained documents do not include a planned preferred source kind.",
                ", ".join(row["preferred_source_kinds"]),
            )
        if required and row["reported_status"] in {
            "partial",
            "missing",
            "stale",
            "conflicting",
            "entitlement_blocked",
            "limited",
        }:
            gap(
                "critical",
                str(row["area"]),
                row["limitation"] or f"Required coverage is reported as {row['reported_status']}.",
                ", ".join(row["preferred_source_kinds"]) or "Coverage-plan-compliant evidence",
            )
    if claim_support["unlinked_claim_count"]:
        gap(
            "critical" if claim_support["unlinked_claim_count"] == claim_support["claim_count"] else "warning",
            "claims",
            f"{claim_support['unlinked_claim_count']} claims have no explicit document or metric lineage.",
            "Explicit claim-to-document references",
        )
    if claim_support["claims_without_accessible_support"]:
        gap(
            "critical",
            "claims",
            f"{claim_support['claims_without_accessible_support']} claims reference no accessible supporting document.",
            "Accessible supporting documents",
        )
    if linked_sources and opened_attributable_link_count == 0:
        gap(
            "warning",
            "linked_reporting",
            (
                "No linked reporting item has the combined canonical URL, allowed-access receipt, and "
                "opened or attributable verification status required for source use."
            ),
            "Opened and entitlement-checked publisher sources",
        )

    has_plan = any(row["planned_minimum"] is not None for row in coverage_rows)
    required_failure = any(
        row["required"] is True
        and (
            row["minimum_met"] is False
            or row["preferred_kind_met"] is False
            or row["reported_status"]
            in {"partial", "missing", "stale", "conflicting", "entitlement_blocked", "limited"}
        )
        for row in coverage_rows
    )
    if required_failure:
        coverage_verdict = "insufficient"
    elif not has_plan:
        coverage_verdict = "unassessed"
    else:
        coverage_verdict = "sufficient_by_declared_plan"
    document_label = "document" if len(documents) == 1 else "documents"
    linked_label = "item" if len(linked_sources) == 1 else "items"
    publisher_label = "publisher" if len(publisher_counts) == 1 else "publishers"
    host_label = "host" if len(host_counts) == 1 else "hosts"
    summary = (
        f"{len(documents)} retained {document_label} include {document_traceability_counts['canonical']} canonical, "
        f"{document_access_counts['accessible']} accessible, {document_access_counts['blocked']} blocked, and "
        f"{document_access_counts['access_unknown']} access-unknown records. "
        f"{len(linked_sources)} linked source {linked_label} were retained "
        f"across {len(publisher_counts)} declared {publisher_label} and "
        f"{len(host_counts)} origin {host_label}. "
        + (
            "No coverage plan was available, so coverage is unassessed."
            if not has_plan
            else f"The declared-plan coverage verdict is {coverage_verdict.replace('_', ' ')}."
        )
    )
    return {
        "verdict": coverage_verdict,
        "coverage_verdict": coverage_verdict,
        "summary": summary,
        "basis": {
            "documents": document_basis,
            "coverage_plan": "research_plan" if has_plan else "not_declared",
            "source_identity": (
                "Canonical requires both a safe canonical web URI and a valid SHA-256 digest. Coverage and "
                "claim-source counts are deduplicated by exact URI or digest."
            ),
            "retrieval_providers": (
                "Exact Provenance.provider labels from legacy run evidence."
                if document_basis == "run_evidence"
                else "Not declared by the strict v3 dossier; publisher labels are not retrieval providers."
            ),
            "independence": (
                (
                    "Unsupported by the strict v3 dossier. A versioned ownership/control receipt is required; "
                    "publisher and origin-host diversity remain separate proxies."
                )
                if independence_status == "unsupported_by_v3_contract"
                else (
                    "No versioned ownership/control receipt was retained; publisher and origin-host diversity "
                    "remain separate proxies."
                )
            ),
        },
        "totals": {
            "retained_document_record_count": len(documents),
            "canonical_document_count": document_traceability_counts["canonical"],
            "attributable_document_count": document_traceability_counts["attributable"],
            "unattributable_document_count": document_traceability_counts["unattributable"],
            "accessible_document_count": document_access_counts["accessible"],
            "blocked_document_count": document_access_counts["blocked"],
            "access_unknown_document_count": document_access_counts["access_unknown"],
            "linked_source_item_count": len(linked_sources),
            "linked_accessible_count": linked_access_counts["accessible"],
            "linked_blocked_count": linked_access_counts["blocked"],
            "linked_access_unknown_count": linked_access_counts["access_unknown"],
            "opened_attributable_link_count": opened_attributable_link_count,
            "primary_confirmed_link_count": linked_verification_counts["primary_confirmed"],
            "multi_source_confirmed_link_count": linked_verification_counts["multi_source_confirmed"],
            "single_source_reported_link_count": linked_verification_counts["single_source_reported"],
            "discovery_only_link_count": linked_verification_counts["discovery_only"],
            "unverified_link_count": linked_verification_counts["unverified"],
            "unique_retained_source_count": len(unique_records),
            "unique_traceable_source_count": len(unique_traceable_records),
            "source_metadata_conflict_count": len(metadata_conflicts),
            "unique_canonical_uri_count": len(set(canonical_uris)),
            "duplicate_uri_count": len(canonical_uris) - len(set(canonical_uris)),
            "unique_content_sha256_count": len(set(content_hashes)),
            "duplicate_content_count": len(content_hashes) - len(set(content_hashes)),
            "declared_publisher_count": len(publisher_counts),
            "undeclared_publisher_record_count": len(unique_records) - sum(publisher_counts.values()),
            "origin_host_count": len(host_counts),
            "undeclared_origin_host_record_count": len(unique_records) - sum(host_counts.values()),
            "retrieval_provider_count": len(retrieval_provider_counts),
            "undeclared_retrieval_provider_record_count": (len(observations) - sum(retrieval_provider_counts.values())),
        },
        "publisher_counts": publisher_counts,
        "origin_host_counts": host_counts,
        "retrieval_provider_counts": retrieval_provider_counts,
        "document_kind_counts": _declared_counts(documents, "kind"),
        "document_traceability_counts": dict(document_traceability_counts),
        "document_access_counts": dict(document_access_counts),
        "linked_quality_counts": _declared_counts(linked_sources, "source_quality"),
        "linked_verification_counts": dict(linked_verification_counts),
        "linked_access_counts": dict(linked_access_counts),
        "source_metadata_conflicts": metadata_conflicts,
        "independence": {
            "status": independence_status,
            "contract_support": False,
            "required_receipt": "versioned_source_portfolio_ownership_receipt",
            "declared_group_count": 0,
            "declared_group_counts": {},
            "undeclared_record_count": len(unique_records),
        },
        "concentration": concentration,
        "coverage_rows": coverage_rows,
        "claim_support": claim_support,
        "gaps": gaps,
    }


def _intelligence_projection(result: RunResult) -> dict[str, Any]:
    source_qualities = Counter(_source_quality(item) for item in result.evidence)
    categories = Counter(item.category for item in result.evidence)
    completed_dossier = _completed_research_dossier(result) or {}
    strict_v3_dossier = completed_dossier.get("schema_version") == "2026-08-03.v3"
    providers = (
        Counter({"undeclared": len(result.evidence)})
        if strict_v3_dossier and result.evidence
        else Counter(item.provenance.provider or "unknown" for item in result.evidence)
    )
    source_types = Counter(item.provenance.source_type or "unknown" for item in result.evidence)
    source_urls = [
        source_url for item in result.evidence if (source_url := _safe_web_url(item.provenance.source_uri)) is not None
    ]
    source_dates = [item.provenance.source_date for item in result.evidence if item.provenance.source_date]
    retrieved_dates = [item.provenance.retrieved_at for item in result.evidence if item.provenance.retrieved_at]
    oldest_source_date = min(source_dates, default=None)
    latest_source_date = max(source_dates, default=None)

    news: list[dict[str, Any]] = []
    for item in result.evidence:
        for article in _normalize_records(item, "articles", "headline"):
            if article.get("source_quality") not in SOURCE_QUALITY_VOCABULARY:
                article["source_quality"] = _source_quality(item)
            for url_key in ("url", "source_url"):
                if url_key in article:
                    safe_url = _safe_web_url(article[url_key])
                    if safe_url is None:
                        article.pop(url_key)
                    else:
                        article[url_key] = safe_url
                        source_urls.append(safe_url)
            news.append(article)

    risk_register = [record for item in result.evidence for record in _normalize_records(item, "risks", "risk")]
    risk_register.extend(
        {"risk": constraint, "source": "risk_decision.constraints"} for constraint in result.risk_decision.constraints
    )
    unknowns = [record for item in result.evidence for record in _normalize_records(item, "unknowns", "unknown")]
    unknowns.extend(
        {"unknown": unresolved, "source": "risk_decision.unresolved"} for unresolved in result.risk_decision.unresolved
    )
    monitoring_conditions = [
        record for item in result.evidence for record in _normalize_records(item, "monitoring_conditions", "condition")
    ]

    return {
        "coverage": {
            "evidence_count": len(result.evidence),
            "analyst_count": len(result.analyst_reports),
            "limitation_count": sum(len(item.limitations) for item in result.evidence),
            "source_url_count": len(source_urls),
            "dated_source_count": len(source_dates),
            "source_quality_buckets": dict(sorted(source_qualities.items())),
            "unrecognized_source_quality_count": sum(
                _has_unrecognized_source_quality(item) for item in result.evidence
            ),
        },
        "source_mix": {
            "categories": dict(sorted(categories.items())),
            "providers": dict(sorted(providers.items())),
            "provider_basis": (
                "undeclared_by_strict_v3_dossier" if strict_v3_dossier else "evidence_provenance_provider"
            ),
            "source_types": dict(sorted(source_types.items())),
        },
        "freshness": {
            "cutoff": result.request.as_of_date,
            "oldest_source_date": oldest_source_date,
            "latest_source_date": latest_source_date,
            "source_history_days": _date_distance_days(oldest_source_date, latest_source_date),
            "latest_source_lag_days": _date_distance_days(latest_source_date, result.request.as_of_date),
            "oldest_retrieved_at": _timestamp_extreme(retrieved_dates, latest=False),
            "latest_retrieved_at": _timestamp_extreme(retrieved_dates, latest=True),
        },
        "evidence_metrics": [record for item in result.evidence for record in _normalize_metrics(item)],
        "news": news,
        "catalysts": [
            record for item in result.evidence for record in _normalize_records(item, "catalysts", "catalyst")
        ],
        "risk_register": risk_register,
        "conflicts": [
            record for item in result.evidence for record in _normalize_records(item, "conflicts", "conflict")
        ],
        "unknowns": unknowns,
        "monitoring_conditions": monitoring_conditions,
        "source_analysis": _source_analysis(result, news),
    }


def build_run_view(
    result: RunResult,
    events: tuple[RunEvent, ...],
    *,
    quality_projection: Mapping[str, object] | None = None,
) -> RunView:
    """Expose every RunResult section without collapsing its meanings."""
    semantics = build_completed_run_semantics(result, events).to_dict() if result.status.value == "completed" else None
    persistence = result.persistence.to_dict()
    capability = result.capability.to_dict()
    checkpoint = result.persistence.checkpoint_enabled
    completed = result.status.value == "completed"
    artifacts = [artifact.to_dict() for artifact in result.artifacts]
    artifact_ids = {artifact.id for artifact in result.artifacts}
    request = result.request.to_dict()
    # Adapter configuration may contain provider credentials.  The view keeps
    # the field visible while never reflecting its values.
    request["legacy_config"] = {
        "configured": bool(result.request.legacy_config),
        "keys": sorted(result.request.legacy_config),
        "values_redacted": bool(result.request.legacy_config),
    }

    payload: dict[str, Any] = {
        "schema_version": result.schema_version,
        "ok": True,
        "run_id": result.run_id,
        "overview": {
            "symbol": result.request.symbol,
            "company_of_interest": result.instrument.company_of_interest or result.request.symbol,
            "instrument_context": result.instrument.instrument_context,
            "as_of_date": result.request.as_of_date,
            "trade_date": result.instrument.trade_date or result.request.as_of_date,
            "asset_type": result.request.asset_type,
            "status": result.status.value,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "prototype_notice": result.prototype_notice,
            "warnings": list(result.warnings),
        },
        "semantics": semantics,
        "request": request,
        "execution_config": result.execution_config.to_dict(),
        "topology": result.topology.to_dict(),
        "evidence": [item.to_dict() for item in result.evidence],
        "intelligence": _intelligence_projection(result),
        "research_request": _completed_research_request(result),
        "research_dossier": _completed_research_dossier(result),
        "research_lab": {
            "analytics": _completed_artifact_content(result, "analytics_bundle.v1"),
            "run_card": _completed_artifact_content(result, "run_card.v1"),
            "hypotheses": _completed_artifact_content(result, "hypothesis_ledger.v1"),
            "iterations": _completed_artifact_content(result, "research_iterations.v1"),
            "quality": _completed_artifact_content(result, "research_quality.v1"),
            "forecasts": _completed_artifact_content(result, "forecast_set.v1"),
            "quality_history": dict(quality_projection) if completed and quality_projection is not None else None,
        },
        "analyst_reports": [report.to_dict() for report in result.analyst_reports],
        "report_sections": result.report_sections.to_dict(),
        "reports": {
            "groups": report_groups(result.artifacts),
            "complete_artifact_id": "report.complete" if "report.complete" in artifact_ids else None,
        },
        "debates": {
            "research": {
                "turns": [turn.to_dict() for turn in result.research_debate],
                "snapshot": result.research_debate_snapshot.to_dict(),
            },
            "risk": {
                "turns": [turn.to_dict() for turn in result.risk_debate],
                "snapshot": result.risk_debate_snapshot.to_dict(),
            },
        },
        "decisions": {
            "research": result.research_decision.to_dict(),
            "trader": result.trader_decision.to_dict(),
            "risk": result.risk_decision.to_dict(),
            "portfolio": result.portfolio_decision.to_dict(),
        },
        "outputs": {
            "investment_plan": result.investment_plan,
            "trader_investment_plan": result.trader_investment_plan,
            "portfolio_manager_decision": result.portfolio_manager_decision,
            "final_trade_decision": result.final_trade_decision,
        },
        "signal": {
            "processed_signal": result.processed_signal,
            "source": "portfolio_rating",
            "meaning": "Derived from the Portfolio Manager rating; it is research output, never an order.",
            "executable": False,
            "execution_authority": "none",
            "submitted": False,
        },
        "persistence": {
            "metadata": persistence,
            "badges": [
                _badge("Decision memory", result.persistence.decision_memory_enabled, "info", "Executor behavior"),
                _badge("Run logging", result.persistence.run_logging_enabled, "info", "Executor behavior"),
                _badge(
                    "Checkpoint resume",
                    checkpoint,
                    "enabled" if checkpoint else "muted",
                    "Opt-in; disabled by default",
                ),
                _badge(
                    "Writes expected",
                    result.persistence.writes_expected,
                    "warning" if result.persistence.writes_expected else "safe",
                    ", ".join(result.persistence.outputs) or "No declared outputs",
                ),
            ],
        },
        "capability": {
            "metadata": capability,
            "badges": [
                _badge("Executor", result.capability.executor, "info", result.capability.observation_mode),
                _badge("Deterministic", result.capability.deterministic, "safe", "Replay characteristic"),
                _badge("Live data", result.capability.live_data, "warning", "Data-source characteristic"),
                _badge(
                    "Portable boundary credentials",
                    result.capability.portable_boundary_credentials_required,
                    "warning" if result.capability.portable_boundary_credentials_required else "safe",
                    "The portable host-plan/import boundary never accepts credentials",
                ),
                _badge("Host tool auth", result.capability.host_tool_auth, "info", "Owned by the selected harness"),
                _badge("Execution authority", "none", "safe", "No broker or order surface exists"),
            ],
        },
        "events": [event.to_dict() for event in events],
        "artifacts": artifacts,
        "actions": [
            {
                "id": "view_complete_report",
                "available": "report.complete" in artifact_ids,
                "reason": "Available from the canonical in-memory report bundle."
                if "report.complete" in artifact_ids
                else "No complete-report artifact was produced.",
            },
            {
                "id": "resume",
                "available": checkpoint and not completed,
                "reason": "Resume requires an opted-in checkpoint and an incomplete run."
                if not (checkpoint and not completed)
                else "An incomplete checkpoint-enabled run can be resumed by its executor.",
            },
            {
                "id": "cancel",
                "available": not completed,
                "reason": "Completed runs cannot be cancelled." if completed else "Run is still active.",
            },
        ],
    }
    return RunView(payload)
