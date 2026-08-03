from __future__ import annotations

import json
from pathlib import Path

from tradingagents_portable import cli
from tradingagents_portable.lifecycle import HostRunCoordinator, LifecycleStore
from tradingagents_portable.store import RunStore


def _payload(capsys: object) -> dict[str, object]:
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    return json.loads(output)


def test_cli_exposes_durable_control_events_and_cooperative_cancellation(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    coordinator = HostRunCoordinator(LifecycleStore(tmp_path), RunStore(tmp_path))
    monkeypatch.setattr(cli, "HOST_RUN_COORDINATOR", coordinator)  # type: ignore[attr-defined]

    assert (
        cli.main(
            [
                "host-init",
                "MSFT",
                "--date",
                "2026-08-01",
                "--analyst",
                "market",
                "--no-decision-memory",
            ]
        )
        == 0
    )
    created = _payload(capsys)
    control = created["control"]
    run_id = control["run_id"]

    assert cli.main(["host-start", run_id, "--revision", str(control["revision"])]) == 0
    started = _payload(capsys)
    assert started["stage"]["id"] == "analyst.market"

    assert cli.main(["run-events", run_id, "--after", "1", "--limit", "1"]) == 0
    page = _payload(capsys)
    assert len(page["events"]) == 1
    assert page["events"][0]["status"] == "running"

    revision = started["control"]["revision"]
    assert (
        cli.main(
            [
                "run-cancel",
                run_id,
                "--revision",
                str(revision),
                "--reason",
                "Stop the test run.",
            ]
        )
        == 0
    )
    requested = _payload(capsys)
    assert requested["control"]["status"] == "cancel_requested"

    assert (
        cli.main(
            [
                "run-cancel-ack",
                run_id,
                "--revision",
                str(requested["control"]["revision"]),
                "--host-receipt-id",
                "host-stopped-1",
            ]
        )
        == 0
    )
    cancelled = _payload(capsys)
    assert cancelled["control"]["status"] == "cancelled"


def test_interactive_host_init_collects_only_portable_non_secret_settings(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    coordinator = HostRunCoordinator(LifecycleStore(tmp_path), RunStore(tmp_path))
    monkeypatch.setattr(cli, "HOST_RUN_COORDINATOR", coordinator)  # type: ignore[attr-defined]
    answers = iter(["ORCL", "2026-08-01", "stock", "market,news", "2", "2", "English"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))  # type: ignore[attr-defined]

    assert cli.main(["host-init", "--interactive", "--no-decision-memory"]) == 0
    created = _payload(capsys)

    run_id = created["control"]["run_id"]
    first = coordinator.start(run_id, created["control"]["revision"])
    assert first["stage"]["id"] == "analyst.market"
    record = coordinator.lifecycle_store.get(run_id)
    assert record is not None
    assert record["request"]["analysts"] == ["market", "news"]
    assert record["request"]["debate_rounds"] == 2
    assert record["request"]["risk_rounds"] == 2
