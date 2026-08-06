"""Production composition root for StockResearchAgents application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .application_ports import LifecycleRepository, ResearchHistoryPort, ResultPublicationPort
from .company_lifecycle import CompanyAnalyticsCoordinator
from .lifecycle import LIFECYCLE_STORE, default_decision_memory_store
from .lifecycle_profiles import COMPANY_ANALYTICS_LIFECYCLE_PROFILE, WorkflowDefinition
from .store import RUN_STORE


@dataclass(frozen=True, slots=True)
class ApplicationRuntime:
    """Explicitly composed default dependencies for inbound adapters."""

    lifecycle_store: LifecycleRepository
    result_store: ResultPublicationPort
    coordinator: CompanyAnalyticsCoordinator


def create_company_analytics_coordinator(
    *,
    lifecycle_store: LifecycleRepository,
    result_store: ResultPublicationPort,
    memory_store: ResearchHistoryPort | None = None,
    memory_store_factory: Callable[[], ResearchHistoryPort] | None = None,
    profile: WorkflowDefinition = COMPANY_ANALYTICS_LIFECYCLE_PROFILE,
    use_default_memory: bool = True,
) -> CompanyAnalyticsCoordinator:
    """Compose a coordinator from explicit ports, defaulting only its memory factory."""
    if use_default_memory and memory_store is None and memory_store_factory is None:
        memory_store_factory = default_decision_memory_store
    return CompanyAnalyticsCoordinator(
        lifecycle_store,
        result_store,
        memory_store=memory_store,
        memory_store_factory=memory_store_factory,
        profile=profile,
    )


DEFAULT_RUNTIME = ApplicationRuntime(
    lifecycle_store=LIFECYCLE_STORE,
    result_store=RUN_STORE,
    coordinator=create_company_analytics_coordinator(
        lifecycle_store=LIFECYCLE_STORE,
        result_store=RUN_STORE,
    ),
)

# Compatibility export for existing Python callers.
COMPANY_ANALYTICS_COORDINATOR = DEFAULT_RUNTIME.coordinator
