"""Loopback-only Research Dossier Viewer implementation."""

from __future__ import annotations

import hmac
import json
import mimetypes
import re
import socket
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from threading import Thread
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, quote, unquote, urlparse, urlsplit

from .bootstrap import DEFAULT_RUNTIME
from .company_analytics import quality_projection_for_result
from .company_analytics_v1 import CompanyAnalyticsResultV1
from .company_lifecycle import require_completed_publication
from .contracts import PROTOTYPE_NOTICE
from .research_quality_v1.store import QualityStore
from .semantics import build_completed_run_semantics
from .store import RunStore
from .view import build_run_view

RUN_STORE: RunStore = cast(RunStore, DEFAULT_RUNTIME.result_store)
COMPANY_ANALYTICS_COORDINATOR = DEFAULT_RUNTIME.coordinator

_SERVERS: list[ThreadingHTTPServer] = []
_VIEWER_COOKIE = "stockresearchagents_viewer"


class _ThreadingHTTPServerV6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def _http_authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ip_address(host).version == 6 else f"{host}:{port}"


class PublicationCoordinator(Protocol):
    def control(self, run_id: str) -> dict[str, Any]: ...


class _DefaultPublicationCoordinator:
    def control(self, run_id: str) -> dict[str, Any]:
        return COMPANY_ANALYTICS_COORDINATOR.control(run_id)


_DEFAULT_PUBLICATION_COORDINATOR = _DefaultPublicationCoordinator()


def _default_web_root() -> Path:
    return Path(__file__).resolve().parent / "web"


def _publication_coordinator(
    store: RunStore,
    coordinator: PublicationCoordinator | None,
) -> PublicationCoordinator | None:
    if coordinator is not None:
        return coordinator
    return _DEFAULT_PUBLICATION_COORDINATOR if store is RUN_STORE else None


def _resolve_completed_run_id(
    requested_run_id: str,
    store: RunStore,
    coordinator: PublicationCoordinator | None,
) -> str | None:
    """Resolve a viewer alias only when its canonical completed result is public."""
    try:
        run_id = require_completed_publication(requested_run_id, store, coordinator)
    except ValueError:
        return None
    if run_id is None or store.resolve_run_id(run_id) is None:
        return None
    result = store.get_result(run_id)
    if result is None or result.status.value != "completed":
        return None
    return run_id


def viewer_report(
    run_id: str,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
) -> dict[str, object]:
    publication_coordinator = _publication_coordinator(store, coordinator)
    resolved_run_id = _resolve_completed_run_id(run_id, store, publication_coordinator)
    result = store.get_result(resolved_run_id) if resolved_run_id else None
    if not isinstance(result, CompanyAnalyticsResultV1):
        return {"ok": False, "error": {"code": "run_not_found", "run_id": run_id}}
    dossier = result.submission.company_research.dossier
    return {
        "ok": True,
        "run_id": result.run_id,
        "symbol": dossier.identity.symbol,
        "status": result.status.value,
        "profile": result.profile,
        "executor_runtime": result.submission.run_card.executor_runtime,
        "stage_count": len(result.submission.run_card.stages),
        "document_count": len(dossier.documents),
        "claim_count": len(dossier.claims),
        "recommendation": dossier.recommendation,
        "non_executable": result.non_executable,
        "warnings": list(result.warnings),
        "prototype_notice": result.prototype_notice,
    }


def _handler(
    store: RunStore,
    web_root: Path,
    coordinator: PublicationCoordinator | None,
    *,
    health_metadata: Mapping[str, object] | None = None,
    request_observer: Callable[[], None] | None = None,
    shutdown_callback: Callable[[], None] | None = None,
    access_token: str | None = None,
    session_cookie_name: str = _VIEWER_COOKIE,
) -> type[BaseHTTPRequestHandler]:
    durable_state_dir = store.state_dir

    def request_store() -> RunStore:
        # A detached viewer can outlive the process that published the first
        # run. Durable stores therefore get a fresh snapshot per request;
        # in-memory/custom stores retain their existing object semantics.
        return RunStore(durable_state_dir) if durable_state_dir is not None else store

    def request_quality_projection(result: Any) -> Mapping[str, object] | None:
        # Outcome observations may be appended by another publisher after this
        # detached viewer starts, so durable quality state is reloaded per view.
        if durable_state_dir is None:
            return quality_projection_for_result(result)
        return quality_projection_for_result(
            result,
            quality_store=QualityStore(durable_state_dir / "quality"),
        )

    class ViewerHandler(BaseHTTPRequestHandler):
        server_version = "StockResearchAgents/0.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_security_headers(self) -> None:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'none'; connect-src 'self'; frame-ancestors 'none'; "
                "form-action 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'",
            )
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), geolocation=(), microphone=(), payment=()")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")

        def _bound_endpoint(self) -> tuple[str, int]:
            server_address = cast(tuple[str | int, ...], self.server.server_address)
            return str(server_address[0]), int(server_address[1])

        def _bound_authority(self) -> str:
            return _http_authority(*self._bound_endpoint())

        def _authority_is_this_loopback(self, authority: str) -> bool:
            bound_host, bound_port = self._bound_endpoint()
            if authority != _http_authority(bound_host, bound_port):
                return False
            try:
                parsed = urlsplit(f"//{authority}")
                host = parsed.hostname
                port = parsed.port
                address = ip_address(host) if host is not None else None
            except ValueError:
                return False
            if address is None or not address.is_loopback or parsed.username is not None or parsed.password is not None:
                return False
            bound_address = ip_address(bound_host)
            if address != bound_address:
                return False
            return port == bound_port and parsed.path == "" and parsed.query == "" and parsed.fragment == ""

        def _request_headers_are_safe(self) -> tuple[bool, str]:
            host = self.headers.get("Host")
            if host is None or not self._authority_is_this_loopback(host):
                return False, "invalid_host"
            origin = self.headers.get("Origin")
            if origin is None:
                return True, ""
            parsed = urlsplit(origin)
            if (
                origin != f"http://{self._bound_authority()}"
                or parsed.scheme != "http"
                or parsed.path != ""
                or parsed.query != ""
                or parsed.fragment != ""
                or not self._authority_is_this_loopback(parsed.netloc)
            ):
                return False, "invalid_origin"
            return True, ""

        def _api_token_is_valid(self) -> bool:
            if access_token is None:
                return True
            supplied = self.headers.get("X-StockResearchAgents-Viewer-Token", "")
            if hmac.compare_digest(supplied, access_token):
                return True
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except CookieError:
                return False
            morsel = cookie.get(session_cookie_name)
            return morsel is not None and hmac.compare_digest(morsel.value, access_token)

        def _json(
            self,
            payload: object,
            status: HTTPStatus = HTTPStatus.OK,
            *,
            extra_headers: Mapping[str, str] | None = None,
        ) -> None:
            data = json.dumps(payload, default=str, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_security_headers()
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_file(self, request_path: str) -> None:
            relative = "index.html" if request_path in ("", "/") else unquote(request_path.lstrip("/"))
            candidate = (web_root / relative).resolve()
            try:
                candidate.relative_to(web_root.resolve())
            except ValueError:
                self._json({"ok": False, "error": {"code": "forbidden_path"}}, HTTPStatus.FORBIDDEN)
                return
            if not candidate.is_file() and "." not in Path(relative).name:
                candidate = web_root / "index.html"
            if not candidate.is_file():
                self._json(
                    {"ok": False, "error": {"code": "viewer_assets_missing", "web_root": str(web_root)}},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorize_request(self, path: str) -> bool:
            safe_headers, header_error = self._request_headers_are_safe()
            if not safe_headers:
                self._json(
                    {"ok": False, "error": {"code": header_error}},
                    HTTPStatus.MISDIRECTED_REQUEST if header_error == "invalid_host" else HTTPStatus.FORBIDDEN,
                )
                return False
            if path.startswith("/api/") and not self._api_token_is_valid():
                self._json({"ok": False, "error": {"code": "viewer_token_required"}}, HTTPStatus.UNAUTHORIZED)
                return False
            if request_observer is not None:
                request_observer()
            return True

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            parsed_url = urlparse(self.path)
            path = parsed_url.path
            if not self._authorize_request(path):
                return
            active_store = request_store()
            if path == "/api/health":
                self._json(
                    {
                        "ok": True,
                        "loopback_only": True,
                        "prototype_notice": PROTOTYPE_NOTICE,
                        **dict(health_metadata or {}),
                    }
                )
                return
            if path == "/api/session":
                session_headers = (
                    {"Set-Cookie": (f"{session_cookie_name}={access_token}; HttpOnly; Path=/api; SameSite=Strict")}
                    if access_token is not None
                    else None
                )
                self._json({"ok": True}, extra_headers=session_headers)
                return
            if path == "/api/runs":
                reports = [
                    viewer_report(item.run_id, active_store, coordinator=coordinator)
                    for item in active_store.list_results()
                ]
                self._json({"runs": [report for report in reports if report["ok"]]})
                return
            if path.startswith("/api/runs/"):
                parts = path.strip("/").split("/")
                requested_run_id = parts[2] if len(parts) >= 3 else ""
                run_id = _resolve_completed_run_id(requested_run_id, active_store, coordinator)
                if len(parts) == 3:
                    report = viewer_report(requested_run_id, active_store, coordinator=coordinator)
                    self._json(
                        report,
                        HTTPStatus.OK if report["ok"] else HTTPStatus.NOT_FOUND,
                    )
                    return
                if len(parts) == 4 and parts[3] == "events":
                    query = parse_qs(parsed_url.query)
                    try:
                        after_sequence = int(query.get("after", ["0"])[0])
                        limit = int(query.get("limit", ["1000"])[0])
                        events = (
                            active_store.get_events_after(run_id, after_sequence=after_sequence, limit=limit)
                            if run_id
                            else None
                        )
                    except ValueError as exc:
                        self._json(
                            {"ok": False, "error": {"code": "invalid_event_cursor", "message": str(exc)}},
                            HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._json(
                        {
                            "ok": events is not None,
                            "run_id": run_id or requested_run_id,
                            "after_sequence": after_sequence,
                            "last_sequence": events[-1].sequence if events else after_sequence,
                            "events": [event.to_dict() for event in events or ()],
                        },
                        HTTPStatus.OK if events is not None else HTTPStatus.NOT_FOUND,
                    )
                    return
                if len(parts) == 4 and parts[3] == "result":
                    result = active_store.get_result(run_id) if run_id else None
                    self._json(
                        {"ok": result is not None, "result": result.to_dict() if result else None},
                        HTTPStatus.OK if result is not None else HTTPStatus.NOT_FOUND,
                    )
                    return
                if len(parts) == 4 and parts[3] in {"semantics", "view"}:
                    result = active_store.get_result(run_id) if run_id else None
                    events = active_store.get_events(run_id) if run_id else None
                    if not isinstance(result, CompanyAnalyticsResultV1) or events is None:
                        if parts[3] == "semantics":
                            payload = {
                                "ok": False,
                                "error": {"code": "run_not_found", "run_id": requested_run_id},
                            }
                        else:
                            payload = {"ok": False, "view": None}
                        status = HTTPStatus.NOT_FOUND
                    elif parts[3] == "semantics":
                        payload = build_completed_run_semantics(result, events).to_dict()
                        status = HTTPStatus.OK
                    else:
                        payload = {
                            "ok": True,
                            "view": build_run_view(
                                result,
                                events,
                                quality_projection=request_quality_projection(result),
                            ).to_dict(),
                        }
                        status = HTTPStatus.OK
                    self._json(payload, status)
                    return
            if path.startswith("/api/"):
                self._json({"ok": False, "error": {"code": "not_found"}}, HTTPStatus.NOT_FOUND)
                return
            self._serve_file(path)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            path = urlparse(self.path).path
            if not self._authorize_request(path):
                return
            if path == "/api/shutdown" and shutdown_callback is not None:
                self._json({"ok": True, "shutdown_requested": True})
                shutdown_callback()
                return
            self._json({"ok": False, "error": {"code": "not_found"}}, HTTPStatus.NOT_FOUND)

    return ViewerHandler


def create_viewer_server(
    host: str = "127.0.0.1",
    port: int = 0,
    web_root: str | Path | None = None,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
    health_metadata: Mapping[str, object] | None = None,
    request_observer: Callable[[], None] | None = None,
    shutdown_callback: Callable[[], None] | None = None,
    access_token: str | None = None,
    session_cookie_name: str = _VIEWER_COOKIE,
) -> ThreadingHTTPServer:
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ValueError("viewer host must be an explicit loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("viewer may bind only to a loopback address")
    if re.fullmatch(r"[A-Za-z0-9_]{1,64}", session_cookie_name) is None:
        raise ValueError("viewer session cookie name must contain only letters, digits, or underscores")
    root = Path(web_root).resolve() if web_root else _default_web_root()
    publication_coordinator = _publication_coordinator(store, coordinator)
    server_type = _ThreadingHTTPServerV6 if address.version == 6 else ThreadingHTTPServer
    return server_type(
        (host, port),
        _handler(
            store,
            root,
            publication_coordinator,
            health_metadata=health_metadata,
            request_observer=request_observer,
            shutdown_callback=shutdown_callback,
            access_token=access_token,
            session_cookie_name=session_cookie_name,
        ),
    )


def launch_viewer(
    host: str = "127.0.0.1",
    port: int = 0,
    web_root: str | Path | None = None,
    run_id: str | None = None,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
) -> dict[str, object]:
    publication_coordinator = _publication_coordinator(store, coordinator)
    if run_id is not None and _resolve_completed_run_id(run_id, store, publication_coordinator) is None:
        raise ValueError(f"completed run not found: {run_id}")
    server = create_viewer_server(host, port, web_root, store, coordinator=publication_coordinator)
    thread = Thread(target=server.serve_forever, name="stockresearchagents-viewer", daemon=True)
    thread.start()
    _SERVERS.append(server)
    bound_host = str(server.server_address[0])
    bound_port = int(server.server_address[1])
    return {
        "ok": True,
        "url": f"http://{_http_authority(bound_host, bound_port)}/"
        + (f"?run={quote(run_id, safe='')}" if run_id else ""),
        "run_id": run_id,
        "host": bound_host,
        "port": bound_port,
        "loopback_only": True,
        "web_root": str(Path(web_root).resolve() if web_root else _default_web_root()),
        "prototype_notice": PROTOTYPE_NOTICE,
    }
