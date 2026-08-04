from __future__ import annotations

import json
from dataclasses import replace
from threading import Thread
from urllib.request import urlopen

import pytest
from company_analytics_fixtures import complete_v4_submission

from tradingagents_portable import cli, mcp_server
from tradingagents_portable.company_analytics import submit_company_analytics
from tradingagents_portable.dashboard import create_dashboard_server
from tradingagents_portable.export import export_run_bundle
from tradingagents_portable.research_quality_v1 import QualityStore
from tradingagents_portable.semantics import (
    CompletedRunSemanticsV1,
    build_completed_run_semantics,
    semantics_digest,
    verify_semantics_digest,
)
from tradingagents_portable.store import RunStore
from tradingagents_portable.view import build_run_view


def test_completed_v4_semantics_are_identical_across_every_surface(tmp_path, monkeypatch) -> None:
    store = RunStore(tmp_path / "runs")
    result, events = submit_company_analytics(
        complete_v4_submission("META"),
        store=store,
        quality_store=QualityStore(tmp_path / "quality"),
    )
    expected = build_completed_run_semantics(result, events).to_dict()

    monkeypatch.setattr(cli.HOST_RUN_COORDINATOR, "result_store", store)
    cli_output = tmp_path / "cli-semantics.json"
    assert cli.main(["run-semantics", result.run_id, "--output", str(cli_output)]) == 0
    assert json.loads(cli_output.read_text(encoding="utf-8")) == expected

    monkeypatch.setattr(mcp_server, "RUN_STORE", store)
    assert mcp_server.get_run_semantics(result.run_id) == expected

    export_path = tmp_path / "exported-run"
    receipt = export_run_bundle(result, events, export_path)
    exported = json.loads((export_path / "semantics.v1.json").read_text(encoding="utf-8"))
    assert CompletedRunSemanticsV1.from_dict(exported).to_dict() == expected
    assert receipt.semantics_sha256 == expected["digest"]
    manifest = json.loads((export_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["semantics_sha256"] == expected["digest"]

    server = create_dashboard_server(store=store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with urlopen(f"http://{host}:{port}/api/runs/{result.run_id}/semantics", timeout=5) as response:  # noqa: S310
            assert json.load(response) == expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    view_semantics = build_run_view(result, events).to_dict()["semantics"]
    assert view_semantics == expected


def test_semantics_digest_rejects_tampering_and_ignores_transport_only_changes(tmp_path) -> None:
    result, events = submit_company_analytics(
        complete_v4_submission("ORCL"),
        store=RunStore(tmp_path / "runs"),
        quality_store=QualityStore(tmp_path / "quality"),
    )
    original = build_completed_run_semantics(result, events).to_dict()

    tampered = dict(original)
    tampered["processed_signal"] = "SELL" if original["processed_signal"] != "SELL" else "BUY"
    assert semantics_digest(tampered) != original["digest"]
    assert verify_semantics_digest(tampered) is False
    with pytest.raises(ValueError, match="digest mismatch"):
        CompletedRunSemanticsV1.from_dict(tampered)

    aliased_run_id = "transport-alias"
    transported_result = replace(
        result,
        run_id=aliased_run_id,
        started_at="2099-01-01T00:00:00Z",
        completed_at="2099-01-01T00:01:00Z",
    )
    transported_events = tuple(
        replace(
            event,
            id=f"transport-event-{index}",
            run_id=aliased_run_id,
            timestamp="2099-01-01T00:00:00Z",
            message=f"transport wrapper message {index}",
            data={"transport": "changed"},
        )
        for index, event in enumerate(reversed(events), start=1)
    )
    assert build_completed_run_semantics(transported_result, transported_events).to_dict() == original


def test_semantics_content_addresses_detect_terminal_artifact_tampering(tmp_path) -> None:
    result, events = submit_company_analytics(
        complete_v4_submission("META"),
        store=RunStore(tmp_path / "runs"),
        quality_store=QualityStore(tmp_path / "quality"),
    )
    original = build_completed_run_semantics(result, events).to_dict()
    artifact = result.artifacts[0]
    tampered_artifact = replace(artifact, content={"tampered": True})
    tampered_result = replace(result, artifacts=(tampered_artifact, *result.artifacts[1:]))
    tampered = build_completed_run_semantics(tampered_result, events).to_dict()

    assert tampered["digest"] != original["digest"]
    assert tampered["content_addresses"] != original["content_addresses"]
