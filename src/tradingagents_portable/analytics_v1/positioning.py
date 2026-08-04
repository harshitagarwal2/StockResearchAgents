"""Ownership, insider-activity, and short-interest observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tradingagents_portable.research_contracts import StrictModel, _bounded_text, _utc_timestamp, _validate_id

from .common import validate_decimal


@dataclass(frozen=True, slots=True)
class OwnershipSnapshot(StrictModel):
    snapshot_id: str
    holder_type: Literal["institutional", "insider", "government", "public", "other"]
    as_of_at: str
    available_at: str
    shares_held: str
    shares_outstanding: str
    ownership_percent: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.snapshot_id, "snapshot_id")
        as_of = _utc_timestamp(self.as_of_at, "as_of_at")
        if _utc_timestamp(self.available_at, "available_at") < as_of:
            raise ValueError("ownership available_at must not precede as_of_at")
        for name in ("shares_held", "shares_outstanding", "ownership_percent"):
            validate_decimal(getattr(self, name), name)
        if not self.source_ids:
            raise ValueError("ownership snapshot requires source IDs")


@dataclass(frozen=True, slots=True)
class InsiderTransaction(StrictModel):
    transaction_id: str
    insider_name: str
    role: str
    transaction_type: Literal["purchase", "sale", "grant", "exercise", "gift", "other"]
    transaction_at: str
    available_at: str
    shares: str
    price: str | None
    source_id: str
    automatic_plan: bool | None

    def __post_init__(self) -> None:
        _validate_id(self.transaction_id, "transaction_id")
        _bounded_text(self.insider_name, "insider_name", 256)
        _bounded_text(self.role, "role", 128)
        transaction = _utc_timestamp(self.transaction_at, "transaction_at")
        if _utc_timestamp(self.available_at, "available_at") < transaction:
            raise ValueError("insider transaction available_at must not precede transaction_at")
        validate_decimal(self.shares, "shares")
        if self.price is not None:
            validate_decimal(self.price, "price")
        _validate_id(self.source_id, "source_id")


@dataclass(frozen=True, slots=True)
class ShortInterestSnapshot(StrictModel):
    snapshot_id: str
    settlement_at: str
    available_at: str
    shares_short: str
    float_shares: str
    short_percent_float: str
    average_daily_volume: str
    days_to_cover: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.snapshot_id, "snapshot_id")
        settlement = _utc_timestamp(self.settlement_at, "settlement_at")
        if _utc_timestamp(self.available_at, "available_at") < settlement:
            raise ValueError("short-interest availability must not precede settlement")
        for name in (
            "shares_short",
            "float_shares",
            "short_percent_float",
            "average_daily_volume",
            "days_to_cover",
        ):
            validate_decimal(getattr(self, name), name)
        if not self.source_ids:
            raise ValueError("short-interest snapshot requires source IDs")
