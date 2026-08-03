#!/usr/bin/env python3
"""Validate or update the pinned upstream TradingAgents revision."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PYPROJECT_RE = re.compile(
    r"(tradingagents @ git\+https://github\.com/TauricResearch/TradingAgents\.git@)([0-9a-f]{40})"
)
CONFORMANCE_RE = re.compile(r'(PINNED_UPSTREAM_REVISION = ")([0-9a-f]{40})(")')
UV_RE = re.compile(r"https://github\.com/TauricResearch/TradingAgents\.git\?rev=([0-9a-f]{40})")


class PinError(RuntimeError):
    """Raised when an upstream pin is missing or inconsistent."""


def _load_lock(root: Path) -> dict[str, str]:
    path = root / "upstream.lock.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    expected_repository = "TauricResearch/TradingAgents"
    if data.get("repository") != expected_repository:
        raise PinError(f"upstream repository must be {expected_repository}")
    revision = data.get("revision", "")
    if not SHA_RE.fullmatch(revision):
        raise PinError("upstream revision must be a full lowercase 40-character Git SHA")
    if not data.get("tracking_ref"):
        raise PinError("upstream tracking_ref is required")
    return data


def _single_revision(pattern: re.Pattern[str], text: str, label: str, group: int) -> str:
    revisions = {match.group(group) for match in pattern.finditer(text)}
    if len(revisions) != 1:
        raise PinError(f"{label} must contain exactly one upstream revision; found {sorted(revisions)}")
    return revisions.pop()


def observed_revisions(root: Path) -> dict[str, str]:
    return {
        "lock": _load_lock(root)["revision"],
        "pyproject": _single_revision(PYPROJECT_RE, (root / "pyproject.toml").read_text(), "pyproject.toml", 2),
        "conformance": _single_revision(
            CONFORMANCE_RE,
            (root / "src" / "tradingrearchagents" / "conformance.py").read_text(),
            "conformance.py",
            2,
        ),
        "uv_lock": _single_revision(UV_RE, (root / "uv.lock").read_text(), "uv.lock", 1),
    }


def check(root: Path) -> str:
    revisions = observed_revisions(root)
    expected = revisions["lock"]
    mismatches = {name: revision for name, revision in revisions.items() if revision != expected}
    if mismatches:
        details = ", ".join(f"{name}={revision}" for name, revision in mismatches.items())
        raise PinError(f"upstream pin drift: lock={expected}; {details}")
    return expected


def set_revision(root: Path, revision: str) -> None:
    revision = revision.lower()
    if not SHA_RE.fullmatch(revision):
        raise PinError("new revision must be a full 40-character Git SHA")

    current = check(root)
    lock = _load_lock(root)
    lock["revision"] = revision
    (root / "upstream.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    pyproject_path = root / "pyproject.toml"
    pyproject = PYPROJECT_RE.sub(lambda match: f"{match.group(1)}{revision}", pyproject_path.read_text())
    pyproject_path.write_text(pyproject, encoding="utf-8")

    conformance_path = root / "src" / "tradingrearchagents" / "conformance.py"
    conformance = CONFORMANCE_RE.sub(
        lambda match: f"{match.group(1)}{revision}{match.group(3)}",
        conformance_path.read_text(),
    )
    conformance_path.write_text(conformance, encoding="utf-8")

    uv_path = root / "uv.lock"
    uv_path.write_text(uv_path.read_text().replace(current, revision), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--print-revision", action="store_true")
    action.add_argument("--print-repository", action="store_true")
    action.add_argument("--print-tracking-ref", action="store_true")
    action.add_argument("--set-revision")
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        if args.set_revision:
            set_revision(root, args.set_revision)
            print(args.set_revision.lower())
        elif args.print_repository:
            print(_load_lock(root)["repository"])
        elif args.print_tracking_ref:
            print(_load_lock(root)["tracking_ref"])
        elif args.print_revision:
            print(_load_lock(root)["revision"])
        else:
            print(f"upstream pin {check(root)} is consistent")
    except (OSError, ValueError, PinError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
