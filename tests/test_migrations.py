from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tradingagents_portable.contracts import SCHEMA_VERSION
from tradingagents_portable.export import migrate_export_bundle
from tradingagents_portable.memory import DecisionMemoryStore
from tradingagents_portable.migrations import migrate_json_file, migrate_payload, migrated_copy_path
from tradingagents_portable.serialization import deserialize_run_event, deserialize_run_result
from tradingagents_portable.store import RunStore

FIXTURE = Path(__file__).parent / "fixtures" / "retained_historical_schema_run_bundle_2026-08-02.json"
FIXED_TIME = "2026-08-03T00:00:00Z"


def _historical_bundle() -> dict[str, object]:
    return json.loads(FIXTURE.read_bytes())


def test_retained_historical_schema_bundle_migration_is_deterministic_safe_and_idempotent() -> None:
    original = _historical_bundle()
    pristine = json.loads(json.dumps(original))

    first = migrate_payload(original, "durable_bundle", timestamp=FIXED_TIME)
    second = migrate_payload(original, "durable_bundle", timestamp=FIXED_TIME)
    current = migrate_payload(first.payload, "durable_bundle", timestamp=FIXED_TIME)

    assert original == pristine
    assert first.payload == second.payload == current.payload
    assert first.receipt == second.receipt
    assert current.receipt.migration_ids == ()
    result = first.payload["result"]
    assert result["research_decision"]["recommendation"] == "buy"
    assert result["research_decision"]["raw_markdown"] == "Buy"
    assert result["trader_decision"]["action"] == "unknown"
    assert result["trader_decision"]["execution_authority"] == "none"
    assert result["trader_decision"]["executable"] is False
    assert result["portfolio_decision"]["rating"] == "unknown"
    assert result["portfolio_decision"]["executive_summary"] == "A useful research case, not an order."
    assert result["portfolio_decision"]["submitted"] is False


def test_durable_bundle_migration_preserves_opaque_nested_schema_sentinels() -> None:
    original = _historical_bundle()
    sentinel = {
        "schema_version": "2026-08-02",
        "payload": "opaque evidence bytes: \u0000  café",
        "portfolio_decision": {
            "schema_version": "2026-08-02",
            "action": "must-not-be-reinterpreted",
            "summary": "free-form nested content",
        },
    }
    original["result"]["evidence"].append({"opaque": sentinel})
    original["result"]["artifacts"].append({"content": sentinel})
    original["events"][0]["data"]["opaque"] = sentinel

    migrated = migrate_payload(original, "durable_bundle", timestamp=FIXED_TIME).payload

    assert migrated["result"]["evidence"][0]["opaque"] == sentinel
    assert migrated["result"]["artifacts"][0]["content"] == sentinel
    assert migrated["events"][0]["data"]["opaque"] == sentinel
    assert migrated["result"]["schema_version"] == SCHEMA_VERSION
    assert migrated["events"][0]["schema_version"] == SCHEMA_VERSION


def test_run_event_migration_only_updates_the_event_envelope_schema() -> None:
    event = _historical_bundle()["events"][0]
    opaque = {"schema_version": "2026-08-02", "raw": [0, "unchanged", {"schema_version": "2026-08-02"}]}
    event["data"] = {"opaque": opaque}

    migrated = migrate_payload(event, "run_event", timestamp=FIXED_TIME).payload

    assert migrated["schema_version"] == SCHEMA_VERSION
    assert migrated["data"]["opaque"] == opaque


def test_copy_on_write_retained_historical_schema_golden_preserves_original_and_reuses_receipt(
    tmp_path: Path,
) -> None:
    original = tmp_path / "historical.json"
    original.write_bytes(FIXTURE.read_bytes())
    before = original.read_bytes()

    first = migrate_json_file(original, "durable_bundle", timestamp=FIXED_TIME)
    second = migrate_json_file(original, "durable_bundle", timestamp="2099-01-01T00:00:00Z")
    migrated = migrated_copy_path(original)

    assert original.read_bytes() == before
    assert migrated.is_file()
    assert first == second
    assert first.original_path == str(original)
    assert first.migrated_path == str(migrated)
    assert first.receipt_version == "tradingagents-portable-migration-receipt-v1"
    assert (
        first.before_sha256
        == hashlib.sha256(json.dumps(json.loads(before), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    assert json.loads(migrated.read_bytes())["result"]["schema_version"] == SCHEMA_VERSION


def test_run_store_migrates_historical_bundle_and_reads_it_after_restart(tmp_path: Path) -> None:
    state = tmp_path / "state"
    bundle_path = state / "bundles" / "historical-run.json"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_bytes(FIXTURE.read_bytes())

    first = RunStore(state)
    result = first.get_result("historical-run")
    restarted = RunStore(state)
    restored = restarted.get_result("historical-run")

    assert result == restored
    assert restored.research_decision.recommendation == "buy"
    assert restored.trader_decision.action == "unknown"
    assert restored.portfolio_decision.rating == "unknown"
    assert json.loads(bundle_path.read_bytes())["result"]["schema_version"] == "2026-08-02"
    assert migrated_copy_path(bundle_path).is_file()


def test_unknown_schema_fails_closed() -> None:
    payload = _historical_bundle()
    payload["result"]["schema_version"] = "1900-01-01"
    with pytest.raises(ValueError, match="schema_version"):
        migrate_payload(payload, "durable_bundle")


@pytest.mark.parametrize("artifact", ("result", "event"))
def test_skeletal_historical_artifacts_fail_required_field_validation(artifact: str) -> None:
    payload = {"schema_version": "2026-08-02", "run_id": "historical-run"}

    with pytest.raises(ValueError, match="missing required fields"):
        if artifact == "result":
            deserialize_run_result(json.dumps(payload))
        else:
            deserialize_run_event(json.dumps(payload))


def test_corrupt_historical_event_fails_conformance_validation() -> None:
    payload = _historical_bundle()["events"][0]
    payload["sequence"] = 0

    with pytest.raises(ValueError, match="sequence must be positive"):
        deserialize_run_event(json.dumps(payload))


def test_export_bundle_migration_updates_checksums_without_touching_source(tmp_path: Path) -> None:
    historical = _historical_bundle()
    source = tmp_path / "historical-export"
    source.mkdir()
    result_data = (json.dumps(historical["result"], sort_keys=True, separators=(",", ":")) + "\n").encode()
    event_data = b"".join(
        (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode() for event in historical["events"]
    )
    (source / "result.json").write_bytes(result_data)
    (source / "events.ndjson").write_bytes(event_data)
    manifest = {
        "schema_version": "2026-08-02",
        "bundle_format": "tradingagents-portable-run-bundle-v1",
        "run_id": "historical-run",
        "files": [
            {"path": "result.json", "sha256": hashlib.sha256(result_data).hexdigest(), "bytes": len(result_data)},
            {"path": "events.ndjson", "sha256": hashlib.sha256(event_data).hexdigest(), "bytes": len(event_data)},
        ],
    }
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    source_before = (source / "result.json").read_bytes()

    receipt = migrate_export_bundle(source, timestamp=FIXED_TIME)
    repeated = migrate_export_bundle(source, timestamp="2099-01-01T00:00:00Z")
    destination = Path(receipt.migrated_path or "")

    assert receipt == repeated
    assert (source / "result.json").read_bytes() == source_before
    assert json.loads((destination / "manifest.json").read_bytes())["schema_version"] == SCHEMA_VERSION
    assert deserialize_run_result((destination / "result.json").read_bytes()).run_id == "historical-run"


def test_decision_memory_migrates_historical_rows_and_reopens(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE decisions (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL UNIQUE,
                run_id TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                context_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE outcomes (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                outcome_id TEXT NOT NULL UNIQUE,
                memory_id TEXT NOT NULL,
                outcome_json TEXT NOT NULL,
                reflection TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );
            CREATE TABLE portable_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO portable_metadata VALUES ('schema_version', '2026-08-02');
            """
        )
        decision = {
            "portfolio_decision": {
                "schema_version": "2026-08-02",
                "action": "approve_research_case",
                "summary": "Historical memory summary.",
                "executable": True,
            }
        }
        connection.execute(
            "INSERT INTO decisions(memory_id, run_id, symbol, as_of_date, decision_json, context_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "mem-old",
                "historical-run",
                "ORCL",
                "2026-08-02",
                json.dumps(decision),
                "{}",
                "2026-08-02T12:00:00Z",
            ),
        )

    with DecisionMemoryStore(path) as memory:
        migrated = memory.recall("ORCL").same_symbol[0].decision["portfolio_decision"]
    with DecisionMemoryStore(path) as reopened:
        restored = reopened.recall("ORCL").same_symbol[0].decision["portfolio_decision"]

    assert migrated == restored
    assert restored["rating"] == "unknown"
    assert restored["execution_authority"] == "none"
    assert restored["executable"] is False
    assert Path(f"{path}.pre-migration-2026-08-02.sqlite3").is_file()
    assert Path(f"{path}.migration-receipt.json").is_file()
    with sqlite3.connect(f"{path}.pre-migration-2026-08-02.sqlite3") as original:
        assert original.execute("SELECT value FROM portable_metadata WHERE key = 'schema_version'").fetchone() == (
            "2026-08-02",
        )


def test_decision_memory_unknown_schema_fails_before_mutation(tmp_path: Path) -> None:
    path = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE portable_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO portable_metadata VALUES ('schema_version', '1900-01-01')")
    before = path.read_bytes()

    with pytest.raises(RuntimeError, match="unsupported decision memory schema"):
        DecisionMemoryStore(path)

    assert path.read_bytes() == before
