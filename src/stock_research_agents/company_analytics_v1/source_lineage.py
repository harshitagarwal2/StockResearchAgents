"""Provider-neutral inward source lineage for completed analytics publications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from stock_research_agents.analytics_v1.common import validate_digest
from stock_research_agents.research_contracts import (
    StrictModel,
    _validate_id,
    _validate_public_uri,
)

SOURCE_LINEAGE_SCHEMA_VERSION = "source-lineage-crosswalk.v1"


@dataclass(frozen=True, slots=True)
class SourceLineageBindingV1(StrictModel):
    """One identity-preserving link from caller observation to retained evidence."""

    binding_id: str
    source_batch_id: str
    source_observation_id: str
    content_sha256_scope: Literal["source_content", "bounded_extract", "normalized_source_record"]
    content_sha256: str
    canonical_uri: str
    license_receipt_id: str
    dossier_document_id: str
    analytics_source_id: str
    analytics_license_receipt_id: str
    entitlement_access: Literal["public", "licensed", "entitlement_blocked"]
    redistributable: bool
    terms_uri: str | None

    def __post_init__(self) -> None:
        for path, value in (
            ("binding_id", self.binding_id),
            ("source_batch_id", self.source_batch_id),
            ("source_observation_id", self.source_observation_id),
            ("license_receipt_id", self.license_receipt_id),
            ("dossier_document_id", self.dossier_document_id),
            ("analytics_source_id", self.analytics_source_id),
            ("analytics_license_receipt_id", self.analytics_license_receipt_id),
        ):
            _validate_id(value, path)
        validate_digest(self.content_sha256, "content_sha256")
        _validate_public_uri(self.canonical_uri, "canonical_uri")
        if self.terms_uri is not None:
            _validate_public_uri(self.terms_uri, "terms_uri")
        if self.entitlement_access == "entitlement_blocked" and self.redistributable:
            raise ValueError("entitlement-blocked lineage cannot be redistributable")


@dataclass(frozen=True, slots=True)
class SourceLineageCrosswalkV1(StrictModel):
    """Complete source identity and entitlement bridge for one analytics publication."""

    schema_version: Literal["source-lineage-crosswalk.v1"]
    bindings: tuple[SourceLineageBindingV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SOURCE_LINEAGE_SCHEMA_VERSION:
            raise ValueError("unsupported source lineage crosswalk version")
        if not self.bindings:
            raise ValueError("source lineage crosswalk requires at least one binding")
        unique_groups = (
            ("binding IDs", tuple(item.binding_id for item in self.bindings)),
            (
                "source observations within a batch",
                tuple((item.source_batch_id, item.source_observation_id) for item in self.bindings),
            ),
            ("dossier document IDs", tuple(item.dossier_document_id for item in self.bindings)),
            ("analytics source IDs", tuple(item.analytics_source_id for item in self.bindings)),
            (
                "analytics license receipt IDs",
                tuple(item.analytics_license_receipt_id for item in self.bindings),
            ),
        )
        for label, values in unique_groups:
            if len(values) != len(set(values)):
                raise ValueError(f"source lineage {label} must be unique")


__all__ = [
    "SOURCE_LINEAGE_SCHEMA_VERSION",
    "SourceLineageBindingV1",
    "SourceLineageCrosswalkV1",
]
