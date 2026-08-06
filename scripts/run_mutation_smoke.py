#!/usr/bin/env python3
"""Run a small, deterministic mutation gate against critical policy boundaries."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Mutation:
    mutation_id: str
    relative_path: str
    original: str
    replacement: str
    expected_occurrences: int
    tests: tuple[str, ...]


MUTATIONS = (
    Mutation(
        "binary-brier-formula",
        "src/stock_research_agents/research_quality_v1/cohorts.py",
        "(probability - outcome) ** 2",
        "abs(probability - outcome)",
        1,
        ("tests/test_research_quality_cohorts.py",),
    ),
    Mutation(
        "lifecycle-revision-increment",
        "src/stock_research_agents/lifecycle.py",
        'candidate["revision"] = expected_revision + 1',
        'candidate["revision"] = expected_revision',
        2,
        ("tests/test_lifecycle_store_concurrency.py",),
    ),
    Mutation(
        "chrome-public-address-gate",
        "src/stock_research_agents_host/adapters/chrome.py",
        """return (
        address.is_global
        and not address.is_multicast
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_reserved
        and not address.is_unspecified
        and not getattr(address, \"is_site_local\", False)
    )""",
        "return True",
        1,
        ("tests/test_chrome_routability_invariant.py",),
    ),
)


def _run_tests(root: Path, tests: tuple[str, ...], state_name: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["STOCKRESEARCHAGENTS_STATE_DIR"] = str(root / ".mutation-state" / state_name)
    return subprocess.run(  # noqa: S603 - fixed current interpreter and repository-owned test paths
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="stockresearchagents-mutation-") as directory:
        isolated = Path(directory)
        shutil.copytree(ROOT / "src", isolated / "src")
        shutil.copytree(ROOT / "tests", isolated / "tests")

        baseline_commands = {mutation.tests for mutation in MUTATIONS}
        for index, tests in enumerate(sorted(baseline_commands)):
            baseline = _run_tests(isolated, tests, f"baseline-{index}")
            if baseline.returncode != 0:
                print(baseline.stdout)
                print(baseline.stderr, file=sys.stderr)
                raise RuntimeError(f"mutation baseline failed for {' '.join(tests)}")

        for mutation in MUTATIONS:
            path = isolated / mutation.relative_path
            original_bytes = path.read_bytes()
            source = original_bytes.decode()
            occurrences = source.count(mutation.original)
            if occurrences != mutation.expected_occurrences:
                raise RuntimeError(
                    f"{mutation.mutation_id} expected {mutation.expected_occurrences} source matches, got {occurrences}"
                )
            path.write_text(source.replace(mutation.original, mutation.replacement), encoding="utf-8")
            completed = _run_tests(isolated, mutation.tests, mutation.mutation_id)
            path.write_bytes(original_bytes)
            killed = completed.returncode != 0
            results.append(
                {
                    "mutation_id": mutation.mutation_id,
                    "killed": killed,
                    "test_exit_code": completed.returncode,
                }
            )
            if not killed:
                print(completed.stdout)
                print(completed.stderr, file=sys.stderr)

    report = {
        "schema_version": "stockresearchagents-mutation-smoke.v1",
        "mutations": results,
        "passed": all(item["killed"] is True for item in results),
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
