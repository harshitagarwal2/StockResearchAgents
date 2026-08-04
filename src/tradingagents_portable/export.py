"""Atomic, durable export of canonical TradingAgents run bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .contracts import SCHEMA_VERSION, RunEvent, RunResult, reject_secret_shaped_keys
from .migrations import HISTORICAL_SCHEMA_VERSION, MigrationReceipt, migrate_payload
from .reporting import build_report_artifacts
from .semantics import CompletedRunSemanticsV1, build_completed_run_semantics
from .serialization import deserialize_run_event, deserialize_run_result, serialize_run_event, serialize_run_result

_BUNDLE_FORMAT = "tradingagents-portable-run-bundle-v1"
_OVERWRITE_JOURNAL_FORMAT = "tradingagents-portable-overwrite-journal-v1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ExportedFile:
    path: str
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


@dataclass(frozen=True, slots=True)
class RunExportReceipt:
    run_id: str
    output_path: str
    files: tuple[ExportedFile, ...]
    manifest_sha256: str
    semantics_sha256: str
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "output_path": self.output_path,
            "files": [item.to_dict() for item in self.files],
            "manifest_sha256": self.manifest_sha256,
            "semantics_sha256": self.semantics_sha256,
        }


def _write_file(root: Path, relative: str, content: bytes) -> ExportedFile:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return ExportedFile(relative, hashlib.sha256(content).hexdigest(), len(content))


def _text(value: str) -> bytes:
    return (value.rstrip("\n") + "\n").encode("utf-8")


def _json_lines(entries: Iterable[Mapping[str, object] | RunEvent]) -> bytes:
    lines: list[str] = []
    for index, entry in enumerate(entries):
        value: object = entry.to_dict() if isinstance(entry, RunEvent) else dict(entry)
        reject_secret_shaped_keys(value)
        try:
            lines.append(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"lifecycle_log[{index}] must be JSON-compatible") from exc
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _report_contents(result: RunResult) -> dict[str, str]:
    reports = result.report_sections
    research = result.research_debate_snapshot
    risk = result.risk_debate_snapshot
    complete = next(artifact for artifact in build_report_artifacts(result) if artifact.kind == "complete_report")
    portfolio = (
        result.portfolio_manager_decision
        or risk.judge_decision
        or result.portfolio_decision.raw_markdown
        or result.portfolio_decision.render_markdown()
    )
    trader = (
        result.trader_investment_plan or result.trader_decision.raw_markdown or result.trader_decision.render_markdown()
    )
    return {
        "1_analysts/market.md": reports.market_report,
        "1_analysts/sentiment.md": reports.sentiment_report,
        "1_analysts/news.md": reports.news_report,
        "1_analysts/fundamentals.md": reports.fundamentals_report,
        "2_research/bull.md": research.role_histories.get("bull", ""),
        "2_research/bear.md": research.role_histories.get("bear", ""),
        "2_research/manager.md": research.judge_decision or result.investment_plan,
        "3_trading/trader.md": trader,
        "4_risk/aggressive.md": risk.role_histories.get("aggressive", ""),
        "4_risk/conservative.md": risk.role_histories.get("conservative", ""),
        "4_risk/neutral.md": risk.role_histories.get("neutral", ""),
        "5_portfolio/decision.md": portfolio,
        "complete_report.md": str(complete.content),
    }


def _safe_export_target(output_dir: str | os.PathLike[str]) -> Path:
    target = Path(output_dir).expanduser().absolute()
    if target.is_symlink():
        raise ValueError(f"export target must not be a symlink: {target}")
    protected = {Path(target.anchor), Path.home().absolute(), Path.cwd().absolute()}
    resolved = target.resolve(strict=False)
    resolved_protected = {path.resolve(strict=False) for path in protected}
    if any(target == path or target in path.parents for path in protected) or any(
        resolved == path or resolved in path.parents for path in resolved_protected
    ):
        raise ValueError(f"refusing protected export target: {target}")
    return target


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_prior_export_bundle(target: Path) -> str:
    if target.is_symlink() or not target.is_dir():
        raise ValueError(f"overwrite target is not a prior TradingAgents portable export bundle: {target}")
    manifest_path = target / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(f"overwrite target has no valid export manifest: {target}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"overwrite target has no valid export manifest: {target}") from exc
    if not isinstance(manifest, dict) or manifest.get("bundle_format") != _BUNDLE_FORMAT:
        raise ValueError(f"overwrite target is not a TradingAgents portable export bundle: {target}")
    if manifest.get("schema_version") != SCHEMA_VERSION or not isinstance(manifest.get("run_id"), str):
        raise ValueError(f"overwrite target has an invalid export manifest: {target}")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError(f"overwrite target has an invalid export manifest: {target}")

    declared: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"overwrite target has an invalid export manifest: {target}")
        relative = entry.get("path")
        digest = entry.get("sha256")
        byte_count = entry.get("bytes")
        if (
            not isinstance(relative, str)
            or not relative
            or relative in declared
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(digest, str)
            or _SHA256_PATTERN.fullmatch(digest) is None
            or not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
        ):
            raise ValueError(f"overwrite target has an invalid export manifest: {target}")
        path = target / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"overwrite target does not match its export manifest: {target}")
        content = path.read_bytes()
        if len(content) != byte_count or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"overwrite target does not match its export manifest: {target}")
        declared.add(relative)

    required = {
        "1_analysts/market.md",
        "1_analysts/sentiment.md",
        "1_analysts/news.md",
        "1_analysts/fundamentals.md",
        "2_research/bull.md",
        "2_research/bear.md",
        "2_research/manager.md",
        "3_trading/trader.md",
        "4_risk/aggressive.md",
        "4_risk/conservative.md",
        "4_risk/neutral.md",
        "5_portfolio/decision.md",
        "complete_report.md",
        "result.json",
        "events.ndjson",
        "semantics.v1.json",
    }
    actual: set[str] = set()
    actual_directories: set[str] = set()
    for path in target.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"overwrite target contains a symlink: {target}")
        if path.is_file():
            actual.add(path.relative_to(target).as_posix())
        elif path.is_dir():
            actual_directories.add(path.relative_to(target).as_posix())
    expected_directories = {
        parent.as_posix() for relative in declared for parent in Path(relative).parents if parent != Path(".")
    }
    if not required <= declared or actual != declared | {"manifest.json"} or actual_directories != expected_directories:
        raise ValueError(f"overwrite target does not match its export manifest: {target}")
    try:
        result = deserialize_run_result((target / "result.json").read_bytes())
        events = tuple(
            deserialize_run_event(line) for line in (target / "events.ndjson").read_bytes().splitlines() if line.strip()
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"overwrite target contains invalid portable run data: {target}") from exc
    run_id = manifest["run_id"]
    if result.run_id != run_id or any(event.run_id != run_id for event in events):
        raise ValueError(f"overwrite target contains mismatched portable run data: {target}")
    try:
        semantic_payload = json.loads((target / "semantics.v1.json").read_text(encoding="utf-8"))
        if not isinstance(semantic_payload, dict):
            raise ValueError("semantic projection must be an object")
        semantics = CompletedRunSemanticsV1.from_dict(semantic_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"overwrite target contains invalid completed-run semantics: {target}") from exc
    expected_semantics = build_completed_run_semantics(result, events).to_dict()
    if semantics.to_dict() != expected_semantics or manifest.get("semantics_sha256") != semantic_payload["digest"]:
        raise ValueError(f"overwrite target semantics do not match its portable run data: {target}")
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _overwrite_journal_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.overwrite.json")


def _write_overwrite_journal(
    target: Path,
    staging: Path,
    backup: Path,
    old_manifest_sha256: str,
    new_manifest_sha256: str,
) -> Path:
    journal = _overwrite_journal_path(target)
    payload = _text(
        json.dumps(
            {
                "format": _OVERWRITE_JOURNAL_FORMAT,
                "target_name": target.name,
                "staging_name": staging.name,
                "backup_name": backup.name,
                "old_manifest_sha256": old_manifest_sha256,
                "new_manifest_sha256": new_manifest_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    journal_temp = journal.with_name(f".{journal.name}.tmp-{uuid4().hex}")
    try:
        descriptor = os.open(journal_temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(journal_temp, journal, follow_symlinks=False)
        except FileExistsError as exc:
            raise ValueError(f"export target has an unresolved overwrite journal: {journal}") from exc
        _fsync_directory(target.parent)
    finally:
        journal_temp.unlink(missing_ok=True)
    return journal


def _load_overwrite_journal(target: Path) -> tuple[Path, Path, str, str] | None:
    journal = _overwrite_journal_path(target)
    if not journal.exists() and not journal.is_symlink():
        return None
    if journal.is_symlink() or not journal.is_file():
        raise ValueError(f"invalid overwrite journal for export target: {target}")
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid overwrite journal for export target: {target}") from exc
    expected_keys = {
        "format",
        "target_name",
        "staging_name",
        "backup_name",
        "old_manifest_sha256",
        "new_manifest_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError(f"invalid overwrite journal for export target: {target}")
    staging_name = payload.get("staging_name")
    backup_name = payload.get("backup_name")
    old_digest = payload.get("old_manifest_sha256")
    new_digest = payload.get("new_manifest_sha256")
    if (
        payload.get("format") != _OVERWRITE_JOURNAL_FORMAT
        or payload.get("target_name") != target.name
        or not isinstance(staging_name, str)
        or not staging_name.startswith(f".{target.name}.tmp-")
        or Path(staging_name).name != staging_name
        or not isinstance(backup_name, str)
        or not backup_name.startswith(f".{target.name}.backup-")
        or Path(backup_name).name != backup_name
        or not isinstance(old_digest, str)
        or _SHA256_PATTERN.fullmatch(old_digest) is None
        or not isinstance(new_digest, str)
        or _SHA256_PATTERN.fullmatch(new_digest) is None
    ):
        raise ValueError(f"invalid overwrite journal for export target: {target}")
    return target.parent / staging_name, target.parent / backup_name, old_digest, new_digest


def _remove_validated_bundle(path: Path, expected_digest: str) -> None:
    if _validate_prior_export_bundle(path) != expected_digest:
        raise ValueError(f"recovery artifact does not match its overwrite journal: {path}")
    shutil.rmtree(path)


def _is_expected_bundle(path: Path, expected_digest: str) -> bool:
    try:
        return _validate_prior_export_bundle(path) == expected_digest
    except (OSError, ValueError):
        return False


def _recover_interrupted_overwrite(target: Path) -> None:
    recovery = _load_overwrite_journal(target)
    if recovery is None:
        return
    staging, backup, old_digest, new_digest = recovery
    journal = _overwrite_journal_path(target)
    target_present = target.exists() or target.is_symlink()
    backup_present = backup.exists() or backup.is_symlink()
    staging_present = staging.exists() or staging.is_symlink()

    if target_present:
        target_digest = _validate_prior_export_bundle(target)
        if target_digest == new_digest:
            remove_backup = backup_present and _is_expected_bundle(backup, old_digest)
            remove_staging = staging_present and _is_expected_bundle(staging, new_digest)
            journal.unlink()
            _fsync_directory(target.parent)
            if remove_backup:
                _remove_validated_bundle(backup, old_digest)
            if remove_staging:
                _remove_validated_bundle(staging, new_digest)
            return
        if target_digest == old_digest and not backup_present and staging_present:
            remove_staging = _is_expected_bundle(staging, new_digest)
            journal.unlink()
            _fsync_directory(target.parent)
            if remove_staging:
                _remove_validated_bundle(staging, new_digest)
            return
        raise ValueError(f"export target does not match its overwrite recovery journal: {target}")

    if not backup_present:
        raise ValueError(f"incomplete overwrite recovery artifacts for export target: {target}")
    if _validate_prior_export_bundle(backup) != old_digest:
        raise ValueError(f"overwrite backup does not match its recovery journal: {backup}")
    remove_staging = staging_present and _is_expected_bundle(staging, new_digest)
    os.replace(backup, target)
    _fsync_directory(target.parent)
    journal.unlink()
    _fsync_directory(target.parent)
    if remove_staging:
        _remove_validated_bundle(staging, new_digest)


def export_run_bundle(
    result: RunResult,
    events: Iterable[RunEvent],
    output_dir: str | os.PathLike[str],
    *,
    lifecycle_log: Iterable[Mapping[str, object] | RunEvent] | None = None,
    overwrite: bool = False,
) -> RunExportReceipt:
    """Publish a new bundle atomically; make validated overwrites crash-recoverable."""
    if not isinstance(result, RunResult):
        raise TypeError("result must be a RunResult")
    event_values = tuple(events)
    if not all(isinstance(event, RunEvent) for event in event_values):
        raise TypeError("events must contain only RunEvent values")
    if any(event.run_id != result.run_id for event in event_values):
        raise ValueError("every event must match result.run_id")

    target = _safe_export_target(output_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    _recover_interrupted_overwrite(target)
    if target.exists():
        if not overwrite:
            raise FileExistsError(f"export target already exists: {target}")
        _validate_prior_export_bundle(target)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
    try:
        files = [_write_file(staging, path, _text(content)) for path, content in _report_contents(result).items()]
        files.append(_write_file(staging, "result.json", _text(serialize_run_result(result))))
        event_data = "".join(f"{serialize_run_event(event)}\n" for event in event_values).encode("utf-8")
        files.append(_write_file(staging, "events.ndjson", event_data))
        semantics = build_completed_run_semantics(result, event_values).to_dict()
        semantics_data = _text(
            json.dumps(semantics, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        )
        files.append(_write_file(staging, "semantics.v1.json", semantics_data))
        if lifecycle_log is not None:
            files.append(_write_file(staging, "lifecycle/log.jsonl", _json_lines(lifecycle_log)))
        files.sort(key=lambda item: item.path)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "bundle_format": _BUNDLE_FORMAT,
            "run_id": result.run_id,
            "semantics_sha256": semantics["digest"],
            "files": [item.to_dict() for item in files],
        }
        manifest_data = _text(
            json.dumps(manifest, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        )
        _write_file(staging, "manifest.json", manifest_data)
        _fsync_directory(staging)
        new_manifest_sha256 = hashlib.sha256(manifest_data).hexdigest()

        if target.is_symlink():
            raise ValueError(f"export target must not be a symlink: {target}")
        if target.exists():
            if not overwrite:
                raise FileExistsError(f"export target already exists: {target}")
            old_manifest_sha256 = _validate_prior_export_bundle(target)
            backup = target.with_name(f".{target.name}.backup-{uuid4().hex}")
            journal = _write_overwrite_journal(
                target,
                staging,
                backup,
                old_manifest_sha256,
                new_manifest_sha256,
            )
            try:
                os.replace(target, backup)
                _fsync_directory(target.parent)
                if _validate_prior_export_bundle(backup) != old_manifest_sha256:
                    raise ValueError(f"overwrite backup changed during publication: {backup}")
                os.replace(staging, target)
                _fsync_directory(target.parent)
                if _validate_prior_export_bundle(target) != new_manifest_sha256:
                    raise ValueError(f"published export does not match staged bundle: {target}")
                journal.unlink()
                _fsync_directory(target.parent)
                _remove_validated_bundle(backup, old_manifest_sha256)
            except BaseException:
                try:
                    _recover_interrupted_overwrite(target)
                except Exception:
                    pass
                raise
        else:
            os.replace(staging, target)
            _fsync_directory(target.parent)
        return RunExportReceipt(
            run_id=result.run_id,
            output_path=str(target),
            files=tuple(files),
            manifest_sha256=new_manifest_sha256,
            semantics_sha256=str(semantics["digest"]),
        )
    except BaseException:
        if not _overwrite_journal_path(target).exists() and staging.exists():
            shutil.rmtree(staging)
        raise


def _bundle_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def migrate_export_bundle(
    source_dir: str | os.PathLike[str],
    destination_dir: str | os.PathLike[str] | None = None,
    *,
    timestamp: str | None = None,
) -> MigrationReceipt:
    """Copy and migrate a verified 2026-08-02 export bundle."""
    source = Path(source_dir).expanduser().absolute()
    destination = (
        Path(destination_dir).expanduser().absolute()
        if destination_dir is not None
        else source.with_name(f"{source.name}.migrated-{SCHEMA_VERSION}")
    )
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"export bundle source must be a directory, not a symlink: {source}")
    if destination == source or source in destination.parents:
        raise ValueError("migration destination must be outside the source export bundle")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = source / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"export bundle has no valid manifest: {source}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"export bundle has no valid manifest: {source}")
    schema = manifest.get("schema_version")
    if schema not in {HISTORICAL_SCHEMA_VERSION, SCHEMA_VERSION}:
        raise ValueError(f"unsupported export_bundle schema version: {schema!r}")
    if schema == SCHEMA_VERSION:
        return migrate_payload(
            manifest,
            "export_bundle",
            timestamp=timestamp,
            original_path=source,
            migrated_path=source,
        ).receipt
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError(f"export bundle has no valid file manifest: {source}")
    declared: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"export bundle has no valid file manifest: {source}")
        relative, expected_digest, expected_bytes = entry.get("path"), entry.get("sha256"), entry.get("bytes")
        if (
            not isinstance(relative, str)
            or relative in declared
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(expected_digest, str)
            or not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
        ):
            raise ValueError(f"export bundle has no valid file manifest: {source}")
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"export bundle does not match its file manifest: {source}")
        content = path.read_bytes()
        if len(content) != expected_bytes or hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError(f"export bundle does not match its file manifest: {source}")
        declared.add(relative)
    actual = set()
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"export bundle contains a symlink: {source}")
        if path.is_file():
            actual.add(path.relative_to(source).as_posix())
    if actual != declared | {"manifest.json"}:
        raise ValueError(f"export bundle does not match its file manifest: {source}")

    before_sha256 = _bundle_digest(source)
    result_payload = json.loads((source / "result.json").read_bytes())
    result_migration = migrate_payload(result_payload, "run_result", timestamp=timestamp)
    event_payloads = [json.loads(line) for line in (source / "events.ndjson").read_bytes().splitlines() if line.strip()]
    event_migrations = [migrate_payload(item, "run_event", timestamp=timestamp) for item in event_payloads]
    migration_ids = list(result_migration.receipt.migration_ids)
    for item in event_migrations:
        for migration_id in item.receipt.migration_ids:
            if migration_id not in migration_ids:
                migration_ids.append(migration_id)

    receipt_path = destination.with_name(f"{destination.name}.migration-receipt.json")
    if destination.exists() or receipt_path.exists():
        try:
            existing = json.loads(receipt_path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FileExistsError(f"migration destination already exists: {destination}") from exc
        if (
            destination.is_dir()
            and isinstance(existing, dict)
            and existing.get("before_sha256") == before_sha256
            and existing.get("after_sha256") == _bundle_digest(destination)
            and existing.get("source_schema") == HISTORICAL_SCHEMA_VERSION
            and existing.get("target_schema") == SCHEMA_VERSION
        ):
            return MigrationReceipt(
                HISTORICAL_SCHEMA_VERSION,
                SCHEMA_VERSION,
                "export_bundle",
                before_sha256,
                str(existing["after_sha256"]),
                tuple(str(item) for item in existing.get("migration_ids", [])),
                str(existing["timestamp"]),
                str(source),
                str(destination),
            )
        raise FileExistsError(f"migration destination already exists: {destination}")

    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True)
        result_content = _text(json.dumps(result_migration.payload, sort_keys=True, separators=(",", ":")))
        (staging / "result.json").write_bytes(result_content)
        event_content = b"".join(
            _text(json.dumps(item.payload, sort_keys=True, separators=(",", ":"))) for item in event_migrations
        )
        (staging / "events.ndjson").write_bytes(event_content)
        updated_entries: list[dict[str, object]] = []
        for entry in entries:
            relative = str(entry["path"])
            content = (staging / relative).read_bytes()
            updated_entries.append(
                {"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            )
        manifest["schema_version"] = SCHEMA_VERSION
        manifest["files"] = updated_entries
        (staging / "manifest.json").write_bytes(_text(json.dumps(manifest, sort_keys=True, separators=(",", ":"))))
        os.replace(staging, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    receipt = MigrationReceipt(
        HISTORICAL_SCHEMA_VERSION,
        SCHEMA_VERSION,
        "export_bundle",
        before_sha256,
        _bundle_digest(destination),
        tuple(migration_ids),
        timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        str(source),
        str(destination),
    )
    receipt_path.write_bytes(_text(json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":"))))
    return receipt


# Friendly integration alias.
export_bundle = export_run_bundle
