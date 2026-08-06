"""Framework-neutral sequential executor for the company analytics lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .bootstrap import create_company_analytics_coordinator
from .company_analytics_v1 import CompanyAnalyticsResultV1
from .company_lifecycle import CompanyAnalyticsCoordinator
from .contracts import RunEvent, reject_secret_shaped_keys
from .lifecycle import LifecycleStatus, LifecycleStore
from .research_contracts import CompanyResearchRequest
from .research_quality_v1 import QualityStore
from .store import RunStore


class LifecycleStageExecutor(Protocol):
    """Caller-supplied boundary for executing one durable analytics stage at a time."""

    def execute_stage(
        self,
        stage: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


def _stage_mapping(value: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"stage {stage_id} output must be an object")
    output = dict(value)
    reject_secret_shaped_keys(output, ("stage_outputs", stage_id))
    return output


def run_sequential_company_lifecycle(
    executor: LifecycleStageExecutor,
    *,
    request: CompanyResearchRequest | Mapping[str, object] | None = None,
    run_id: str | None = None,
    coordinator: CompanyAnalyticsCoordinator | None = None,
    research_pack_id: str | None = None,
    execution_mode: str | None = None,
    decision_memory_enabled: bool = False,
) -> tuple[CompanyAnalyticsResultV1, tuple[RunEvent, ...]]:
    """Execute or resume the durable company analytics lifecycle sequentially."""

    if coordinator is None:
        coordinator = create_company_analytics_coordinator(
            lifecycle_store=LifecycleStore(),
            result_store=RunStore(),
            quality_store=QualityStore(),
            use_default_memory=False,
        )

    if run_id is None:
        if request is None:
            raise ValueError("request is required when creating a sequential lifecycle run")
        control = coordinator.create(
            request,
            research_pack_id=research_pack_id,
            execution_mode=execution_mode,
            decision_memory_enabled=decision_memory_enabled,
        )
        run_id = str(control["run_id"])
        next_stage = coordinator.start(run_id, int(control["revision"]))
    else:
        if request is not None:
            raise ValueError("request cannot be supplied when resuming an existing lifecycle run")
        control = coordinator.control(run_id)
        status = control["status"]
        if status == LifecycleStatus.PREPARED.value:
            next_stage = coordinator.start(run_id, int(control["revision"]))
        elif status in {LifecycleStatus.RUNNING.value, LifecycleStatus.PAUSED.value}:
            next_stage = coordinator.resume(run_id, int(control["revision"]))
        elif status in {LifecycleStatus.FINALIZING.value, LifecycleStatus.COMPLETED.value}:
            return coordinator.finalize(run_id, int(control["revision"]))
        else:
            raise ValueError(f"run {run_id} cannot be executed sequentially while status is {status}")

    while next_stage["stage"] is not None:
        stage = next_stage["stage"]
        context = next_stage["context"]
        envelope = _stage_mapping(executor.execute_stage(stage, context), str(stage["id"]))
        next_stage = coordinator.commit_stage(
            run_id,
            str(stage["id"]),
            envelope,
            int(next_stage["control"]["revision"]),
            attempt=int(next_stage["attempt"]),
        )

    return coordinator.finalize(run_id, int(next_stage["control"]["revision"]))
