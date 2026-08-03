from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from tradingrearchagents.conformance import PINNED_UPSTREAM_REVISION

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upstream_pin.py"


def _run(*args: str, root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_upstream_pin_is_consistent_and_matches_runtime_contract() -> None:
    checked = _run("--check")
    printed = _run("--print-revision")
    repository = _run("--print-repository")
    tracking_ref = _run("--print-tracking-ref")

    assert checked.returncode == 0, checked.stderr
    assert printed.returncode == 0, printed.stderr
    assert printed.stdout.strip() == PINNED_UPSTREAM_REVISION
    assert repository.stdout.strip() == "TauricResearch/TradingAgents"
    assert tracking_ref.stdout.strip() == "main"


def test_upstream_pin_update_changes_every_pinned_surface(tmp_path: Path) -> None:
    for relative in (
        "upstream.lock.json",
        "pyproject.toml",
        "uv.lock",
        "src/tradingrearchagents/conformance.py",
    ):
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    revision = "1" * 40
    updated = _run("--set-revision", revision, root=tmp_path)
    checked = _run("--check", root=tmp_path)
    lock = json.loads((tmp_path / "upstream.lock.json").read_text(encoding="utf-8"))

    assert updated.returncode == 0, updated.stderr
    assert checked.returncode == 0, checked.stderr
    assert lock["revision"] == revision
    for relative in ("pyproject.toml", "uv.lock", "src/tradingrearchagents/conformance.py"):
        assert revision in (tmp_path / relative).read_text(encoding="utf-8")
