from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tradingrearchagents.contracts import RunRequest
from tradingrearchagents.export import export_run_bundle
from tradingrearchagents.fixture import run_fixture
from tradingrearchagents.store import RunStore

EXPECTED_REPORTS = {
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
}

ROOT = Path(__file__).resolve().parents[1]


def _crash_overwrite_between_renames(target: Path) -> subprocess.CompletedProcess[str]:
    script = r"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))
import tradingrearchagents.export as export_module
from tradingrearchagents.contracts import RunRequest
from tradingrearchagents.fixture import run_fixture
from tradingrearchagents.store import RunStore

target = Path(sys.argv[1])
real_replace = export_module.os.replace

def crash_before_publish(source, destination):
    source_path = Path(source)
    if Path(destination) == target and source_path.name.startswith(f".{target.name}.tmp-"):
        os._exit(73)
    return real_replace(source, destination)

export_module.os.replace = crash_before_publish
result, events = run_fixture(RunRequest(), RunStore())
export_module.export_run_bundle(
    result,
    events,
    target,
    lifecycle_log=({"kind": "interrupted", "run_id": result.run_id},),
    overwrite=True,
)
"""
    return subprocess.run(
        [sys.executable, "-c", script, str(target)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_export_writes_atomic_upstream_compatible_bundle_with_verified_manifest(tmp_path: Path) -> None:
    result, events = run_fixture(RunRequest(symbol="ORCL"), RunStore())
    target = tmp_path / "bundle"
    receipt = export_run_bundle(
        result,
        events,
        target,
        lifecycle_log=({"kind": "completed", "run_id": result.run_id},),
    )

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert EXPECTED_REPORTS <= paths
    assert {"result.json", "events.ndjson", "lifecycle/log.jsonl"} <= paths
    assert receipt.manifest_sha256 == hashlib.sha256((target / "manifest.json").read_bytes()).hexdigest()
    assert json.loads(json.dumps(receipt.to_dict(), allow_nan=False))["run_id"] == result.run_id
    for item in manifest["files"]:
        content = (target / item["path"]).read_bytes()
        assert item["bytes"] == len(content)
        assert item["sha256"] == hashlib.sha256(content).hexdigest()

    event_lines = (target / "events.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == len(events)
    assert all(json.loads(line)["run_id"] == result.run_id for line in event_lines)
    assert json.loads((target / "result.json").read_text(encoding="utf-8"))["run_id"] == result.run_id


def test_export_refuses_existing_target_without_leaving_staging_directory(tmp_path: Path) -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    target = tmp_path / "bundle"
    target.mkdir()
    marker = target / "owned.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError):
        export_run_bundle(result, events, target)

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def test_export_overwrite_refuses_arbitrary_directory_and_preserves_contents(tmp_path: Path) -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    target = tmp_path / "bundle"
    target.mkdir()
    marker = target / "owned.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest"):
        export_run_bundle(result, events, target, overwrite=True)

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def test_export_rejects_symlink_destination_without_touching_referent(tmp_path: Path) -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    referent = tmp_path / "referent"
    referent.mkdir()
    marker = referent / "owned.txt"
    marker.write_text("preserve", encoding="utf-8")
    target = tmp_path / "bundle"
    target.symlink_to(referent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        export_run_bundle(result, events, target, overwrite=True)

    assert target.is_symlink()
    assert marker.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("target", (Path.home(), Path.cwd(), Path.cwd().parent))
def test_export_rejects_protected_broad_destination(target: Path) -> None:
    result, events = run_fixture(RunRequest(), RunStore())

    with pytest.raises(ValueError, match="protected"):
        export_run_bundle(result, events, target, overwrite=True)


def test_export_overwrite_refuses_tampered_prior_bundle(tmp_path: Path) -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    target = tmp_path / "bundle"
    export_run_bundle(result, events, target)
    report = target / "complete_report.md"
    report.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest"):
        export_run_bundle(result, events, target, overwrite=True)

    assert report.read_text(encoding="utf-8") == "tampered\n"


def test_export_overwrite_replaces_valid_prior_bundle(tmp_path: Path) -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    target = tmp_path / "bundle"
    export_run_bundle(result, events, target)

    receipt = export_run_bundle(
        result,
        events,
        target,
        lifecycle_log=({"kind": "completed", "run_id": result.run_id},),
        overwrite=True,
    )

    assert (target / "lifecycle/log.jsonl").is_file()
    assert receipt.manifest_sha256 == hashlib.sha256((target / "manifest.json").read_bytes()).hexdigest()
    assert not list(tmp_path.glob(".bundle.tmp-*"))
    assert not list(tmp_path.glob(".bundle.backup-*"))


def test_export_recovers_process_crash_between_overwrite_renames(tmp_path: Path) -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    target = tmp_path / "bundle"
    export_run_bundle(result, events, target)

    crashed = _crash_overwrite_between_renames(target)

    assert crashed.returncode == 73, crashed.stderr
    assert not target.exists()
    assert len(list(tmp_path.glob(".bundle.overwrite.json"))) == 1
    assert len(list(tmp_path.glob(".bundle.backup-*"))) == 1
    assert len(list(tmp_path.glob(".bundle.tmp-*"))) == 1

    export_run_bundle(
        result,
        events,
        target,
        lifecycle_log=({"kind": "recovered", "run_id": result.run_id},),
        overwrite=True,
    )

    assert json.loads((target / "lifecycle/log.jsonl").read_text(encoding="utf-8"))["kind"] == "recovered"
    assert not list(tmp_path.glob(".bundle.overwrite.json"))
    assert not list(tmp_path.glob(".bundle.backup-*"))
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def test_crash_recovery_never_removes_tampered_staging_data(tmp_path: Path) -> None:
    result, events = run_fixture(RunRequest(), RunStore())
    target = tmp_path / "bundle"
    export_run_bundle(result, events, target)
    crashed = _crash_overwrite_between_renames(target)
    assert crashed.returncode == 73, crashed.stderr
    interrupted_staging = next(tmp_path.glob(".bundle.tmp-*"))
    marker = interrupted_staging / "arbitrary-user-data.txt"
    marker.write_text("preserve", encoding="utf-8")

    export_run_bundle(result, events, target, overwrite=True)

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert target.is_dir()
    assert not list(tmp_path.glob(".bundle.overwrite.json"))
    assert not list(tmp_path.glob(".bundle.backup-*"))


def test_export_rejects_mismatched_events_and_secret_shaped_lifecycle_keys(tmp_path: Path) -> None:
    first, first_events = run_fixture(RunRequest(symbol="ORCL"), RunStore())
    mismatched_events = (replace(first_events[0], run_id="another-run"),)

    with pytest.raises(ValueError, match="result.run_id"):
        export_run_bundle(first, mismatched_events, tmp_path / "mismatch")
    with pytest.raises(ValueError, match="credential-shaped"):
        export_run_bundle(
            first,
            first_events,
            tmp_path / "secret",
            lifecycle_log=({"api_key": "forbidden"},),
        )
    assert not (tmp_path / "secret").exists()
