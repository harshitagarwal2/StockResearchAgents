from __future__ import annotations

import http.client
import json
import multiprocessing
import os
import signal
from http.cookiejar import CookieJar
from pathlib import Path
from queue import Empty
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest
from research_v3_fixtures import complete_v3_submission

from tradingagents_portable import presentation
from tradingagents_portable.company_research import submit_company_research
from tradingagents_portable.presentation import ViewerDaemonPresenter
from tradingagents_portable.store import RunStore

_SECURITY_HEADERS = {
    "Content-Security-Policy",
    "Cross-Origin-Resource-Policy",
    "Permissions-Policy",
    "Referrer-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
}


def _request(
    base_url: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
) -> tuple[int, dict[str, str], dict[str, object]]:
    parsed = urlsplit(base_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        payload = json.loads(response.read())
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


def _base_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _token(url: str) -> str:
    return parse_qs(urlsplit(url).fragment)["access_token"][0]


def _registry(store: RunStore) -> tuple[Path, dict[str, object]]:
    assert store.state_dir is not None
    path = store.state_dir / ".presentation" / "viewer.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _publish(store: RunStore, symbol: str = "ORCL") -> str:
    result, _ = submit_company_research(complete_v3_submission(symbol), store=store)
    return result.run_id


def _present_from_process(
    state_dir: str,
    run_id: str,
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    start.wait(timeout=10)
    link = ViewerDaemonPresenter(RunStore(Path(state_dir)), startup_timeout=12).present(run_id)
    results.put(link.to_dict())


@pytest.fixture(scope="module")
def detached_viewer(tmp_path_factory: pytest.TempPathFactory):
    store = RunStore(tmp_path_factory.mktemp("detached-viewer") / "state")
    run_id = _publish(store)
    presenter = ViewerDaemonPresenter(store, startup_timeout=8)
    link = presenter.present(run_id)
    assert link.status == "ready"
    assert link.url is not None
    try:
        yield _base_url(link.url), _token(link.url)
    finally:
        presenter.stop(timeout=5)


def test_detached_daemon_rejects_missing_token(detached_viewer) -> None:
    base_url, _ = detached_viewer

    status, _, payload = _request(base_url, "/api/health")

    assert status == 401
    assert payload["error"]["code"] == "viewer_token_required"  # type: ignore[index]


def test_detached_daemon_rejects_bad_token(detached_viewer) -> None:
    base_url, _ = detached_viewer

    status, _, payload = _request(
        base_url,
        "/api/health",
        headers={"X-TradingAgents-Viewer-Token": "not-the-viewer-token"},
    )

    assert status == 401
    assert payload["error"]["code"] == "viewer_token_required"  # type: ignore[index]


def test_detached_daemon_accepts_valid_token(detached_viewer) -> None:
    base_url, token = detached_viewer

    status, _, payload = _request(
        base_url,
        "/api/health",
        headers={"X-TradingAgents-Viewer-Token": token},
    )

    assert status == 200
    assert payload["ok"] is True


def test_detached_daemon_rejects_unauthenticated_shutdown(detached_viewer) -> None:
    base_url, _ = detached_viewer

    status, _, payload = _request(base_url, "/api/shutdown", method="POST")

    assert status == 401
    assert payload["error"]["code"] == "viewer_token_required"  # type: ignore[index]


def test_detached_daemon_rejects_hostile_host_with_security_headers(detached_viewer) -> None:
    base_url, token = detached_viewer

    status, headers, payload = _request(
        base_url,
        "/api/health",
        headers={
            "Host": "attacker.example:443",
            "X-TradingAgents-Viewer-Token": token,
        },
    )

    assert status == 421
    assert payload["error"]["code"] == "invalid_host"  # type: ignore[index]
    assert _SECURITY_HEADERS <= headers.keys()


@pytest.mark.parametrize("origin", ["https://attacker.example", "http://127.0.0.1:1"])
def test_detached_daemon_rejects_untrusted_origin_with_security_headers(detached_viewer, origin: str) -> None:
    base_url, token = detached_viewer

    status, headers, payload = _request(
        base_url,
        "/api/health",
        headers={
            "Origin": origin,
            "X-TradingAgents-Viewer-Token": token,
        },
    )

    assert status == 403
    assert payload["error"]["code"] == "invalid_origin"  # type: ignore[index]
    assert _SECURITY_HEADERS <= headers.keys()


def test_detached_daemon_rejects_non_authority_host_and_origin_suffixes(detached_viewer) -> None:
    base_url, token = detached_viewer
    authority = urlsplit(base_url).netloc
    token_header = {"X-TradingAgents-Viewer-Token": token}

    host_status, _, _ = _request(
        base_url,
        "/api/health",
        headers={"Host": f"{authority}/suffix", **token_header},
    )
    origin_path_status, _, _ = _request(
        base_url,
        "/api/health",
        headers={"Origin": f"{base_url}/suffix", **token_header},
    )
    origin_query_status, _, _ = _request(
        base_url,
        "/api/health",
        headers={"Origin": f"{base_url}?query=x", **token_header},
    )

    assert host_status == 421
    assert origin_path_status == 403
    assert origin_query_status == 403


def test_browser_sessions_for_two_state_directories_do_not_overwrite_each_other(tmp_path: Path) -> None:
    stores = (RunStore(tmp_path / "a"), RunStore(tmp_path / "b"))
    presenters = tuple(ViewerDaemonPresenter(store, startup_timeout=8) for store in stores)
    links = tuple(
        presenter.present(_publish(store, symbol))
        for presenter, store, symbol in zip(
            presenters,
            stores,
            ("ORCL", "META"),
            strict=True,
        )
    )
    assert all(link.status == "ready" and link.url is not None for link in links)
    opener = build_opener(HTTPCookieProcessor(CookieJar()))

    try:
        for link in links:
            assert link.url is not None
            base_url = _base_url(link.url)
            request = Request(
                f"{base_url}/api/session",
                headers={"X-TradingAgents-Viewer-Token": _token(link.url)},
            )
            with opener.open(request, timeout=5) as response:  # noqa: S310 - authenticated loopback URL
                assert response.status == 200
        for link in links:
            assert link.url is not None
            with opener.open(f"{_base_url(link.url)}/api/health", timeout=5) as response:  # noqa: S310
                assert response.status == 200
    finally:
        for presenter in presenters:
            presenter.stop(timeout=5)


def test_multiprocessing_presenters_converge_on_one_base_url(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "state")
    run_id = _publish(store, "NVDA")
    assert store.state_dir is not None
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_present_from_process,
            args=(str(store.state_dir), run_id, start, results),
        )
        for _ in range(4)
    ]
    presenter = ViewerDaemonPresenter(store)

    try:
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(timeout=20)
        assert [process.exitcode for process in processes] == [0, 0, 0, 0]
        try:
            links = [results.get(timeout=2) for _ in processes]
        except Empty:
            pytest.fail("a presenter process exited without returning its presentation receipt")

        assert all(link["status"] == "ready" and link["url"] for link in links)
        assert len({_base_url(str(link["url"])) for link in links}) == 1
        assert sum(link["reused"] is False for link in links) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        presenter.stop(timeout=5)
        results.close()


def test_killed_daemon_is_replaced_with_a_rotated_token(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "state")
    run_id = _publish(store, "META")
    presenter = ViewerDaemonPresenter(store, startup_timeout=8)

    try:
        first = presenter.present(run_id)
        assert first.status == "ready"
        assert first.url is not None
        _, first_registry = _registry(store)
        os.kill(int(first_registry["pid"]), signal.SIGKILL)

        replacement = presenter.present(run_id)

        assert replacement.status == "ready"
        assert replacement.url is not None
        assert _token(replacement.url) != _token(first.url)
        _, replacement_registry = _registry(store)
        assert replacement_registry["pid"] != first_registry["pid"]
    finally:
        presenter.stop(timeout=5)


@pytest.mark.parametrize("identity_field", ["package_version", "viewer_build_digest"])
def test_identity_mismatch_retires_and_restarts_daemon(tmp_path: Path, identity_field: str) -> None:
    store = RunStore(tmp_path / identity_field)
    run_id = _publish(store, "ADBE")
    presenter = ViewerDaemonPresenter(store, startup_timeout=8)

    try:
        first = presenter.present(run_id)
        assert first.status == "ready"
        registry_path, old_registry = _registry(store)
        old_registry[identity_field] = "stale-generation"
        registry_path.write_text(json.dumps(old_registry), encoding="utf-8")

        replacement = presenter.present(run_id)

        assert replacement.status == "ready"
        _, new_registry = _registry(store)
        assert new_registry["pid"] != old_registry["pid"]
        assert new_registry["instance_id"] != old_registry["instance_id"]
        assert new_registry[identity_field] == presentation._viewer_identity()[identity_field]
    finally:
        presenter.stop(timeout=5)


def test_real_child_startup_exit_returns_diagnostic_path(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path / "state")
    run_id = _publish(store, "MSFT")
    child = tmp_path / "exit-child"
    child.write_text("#!/bin/sh\necho deliberate-child-startup-failure\nexit 23\n", encoding="utf-8")
    child.chmod(0o700)
    monkeypatch.setattr(presentation.sys, "executable", str(child))

    link = ViewerDaemonPresenter(store, startup_timeout=3).present(run_id)

    assert link.status == "unavailable"
    assert link.error is not None
    assert link.error["code"] == "viewer_process_exited"
    assert "code 23" in str(link.error["message"])
    diagnostic_path = Path(str(link.error["diagnostic_log"]))
    assert diagnostic_path.read_text(encoding="utf-8").strip() == "deliberate-child-startup-failure"


def test_path_only_does_not_spawn_or_create_presentation_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RunStore(tmp_path / "state")
    run_id = _publish(store, "QQQ")
    assert store.state_dir is not None

    def unexpected_spawn(*_args: object, **_kwargs: object) -> None:
        pytest.fail("path_only attempted to spawn a viewer")

    monkeypatch.setattr(presentation, "_spawn_viewer", unexpected_spawn)

    link = ViewerDaemonPresenter(store, mode="path_only").present(run_id)

    assert link.status == "path_only"
    assert not (store.state_dir / ".presentation").exists()


def test_presenter_stop_uses_authenticated_daemon_shutdown(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path / "state")
    run_id = _publish(store, "ORCL")
    presenter = ViewerDaemonPresenter(store, startup_timeout=8)
    link = presenter.present(run_id)
    assert link.status == "ready"

    def unexpected_signal(*_args: object, **_kwargs: object) -> None:
        pytest.fail("authenticated shutdown unexpectedly fell back to an OS signal")

    monkeypatch.setattr(presentation.os, "kill", unexpected_signal)

    assert presenter.stop(timeout=5) is True


def test_viewer_build_digest_tracks_transitive_store_runtime(monkeypatch) -> None:
    baseline = presentation._viewer_build_digest()
    original_read_bytes = Path.read_bytes

    def read_with_store_change(path: Path) -> bytes:
        content = original_read_bytes(path)
        return content + b"\n# simulated store build change\n" if path.name == "store.py" else content

    monkeypatch.setattr(Path, "read_bytes", read_with_store_change)

    assert presentation._viewer_build_digest() != baseline
