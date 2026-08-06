"""Atomic, durable export of canonical StockResearchAgents run bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .company_analytics_v1 import CompanyAnalyticsResultV1
from .contracts import SCHEMA_VERSION, RunEvent, reject_secret_shaped_keys
from .publication import validate_completed_publication
from .reporting import build_report_artifacts
from .semantics import CompletedRunSemanticsV1, build_completed_run_semantics
from .serialization import deserialize_run_event, deserialize_run_result, serialize_run_event, serialize_run_result

_BUNDLE_FORMAT = "stock-research-agents-run-bundle-v1"
_OVERWRITE_JOURNAL_FORMAT = "stock-research-agents-overwrite-journal-v1"
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


def _report_contents(result: CompanyAnalyticsResultV1) -> dict[str, str]:
    artifacts = build_report_artifacts(result)
    reports: dict[str, str] = {}
    for artifact in artifacts:
        if artifact.kind == "report_group" and isinstance(artifact.content, Mapping):
            ordinal = artifact.content.get("ordinal")
            slug = artifact.content.get("slug")
            markdown = artifact.content.get("markdown")
            if isinstance(ordinal, int) and isinstance(slug, str) and isinstance(markdown, str):
                reports[f"{ordinal}_{slug}.md"] = markdown
        elif artifact.kind == "complete_report" and isinstance(artifact.content, str):
            reports["complete_report.md"] = artifact.content
    if len(reports) != 6 or "complete_report.md" not in reports:
        raise ValueError("completed analytics report projection must contain five groups and one complete report")
    return reports


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
        raise ValueError(f"overwrite target is not a prior StockResearchAgents export bundle: {target}")
    manifest_path = target / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(f"overwrite target has no valid export manifest: {target}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"overwrite target has no valid export manifest: {target}") from exc
    if not isinstance(manifest, dict) or manifest.get("bundle_format") != _BUNDLE_FORMAT:
        raise ValueError(f"overwrite target is not a StockResearchAgents export bundle: {target}")
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
        "1_executive-summary.md",
        "2_evidence-and-claims.md",
        "3_analytics-and-valuation.md",
        "4_risks-and-counterevidence.md",
        "5_monitoring-and-quality.md",
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
        raise ValueError(f"overwrite target contains invalid StockResearchAgents run data: {target}") from exc
    if not isinstance(result, CompanyAnalyticsResultV1):
        raise ValueError(f"overwrite target contains a retired run result contract: {target}")
    run_id = manifest["run_id"]
    if result.run_id != run_id or any(event.run_id != run_id for event in events):
        raise ValueError(f"overwrite target contains mismatched StockResearchAgents run data: {target}")
    try:
        semantic_payload = json.loads((target / "semantics.v1.json").read_text(encoding="utf-8"))
        if not isinstance(semantic_payload, dict):
            raise ValueError("semantic projection must be an object")
        semantics = CompletedRunSemanticsV1.from_dict(semantic_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"overwrite target contains invalid completed-run semantics: {target}") from exc
    expected_semantics = build_completed_run_semantics(result, events).to_dict()
    if semantics.to_dict() != expected_semantics or manifest.get("semantics_sha256") != semantic_payload["digest"]:
        raise ValueError(f"overwrite target semantics do not match its StockResearchAgents run data: {target}")
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
    result: CompanyAnalyticsResultV1,
    events: Iterable[RunEvent],
    output_dir: str | os.PathLike[str],
    *,
    lifecycle_log: Iterable[Mapping[str, object] | RunEvent] | None = None,
    overwrite: bool = False,
) -> RunExportReceipt:
    """Publish a new bundle atomically; make validated overwrites crash-recoverable."""
    if not isinstance(result, CompanyAnalyticsResultV1):
        raise TypeError("result must be a CompanyAnalyticsResultV1")
    event_values = tuple(events)
    if not all(isinstance(event, RunEvent) for event in event_values):
        raise TypeError("events must contain only RunEvent values")
    validate_completed_publication(result, event_values)

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
