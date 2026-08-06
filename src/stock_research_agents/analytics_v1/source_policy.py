"""Machine-use and redistribution policy receipts for source evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from stock_research_agents.research_contracts import StrictModel, _bounded_text, _utc_timestamp, _validate_id

from .common import validate_digest


@dataclass(frozen=True, slots=True)
class SourceLicenseReceipt(StrictModel):
    receipt_id: str
    source_id: str
    access: Literal["public", "licensed", "entitlement_blocked"]
    permitted_purpose: Literal["research", "personal_research", "commercial_research", "none", "unknown"]
    machine_use: Literal["allowed", "denied", "unknown"]
    retention_days: int | None
    derived_data_rights: Literal["allowed", "restricted", "denied", "unknown"]
    redistribution: Literal["allowed", "bounded_extract", "reference_only", "denied", "unknown"]
    terms_uri: str | None
    checked_at: str
    policy_sha256: str
    limitation: str | None

    def __post_init__(self) -> None:
        _validate_id(self.receipt_id, "receipt_id")
        _validate_id(self.source_id, "source_id")
        if self.retention_days is not None and not 0 <= self.retention_days <= 36_500:
            raise ValueError("retention_days must be between zero and 36500")
        if self.terms_uri is not None and not self.terms_uri.startswith("https://"):
            raise ValueError("terms_uri must be an https URI")
        _utc_timestamp(self.checked_at, "checked_at")
        validate_digest(self.policy_sha256, "policy_sha256")
        blocked = self.access == "entitlement_blocked" or self.machine_use == "denied"
        if blocked and not self.limitation:
            raise ValueError("blocked or machine-use-denied sources require a limitation")
        if self.limitation is not None:
            _bounded_text(self.limitation, "limitation", 1_000)
