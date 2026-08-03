from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tradingagents_portable.cli import main
from tradingagents_portable.contracts import EventKind, RunRequest, RunStatus
from tradingagents_portable.host_native import prepare_host_run, submit_host_run
from tradingagents_portable.store import RunStore
from tradingagents_portable.workflow import load_host_submission_schema


def _payload() -> dict[str, object]:
    evidence = [
        {
            "id": f"ev-{analyst}",
            "category": analyst,
            "title": f"{analyst.title()} evidence",
            "summary": f"Verified {analyst} evidence.",
            "values": {"sample": 1},
            "provenance": {
                "provider": "public-source",
                "source_type": "primary_document",
                "source_uri": f"https://example.com/{analyst}",
                "retrieved_at": "2026-08-02T12:00:00+00:00",
                "source_date": "2026-08-01",
            },
            "limitations": ["Test payload."],
        }
        for analyst in ("market", "social", "news", "fundamentals")
    ]
    reports = [
        {
            "analyst": analyst,
            "thesis": f"{analyst} thesis",
            "evidence_ids": [f"ev-{analyst}"],
            "confidence": 0.7,
            "content": f"Complete {analyst} report.",
        }
        for analyst in ("market", "social", "news", "fundamentals")
    ]
    return {
        "request": {
            "schema_version": "2026-08-02",
            "symbol": "ORCL",
            "as_of_date": "2026-08-01",
            "asset_type": "stock",
            "analysts": ["market", "social", "news", "fundamentals"],
            "debate_rounds": 1,
            "risk_rounds": 1,
            "output_language": "English",
            "executor": "host_native",
            "checkpoint_enabled": False,
        },
        "company_of_interest": "Oracle Corporation",
        "instrument_context": "NYSE common stock",
        "evidence": evidence,
        "analyst_reports": reports,
        "research_debate": [
            {
                "round": 1,
                "speaker": "Bull Researcher",
                "position": "Bull case.",
                "evidence_ids": ["ev-market", "ev-fundamentals"],
            },
            {
                "round": 1,
                "speaker": "Bear Researcher",
                "position": "Bear case.",
                "responds_to": "Bull Researcher",
                "evidence_ids": ["ev-market", "ev-fundamentals"],
            },
        ],
        "research_decision": {"decision": "Hold", "rationale": "Manager synthesis.", "confidence": 0.72},
        "trader_decision": {
            "stance": "hold",
            "plan": "Research-only hold stance.",
            "caveats": ["No suitability review."],
        },
        "risk_debate": [
            {
                "round": 1,
                "speaker": speaker,
                "position": f"{speaker} view.",
                "evidence_ids": ["ev-fundamentals"],
            }
            for speaker in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst")
        ],
        "risk_decision": {
            "risk_level": "high",
            "constraints": ["No order execution."],
            "unresolved": ["Future cash conversion."],
        },
        "portfolio_decision": {"action": "hold", "summary": "Hold research stance; no order is authorized."},
    }


def test_host_native_submission_is_complete_credential_free_and_ui_ready() -> None:
    store = RunStore()
    result, events = submit_host_run(_payload(), store=store)

    assert result.status is RunStatus.COMPLETED
    assert result.request.executor == "host_native"
    assert result.capability.external_credentials_required is False
    assert result.capability.observation_mode == "host_native_submission"
    assert result.trader_decision.executable is False
    assert result.portfolio_decision.executable is False
    assert len(result.analyst_reports) == 4
    assert len(result.research_debate) == 2
    assert len(result.risk_debate) == 3
    assert {artifact.id for artifact in result.artifacts} >= {
        "report.group.1.analysts",
        "report.group.2.research",
        "report.group.3.trading",
        "report.group.4.risk",
        "report.group.5.portfolio",
        "report.complete",
    }
    assert events[0].kind is EventKind.RUN
    assert events[-1].status == RunStatus.COMPLETED.value
    assert store.current_run_id() == result.run_id
    for stage in result.topology.stages:
        stage_events = [event for event in events if event.stage_id == stage.id]
        assert len(stage_events) == 1
        assert stage_events[0].status == "imported"
        assert stage_events[0].data["output_observed"] is True
        assert stage_events[0].data["execution_observed"] is False


def test_canonical_import_payload_validates_against_the_published_json_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = load_host_submission_schema()
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())

    validator.check_schema(schema)
    validator.validate(_payload())


def test_host_import_is_idempotent_for_the_same_complete_payload() -> None:
    store = RunStore()
    first_result, first_events = submit_host_run(_payload(), store=store)
    second_result, second_events = submit_host_run(_payload(), store=store)

    assert second_result == first_result
    assert second_events == first_events


def test_host_plan_is_stateless_and_matches_canonical_topology() -> None:
    plan = prepare_host_run(RunRequest(executor="host_native"))

    assert plan["execution_owner"] == "host_harness"
    assert plan["external_model_api_keys_accepted"] is False
    assert plan["publication"] == "atomic_after_complete_validation"
    assert len(plan["topology"]["stages"]) == 12
    assert plan["workflow_semantics"]["defaults"]["debate_rounds"] == 1
    assert "analyst.market" in plan["workflow_semantics"]["stage_instructions"]
    assert "Never request an API key" in plan["workflow_semantics"]["evidence_policy"]["fallback"]


def test_prepared_request_round_trips_unchanged_through_import() -> None:
    payload = _payload()
    plan = prepare_host_run(RunRequest(symbol="ORCL", as_of_date="2026-08-01", executor="host_native"))
    payload["request"] = plan["request"]

    result, _events = submit_host_run(payload, store=RunStore())

    assert result.request.symbol == "ORCL"
    assert set(plan["request"]) == {
        "schema_version",
        "symbol",
        "as_of_date",
        "asset_type",
        "analysts",
        "debate_rounds",
        "risk_rounds",
        "output_language",
        "executor",
        "checkpoint_enabled",
    }


def test_host_request_preserves_non_english_output_language() -> None:
    payload = _payload()
    payload["request"]["output_language"] = "Japanese"  # type: ignore[index]

    result, _events = submit_host_run(payload, store=RunStore())

    assert result.request.output_language == "Japanese"
    assert result.execution_config.output_language == "Japanese"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("retrieved_at", "not-a-timestamp", "ISO 8601 timestamp"),
        ("retrieved_at", "2026-08-02T12:00:00", "timezone offset"),
        ("source_date", "not-a-date", "ISO date"),
        ("source_date", "2026-08-02", "must not be after"),
    ],
)
def test_host_import_rejects_invalid_or_post_cutoff_provenance(field: str, value: str, message: str) -> None:
    payload = _payload()
    payload["evidence"][0]["provenance"][field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        submit_host_run(payload, store=RunStore())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("debate_rounds", 1.9, "must be an integer"),
        ("risk_rounds", True, "must be an integer"),
    ],
)
def test_host_import_does_not_coerce_round_counts(field: str, value: object, message: str) -> None:
    payload = _payload()
    payload["request"][field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        submit_host_run(payload, store=RunStore())


def test_host_import_requires_public_source_url() -> None:
    payload = _payload()
    payload["evidence"][0]["provenance"]["source_uri"] = None  # type: ignore[index]

    with pytest.raises(ValueError, match="must be a string"):
        submit_host_run(payload, store=RunStore())


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (("risk_decision", "constraints"), "must be an array"),
        (("risk_decision", "unresolved"), "must be an array"),
        (("trader_decision", "caveats"), "must be an array"),
        (("warnings",), "must be an array"),
        (("evidence", 0, "limitations"), "must be an array"),
        (("evidence", 0, "provenance", "notes"), "must be an array"),
    ],
)
def test_host_import_rejects_explicit_null_arrays(path: tuple[object, ...], message: str) -> None:
    payload = _payload()
    target: object = payload
    for segment in path[:-1]:
        target = target[segment]  # type: ignore[index]
    target[path[-1]] = None  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        submit_host_run(payload, store=RunStore())


def test_run_request_rejects_future_cutoff() -> None:
    with pytest.raises(ValueError, match="cannot be in the future"):
        RunRequest(symbol="ORCL", as_of_date="9999-12-31", executor="host_native")


def test_host_import_requires_report_and_debate_provenance() -> None:
    report_payload = _payload()
    report_payload["analyst_reports"][0]["evidence_ids"] = []  # type: ignore[index]
    with pytest.raises(ValueError, match="must reference at least one"):
        submit_host_run(report_payload, store=RunStore())

    debate_payload = _payload()
    debate_payload["research_debate"][0]["evidence_ids"] = []  # type: ignore[index]
    with pytest.raises(ValueError, match="must reference at least one"):
        submit_host_run(debate_payload, store=RunStore())


def test_host_cli_plan_and_import_round_trip(tmp_path: Path) -> None:
    root = tmp_path
    submission = root / "submission.json"
    output = root / "result.json"
    plan_output = root / "plan.json"
    submission.write_text(json.dumps(_payload()), encoding="utf-8")

    assert main(["host-plan", "ORCL", "--date", "2026-08-01", "--output", str(plan_output)]) == 0
    assert main(["host-import", "--input", str(submission), "--output", str(output)]) == 0

    plan = json.loads(plan_output.read_text(encoding="utf-8"))
    response = json.loads(output.read_text(encoding="utf-8"))
    assert plan["request"]["executor"] == "host_native"
    assert response["ok"] is True
    assert response["result"]["request"]["executor"] == "host_native"
    assert response["view"]["capability"]["metadata"]["external_credentials_required"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"api_key": "forbidden"}), "credential-shaped"),
        (lambda value: value["analyst_reports"].pop(), "missing analyst reports"),
        (lambda value: value["research_debate"].pop(), "exactly 2 turns"),
        (
            lambda value: value["analyst_reports"][0].update({"evidence_ids": ["missing"]}),
            "unknown evidence",
        ),
        (
            lambda value: value["trader_decision"].update({"executable": True}),
            "executable must be false",
        ),
        (lambda value: value.update({"status": "completed"}), "unsupported fields"),
    ],
)
def test_host_native_rejects_incomplete_or_secret_bearing_submissions(mutation: object, message: str) -> None:
    payload = copy.deepcopy(_payload())
    mutation(payload)  # type: ignore[operator]
    with pytest.raises(ValueError, match=message):
        submit_host_run(payload, store=RunStore())


def test_failed_host_import_does_not_publish_a_partial_run() -> None:
    store = RunStore()
    payload = _payload()
    payload["risk_debate"] = []

    with pytest.raises(ValueError, match="exactly 3 turns"):
        submit_host_run(payload, store=store)

    assert store.current_run_id() is None
    assert store.list_results() == ()
