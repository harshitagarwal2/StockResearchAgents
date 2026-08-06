"""Canonical completed-only, loopback-only Research Dossier Viewer facade."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from .presentation import PresentationLink, ViewerDaemonPresenter
from .store import RUN_STORE, RunStore
from .viewer_server import PublicationCoordinator, create_viewer_server, launch_viewer, viewer_report


def report_summary(
    run_id: str,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
) -> dict[str, object]:
    """Return the presentation-safe summary for a completed research run."""
    return viewer_report(run_id, store, coordinator=coordinator)


def create_report_server(
    host: str = "127.0.0.1",
    port: int = 0,
    web_root: str | Path | None = None,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
) -> ThreadingHTTPServer:
    """Create the loopback-only Research Dossier Viewer server."""
    return create_viewer_server(host, port, web_root, store, coordinator=coordinator)


def launch_report(
    host: str = "127.0.0.1",
    port: int = 0,
    web_root: str | Path | None = None,
    run_id: str | None = None,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
) -> dict[str, object]:
    """Launch the completed-only Research Dossier Viewer on loopback."""
    return launch_viewer(host, port, web_root, run_id, store, coordinator=coordinator)


def present_completed_run(
    run_id: str,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
    mode: str | None = None,
) -> dict[str, object]:
    """Return a generic viewer link after any durable run completes.

    Presentation is best-effort. A viewer startup problem is represented by an
    ``unavailable`` receipt and never changes or rolls back the saved research.
    """
    try:
        summary = viewer_report(run_id, store, coordinator=coordinator)
        if not summary["ok"]:
            return PresentationLink(
                schema="presentation-link.v1",
                run_id=run_id,
                encoded_path=f"/?run={quote(run_id, safe='')}",
                url=None,
                status="unavailable",
                loopback_only=True,
                reused=False,
                error={"code": "completed_run_not_found", "message": f"completed run not found: {run_id}"},
                url_scope="none",
            ).to_dict()
        return ViewerDaemonPresenter(store, mode=mode).present(run_id).to_dict()
    except Exception as exc:  # presentation must never invalidate a completed publication
        return PresentationLink(
            schema="presentation-link.v1",
            run_id=run_id,
            encoded_path=f"/?run={quote(run_id, safe='')}",
            url=None,
            status="unavailable",
            loopback_only=True,
            reused=False,
            error={"code": "presentation_failed", "message": str(exc)},
            url_scope="none",
        ).to_dict()


def ensure_report_viewer(
    run_id: str,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
    mode: str | None = None,
) -> dict[str, object]:
    """Alias emphasizing idempotent viewer reuse."""
    return present_completed_run(run_id, store, coordinator=coordinator, mode=mode)


__all__ = [
    "create_report_server",
    "ensure_report_viewer",
    "launch_report",
    "present_completed_run",
    "report_summary",
]
