"""Reference harness-neutral sequential executor.

Native harnesses may map the same stage contracts to subagents or tasks. This
fallback proves that no LangGraph or Codex-specific API is required: a host only
needs to implement ``StageExecutor.execute_stage`` and return the declared
mapping for each stage.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .contracts import RunRequest, RunResult, StageKind, reject_secret_shaped_keys
from .host_native import prepare_host_run, submit_host_run
from .store import RUN_STORE, RunStore
from .workflow import StageExecutor, expand_workflow, load_workflow_manifest, stage_runtime_contract


def _stage_mapping(value: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"stage {stage_id} output must be an object")
    output = dict(value)
    reject_secret_shaped_keys(output, ("stage_outputs", stage_id))
    return output


def _stage_array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return deepcopy(value)


def run_sequential_host_workflow(
    request: RunRequest,
    executor: StageExecutor,
    *,
    store: RunStore = RUN_STORE,
) -> tuple[RunResult, tuple[Any, ...]]:
    """Execute the portable workflow sequentially and atomically import it."""
    plan = prepare_host_run(request)
    normalized_request = RunRequest(
        symbol=plan["request"]["symbol"],
        as_of_date=plan["request"]["as_of_date"],
        asset_type=plan["request"]["asset_type"],
        analysts=tuple(plan["request"]["analysts"]),
        debate_rounds=plan["request"]["debate_rounds"],
        risk_rounds=plan["request"]["risk_rounds"],
        output_language=plan["request"]["output_language"],
        executor="host_native",
    )
    topology = expand_workflow(normalized_request)
    manifest = load_workflow_manifest()
    submission: dict[str, Any] = {
        "request": deepcopy(plan["request"]),
        "company_of_interest": normalized_request.symbol,
        "instrument_context": "",
        "evidence": [],
        "analyst_reports": [],
        "research_debate": [],
        "risk_debate": [],
        "warnings": [],
    }
    stage_outputs: dict[str, dict[str, Any]] = {}

    for stage in topology.stages:
        runtime_contract = stage_runtime_contract(stage, manifest)
        instrument_identity = {
            "symbol": normalized_request.symbol,
            "asset_type": normalized_request.asset_type,
            "as_of_date": normalized_request.as_of_date,
            "company_of_interest": submission["company_of_interest"],
            "instrument_context": submission["instrument_context"],
        }
        available_context = {
            "request": deepcopy(plan["request"]),
            "instrument_identity": instrument_identity,
            "evidence": submission["evidence"],
            "analyst_reports": submission["analyst_reports"],
            "research_debate_so_far": submission["research_debate"],
            "research_debate": submission["research_debate"],
            "research_decision": submission.get("research_decision"),
            "trader_decision": submission.get("trader_decision"),
            "risk_debate_so_far": submission["risk_debate"],
            "risk_debate": submission["risk_debate"],
            "optional_past_context": None,
        }
        context_keys = runtime_contract.get("context", ())
        context = {key: deepcopy(available_context[key]) for key in context_keys}
        output = _stage_mapping(
            executor.execute_stage(
                stage,
                str(runtime_contract["instruction"]),
                context,
                tuple(runtime_contract.get("allowed_tools", ())),
            ),
            stage.id,
        )
        stage_outputs[stage.id] = deepcopy(output)

        if stage.kind is StageKind.ANALYST:
            analyst = stage.id.removeprefix("analyst.")
            submission["evidence"].extend(_stage_array(output.get("evidence"), f"{stage.id}.evidence"))
            report = dict(output.get("report", {}))
            report["analyst"] = analyst
            submission["analyst_reports"].append(report)
            if output.get("company_of_interest"):
                submission["company_of_interest"] = output["company_of_interest"]
            if output.get("instrument_context") is not None:
                submission["instrument_context"] = output["instrument_context"]
            continue

        if stage.kind in {StageKind.RESEARCH_DEBATE, StageKind.RISK_DEBATE}:
            parts = stage.id.split(".")
            debate_key = "research_debate" if stage.kind is StageKind.RESEARCH_DEBATE else "risk_debate"
            turn = {
                "round": int(parts[1]),
                "speaker": stage.role,
                **output,
            }
            submission[debate_key].append(turn)
            continue

        if stage.kind is StageKind.RESEARCH_MANAGER:
            submission["research_decision"] = output
        elif stage.kind is StageKind.TRADER:
            submission["trader_decision"] = output
        elif stage.kind is StageKind.PORTFOLIO:
            submission["risk_decision"] = output.get("risk_decision")
            submission["portfolio_decision"] = output.get("portfolio_decision")
            if output.get("final_trade_decision") is not None:
                submission["final_trade_decision"] = output["final_trade_decision"]
            submission["warnings"].extend(_stage_array(output.get("warnings", []), f"{stage.id}.warnings"))

    return submit_host_run(submission, store=store)
