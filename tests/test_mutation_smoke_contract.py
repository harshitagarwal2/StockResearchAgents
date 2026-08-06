from __future__ import annotations

from pathlib import Path

from scripts.run_mutation_smoke import MUTATIONS

ROOT = Path(__file__).resolve().parents[1]


def test_mutation_smoke_targets_distinct_critical_boundaries() -> None:
    assert {mutation.mutation_id for mutation in MUTATIONS} == {
        "binary-brier-formula",
        "chrome-public-address-gate",
        "lifecycle-revision-increment",
    }
    assert all(mutation.expected_occurrences > 0 for mutation in MUTATIONS)
    for mutation in MUTATIONS:
        source = (ROOT / mutation.relative_path).read_text(encoding="utf-8")
        assert source.count(mutation.original) == mutation.expected_occurrences


def test_mutation_workflow_is_scheduled_manual_and_non_release_gating() -> None:
    workflow = (ROOT / ".github" / "workflows" / "quality-depth.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "python scripts/run_mutation_smoke.py" in workflow
