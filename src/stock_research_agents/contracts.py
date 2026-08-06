"""Small shared wire primitives for the independent analytics product."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = "1.0.0"
PROTOTYPE_NOTICE = (
    "Prototype research output only. Not financial advice and never an order, "
    "broker instruction, or authorization to trade."
)

SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "credential",
    "password",
    "private_key",
    "privatekey",
)
SECRET_KEY_WORDS = frozenset({"bearer", "cookie", "secret", "token"})


def reject_secret_shaped_keys(value: object, path: tuple[str, ...] = ()) -> None:
    """Reject credential-shaped mapping keys at any nesting depth."""
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            words = set(key.split("_"))
            authorization_header = key in {
                "authorization",
                "authorization_header",
                "http_authorization",
                "http_authorization_header",
            } or key.startswith("authorization_")
            if (
                any(marker in key for marker in SECRET_KEY_MARKERS)
                or bool(words & SECRET_KEY_WORDS)
                or authorization_header
            ):
                location = ".".join((*path, str(raw_key)))
                raise ValueError(f"credential-shaped config key is forbidden: {location}")
            reject_secret_shaped_keys(nested, (*path, str(raw_key)))
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            reject_secret_shaped_keys(nested, (*path, str(index)))


class WireEnum(StrEnum):
    pass


class RunStatus(WireEnum):
    COMPLETED = "completed"


class EventKind(WireEnum):
    RUN = "run"
    STAGE = "stage"
    ARTIFACT = "artifact"
    WARNING = "warning"


class SupportLevel(WireEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    OPTIONAL = "optional"
    UNAVAILABLE = "unavailable"
    PROHIBITED = "prohibited"


@dataclass(frozen=True, slots=True)
class Contract:
    schema_version: str = field(default=SCHEMA_VERSION, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            item.name: _wire_value(getattr(self, item.name))
            for item in fields(self)
            if not item.metadata.get("ephemeral", False)
        }


def _wire_value(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _wire_value(getattr(value, item.name))
            for item in fields(value)
            if not item.metadata.get("ephemeral", False)
        }
    if isinstance(value, WireEnum):
        return value.value
    if isinstance(value, tuple):
        return tuple(_wire_value(item) for item in value)
    if isinstance(value, list):
        return [_wire_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _wire_value(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class CapabilityFeature(Contract):
    name: str = ""
    level: SupportLevel = SupportLevel.SUPPORTED
    detail: str = ""


@dataclass(frozen=True, slots=True)
class FeatureCapabilityMatrix(Contract):
    capability: str = "stock-research-agents"
    prototype: bool = True
    default_profile: str = "company-analytics.v1"
    features: tuple[CapabilityFeature, ...] = ()
    runtime_readiness: dict[str, Any] = field(default_factory=dict)
    safety_notice: str = PROTOTYPE_NOTICE


@dataclass(frozen=True, slots=True)
class Artifact(Contract):
    id: str = ""
    kind: str = ""
    title: str = ""
    media_type: str = "application/json"
    content: Any = None


@dataclass(frozen=True, slots=True)
class RunEvent(Contract):
    id: str = ""
    run_id: str = ""
    sequence: int = 0
    timestamp: str = ""
    kind: EventKind = EventKind.RUN
    stage_id: str | None = None
    status: str = ""
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SetupGuidance(Contract):
    code: str = "executor_unavailable"
    message: str = ""
    steps: tuple[str, ...] = ()
    retryable: bool = False
