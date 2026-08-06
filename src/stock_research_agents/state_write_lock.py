"""Cross-process serialization for durable state mutations."""

from __future__ import annotations

import errno
import importlib
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, RLock

_LOCK_FILE_NAME = ".state-writer.lock"


@dataclass(slots=True)
class _ProcessLockState:
    gate: RLock = field(default_factory=RLock)
    depth: int = 0
    descriptor: int | None = None


_registry_guard = Lock()
_registry: dict[Path, _ProcessLockState] = {}


def _reset_after_fork() -> None:
    """Discard inherited thread primitives and duplicate lock descriptors."""
    global _registry_guard, _registry
    for state in _registry.values():
        if state.descriptor is not None:
            try:
                os.close(state.descriptor)
            except OSError:
                pass
    _registry_guard = Lock()
    _registry = {}


if hasattr(os, "register_at_fork"):  # pragma: win32 no cover
    os.register_at_fork(after_in_child=_reset_after_fork)


def writer_lock_path(state_root: str | os.PathLike[str]) -> Path:
    """Return the stable lock-file path for one durable state root."""
    return Path(state_root).expanduser().resolve(strict=False) / _LOCK_FILE_NAME


def _state_for(path: Path) -> _ProcessLockState:
    with _registry_guard:
        return _registry.setdefault(path, _ProcessLockState())


def _open_lock_file(path: Path) -> int:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    if hasattr(os, "fchmod"):  # pragma: win32 no cover
        os.fchmod(descriptor, 0o600)
    if sys.platform == "win32" and os.fstat(descriptor).st_size == 0:  # pragma: win32 cover
        os.write(descriptor, b"\0")
        os.fsync(descriptor)
    return descriptor


def _acquire_os_lock(descriptor: int) -> None:
    if sys.platform != "win32":  # pragma: win32 no cover
        locking = importlib.import_module("fcntl")
        locking.flock(descriptor, locking.LOCK_EX)
        return
    locking = importlib.import_module("msvcrt")  # pragma: win32 cover
    os.lseek(descriptor, 0, os.SEEK_SET)  # pragma: win32 cover
    while True:  # pragma: win32 cover
        try:
            locking.locking(descriptor, locking.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            time.sleep(0.01)


def _release_os_lock(descriptor: int) -> None:
    if sys.platform != "win32":  # pragma: win32 no cover
        locking = importlib.import_module("fcntl")
        locking.flock(descriptor, locking.LOCK_UN)
        return
    locking = importlib.import_module("msvcrt")  # pragma: win32 cover
    os.lseek(descriptor, 0, os.SEEK_SET)  # pragma: win32 cover
    locking.locking(descriptor, locking.LK_UNLCK, 1)  # pragma: win32 cover


@contextmanager
def state_write_lock(state_root: str | os.PathLike[str] | None) -> Iterator[None]:
    """Serialize writers for one state root, reentrantly within a process thread."""
    if state_root is None:
        yield
        return

    path = writer_lock_path(state_root)
    state = _state_for(path)
    with state.gate:
        if state.depth == 0:
            descriptor = _open_lock_file(path)
            try:
                _acquire_os_lock(descriptor)
            except BaseException:
                os.close(descriptor)
                raise
            state.descriptor = descriptor
        state.depth += 1
        try:
            yield
        finally:
            state.depth -= 1
            if state.depth == 0:
                release_descriptor = state.descriptor
                state.descriptor = None
                if release_descriptor is not None:
                    try:
                        _release_os_lock(release_descriptor)
                    finally:
                        os.close(release_descriptor)


__all__ = ["state_write_lock", "writer_lock_path"]
