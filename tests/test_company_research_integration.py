from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from research_v3_fixtures import complete_v3_submission

from tradingagents_portable.capabilities import discovery
from tradingagents_portable.cli import main
from tradingagents_portable.company_lifecycle import CompanyResearchCoordinator
from tradingagents_portable.company_research import prepare_company_research, submit_company_research
from tradingagents_portable.conformance import evaluate_conformance
from tradingagents_portable.lifecycle import LifecycleStore
from tradingagents_portable.store import RunStore
from tradingagents_portable.view import build_run_view
from tradingagents_portable.workflow import workflow_profile_catalog


def test_company_plan_advertises_all_stages_and_frozen_terminal_schema() -> None:
    payload = complete_v3_submission("META")

    plan = prepare_company_research(payload["request"])

    assert plan["workflow_profile"] == "company-research.v2"
    assert plan["workflow_id"] == "tradingagents.company-research.v2"
    assert [stage["ordinal"] for stage in plan["stages"]] == list(range(1, 16))
    assert plan["stages"][0]["id"] == "research.plan"
    assert plan["stages"][-1]["id"] == "publish.dossier"
    assert plan["submission_schema"]["$ref"] == "#/$defs/hostSubmission"
    assert plan["execution_owner"] == "host_harness"
    assert plan["external_model_api_keys_accepted"] is False


@pytest.mark.parametrize("symbol", ["ORCL", "META", "QQQ", "ACME"])
def test_company_import_publishes_complete_generic_dossier(symbol: str) -> None:
    store = RunStore()

    result, events = submit_company_research(complete_v3_submission(symbol), store=store)

    assert result.request.symbol == symbol
    assert result.status.value == "completed"
    assert result.portfolio_decision.executable is False
    assert result.portfolio_decision.execution_authority == "none"
    assert result.trader_decision.submitted is False
    assert result.capability.deterministic is True
    assert result.capability.live_data is False
    assert len(result.evidence) >= 1
    assert all(item.provenance.fixture for item in result.evidence)
    assert all(report.analyst != "social" for report in result.analyst_reports)
    blocked_ids = {
        item.id for item in result.evidence if item.values.get("entitlement", {}).get("access") == "entitlement_blocked"
    }
    assert blocked_ids
    assert all(not blocked_ids.intersection(report.evidence_ids) for report in result.analyst_reports)
    debate_turns = (*result.research_debate, *result.risk_debate)
    assert all(not blocked_ids.intersection(turn.evidence_ids) for turn in debate_turns)
    assert result.persistence.decision_memory_enabled is False
    assert result.persistence.checkpoint_enabled is False
    dossier = next(artifact for artifact in result.artifacts if artifact.kind == "research_dossier.v3")
    assert dossier.content["identity"]["symbol"] == symbol
    assert store.get_result(result.run_id) == result
    assert store.get_events(result.run_id) == events
    view = build_run_view(result, events).to_dict()
    assert view["research_request"]["research_mode"] == "fixture"
    assert view["research_dossier"]["identity"]["symbol"] == symbol
    assert view["research_dossier"]["evaluation"]["checks"]
    conformance = evaluate_conformance(result, events)
    checks = {check.name: check for check in conformance.checks}
    assert checks["workflow_stage_order"].passed
    assert checks["research_dossier_v3_semantics"].passed
    assert checks["research_request_v3_truthfulness"].passed


def test_company_import_is_content_addressed_and_symbol_specific() -> None:
    store = RunStore()
    first, _ = submit_company_research(complete_v3_submission("ORCL"), store=store)
    repeated, _ = submit_company_research(complete_v3_submission("ORCL"), store=store)
    other, _ = submit_company_research(complete_v3_submission("META"), store=store)

    assert first.run_id == repeated.run_id
    assert other.run_id != first.run_id


def test_stateless_import_cannot_claim_unperformed_persistence() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        submit_company_research(  # type: ignore[call-arg]
            complete_v3_submission("ORCL"),
            store=RunStore(),
            decision_memory_enabled=True,
        )


def test_projection_preserves_absent_risk_debate_without_synthetic_turns() -> None:
    submission = complete_v3_submission("ORCL")
    assert all(argument["debate"] == "research" for argument in submission["dossier"]["arguments"])

    result, events = submit_company_research(submission, store=RunStore())

    assert len(result.research_debate) == len(submission["dossier"]["arguments"])
    assert result.risk_debate == ()
    assert result.risk_debate_snapshot.count == 0
    report = evaluate_conformance(result, events)
    assert next(item for item in report.checks if item.name == "risk_debate_count").passed


@pytest.mark.parametrize(
    ("research_mode", "deterministic", "live_data", "fixture_provenance"),
    [
        ("fixture", True, False, True),
        ("historical_replay", False, False, False),
        ("live", False, True, False),
    ],
)
def test_research_mode_drives_capability_and_source_truthfulness(
    research_mode: str,
    deterministic: bool,
    live_data: bool,
    fixture_provenance: bool,
) -> None:
    submission = complete_v3_submission("ORCL")
    submission["request"]["research_mode"] = research_mode

    result, events = submit_company_research(submission, store=RunStore())
    view = build_run_view(result, events).to_dict()

    assert result.capability.deterministic is deterministic
    assert result.capability.live_data is live_data
    assert all(item.provenance.fixture is fixture_provenance for item in result.evidence)
    assert view["research_request"]["research_mode"] == research_mode


def test_conformance_rejects_tampered_research_mode_projection() -> None:
    result, events = submit_company_research(complete_v3_submission("ORCL"), store=RunStore())
    artifacts = tuple(
        replace(artifact, content={**artifact.content, "research_mode": "live"})
        if artifact.kind == "research_request.v3"
        else artifact
        for artifact in result.artifacts
    )

    report = evaluate_conformance(replace(result, artifacts=artifacts), events)
    check = next(item for item in report.checks if item.name == "research_request_v3_truthfulness")

    assert check.passed is False


def test_discovery_negotiates_all_versioned_profiles() -> None:
    profiles = workflow_profile_catalog()
    capability = discovery(include_legacy=False)

    assert [item["profile"] for item in profiles] == [
        "financial-research.v1",
        "company-research.v2",
        "company-analytics.v1",
    ]
    assert capability["workflow_profiles"] == profiles
    assert "prepare_company_research" in capability["tools"]
    assert "import_company_research" in capability["tools"]
    assert "create_company_research_run" in capability["tools"]


def test_company_cli_plan_import_and_durable_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = complete_v3_submission("META")
    request_path = tmp_path / "request.json"
    submission_path = tmp_path / "submission.json"
    plan_path = tmp_path / "plan.json"
    result_path = tmp_path / "result.json"
    init_path = tmp_path / "init.json"
    import json

    request_path.write_text(json.dumps(payload["request"]), encoding="utf-8")
    submission_path.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["company-plan", "--input", str(request_path), "--output", str(plan_path)]) == 0
    assert main(["company-import", "--input", str(submission_path), "--output", str(result_path)]) == 0
    coordinator = CompanyResearchCoordinator(
        LifecycleStore(tmp_path / "lifecycle"),
        RunStore(tmp_path / "lifecycle-runs"),
    )
    monkeypatch.setattr("tradingagents_portable.cli.COMPANY_RESEARCH_COORDINATOR", coordinator)
    assert (
        main(
            [
                "company-init",
                "--input",
                str(request_path),
                "--output",
                str(init_path),
                "--no-decision-memory",
            ]
        )
        == 0
    )
    assert json.loads(plan_path.read_text(encoding="utf-8"))["workflow_id"] == "tradingagents.company-research.v2"
    imported = json.loads(result_path.read_text(encoding="utf-8"))
    assert imported["result"]["request"]["symbol"] == "META"
    assert imported["view"]["research_dossier"]["identity"]["symbol"] == "META"
    initialized = json.loads(init_path.read_text(encoding="utf-8"))
    assert initialized["control"]["workflow_profile"] == "company-research.v2"
    assert initialized["control"]["next_stage_id"] == "research.plan"


def test_mcp_company_create_uses_generic_lifecycle_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tradingagents_portable import mcp_server

    coordinator = CompanyResearchCoordinator(
        LifecycleStore(tmp_path / "mcp-lifecycle"),
        RunStore(tmp_path / "mcp-runs"),
    )
    monkeypatch.setattr(mcp_server, "COMPANY_RESEARCH_COORDINATOR", coordinator)

    created = mcp_server.create_company_research_run(
        complete_v3_submission("ORCL")["request"],
        decision_memory_enabled=False,
    )
    control = created["control"]
    started = mcp_server.start_host_run(control["run_id"], control["revision"])

    assert started["stage"]["id"] == "research.plan"
    assert mcp_server.get_run_control(control["run_id"])["control"]["workflow_profile"] == "company-research.v2"
