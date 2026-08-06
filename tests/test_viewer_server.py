from __future__ import annotations

import json
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents import viewer_server
from stock_research_agents.company_analytics import build_company_analytics_draft, submit_company_analytics
from stock_research_agents.research_quality_v1 import QualityStore
from stock_research_agents.store import RunStore
from stock_research_agents.viewer_server import create_viewer_server, launch_viewer, viewer_report

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "src" / "stock_research_agents" / "web"


def _publish(store: RunStore, symbol: str = "ORCL"):
    return submit_company_analytics(
        complete_analytics_submission(symbol),
        store=store,
        quality_store=QualityStore(),
    )


class PublicationCoordinatorStub:
    def __init__(self, controls: dict[str, dict[str, object]]) -> None:
        self.controls = controls

    def control(self, run_id: str) -> dict[str, object]:
        try:
            return self.controls[run_id]
        except KeyError as exc:
            raise KeyError(f"unknown lifecycle run: {run_id}") from exc


class StrictLifecycleCoordinatorStub(PublicationCoordinatorStub):
    def __init__(self, controls: dict[str, dict[str, object]]) -> None:
        super().__init__(controls)
        self.calls: list[str] = []

    def control(self, run_id: str) -> dict[str, object]:
        self.calls.append(run_id)
        if not run_id.startswith("analytics-"):
            raise ValueError("lifecycle run IDs must use the analytics namespace")
        return super().control(run_id)


class DashboardMarkup(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.aria_controls: set[str] = set()
        self.demo_actions: set[str] = set()
        self.external_assets: list[str] = []
        self.local_assets: list[str] = []
        self.inline_handlers: list[str] = []
        self.tables = 0
        self.captions = 0
        self.status_regions = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if values.get("aria-controls"):
            self.aria_controls.add(str(values["aria-controls"]))
        if values.get("data-demo-action"):
            self.demo_actions.add(str(values["data-demo-action"]))
        if tag in {"script", "link"}:
            source = values.get("src") or values.get("href")
            if source and str(source).startswith(("http://", "https://", "//")):
                self.external_assets.append(str(source))
            elif source:
                self.local_assets.append(str(source))
        self.inline_handlers.extend(name for name, _ in attrs if name.lower().startswith("on"))
        if tag == "table":
            self.tables += 1
        elif tag == "caption":
            self.captions += 1
        if values.get("role") == "status" or values.get("aria-live"):
            self.status_regions += 1


def test_viewer_markup_contains_complete_final_report_information() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    parser = DashboardMarkup()
    parser.feed(html)

    required_information_ids = {
        "executive-summary",
        "recommendation",
        "overview-metadata",
        "request-metadata",
        "request-objectives",
        "request-coverage",
        "documents",
        "claims",
        "source-lineage",
        "metrics",
        "calculations",
        "valuations",
        "analytics-bundle",
        "risk-register",
        "counterevidence",
        "limitations",
        "monitoring-rules",
        "research-delta",
        "hypotheses",
        "iterations",
        "quality",
        "forecasts",
        "run-card-meta",
        "run-card-stages",
        "reports",
        "artifacts",
        "events",
        "actions",
    }
    assert required_information_ids <= parser.ids
    assert parser.aria_controls <= parser.ids
    assert parser.demo_actions == set()


def test_viewer_markup_has_basic_accessibility_and_static_safety() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    parser = DashboardMarkup()
    parser.feed(html)

    assert parser.external_assets == []
    assert parser.local_assets
    assert all((WEB_ROOT / asset.removeprefix("./")).is_file() for asset in parser.local_assets)
    assert parser.inline_handlers == []
    assert parser.tables == parser.captions
    assert parser.status_regions >= 1
    assert "NON-EXECUTABLE" in html
    assert "read-only and non-executable" in html.lower()
    assert "no inputs · no recalculation · no authority" in html.lower()
    assert 'id="run-card-stages"' in html

    javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript
    assert "document.cookie" not in javascript
    assert "eval(" not in javascript
    assert "new Function" not in javascript
    assert "https://" not in javascript
    assert "http://" not in javascript


def test_launched_viewer_pins_the_requested_run_and_uses_the_supplied_store() -> None:
    store = RunStore()
    first, _ = _publish(store, "ORCL")
    second, _ = _publish(store, "META")
    launched = launch_viewer("127.0.0.1", 0, WEB_ROOT, run_id=first.run_id, store=store)
    server = viewer_server._SERVERS.pop()
    base = str(launched["url"]).split("?", 1)[0].rstrip("/")
    try:
        assert launched["url"] == f"{base}/?run={first.run_id}"
        with urlopen(f"{base}/api/runs/{first.run_id}/view", timeout=5) as response:  # noqa: S310
            first_view = json.load(response)
        with urlopen(f"{base}/api/runs/current/view", timeout=5) as response:  # noqa: S310
            current_view = json.load(response)

        assert first_view["view"]["run_id"] == first.run_id
        assert current_view["view"]["run_id"] == second.run_id
    finally:
        server.shutdown()
        server.server_close()


def test_launched_viewer_supports_ipv6_loopback_when_available() -> None:
    store = RunStore()
    result, _ = _publish(store)
    try:
        launched = launch_viewer("::1", 0, WEB_ROOT, run_id=result.run_id, store=store)
    except OSError as exc:
        pytest.skip(f"IPv6 loopback is unavailable: {exc}")
    server = viewer_server._SERVERS.pop()
    try:
        assert launched["host"] == "::1"
        assert str(launched["url"]).startswith("http://[::1]:")
        assert str(launched["url"]).endswith(f"/?run={result.run_id}")
    finally:
        server.shutdown()
        server.server_close()


def test_loopback_viewer_serves_html_json_result_and_events() -> None:
    store = RunStore()
    result, events = _publish(store)
    server = create_viewer_server("127.0.0.1", 0, WEB_ROOT, store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/", timeout=5) as response:  # noqa: S310 - verified loopback server
            html = response.read().decode("utf-8")
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "StockResearchAgents" in html

        with urlopen(f"{base}/api/runs/{result.run_id}", timeout=5) as response:  # noqa: S310
            report = json.load(response)
            assert report["ok"] is True
            assert report["run_id"] == result.run_id
            assert report["stage_count"] == len(result.submission.run_card.stages)

        with urlopen(f"{base}/api/runs/{result.run_id}/result", timeout=5) as response:  # noqa: S310
            payload = json.load(response)
            assert payload["ok"] is True
            assert payload["result"]["run_id"] == result.run_id
            assert payload["result"]["non_executable"] is True
            assert payload["result"]["schema_version"] == "company-analytics-result.v1"

        with urlopen(f"{base}/api/runs/{result.run_id}/events", timeout=5) as response:  # noqa: S310
            payload = json.load(response)
            assert payload["ok"] is True
            assert len(payload["events"]) == len(events)
            assert [event["sequence"] for event in payload["events"]] == list(range(1, len(events) + 1))

        with urlopen(f"{base}/api/runs/{result.run_id}/events?after=2&limit=1", timeout=5) as response:  # noqa: S310
            page = json.load(response)
            assert page["after_sequence"] == 2
            assert page["last_sequence"] == 3
            assert [event["sequence"] for event in page["events"]] == [3]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_viewer_current_alias_resolves_the_run_requested_by_the_frontend() -> None:
    store = RunStore()
    result, events = _publish(store)
    server = create_viewer_server("127.0.0.1", 0, WEB_ROOT, store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/api/runs/current", timeout=5) as response:  # noqa: S310
            payload = json.load(response)
            assert payload["ok"] is True
            assert payload["run_id"] == result.run_id
        with urlopen(f"{base}/api/runs/current/events", timeout=5) as response:  # noqa: S310
            payload = json.load(response)
            assert payload["ok"] is True
            assert len(payload["events"]) == len(events)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_viewer_hides_noncompleted_results_from_all_public_routes_and_aliases() -> None:
    store = RunStore()
    draft = build_company_analytics_draft(complete_analytics_submission("ORCL"))
    result = draft.result
    store.put_events(result.run_id, draft.events[:-1])
    server = create_viewer_server("127.0.0.1", 0, WEB_ROOT, store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/api/runs", timeout=5) as response:  # noqa: S310
            assert json.load(response)["runs"] == []
        for requested_run_id in (result.run_id, "current"):
            for suffix in ("", "/result", "/semantics", "/view", "/events"):
                with pytest.raises(HTTPError) as exc_info:
                    urlopen(f"{base}/api/runs/{requested_run_id}{suffix}", timeout=5)  # noqa: S310
                try:
                    assert exc_info.value.code == 404
                    if suffix == "/view":
                        payload = json.load(exc_info.value)
                        assert payload["error"]["code"] == "run_not_found"
                        assert "view" not in payload
                        assert "result" not in payload
                finally:
                    exc_info.value.close()
        with pytest.raises(ValueError, match="completed run not found"):
            launch_viewer("127.0.0.1", 0, WEB_ROOT, run_id="current", store=store)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_viewer_keeps_runs_without_lifecycle_records_visible() -> None:
    store = RunStore()
    result, _events = _publish(store)
    coordinator = PublicationCoordinatorStub({})

    report = viewer_report(result.run_id, store, coordinator=coordinator)

    assert report["ok"] is True
    assert report["run_id"] == result.run_id


def test_viewer_fails_closed_for_malformed_lifecycle_publication_origin() -> None:
    store = RunStore()
    draft = build_company_analytics_draft(complete_analytics_submission("ORCL"))
    malformed_final = replace(
        draft.events[-1],
        data={
            **draft.events[-1].data,
            "publication_origin": {"kind": "durable_lifecycle", "lifecycle_run_id": "not-a-lifecycle-id"},
        },
    )
    store.put(draft.result, (*draft.events[:-1], malformed_final))

    assert viewer_report(draft.result.run_id, store, coordinator=PublicationCoordinatorStub({}))["ok"] is False


def test_viewer_does_not_infer_lifecycle_origin_from_a_direct_import_run_id() -> None:
    store = RunStore()
    result, _events = _publish(store)
    coordinator = StrictLifecycleCoordinatorStub({})
    server = create_viewer_server("127.0.0.1", 0, WEB_ROOT, store, coordinator=coordinator)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        with urlopen(f"http://{host}:{port}/api/runs/current/view", timeout=5) as response:  # noqa: S310
            payload = json.load(response)
        assert payload["ok"] is True
        assert payload["view"]["run_id"] == result.run_id
        assert payload["view"]["research_dossier"]["identity"]["symbol"] == "ORCL"
        assert coordinator.calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("host", ["0.0.0.0", "8.8.8.8", "localhost"])
def test_viewer_rejects_non_explicit_loopback_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        create_viewer_server(host, 0, WEB_ROOT, RunStore())


def test_viewer_rejects_path_traversal() -> None:
    server = create_viewer_server("127.0.0.1", 0, WEB_ROOT, RunStore())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        with pytest.raises(HTTPError) as captured:
            urlopen(f"http://{host}:{port}/%2e%2e/pyproject.toml", timeout=5)  # noqa: S310
        try:
            assert captured.value.code == 403
        finally:
            captured.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
