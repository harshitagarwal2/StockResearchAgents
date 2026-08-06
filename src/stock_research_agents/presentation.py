"""Best-effort presentation of durable, completed research publications.

Presentation is deliberately an adapter concern: publication remains atomic and
pure, while this module may start a detached loopback viewer after publication
has succeeded.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock, Thread
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ._version import __version__
from .contracts import SCHEMA_VERSION, RunStatus
from .store import RUN_STORE, RunStore

if sys.platform == "win32":  # pragma: no cover - exercised by Windows harnesses
    import msvcrt
else:  # pragma: no cover - branch is platform-specific
    import fcntl

_SCHEMA = "presentation-link.v1"
_HOST = "127.0.0.1"
_DEFAULT_IDLE_TTL_SECONDS = 1800.0
_STARTUP_TIMEOUT_SECONDS = 6.0
_MAX_PROBE_RESPONSE_BYTES = 4 * 1024 * 1024
_VIEWER_PROTOCOL_VERSION = "viewer-protocol.v1"
_VIEWER_REGISTRY_SCHEMA = "viewer-daemon-registry.v1"
_HEALTH_RETRY_ATTEMPTS = 4
_HEALTH_RETRY_DELAY_SECONDS = 0.1
_LOCAL_VIEWER_PROCESSES: dict[int, subprocess.Popen[bytes]] = {}
_LOCAL_VIEWER_PROCESSES_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class PresentationLink:
    """Typed receipt for a completed run's presentation location."""

    schema: str
    run_id: str
    encoded_path: str
    url: str | None
    status: Literal["ready", "path_only", "unavailable"]
    loopback_only: bool
    reused: bool
    error: dict[str, object] | None = None
    url_scope: str = "presenter_host_loopback"
    idle_ttl_seconds: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "schema_version": self.schema,
            "run_id": self.run_id,
            "encoded_path": self.encoded_path,
            "path": self.encoded_path,
            "url": self.url,
            "status": self.status,
            "loopback_only": self.loopback_only,
            "reused": self.reused,
            "error": self.error,
            "url_scope": self.url_scope,
            "idle_ttl_seconds": self.idle_ttl_seconds,
        }


@dataclass(frozen=True, slots=True)
class _ViewerInstance:
    base_url: str
    instance_id: str
    access_token: str
    pid: int
    idle_ttl_seconds: float


def _encoded_path(run_id: str) -> str:
    return f"/?run={quote(run_id, safe='')}"


def _error_link(
    run_id: str,
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> PresentationLink:
    error: dict[str, object] = {"code": code, "message": message}
    if details:
        error.update(details)
    return PresentationLink(
        schema=_SCHEMA,
        run_id=run_id,
        encoded_path=_encoded_path(run_id),
        url=None,
        status="unavailable",
        loopback_only=True,
        reused=False,
        error=error,
        url_scope="none",
    )


def _package_version() -> str:
    return __version__


def _viewer_build_digest() -> str:
    package_root = Path(__file__).resolve().parent
    sources = sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix in {".css", ".html", ".js", ".json", ".py"}
    )
    digest = hashlib.sha256()
    for source in sources:
        digest.update(str(source.relative_to(package_root)).encode("utf-8"))
        try:
            digest.update(source.read_bytes())
        except OSError:
            digest.update(b"<unavailable>")
    return digest.hexdigest()


def _viewer_identity() -> dict[str, str]:
    return {
        "viewer_protocol_version": _VIEWER_PROTOCOL_VERSION,
        "package_version": _package_version(),
        "run_schema_version": SCHEMA_VERSION,
        "viewer_build_digest": _viewer_build_digest(),
    }


def _registry_identity_is_current(registry: dict[str, object] | None, fingerprint: str) -> bool:
    if registry is None:
        return False
    return (
        registry.get("schema") == _VIEWER_REGISTRY_SCHEMA
        and registry.get("state_fingerprint") == fingerprint
        and all(registry.get(key) == value for key, value in _viewer_identity().items())
    )


def _state_fingerprint(state_dir: Path) -> str:
    return hashlib.sha256(os.fsencode(str(state_dir))).hexdigest()


def _presentation_dir(state_dir: Path) -> Path:
    directory = state_dir / ".presentation"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return directory


@contextmanager
def _file_lock(path: Path, *, blocking: bool) -> Iterator[bool]:
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        if sys.platform == "win32":  # pragma: no cover - exercised by Windows harnesses
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                if blocking:
                    raise
        else:
            operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(descriptor, operation)
                acquired = True
            except BlockingIOError:
                if blocking:
                    raise
        yield acquired
    finally:
        if acquired:
            if sys.platform == "win32":  # pragma: no cover - exercised by Windows harnesses
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _registry_lock(state_dir: Path) -> Iterator[Path]:
    directory = _presentation_dir(state_dir)
    with _file_lock(directory / "viewer.lock", blocking=True) as acquired:
        if not acquired:  # pragma: no cover - blocking locks either acquire or raise
            raise OSError("unable to acquire presentation registry lock")
        yield directory / "viewer.json"


@contextmanager
def _viewer_lease(state_dir: Path, *, blocking: bool = False) -> Iterator[bool]:
    """Hold the single-daemon lifetime lease for one durable state directory."""
    directory = _presentation_dir(state_dir)
    with _file_lock(directory / "viewer.lease", blocking=blocking) as acquired:
        yield acquired


def _atomic_write_registry(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".viewer.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _read_registry(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_LOOPBACK_OPENER = build_opener(ProxyHandler({}), _RejectRedirects())


def _fetch_json(
    url: str,
    timeout: float,
    *,
    access_token: str | None = None,
    method: str = "GET",
) -> dict[str, object] | None:
    headers = {"Accept": "application/json"}
    if access_token is not None:
        headers["X-StockResearchAgents-Viewer-Token"] = access_token
    request = Request(url, headers=headers, method=method)
    try:
        with _LOOPBACK_OPENER.open(request, timeout=timeout) as response:  # noqa: S310 - loopback-only opener
            content = response.read(_MAX_PROBE_RESPONSE_BYTES + 1)
            if len(content) > _MAX_PROBE_RESPONSE_BYTES:
                return None
            payload = json.loads(content)
    except HTTPError as exc:
        exc.close()
        return None
    except (URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _validated_instance(
    registry: dict[str, object] | None,
    fingerprint: str,
) -> _ViewerInstance | None:
    if registry is None:
        return None
    host = registry.get("host")
    port = registry.get("port")
    instance_id = registry.get("instance_id")
    access_token = registry.get("access_token")
    pid = registry.get("pid")
    idle_ttl_seconds = registry.get("idle_ttl_seconds")
    identity = _viewer_identity()
    if (
        registry.get("schema") != _VIEWER_REGISTRY_SCHEMA
        or host != _HOST
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
        or not isinstance(instance_id, str)
        or not isinstance(access_token, str)
        or len(access_token) < 32
        or not isinstance(pid, int)
        or isinstance(pid, bool)
        or not isinstance(idle_ttl_seconds, int | float)
        or isinstance(idle_ttl_seconds, bool)
        or idle_ttl_seconds <= 0
        or registry.get("state_fingerprint") != fingerprint
        or any(registry.get(key) != value for key, value in identity.items())
    ):
        return None
    base_url = f"http://{_HOST}:{port}"
    health = None
    for attempt in range(_HEALTH_RETRY_ATTEMPTS):
        health = _fetch_json(f"{base_url}/api/health", timeout=0.5, access_token=access_token)
        if health is not None:
            break
        if attempt + 1 < _HEALTH_RETRY_ATTEMPTS:
            time.sleep(_HEALTH_RETRY_DELAY_SECONDS)
    if (
        health is None
        or health.get("ok") is not True
        or health.get("loopback_only") is not True
        or health.get("instance_id") != instance_id
        or health.get("state_fingerprint") != fingerprint
        or any(health.get(key) != value for key, value in identity.items())
    ):
        return None
    return _ViewerInstance(base_url, instance_id, access_token, pid, float(idle_ttl_seconds))


def _probe_registered_generation(
    registry: dict[str, object] | None,
    fingerprint: str,
) -> tuple[int, str] | None:
    """Prove a registry PID owns the loopback daemon before signalling it."""
    if registry is None:
        return None
    host = registry.get("host")
    port = registry.get("port")
    pid = registry.get("pid")
    instance_id = registry.get("instance_id")
    access_token = registry.get("access_token")
    if (
        host != _HOST
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
        or not isinstance(pid, int)
        or isinstance(pid, bool)
        or not isinstance(instance_id, str)
        or registry.get("state_fingerprint") != fingerprint
    ):
        return None
    health = _fetch_json(
        f"http://{_HOST}:{port}/api/health",
        timeout=0.75,
        access_token=access_token if isinstance(access_token, str) else None,
    )
    if (
        health is None
        or health.get("ok") is not True
        or health.get("viewer_daemon") is not True
        or health.get("instance_id") != instance_id
        or health.get("state_fingerprint") != fingerprint
    ):
        return None
    return pid, instance_id


def _lease_is_available(state_dir: Path) -> bool:
    with _viewer_lease(state_dir) as acquired:
        return acquired


def _retire_registered_generation(
    state_dir: Path,
    registry: dict[str, object] | None,
    fingerprint: str,
    *,
    timeout: float = 3.0,
) -> bool:
    owned = _probe_registered_generation(registry, fingerprint)
    if owned is None:
        return False
    access_token = registry.get("access_token") if registry is not None else None
    port = registry.get("port") if registry is not None else None
    shutdown = (
        _fetch_json(
            f"http://{_HOST}:{port}/api/shutdown",
            timeout=1.0,
            access_token=access_token if isinstance(access_token, str) else None,
            method="POST",
        )
        if isinstance(port, int)
        else None
    )
    if shutdown is None or shutdown.get("ok") is not True:
        try:
            os.kill(owned[0], signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        if _lease_is_available(state_dir):
            return True
        time.sleep(0.05)
    return False


def _viewer_url(instance: _ViewerInstance, run_id: str) -> str:
    query = urlencode({"run": run_id})
    fragment = urlencode({"access_token": instance.access_token})
    return f"{instance.base_url}/?{query}#{fragment}"


def _ready_link(run_id: str, instance: _ViewerInstance, *, reused: bool) -> PresentationLink:
    return PresentationLink(
        schema=_SCHEMA,
        run_id=run_id,
        encoded_path=_encoded_path(run_id),
        url=_viewer_url(instance, run_id),
        status="ready",
        loopback_only=True,
        reused=reused,
        idle_ttl_seconds=instance.idle_ttl_seconds,
    )


def _child_environment(state_dir: Path) -> dict[str, str]:
    """Return a credential-free allowlist for the detached local viewer."""
    environment: dict[str, str] = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "PYTHONUNBUFFERED": "1",
        "STOCKRESEARCHAGENTS_STATE_DIR": str(state_dir),
    }
    for name in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _idle_ttl_seconds() -> float:
    raw = os.environ.get("STOCKRESEARCHAGENTS_PRESENTATION_IDLE_TTL_SECONDS")
    if raw is None:
        return _DEFAULT_IDLE_TTL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_IDLE_TTL_SECONDS
    return value if value > 0 else _DEFAULT_IDLE_TTL_SECONDS


def _reap_local_viewer(process: subprocess.Popen[bytes]) -> None:
    """Retain and reap a locally spawned detached viewer without blocking callers."""
    try:
        process.wait()
    finally:
        with _LOCAL_VIEWER_PROCESSES_LOCK:
            if _LOCAL_VIEWER_PROCESSES.get(process.pid) is process:
                _LOCAL_VIEWER_PROCESSES.pop(process.pid, None)


def _track_local_viewer(process: subprocess.Popen[bytes]) -> subprocess.Popen[bytes]:
    with _LOCAL_VIEWER_PROCESSES_LOCK:
        _LOCAL_VIEWER_PROCESSES[process.pid] = process
    Thread(
        target=_reap_local_viewer,
        args=(process,),
        name=f"stockresearchagents-viewer-reaper-{process.pid}",
        daemon=True,
    ).start()
    return process


def _spawn_viewer(
    state_dir: Path,
    registry_path: Path,
    fingerprint: str,
    instance_id: str,
) -> subprocess.Popen[bytes]:
    diagnostic_path = registry_path.with_name("viewer-startup.log")
    descriptor = os.open(diagnostic_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        return _track_local_viewer(
            subprocess.Popen(  # noqa: S603 - fixed interpreter/module and validated local arguments
                [
                    sys.executable,
                    "-m",
                    "stock_research_agents.viewer_daemon",
                    "--state-dir",
                    str(state_dir),
                    "--registry",
                    str(registry_path),
                    "--state-fingerprint",
                    fingerprint,
                    "--instance-id",
                    instance_id,
                    "--idle-ttl",
                    str(_idle_ttl_seconds()),
                ],
                stdin=subprocess.DEVNULL,
                stdout=descriptor,
                stderr=subprocess.STDOUT,
                env=_child_environment(state_dir),
                close_fds=True,
                start_new_session=True,
            )
        )
    finally:
        os.close(descriptor)


def _run_is_ready(instance: _ViewerInstance, run_id: str) -> bool:
    payload = _fetch_json(
        f"{instance.base_url}/api/runs/{quote(run_id, safe='')}/view",
        timeout=0.75,
        access_token=instance.access_token,
    )
    if payload is None or payload.get("ok") is not True:
        return False
    view = payload.get("view")
    return isinstance(view, dict) and view.get("run_id") == run_id


def ensure_completed_run_presentation(
    run_id: str,
    store: RunStore = RUN_STORE,
    *,
    startup_timeout: float = _STARTUP_TIMEOUT_SECONDS,
    mode: str | None = None,
) -> PresentationLink:
    """Ensure one detached viewer for a durable completed run.

    Failure is returned as data so a successful research publication is never
    rolled back or reclassified because presentation could not start.
    """
    path = _encoded_path(run_id)
    result = store.get_result(run_id)
    if result is None or result.status is not RunStatus.COMPLETED:
        return _error_link(run_id, "completed_run_not_found", f"completed run not found: {run_id}")
    if mode is not None:
        selected_mode = mode.strip().lower()
    else:
        selected_mode = (os.environ.get("STOCKRESEARCHAGENTS_PRESENTATION_MODE") or "auto").strip().lower()
    if selected_mode == "path_only":
        return PresentationLink(
            _SCHEMA,
            run_id,
            path,
            None,
            "path_only",
            True,
            False,
            url_scope="none",
        )
    if selected_mode != "auto":
        return _error_link(run_id, "invalid_presentation_mode", "presentation mode must be auto or path_only")
    state_dir = store.state_dir
    if state_dir is None:
        return _error_link(run_id, "durable_store_required", "automatic presentation requires a durable RunStore")
    resolved_state_dir = state_dir.expanduser().resolve()
    if not (resolved_state_dir / "bundles" / f"{run_id}.json").is_file():
        return _error_link(run_id, "durable_publication_missing", "completed run has no durable publication bundle")

    fingerprint = _state_fingerprint(resolved_state_dir)
    try:
        with _registry_lock(resolved_state_dir) as registry_path:
            registered = _read_registry(registry_path)
            existing = _validated_instance(registered, fingerprint)
            if existing is not None:
                deadline = time.monotonic() + min(max(0.1, startup_timeout), 1.0)
                while time.monotonic() < deadline:
                    if _run_is_ready(existing, run_id):
                        return _ready_link(run_id, existing, reused=True)
                    time.sleep(0.05)
                return _error_link(
                    run_id,
                    "viewer_run_not_ready",
                    "the shared viewer is healthy but this completed run is not publicly visible",
                )

            if not _lease_is_available(resolved_state_dir):
                if not _registry_identity_is_current(registered, fingerprint):
                    retired = _retire_registered_generation(resolved_state_dir, registered, fingerprint)
                    if not retired:
                        return _error_link(
                            run_id,
                            "viewer_generation_conflict",
                            "a live viewer generation could not be safely retired",
                        )
                else:
                    return _error_link(
                        run_id,
                        "viewer_temporarily_unavailable",
                        "the shared viewer is alive but did not pass bounded health checks",
                    )
            registry_path.unlink(missing_ok=True)

            instance_id = uuid.uuid4().hex
            spawned = _spawn_viewer(resolved_state_dir, registry_path, fingerprint, instance_id)
            deadline = time.monotonic() + max(0.1, startup_timeout)
            healthy_instance = False
            while time.monotonic() < deadline:
                registry = _read_registry(registry_path)
                if registry is not None and registry.get("instance_id") == instance_id:
                    launched = _validated_instance(registry, fingerprint)
                    if launched is not None:
                        healthy_instance = True
                        if _run_is_ready(launched, run_id):
                            return _ready_link(run_id, launched, reused=False)
                if spawned.poll() is not None:
                    return _error_link(
                        run_id,
                        "viewer_process_exited",
                        f"viewer process exited with code {spawned.returncode}",
                        details={"diagnostic_log": str(registry_path.with_name("viewer-startup.log"))},
                    )
                time.sleep(0.05)
            if not healthy_instance and spawned.poll() is None:
                spawned.terminate()
                try:
                    spawned.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    spawned.kill()
                    spawned.wait(timeout=2)
            if healthy_instance:
                return _error_link(
                    run_id,
                    "viewer_run_not_ready",
                    "the viewer started, but this completed run is not publicly visible",
                )
    except (OSError, subprocess.SubprocessError) as exc:
        return _error_link(run_id, "viewer_start_failed", str(exc))
    return _error_link(
        run_id,
        "viewer_start_timeout",
        "loopback viewer did not become ready in time",
        details={"diagnostic_log": str(_presentation_dir(resolved_state_dir) / "viewer-startup.log")},
    )


def present_completed_run(run_id: str, store: RunStore = RUN_STORE) -> PresentationLink:
    """Default adapter helper honoring the configured presentation mode."""
    return ensure_completed_run_presentation(run_id, store)


class ViewerDaemonPresenter:
    """Small stateful adapter around the cross-process viewer daemon."""

    def __init__(
        self,
        store: RunStore = RUN_STORE,
        *,
        mode: str | None = None,
        startup_timeout: float = _STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        self.store = store
        self.mode = mode
        self.startup_timeout = startup_timeout

    def present(self, run_id: str) -> PresentationLink:
        return ensure_completed_run_presentation(
            run_id,
            self.store,
            startup_timeout=self.startup_timeout,
            mode=self.mode,
        )

    def stop(self, *, timeout: float = 3.0) -> bool:
        return stop_presentation_daemon(self.store, timeout=timeout)


def stop_presentation_daemon(store: RunStore = RUN_STORE, *, timeout: float = 3.0) -> bool:
    """Safely stop the matching detached viewer, primarily for tests."""
    state_dir = store.state_dir
    if state_dir is None:
        return False
    resolved_state_dir = state_dir.expanduser().resolve()
    fingerprint = _state_fingerprint(resolved_state_dir)
    registry_path: Path
    with _registry_lock(resolved_state_dir) as registry_path:
        registry = _read_registry(registry_path)
        if registry is None:
            return False
        owned = _probe_registered_generation(registry, fingerprint)
        if owned is None:
            if registry.get("state_fingerprint") == fingerprint:
                registry_path.unlink(missing_ok=True)
            return False
        _, instance_id = owned
        if not _retire_registered_generation(resolved_state_dir, registry, fingerprint, timeout=timeout):
            return False
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        current = _read_registry(registry_path)
        if current is None or current.get("instance_id") != instance_id:
            return True
        time.sleep(0.05)
    return False


__all__ = [
    "PresentationLink",
    "ViewerDaemonPresenter",
    "ensure_completed_run_presentation",
    "present_completed_run",
    "stop_presentation_daemon",
]
