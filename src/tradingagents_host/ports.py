"""Narrow host interfaces consumed by harness-neutral orchestration."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import SourceBatch, SourceQuery


@runtime_checkable
class SourcePort(Protocol):
    """Open-ended host source adapter selected by an explicit capability route."""

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch: ...


@runtime_checkable
class ExperimentRunnerPort(Protocol):
    def run(self, spec: object) -> object: ...


@runtime_checkable
class OutcomeResolverPort(Protocol):
    def resolve(self, forecast: object) -> object: ...


@runtime_checkable
class NotificationPort(Protocol):
    def emit(self, alert: object) -> object: ...
