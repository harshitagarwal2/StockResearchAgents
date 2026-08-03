"""Loopback-only dashboard server for the Designer-owned static frontend."""

from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from threading import Thread
from urllib.parse import quote, unquote, urlparse

from .contracts import PROTOTYPE_NOTICE
from .store import RUN_STORE, RunStore
from .view import build_run_view

_SERVERS: list[ThreadingHTTPServer] = []


def _default_web_root() -> Path:
    return Path(__file__).resolve().parent / "web"


def dashboard_report(run_id: str, store: RunStore = RUN_STORE) -> dict[str, object]:
    resolved_run_id = store.resolve_run_id(run_id)
    result = store.get_result(resolved_run_id) if resolved_run_id else None
    if result is None:
        return {"ok": False, "error": {"code": "run_not_found", "run_id": run_id}}
    return {
        "ok": True,
        "run_id": result.run_id,
        "symbol": result.request.symbol,
        "status": result.status.value,
        "executor": result.request.executor,
        "stage_count": len(result.topology.stages),
        "evidence_count": len(result.evidence),
        "research_decision": result.research_decision.to_dict(),
        "trader_decision": result.trader_decision.to_dict(),
        "risk_decision": result.risk_decision.to_dict(),
        "portfolio_decision": result.portfolio_decision.to_dict(),
        "warnings": result.warnings,
        "prototype_notice": result.prototype_notice,
    }


def _handler(store: RunStore, web_root: Path) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "TradingAgentsPortable/0.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, default=str, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_file(self, request_path: str) -> None:
            relative = "index.html" if request_path in ("", "/") else unquote(request_path.lstrip("/"))
            candidate = (web_root / relative).resolve()
            try:
                candidate.relative_to(web_root.resolve())
            except ValueError:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not candidate.is_file() and "." not in Path(relative).name:
                candidate = web_root / "index.html"
            if not candidate.is_file():
                self._json(
                    {"ok": False, "error": {"code": "dashboard_assets_missing", "web_root": str(web_root)}},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            path = urlparse(self.path).path
            if path == "/api/health":
                self._json({"ok": True, "loopback_only": True, "prototype_notice": PROTOTYPE_NOTICE})
                return
            if path == "/api/runs":
                self._json({"runs": [dashboard_report(item.run_id, store) for item in store.list_results()]})
                return
            if path.startswith("/api/runs/"):
                parts = path.strip("/").split("/")
                requested_run_id = parts[2] if len(parts) >= 3 else ""
                run_id = store.resolve_run_id(requested_run_id)
                if len(parts) == 3:
                    self._json(
                        dashboard_report(requested_run_id, store),
                        HTTPStatus.OK if run_id else HTTPStatus.NOT_FOUND,
                    )
                    return
                if len(parts) == 4 and parts[3] == "events":
                    events = store.get_events(run_id) if run_id else None
                    self._json(
                        {
                            "ok": events is not None,
                            "run_id": run_id or requested_run_id,
                            "events": [event.to_dict() for event in events or ()],
                        },
                        HTTPStatus.OK if events is not None else HTTPStatus.NOT_FOUND,
                    )
                    return
                if len(parts) == 4 and parts[3] == "result":
                    result = store.get_result(run_id) if run_id else None
                    self._json(
                        {"ok": result is not None, "result": result.to_dict() if result else None},
                        HTTPStatus.OK if result is not None else HTTPStatus.NOT_FOUND,
                    )
                    return
                if len(parts) == 4 and parts[3] == "view":
                    result = store.get_result(run_id) if run_id else None
                    events = store.get_events(run_id) if run_id else None
                    self._json(
                        {
                            "ok": result is not None and events is not None,
                            "view": build_run_view(result, events).to_dict()
                            if result is not None and events is not None
                            else None,
                        },
                        HTTPStatus.OK if result is not None and events is not None else HTTPStatus.NOT_FOUND,
                    )
                    return
            if path.startswith("/api/"):
                self._json({"ok": False, "error": {"code": "not_found"}}, HTTPStatus.NOT_FOUND)
                return
            self._serve_file(path)

    return DashboardHandler


def create_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 0,
    web_root: str | Path | None = None,
    store: RunStore = RUN_STORE,
) -> ThreadingHTTPServer:
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ValueError("dashboard host must be an explicit loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("dashboard may bind only to a loopback address")
    root = Path(web_root).resolve() if web_root else _default_web_root()
    return ThreadingHTTPServer((host, port), _handler(store, root))


def launch_dashboard(
    host: str = "127.0.0.1",
    port: int = 0,
    web_root: str | Path | None = None,
    run_id: str | None = None,
    store: RunStore = RUN_STORE,
) -> dict[str, object]:
    if run_id is not None and store.get_result(run_id) is None:
        raise ValueError(f"completed run not found: {run_id}")
    server = create_dashboard_server(host, port, web_root, store)
    thread = Thread(target=server.serve_forever, name="tradingagents-dashboard", daemon=True)
    thread.start()
    _SERVERS.append(server)
    bound_host = str(server.server_address[0])
    bound_port = int(server.server_address[1])
    return {
        "ok": True,
        "url": f"http://{bound_host}:{bound_port}/" + (f"?run={quote(run_id, safe='')}" if run_id else ""),
        "run_id": run_id,
        "host": bound_host,
        "port": bound_port,
        "loopback_only": True,
        "web_root": str(Path(web_root).resolve() if web_root else _default_web_root()),
        "prototype_notice": PROTOTYPE_NOTICE,
    }
