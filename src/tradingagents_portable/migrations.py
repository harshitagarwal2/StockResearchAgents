"""Copy-on-write migrations for persisted public TradingAgents artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .contracts import SCHEMA_VERSION

HISTORICAL_SCHEMA_VERSION = "2026-08-02"
SUPPORTED_SCHEMA_VERSIONS = frozenset({HISTORICAL_SCHEMA_VERSION, SCHEMA_VERSION})

ArtifactKind = Literal[
    "run_result",
    "run_event",
    "run_events",
    "durable_bundle",
    "export_bundle",
    "decision_memory_row",
    "decision_memory_schema",
]

_BASE_MIGRATION_ID = "schema.2026-08-02-to-2026-08-03"
_RESEARCH_MIGRATION_ID = "research-decision.2026-08-02-to-2026-08-03"
_TRADER_MIGRATION_ID = "trader-decision.2026-08-02-to-2026-08-03"
_PORTFOLIO_MIGRATION_ID = "portfolio-decision.2026-08-02-to-2026-08-03"
_RECEIPT_VERSION = "tradingagents-portable-migration-receipt-v1"
_RECOMMENDATIONS = frozenset({"buy", "overweight", "hold", "underweight", "sell"})
_TRADER_ACTIONS = frozenset({"buy", "hold", "sell"})
_RUN_RESULT_TYPED_SCHEMA_FIELDS = frozenset(
    {
        "capability",
        "execution_config",
        "instrument",
        "persistence",
        "report_sections",
        "request",
        "research_debate_snapshot",
        "risk_debate_snapshot",
        "risk_decision",
        "topology",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    source_schema: str
    target_schema: str
    artifact_kind: ArtifactKind
    before_sha256: str
    after_sha256: str
    migration_ids: tuple[str, ...]
    timestamp: str
    original_path: str | None = None
    migrated_path: str | None = None
    receipt_version: str = _RECEIPT_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt_version": self.receipt_version,
            "source_schema": self.source_schema,
            "target_schema": self.target_schema,
            "artifact_kind": self.artifact_kind,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "migration_ids": list(self.migration_ids),
            "timestamp": self.timestamp,
            "original_path": self.original_path,
            "migrated_path": self.migrated_path,
        }


@dataclass(frozen=True, slots=True)
class MigratedArtifact:
    payload: object
    receipt: MigrationReceipt


def _schema_from_payload(payload: object, artifact_kind: ArtifactKind) -> str:
    if artifact_kind == "run_events":
        if not isinstance(payload, list) or not payload:
            raise ValueError("run event arrays must be non-empty to determine their schema")
        if not all(isinstance(item, Mapping) for item in payload):
            raise ValueError("run event arrays must contain only objects")
        raw_schemas = [item.get("schema_version") for item in payload]
        if not all(isinstance(item, str) for item in raw_schemas):
            raise ValueError("run event arrays must contain one explicit schema version")
        schemas = set(raw_schemas)
        if len(schemas) != 1:
            raise ValueError("run event arrays must contain one explicit schema version")
        schema = next(iter(schemas))
    elif artifact_kind == "durable_bundle":
        if not isinstance(payload, Mapping) or not isinstance(payload.get("result"), Mapping):
            raise ValueError("durable bundle must contain a result object")
        schema = payload["result"].get("schema_version")
    elif artifact_kind == "decision_memory_row":
        if not isinstance(payload, Mapping):
            raise ValueError("decision memory row must be an object")
        schema = payload.get("schema_version")
    else:
        if not isinstance(payload, Mapping):
            raise ValueError(f"{artifact_kind} must be an object")
        schema = payload.get("schema_version")
    if not isinstance(schema, str) or schema not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"{artifact_kind}.schema_version is unsupported: {schema!r}")
    return schema


def _normalized(value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str):
        return "unknown"
    normalized = value.strip().lower().replace(" ", "_")
    return normalized if normalized in allowed else "unknown"


def _raw_text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _migrate_research(value: Mapping[str, object]) -> dict[str, object]:
    raw_decision = value.get("decision", "")
    rationale = value.get("rationale", "")
    raw = _raw_text(raw_decision)
    return {
        "schema_version": SCHEMA_VERSION,
        "recommendation": _normalized(raw_decision, _RECOMMENDATIONS),
        "rationale": rationale if isinstance(rationale, str) else "",
        "strategic_actions": "",
        "raw_markdown": raw,
        "supporting_turns": copy.deepcopy(value.get("supporting_turns", [])),
        "confidence": value.get("confidence", 0.0),
        "projection_quality": "parsed" if raw else "synthetic",
    }


def _migrate_trader(value: Mapping[str, object]) -> dict[str, object]:
    raw = _raw_text(value.get("plan", ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "action": _normalized(value.get("stance"), _TRADER_ACTIONS),
        "reasoning": raw,
        "entry_price": None,
        "stop_loss": None,
        "position_sizing": None,
        "raw_markdown": raw,
        "executable": False,
        "execution_authority": "none",
        "submitted": False,
        "caveats": copy.deepcopy(value.get("caveats", [])),
        "projection_quality": "parsed" if raw else "synthetic",
    }


def _migrate_portfolio(value: Mapping[str, object]) -> dict[str, object]:
    raw = _raw_text(value.get("summary", ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "rating": _normalized(value.get("action"), _RECOMMENDATIONS),
        "executive_summary": raw,
        "investment_thesis": "",
        "price_target": None,
        "time_horizon": None,
        "raw_markdown": raw,
        "executable": False,
        "execution_authority": "none",
        "submitted": False,
        "disclaimer": copy.deepcopy(value.get("disclaimer", "")),
        "projection_quality": "parsed" if raw else "synthetic",
    }


def _migrate_decision_fields(value: Mapping[str, object], migration_ids: list[str]) -> dict[str, object]:
    """Migrate only contract-defined decision fields; all other content is opaque."""
    migrated = copy.deepcopy(dict(value))
    for key, migrator, migration_id in (
        ("research_decision", _migrate_research, _RESEARCH_MIGRATION_ID),
        ("trader_decision", _migrate_trader, _TRADER_MIGRATION_ID),
        ("portfolio_decision", _migrate_portfolio, _PORTFOLIO_MIGRATION_ID),
    ):
        child = value.get(key)
        if isinstance(child, Mapping) and child.get("schema_version") == HISTORICAL_SCHEMA_VERSION:
            migrated[key] = migrator(child)
            if migration_id not in migration_ids:
                migration_ids.append(migration_id)
    return migrated


def _migrate_run_result(value: Mapping[str, object], migration_ids: list[str]) -> dict[str, object]:
    migrated = _migrate_decision_fields(value, migration_ids)
    migrated["schema_version"] = SCHEMA_VERSION
    for key in _RUN_RESULT_TYPED_SCHEMA_FIELDS:
        child = value.get(key)
        if isinstance(child, Mapping) and child.get("schema_version") == HISTORICAL_SCHEMA_VERSION:
            migrated[key] = _migrate_root_schema(child)
    return migrated


def _migrate_root_schema(value: Mapping[str, object]) -> dict[str, object]:
    migrated = copy.deepcopy(dict(value))
    migrated["schema_version"] = SCHEMA_VERSION
    return migrated


def _migrate_artifact(payload: object, artifact_kind: ArtifactKind, migration_ids: list[str]) -> object:
    """Apply migrations at schema-owned paths without traversing opaque payload content."""
    if artifact_kind == "run_result":
        assert isinstance(payload, Mapping)
        return _migrate_run_result(payload, migration_ids)
    if artifact_kind == "run_event":
        assert isinstance(payload, Mapping)
        return _migrate_root_schema(payload)
    if artifact_kind == "run_events":
        assert isinstance(payload, list)
        return [_migrate_root_schema(item) for item in payload if isinstance(item, Mapping)]
    if artifact_kind == "durable_bundle":
        assert isinstance(payload, Mapping)
        migrated = copy.deepcopy(dict(payload))
        result = payload.get("result")
        assert isinstance(result, Mapping)
        migrated["result"] = _migrate_run_result(result, migration_ids)
        events = payload.get("events")
        if isinstance(events, list):
            migrated["events"] = [_migrate_root_schema(item) for item in events if isinstance(item, Mapping)]
        return migrated
    if artifact_kind == "decision_memory_row":
        assert isinstance(payload, Mapping)
        migrated = _migrate_root_schema(payload)
        decision_json = payload.get("decision_json")
        if isinstance(decision_json, str):
            try:
                decision = json.loads(decision_json)
            except json.JSONDecodeError as exc:
                raise ValueError("decision memory row decision_json must be valid JSON") from exc
            if not isinstance(decision, Mapping):
                raise ValueError("decision memory row decision_json must contain an object")
            migrated_decision = _migrate_decision_fields(decision, migration_ids)
            migrated["decision_json"] = _json_bytes(migrated_decision).decode("utf-8")
        return migrated
    assert isinstance(payload, Mapping)
    return _migrate_root_schema(payload)


def migrate_payload(
    payload: object,
    artifact_kind: ArtifactKind,
    *,
    timestamp: str | None = None,
    original_path: str | os.PathLike[str] | None = None,
    migrated_path: str | os.PathLike[str] | None = None,
) -> MigratedArtifact:
    """Return a deterministic deep-copied payload and an auditable receipt."""
    source_schema = _schema_from_payload(payload, artifact_kind)
    migration_ids: list[str] = []
    if source_schema == HISTORICAL_SCHEMA_VERSION:
        migration_ids.append(_BASE_MIGRATION_ID)
        migrated = _migrate_artifact(payload, artifact_kind, migration_ids)
    else:
        migrated = copy.deepcopy(payload)
    receipt = MigrationReceipt(
        source_schema=source_schema,
        target_schema=SCHEMA_VERSION,
        artifact_kind=artifact_kind,
        before_sha256=_sha256(payload),
        after_sha256=_sha256(migrated),
        migration_ids=tuple(migration_ids),
        timestamp=timestamp or _utc_now(),
        original_path=os.fspath(original_path) if original_path is not None else None,
        migrated_path=os.fspath(migrated_path) if migrated_path is not None else None,
    )
    return MigratedArtifact(migrated, receipt)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def migrate_json_file(
    path: str | os.PathLike[str],
    artifact_kind: ArtifactKind,
    *,
    destination: str | os.PathLike[str] | None = None,
    timestamp: str | None = None,
) -> MigrationReceipt:
    """Migrate one JSON artifact without modifying the original file."""
    original = Path(path)
    migrated_path = Path(destination) if destination is not None else original.parent / ".migrations" / original.name
    try:
        payload = json.loads(original.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"saved {artifact_kind} must be valid JSON: {original}") from exc
    artifact = migrate_payload(
        payload,
        artifact_kind,
        timestamp=timestamp,
        original_path=original,
        migrated_path=migrated_path,
    )
    receipt_path = migrated_path.with_suffix(migrated_path.suffix + ".migration-receipt.json")
    migrated_content = _json_bytes(artifact.payload) + b"\n"
    if migrated_path.is_file() and receipt_path.is_file() and migrated_path.read_bytes() == migrated_content:
        try:
            existing = json.loads(receipt_path.read_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError):
            existing = None
        if (
            isinstance(existing, dict)
            and all(
                existing.get(key) == value for key, value in artifact.receipt.to_dict().items() if key != "timestamp"
            )
            and isinstance(existing.get("timestamp"), str)
        ):
            return MigrationReceipt(
                artifact.receipt.source_schema,
                artifact.receipt.target_schema,
                artifact.receipt.artifact_kind,
                artifact.receipt.before_sha256,
                artifact.receipt.after_sha256,
                artifact.receipt.migration_ids,
                existing["timestamp"],
                artifact.receipt.original_path,
                artifact.receipt.migrated_path,
            )
    _atomic_write(migrated_path, migrated_content)
    _atomic_write(receipt_path, _json_bytes(artifact.receipt.to_dict()) + b"\n")
    return artifact.receipt


def migrated_copy_path(path: str | os.PathLike[str]) -> Path:
    original = Path(path)
    return original.parent / ".migrations" / original.name
