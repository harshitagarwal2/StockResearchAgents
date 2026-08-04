from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

from research_v3_fixtures import complete_v3_submission

from tradingagents_portable import mcp_server, presentation
from tradingagents_portable.company_research import submit_company_research
from tradingagents_portable.presentation import ViewerDaemonPresenter
from tradingagents_portable.report_server import present_completed_run
from tradingagents_portable.store import RunStore


def _base_url(url: str) -> str:
    return url.split("/?", 1)[0]


def _view(presentation_url: str, run_id: str) -> dict[str, object]:
    parsed = urlsplit(presentation_url)
    access_token = parse_qs(parsed.fragment)["access_token"][0]
    endpoint = f"{parsed.scheme}://{parsed.netloc}/api/runs/{quote(run_id, safe='')}/view"
    request = Request(endpoint, headers={"X-TradingAgents-Viewer-Token": access_token})
    with urlopen(request, timeout=5) as response:  # noqa: S310 - verified loopback presentation URL
        payload = json.load(response)
    assert isinstance(payload, dict)
    return payload


def test_path_only_presentation_supports_completed_in_memory_runs() -> None:
    store = RunStore()
    result, _events = submit_company_research(complete_v3_submission("QQQ"), store=store)

    receipt = present_completed_run(result.run_id, store, mode="path_only")

    assert receipt == {
        "schema": "presentation-link.v1",
        "schema_version": "presentation-link.v1",
        "run_id": result.run_id,
        "encoded_path": f"/?run={result.run_id}",
        "path": f"/?run={result.run_id}",
        "url": None,
        "status": "path_only",
        "loopback_only": True,
        "reused": False,
        "error": None,
        "url_scope": "none",
        "idle_ttl_seconds": None,
    }


def test_viewer_child_environment_is_credential_free(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross")
    monkeypatch.setenv("CODEX_AUTH_TOKEN", "must-not-cross")

    environment = presentation._child_environment(tmp_path)

    assert environment["STOCKRESEARCHAGENTS_STATE_DIR"] == str(tmp_path)
    assert environment["TRADINGAGENTS_PORTABLE_STATE_DIR"] == str(tmp_path)
    assert environment["PYTHONPATH"].endswith("/src")
    assert "OPENAI_API_KEY" not in environment
    assert "CODEX_AUTH_TOKEN" not in environment
    assert not any("KEY" in name or "TOKEN" in name or "SECRET" in name for name in environment)


def test_one_daemon_renders_companies_published_before_and_after_start(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "state")
    first, _ = submit_company_research(complete_v3_submission("ORCL"), store=store)
    presenter = ViewerDaemonPresenter(store, startup_timeout=8)

    try:
        first_link = presenter.present(first.run_id)
        assert first_link.status == "ready"
        assert first_link.url is not None
        assert first_link.reused is False

        second, _ = submit_company_research(complete_v3_submission("META"), store=store)
        second_link = presenter.present(second.run_id)
        assert second_link.status == "ready"
        assert second_link.url is not None
        assert second_link.reused is True
        assert _base_url(second_link.url) == _base_url(first_link.url)

        first_view = _view(first_link.url, first.run_id)
        second_view = _view(second_link.url, second.run_id)
        assert first_view["view"]["research_dossier"]["identity"]["symbol"] == "ORCL"  # type: ignore[index]
        assert second_view["view"]["research_dossier"]["identity"]["symbol"] == "META"  # type: ignore[index]

        registry = store.state_dir / ".presentation" / "viewer.json"  # type: ignore[operator]
        assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    finally:
        presenter.stop(timeout=5)


def test_concurrent_presenters_converge_on_one_viewer(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "state")
    result, _ = submit_company_research(complete_v3_submission("NVDA"), store=store)
    presenter = ViewerDaemonPresenter(store, startup_timeout=8)

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            links = tuple(executor.map(lambda _index: presenter.present(result.run_id), range(4)))

        assert all(link.status == "ready" and link.url is not None for link in links)
        assert len({_base_url(str(link.url)) for link in links}) == 1
        assert sum(not link.reused for link in links) == 1
    finally:
        presenter.stop(timeout=5)


def test_presentation_failure_does_not_rollback_completed_research(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RunStore(tmp_path / "state")
    result, events = submit_company_research(complete_v3_submission("MSFT"), store=store)

    def fail_spawn(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected viewer startup failure")

    monkeypatch.setattr(presentation, "_spawn_viewer", fail_spawn)
    receipt = present_completed_run(result.run_id, store)

    assert receipt["status"] == "unavailable"
    assert receipt["error"]["code"] == "viewer_start_failed"  # type: ignore[index]
    assert store.get_result(result.run_id) == result
    assert store.get_events(result.run_id) == events


def test_mcp_completed_response_returns_generic_presentation_and_compatibility_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RunStore(tmp_path / "state")
    payload = complete_v3_submission("ADBE")
    monkeypatch.setattr(mcp_server, "RUN_STORE", store)
    monkeypatch.setattr(
        mcp_server,
        "execute_company_research_import",
        lambda submission: submit_company_research(submission, store=store),
    )
    monkeypatch.setenv("STOCKRESEARCHAGENTS_PRESENTATION_MODE", "path_only")

    response = mcp_server.import_company_research(payload)

    assert response["result"]["request"]["symbol"] == "ADBE"
    assert response["presentation"]["status"] == "path_only"
    assert response["dashboard_path"] == response["presentation"]["path"]


def test_short_lived_cli_returns_a_viewer_url_that_outlives_the_command(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    environment = os.environ.copy()
    environment["STOCKRESEARCHAGENTS_STATE_DIR"] = str(state_dir)
    environment["STOCKRESEARCHAGENTS_PRESENTATION_IDLE_TTL_SECONDS"] = "60"

    completed = subprocess.run(  # noqa: S603 - fixed interpreter and package module
        [sys.executable, "-m", "tradingagents_portable.cli", "fixture"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
    )
    payload = json.loads(completed.stdout)
    presenter = ViewerDaemonPresenter(RunStore(state_dir))

    try:
        assert payload["presentation"]["status"] == "ready"
        assert payload["presentation"]["url"]
        with urlopen(payload["presentation"]["url"], timeout=5) as response:  # noqa: S310 - loopback receipt
            assert response.status == 200
            assert "Research Dossier Viewer" in response.read().decode("utf-8")
    finally:
        presenter.stop(timeout=5)
