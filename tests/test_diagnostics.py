from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_research_agents.diagnostics import DiagnosticCheck, run_state_diagnostics
from stock_research_agents.state import StateLayout
from stock_research_agents.state_migrations import migrate_state


def test_diagnostics_do_not_initialize_missing_state(tmp_path: Path) -> None:
    layout = StateLayout(tmp_path / "missing")

    report = run_state_diagnostics(layout)

    assert report.status == "degraded"
    assert {check.check_id: check.status for check in report.checks}["state_root"] == "warning"
    assert not layout.root.exists()


def test_diagnostics_report_current_private_state_as_healthy(tmp_path: Path) -> None:
    layout = StateLayout(tmp_path / "state")
    migrate_state(layout.root, apply=True)
    layout.root.chmod(0o700)

    report = run_state_diagnostics(layout)

    assert report.status == "ok"
    assert all(check.status == "passed" for check in report.checks)


def test_diagnostics_surface_pending_publication_without_identifiers(tmp_path: Path) -> None:
    layout = StateLayout(tmp_path / "state")
    migrate_state(layout.root, apply=True)
    staged = layout.root / "staged"
    staged.mkdir()
    staged.chmod(0o700)
    (staged / "sensitive-run-name.json").write_text("{}\n", encoding="utf-8")
    (staged / "sensitive-run-name.json").chmod(0o600)

    payload = run_state_diagnostics(layout).to_dict()
    serialized = json.dumps(payload)

    assert payload["status"] == "degraded"
    pending = next(check for check in payload["checks"] if check["check_id"] == "publication_recovery")
    assert pending["details"] == {"pending_artifact_count": 1}
    assert "sensitive-run-name" not in serialized


def test_diagnostics_fail_closed_without_leaking_registry_credentials(tmp_path: Path) -> None:
    layout = StateLayout(tmp_path / "state")
    migrate_state(layout.root, apply=True)
    registry_dir = layout.root / ".presentation"
    registry_dir.mkdir(mode=0o700)
    registry = registry_dir / "viewer.json"
    registry.write_text('{"access_token":"do-not-leak","instance_id":"viewer"}\n', encoding="utf-8")
    registry.chmod(0o600)

    serialized = json.dumps(run_state_diagnostics(layout).to_dict())

    assert "do-not-leak" not in serialized
    assert "access_token" not in serialized


def test_diagnostic_details_reject_secret_shaped_fields() -> None:
    with pytest.raises(ValueError, match="secret-shaped"):
        DiagnosticCheck("unsafe", "passed", "unsafe", {"access_token": "hidden"})
