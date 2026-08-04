from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tradingagents_portable.oracle_semantics import (
    DEFAULT_ORACLE_CASES,
    SemanticDifference,
    compare_observable_projections,
    portable_observable_projection,
    run_semantic_differential,
    upstream_observable_projection,
)
from tradingagents_portable.workflow import load_legacy_transition_manifest

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT.parent / "tradingAgents"


def test_pinned_upstream_pure_semantics_match_portable_contract() -> None:
    report = run_semantic_differential(upstream_path=UPSTREAM, portable_root=ROOT)

    assert report.passed is True
    assert report.release_evidence_eligible is (not report.portable_worktree_dirty)
    assert report.differences == ()
    assert len(report.case_digest) == 64
    assert len(report.comparator_digest) == 64
    assert len(report.cases) == len(DEFAULT_ORACLE_CASES)
    assert all(item["passed"] is True for item in report.cases)


def test_semantic_differential_reports_json_pointer_drift() -> None:
    case = DEFAULT_ORACLE_CASES[0]
    upstream = upstream_observable_projection(case, upstream_path=UPSTREAM)
    portable = portable_observable_projection(case, portable_root=ROOT)
    broken = replace(portable, processed_signal_vocabulary=("buy", "hold", "sell"))

    differences = compare_observable_projections(upstream, broken)

    assert differences == (
        SemanticDifference(
            "/processed_signal_vocabulary",
            ["buy", "overweight", "hold", "underweight", "sell"],
            ["buy", "hold", "sell"],
        ),
    )


def test_upstream_probe_fails_before_import_for_wrong_checkout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="checkout not found"):
        upstream_observable_projection(DEFAULT_ORACLE_CASES[0], upstream_path=tmp_path)


def test_parity_ledger_covers_every_scoped_upstream_observable_once() -> None:
    ledger = json.loads((ROOT / "evidence" / "parity-ledger.v1.json").read_text(encoding="utf-8"))
    whitelist = load_legacy_transition_manifest()["oracle"]["whitelist"]

    assert ledger["upstream_revision"] == load_legacy_transition_manifest()["oracle"]["exact_revision"]
    assert [row["observable"] for row in ledger["rows"]] == whitelist
    assert all(row["status"] == "implemented_unverified" for row in ledger["rows"])
