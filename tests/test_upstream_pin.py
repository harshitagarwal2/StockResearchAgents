from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents_portable.conformance import PINNED_UPSTREAM_REVISION

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upstream_pin.py"
PINNED_SURFACES = (
    "upstream.lock.json",
    "pyproject.toml",
    "uv.lock",
    "src/tradingagents_portable/conformance.py",
    ".github/workflows/ci.yml",
    "src/tradingagents_portable/workflow/legacy-transition.v1.json",
    "evidence/parity-ledger.v1.json",
)


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
    for relative in PINNED_SURFACES:
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    unrelated = tmp_path / "uv.lock"
    unrelated.write_text(
        unrelated.read_text(encoding="utf-8") + f"\n# unrelated revision marker: {PINNED_UPSTREAM_REVISION}\n",
        encoding="utf-8",
    )

    revision = "1" * 40
    updated = _run("--set-revision", revision, root=tmp_path)
    checked = _run("--check", root=tmp_path)
    lock = json.loads((tmp_path / "upstream.lock.json").read_text(encoding="utf-8"))

    assert updated.returncode == 0, updated.stderr
    assert checked.returncode == 0, checked.stderr
    assert lock["revision"] == revision
    for relative in PINNED_SURFACES[1:]:
        assert revision in (tmp_path / relative).read_text(encoding="utf-8")
    assert f"unrelated revision marker: {PINNED_UPSTREAM_REVISION}" in unrelated.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("relative", "literal"),
    (
        ("pyproject.toml", "TradingAgents.git@"),
        ("uv.lock", "TradingAgents.git?rev="),
        ("uv.lock", f"TradingAgents.git?rev={PINNED_UPSTREAM_REVISION}#"),
        ("src/tradingagents_portable/conformance.py", 'PINNED_UPSTREAM_REVISION = "'),
        (".github/workflows/ci.yml", "ref: "),
        ("src/tradingagents_portable/workflow/legacy-transition.v1.json", '"exact_revision": "'),
        ("evidence/parity-ledger.v1.json", '"upstream_revision": "'),
    ),
)
def test_upstream_pin_check_rejects_drift_on_each_surface(tmp_path: Path, relative: str, literal: str) -> None:
    for pinned_surface in PINNED_SURFACES:
        source = ROOT / pinned_surface
        destination = tmp_path / pinned_surface
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    path = tmp_path / relative
    text = path.read_text(encoding="utf-8")
    start = text.index(literal) + len(literal)
    path.write_text(text[:start] + ("2" * 40) + text[start + 40 :], encoding="utf-8")

    checked = _run("--check", root=tmp_path)

    assert checked.returncode != 0
    assert "upstream" in checked.stderr
