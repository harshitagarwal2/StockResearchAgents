"""Redacted, read-only operational diagnostics for one local state layout."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .state import StateLayout
from .state_migrations import plan_state_migration

_DETAIL_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SECRET_TERMS = ("authorization", "cookie", "credential", "password", "secret", "token")


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    check_id: str
    status: Literal["passed", "warning", "failed"]
    summary: str
    details: dict[str, str | int | bool | None]

    def __post_init__(self) -> None:
        if _DETAIL_KEY.fullmatch(self.check_id) is None:
            raise ValueError("diagnostic check_id must be a safe identifier")
        if self.status not in {"passed", "warning", "failed"}:
            raise ValueError("diagnostic status is invalid")
        if not self.summary or len(self.summary) > 256:
            raise ValueError("diagnostic summary must contain 1-256 characters")
        for key, value in self.details.items():
            if _DETAIL_KEY.fullmatch(key) is None:
                raise ValueError("diagnostic detail keys must be safe identifiers")
            if any(term in key for term in _SECRET_TERMS):
                raise ValueError("diagnostic details must not contain secret-shaped fields")
            if not isinstance(value, str | int | bool | None):
                raise ValueError("diagnostic detail values must be scalar")
            if isinstance(value, str) and len(value) > 128:
                raise ValueError("diagnostic string details must be no longer than 128 characters")

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "summary": self.summary,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class StateDiagnosticsReport:
    schema_version: Literal["stockresearchagents-diagnostics.v1"]
    status: Literal["ok", "degraded", "error"]
    checks: tuple[DiagnosticCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
        }


def _root_check(root: Path) -> DiagnosticCheck:
    if not root.exists():
        return DiagnosticCheck("state_root", "warning", "State has not been initialized.", {"exists": False})
    if not root.is_dir() or root.is_symlink():
        return DiagnosticCheck("state_root", "failed", "State root is not a private directory.", {"exists": True})
    private = root.stat().st_mode & 0o077 == 0
    return DiagnosticCheck(
        "state_root",
        "passed" if private else "failed",
        "State root permissions are private." if private else "State root is accessible to group or other users.",
        {"exists": True, "private_permissions": private},
    )


def _artifact_checks(root: Path) -> tuple[DiagnosticCheck, DiagnosticCheck]:
    try:
        plan = plan_state_migration(root)
    except ValueError:
        return (
            DiagnosticCheck("artifact_integrity", "failed", "A durable state artifact failed validation.", {}),
            DiagnosticCheck("state_schema", "warning", "State schema status is unavailable.", {}),
        )
    integrity = DiagnosticCheck(
        "artifact_integrity",
        "passed",
        "Durable JSON and SQLite artifacts passed bounded integrity checks.",
        {
            "validated_json_files": plan.validated_json_files,
            "validated_sqlite_databases": plan.validated_sqlite_databases,
        },
    )
    current = plan.status == "current"
    schema = DiagnosticCheck(
        "state_schema",
        "passed" if current else "warning",
        "State schema is current." if current else "State schema is uninitialized or requires backup-first adoption.",
        {"current": current},
    )
    return integrity, schema


def _pending_artifacts(root: Path) -> DiagnosticCheck:
    paths = (
        root / "staged",
        root / "quality" / "staged-registrations",
    )
    count = sum(1 for directory in paths if directory.is_dir() for path in directory.glob("*.json") if path.is_file())
    return DiagnosticCheck(
        "publication_recovery",
        "warning" if count else "passed",
        "Pending staged publication artifacts require retry."
        if count
        else "No staged publication artifacts are pending.",
        {"pending_artifact_count": count},
    )


def _viewer_registry(root: Path) -> DiagnosticCheck:
    registry = root / ".presentation" / "viewer.json"
    if not registry.exists():
        return DiagnosticCheck(
            "viewer_registry",
            "passed",
            "No detached viewer registry is present.",
            {"present": False},
        )
    if registry.is_symlink() or registry.stat().st_mode & 0o077:
        return DiagnosticCheck(
            "viewer_registry",
            "failed",
            "Detached viewer registry permissions are unsafe.",
            {"present": True, "private_permissions": False},
        )
    try:
        value = json.loads(registry.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    valid = isinstance(value, dict)
    return DiagnosticCheck(
        "viewer_registry",
        "passed" if valid else "failed",
        "Detached viewer registry is private and structurally valid."
        if valid
        else "Detached viewer registry is not valid JSON.",
        {"present": True, "private_permissions": True, "valid_json": valid},
    )


def run_state_diagnostics(layout: StateLayout) -> StateDiagnosticsReport:
    """Inspect state without creating files, opening providers, or exposing identifiers."""
    root = layout.root
    root_check = _root_check(root)
    integrity, schema = _artifact_checks(root)
    checks = (root_check, integrity, schema, _pending_artifacts(root), _viewer_registry(root))
    if any(check.status == "failed" for check in checks):
        status: Literal["ok", "degraded", "error"] = "error"
    elif any(check.status == "warning" for check in checks):
        status = "degraded"
    else:
        status = "ok"
    return StateDiagnosticsReport("stockresearchagents-diagnostics.v1", status, checks)


__all__ = ["DiagnosticCheck", "StateDiagnosticsReport", "run_state_diagnostics"]
