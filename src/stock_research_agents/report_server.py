"""Canonical completed-only, loopback-only Research Dossier Viewer facade."""

from __future__ import annotations

import os
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from .application_ports import CompletedPublicationCoordinator, CompletedResultReader
from .company_lifecycle import require_completed_publication
from .contracts import RunStatus
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
    store: CompletedResultReader = RUN_STORE,
    *,
    coordinator: CompletedPublicationCoordinator | None = None,
    mode: Literal["auto", "path_only"] | None = None,
) -> dict[str, object]:
    """Return a presentation receipt after completed publication.

    Presentation is best-effort. A viewer startup problem is represented by an
    ``unavailable`` receipt and never changes or rolls back the saved research.
    """
    try:
        run_id = require_completed_publication(run_id, store, coordinator)
        result = store.get_result(run_id)
        if result is None or result.status is not RunStatus.COMPLETED:
            return _unavailable_presentation(
                run_id,
                "completed_run_not_found",
                f"completed run not found: {run_id}",
            )

        selected_mode = (
            (mode if mode is not None else os.environ.get("STOCKRESEARCHAGENTS_PRESENTATION_MODE", "auto"))
            .strip()
            .lower()
        )
        if selected_mode == "path_only":
            return _path_only_presentation(run_id)
        if selected_mode != "auto":
            return _unavailable_presentation(
                run_id,
                "invalid_presentation_mode",
                "presentation mode must be auto or path_only",
            )
        if not isinstance(store, RunStore):
            return _unavailable_presentation(
                run_id,
                "automatic_presentation_requires_run_store",
                "automatic viewer presentation requires the bundled RunStore adapter",
            )

        summary = viewer_report(run_id, store, coordinator=coordinator)
        if not summary["ok"]:
            return _unavailable_presentation(
                run_id,
                "completed_run_not_found",
                f"completed run not found: {run_id}",
            )
        return ViewerDaemonPresenter(store, mode=selected_mode).present(run_id).to_dict()
    except Exception as exc:  # presentation must never invalidate a completed publication
        return _unavailable_presentation(run_id, "presentation_failed", str(exc))


def _path_only_presentation(run_id: str) -> dict[str, object]:
    return PresentationLink(
        schema="presentation-link.v1",
        run_id=run_id,
        encoded_path=f"/?run={quote(run_id, safe='')}",
        url=None,
        status="path_only",
        loopback_only=True,
        reused=False,
        url_scope="none",
    ).to_dict()


def _unavailable_presentation(run_id: str, code: str, message: str) -> dict[str, object]:
    return PresentationLink(
        schema="presentation-link.v1",
        run_id=run_id,
        encoded_path=f"/?run={quote(run_id, safe='')}",
        url=None,
        status="unavailable",
        loopback_only=True,
        reused=False,
        error={"code": code, "message": message},
        url_scope="none",
    ).to_dict()


def ensure_report_viewer(
    run_id: str,
    store: RunStore = RUN_STORE,
    *,
    coordinator: PublicationCoordinator | None = None,
    mode: Literal["auto", "path_only"] | None = None,
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
