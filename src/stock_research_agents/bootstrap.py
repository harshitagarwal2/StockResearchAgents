"""Production composition root for StockResearchAgents application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .application_ports import (
    LifecycleRepository,
    QualityIndexPort,
    QualitySidecarPort,
    ResearchHistoryPort,
    ResultPublicationPort,
)
from .company_lifecycle import CompanyAnalyticsCoordinator
from .lifecycle import LIFECYCLE_STORE, default_decision_memory_store
from .lifecycle_profiles import CompanyAnalyticsLifecycleProfile, WorkflowDefinition
from .research_quality_v1 import QUALITY_STORE
from .store import RUN_STORE


@dataclass(frozen=True, slots=True)
class ApplicationRuntime:
    """Explicitly composed default dependencies for inbound adapters."""

    lifecycle_store: LifecycleRepository
    result_store: ResultPublicationPort
    quality_store: QualitySidecarPort
    coordinator: CompanyAnalyticsCoordinator


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


DEFAULT_RUNTIME = ApplicationRuntime(
    lifecycle_store=LIFECYCLE_STORE,
    result_store=RUN_STORE,
    quality_store=QUALITY_STORE,
    coordinator=create_company_analytics_coordinator(
        lifecycle_store=LIFECYCLE_STORE,
        result_store=RUN_STORE,
        quality_store=QUALITY_STORE,
    ),
)

# Compatibility export for existing Python callers.
COMPANY_ANALYTICS_COORDINATOR = DEFAULT_RUNTIME.coordinator
