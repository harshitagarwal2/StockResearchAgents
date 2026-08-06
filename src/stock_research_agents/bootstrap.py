"""Production composition root for StockResearchAgents application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .application import StockResearchApplication
from .application_ports import (
    LifecycleRepository,
    QualityIndexPort,
    QualitySidecarPort,
    ResearchHistoryPort,
    ResultPublicationPort,
)
from .company_lifecycle import CompanyAnalyticsCoordinator
from .lifecycle import LIFECYCLE_STORE, LifecycleStore, default_decision_memory_store
from .lifecycle_profiles import CompanyAnalyticsLifecycleProfile, WorkflowDefinition
from .memory import ResearchHistoryRepository
from .research_quality_v1 import QUALITY_STORE, QualityStore
from .state import DEFAULT_STATE_LAYOUT, StateLayout
from .state_migrations import ensure_runtime_state
from .store import RUN_STORE, RunStore


@dataclass(frozen=True, slots=True)
class ApplicationRuntime:
    """Explicitly composed default dependencies for inbound adapters."""

    lifecycle_store: LifecycleRepository
    result_store: ResultPublicationPort
    quality_store: QualitySidecarPort
    coordinator: CompanyAnalyticsCoordinator
    state_layout: StateLayout | None = None

    def close(self) -> None:
        """Release resources created lazily by the composed coordinator."""
        self.coordinator.close()

    @property
    def application(self) -> StockResearchApplication:
        """Expose one transport-neutral facade over the composed runtime."""
        # These inbound adapters import DEFAULT_RUNTIME, so resolve them only
        # after composition is complete to keep the dependency direction acyclic.
        from .report_server import present_completed_run
        from .view import build_run_view

        return StockResearchApplication(
            coordinator=self.coordinator,
            result_store=self.result_store,
            quality_store=self.quality_store,
            presenter=present_completed_run,
            view_builder=build_run_view,
            state_layout=self.state_layout,
        )

    def __enter__(self) -> ApplicationRuntime:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def create_company_analytics_coordinator(
    *,
    lifecycle_store: LifecycleRepository,
    result_store: ResultPublicationPort,
    quality_store: QualityIndexPort,
    memory_store: ResearchHistoryPort | None = None,
    memory_store_factory: Callable[[], ResearchHistoryPort] | None = None,
    profile: WorkflowDefinition | None = None,
    use_default_memory: bool = True,
) -> CompanyAnalyticsCoordinator:
    """Compose a coordinator from explicit ports, defaulting only its memory factory."""
    if use_default_memory and memory_store is None and memory_store_factory is None:
        memory_store_factory = default_decision_memory_store
    workflow = profile or CompanyAnalyticsLifecycleProfile(quality_store)
    return CompanyAnalyticsCoordinator(
        lifecycle_store,
        result_store,
        memory_store=memory_store,
        memory_store_factory=memory_store_factory,
        profile=workflow,
    )


def create_runtime(state_layout: StateLayout) -> ApplicationRuntime:
    """Compose an isolated application runtime from one immutable state layout."""
    ensure_runtime_state(state_layout.root)
    lifecycle_store = LifecycleStore(state_layout.root)
    result_store = RunStore(state_layout.root)
    quality_store = QualityStore(state_layout.quality_dir)
    coordinator = create_company_analytics_coordinator(
        lifecycle_store=lifecycle_store,
        result_store=result_store,
        quality_store=quality_store,
        memory_store_factory=lambda: ResearchHistoryRepository(state_layout.memory_database),
        use_default_memory=False,
    )
    return ApplicationRuntime(
        lifecycle_store=lifecycle_store,
        result_store=result_store,
        quality_store=quality_store,
        coordinator=coordinator,
        state_layout=state_layout,
    )


DEFAULT_RUNTIME = ApplicationRuntime(
    lifecycle_store=LIFECYCLE_STORE,
    result_store=RUN_STORE,
    quality_store=QUALITY_STORE,
    coordinator=create_company_analytics_coordinator(
        lifecycle_store=LIFECYCLE_STORE,
        result_store=RUN_STORE,
        quality_store=QUALITY_STORE,
    ),
    state_layout=DEFAULT_STATE_LAYOUT,
)


def ensure_default_runtime_state() -> None:
    """Gate the shared default runtime before any operational adapter exposes it."""
    if DEFAULT_RUNTIME.state_layout is None:  # pragma: no cover - composition invariant
        raise RuntimeError("default runtime requires an explicit state layout")
    ensure_runtime_state(DEFAULT_RUNTIME.state_layout.root)


# Compatibility export for existing Python callers.
COMPANY_ANALYTICS_COORDINATOR = DEFAULT_RUNTIME.coordinator
