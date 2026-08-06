"""Detached loopback Research Dossier Viewer process."""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import threading
import time
from pathlib import Path
from typing import Any

from .bootstrap import create_company_analytics_coordinator
from .lifecycle import LifecycleStore
from .memory import ResearchHistoryRepository
from .presentation import (
    _VIEWER_REGISTRY_SCHEMA,
    _atomic_write_registry,
    _read_registry,
    _registry_lock,
    _viewer_identity,
    _viewer_lease,
)
from .research_quality_v1 import QualityStore
from .store import RunStore
from .viewer_server import create_viewer_server


class _DurablePublicationCoordinator:
    """Read lifecycle visibility from disk without retaining stale run state."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    def control(self, run_id: str) -> dict[str, Any]:
        lifecycle_store = LifecycleStore(self.state_dir)
        result_store = RunStore(self.state_dir)

        def memory_store_factory() -> ResearchHistoryRepository:
            return ResearchHistoryRepository(self.state_dir / "decision-memory.sqlite3")

        analytics = create_company_analytics_coordinator(
            lifecycle_store=lifecycle_store,
            result_store=result_store,
            quality_store=QualityStore(self.state_dir / "quality"),
            memory_store_factory=memory_store_factory,
        )
        try:
            return analytics.control(run_id)
        finally:
            if analytics.memory_store is not None:
                analytics.memory_store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a detached completed-research viewer")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--state-fingerprint", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--idle-ttl", required=True, type=float)
    return parser


def _owned_registry(registry_path: Path, instance_id: str) -> bool:
    registry = _read_registry(registry_path)
    return registry is not None and registry.get("instance_id") == instance_id


def _cleanup_owned_registry(state_dir: Path, registry_path: Path, instance_id: str) -> None:
    try:
        with _registry_lock(state_dir) as locked_registry_path:
            if locked_registry_path == registry_path and _owned_registry(registry_path, instance_id):
                registry_path.unlink(missing_ok=True)
    except OSError:
        return


def _serve(args: argparse.Namespace, state_dir: Path, registry_path: Path) -> int:
    stop_event = threading.Event()
    activity_lock = threading.Lock()
    last_activity = time.monotonic()
    access_token = secrets.token_urlsafe(32)
    identity = _viewer_identity()

    def observe_request() -> None:
        nonlocal last_activity
        with activity_lock:
            last_activity = time.monotonic()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    server = create_viewer_server(
        "127.0.0.1",
        0,
        store=RunStore(state_dir),
        coordinator=_DurablePublicationCoordinator(state_dir),
        health_metadata={
            "viewer_daemon": True,
            "instance_id": args.instance_id,
            "state_fingerprint": args.state_fingerprint,
            **identity,
        },
        request_observer=observe_request,
        shutdown_callback=stop_event.set,
        access_token=access_token,
        session_cookie_name=f"stockresearchagents_viewer_{args.state_fingerprint[:16]}",
    )
    host, port = server.server_address[:2]
    try:
        _atomic_write_registry(
            registry_path,
            {
                "schema": _VIEWER_REGISTRY_SCHEMA,
                "instance_id": args.instance_id,
                "state_fingerprint": args.state_fingerprint,
                "pid": os.getpid(),
                "host": str(host),
                "port": int(port),
                "idle_ttl_seconds": args.idle_ttl,
                "access_token": access_token,
                **identity,
            },
        )
        server_thread = threading.Thread(target=server.serve_forever, name="research-viewer", daemon=True)
        server_thread.start()
        try:
            while not stop_event.wait(0.25):
                with activity_lock:
                    idle_for = time.monotonic() - last_activity
                if idle_for >= args.idle_ttl:
                    break
        finally:
            server.shutdown()
            server_thread.join(timeout=3)
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    state_dir = Path(args.state_dir).expanduser().resolve()
    registry_path = Path(args.registry).expanduser().resolve()
    expected_registry = state_dir / ".presentation" / "viewer.json"
    if registry_path != expected_registry:
        raise SystemExit("registry must be the private registry for state-dir")
    if args.idle_ttl <= 0:
        raise SystemExit("idle TTL must be positive")

    exit_code = 75
    with _viewer_lease(state_dir) as acquired:
        if acquired:
            exit_code = _serve(args, state_dir, registry_path)
    _cleanup_owned_registry(state_dir, registry_path, args.instance_id)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
