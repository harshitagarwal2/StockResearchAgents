"""Replay completed host submissions through every durable lifecycle boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from tradingagents_portable.conformance import evaluate_conformance
from tradingagents_portable.contracts import RunRequest, StageKind
from tradingagents_portable.export import export_run_bundle
from tradingagents_portable.lifecycle import HostRunCoordinator, LifecycleStore
from tradingagents_portable.memory import DecisionMemoryStore
from tradingagents_portable.store import RunStore

_NON_STRUCTURAL_CHECKS = {"pinned_upstream_identity", "stage_completion_receipts"}


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _lifecycle_smoke_validation(
    result: Any,
    events: tuple[Any, ...],
    conformance: Any,
    *,
    upstream_required: bool,
) -> dict[str, object]:
    checks = {check.name: check for check in conformance.checks}
    structural_checks = [check for check in conformance.checks if check.name not in _NON_STRUCTURAL_CHECKS]
    structural_ok = bool(structural_checks) and all(check.verified and check.passed for check in structural_checks)
    identity = checks["pinned_upstream_identity"]
    identity_ok = not upstream_required or (identity.verified and identity.passed)
    expected_stage_ids = tuple(stage.id for stage in result.topology.stages)
    commits = tuple(event for event in events if event.kind.value == "stage" and event.status == "committed")
    receipts = {
        event.data.get("receipt_id"): event
        for event in events
        if event.kind.value == "stage" and isinstance(event.data.get("receipt_id"), str)
    }
    boundaries_ok = tuple(event.stage_id for event in commits) == expected_stage_ids
    for ordinal, event in enumerate(commits, start=1):
        data = event.data
        receipt_ids = data.get("execution_receipt_ids")
        attempt = data.get("attempt")
        digest = data.get("output_digest")
        if not (
            data.get("checkpoint_ordinal") == ordinal
            and isinstance(attempt, int)
            and attempt > 0
            and _is_sha256(digest)
            and data.get("envelope_observed") is True
            and data.get("output_observed") is True
            and data.get("output_content_verified") is True
            and data.get("host_completion_attested") is True
            and data.get("execution_observed") is False
            and isinstance(receipt_ids, list)
            and len(receipt_ids) == 2
        ):
            boundaries_ok = False
            break
        start = receipts.get(receipt_ids[0])
        completion = receipts.get(receipt_ids[1])
        if not (
            start is not None
            and completion is not None
            and start.stage_id == event.stage_id
            and completion.stage_id == event.stage_id
            and start.data.get("kind") == "stage_started"
            and completion.data.get("kind") == "stage_completed"
            and start.data.get("attempt") == attempt
            and completion.data.get("attempt") == attempt
            and completion.data.get("output_digest") == digest
        ):
            boundaries_ok = False
            break
    passed = structural_ok and identity_ok and boundaries_ok
    return {
        "passed": passed,
        "structural_checks_passed": structural_ok,
        "upstream_identity_required": upstream_required,
        "upstream_identity_passed": identity_ok,
        "attested_commit_boundaries_passed": boundaries_ok,
        "committed_boundaries": len(commits),
        "expected_boundaries": len(expected_stage_ids),
        "execution_observed": False,
    }


def _request(payload: dict[str, Any]) -> RunRequest:
    request = payload["request"]
    return RunRequest(
        symbol=request["symbol"],
        as_of_date=request["as_of_date"],
        asset_type=request["asset_type"],
        analysts=tuple(request["analysts"]),
        debate_rounds=request["debate_rounds"],
        risk_rounds=request["risk_rounds"],
        output_language=request["output_language"],
        executor="host_native",
    )


def _stage_output(
    payload: dict[str, Any],
    stage: dict[str, Any],
) -> dict[str, Any]:
    kind = StageKind(stage["kind"])
    stage_id = stage["id"]
    if kind is StageKind.ANALYST:
        analyst = stage_id.removeprefix("analyst.")
        report = next(item for item in payload["analyst_reports"] if item["analyst"] == analyst)
        retained = set(report["evidence_ids"])
        output = {
            "company_of_interest": payload["company_of_interest"],
            "instrument_context": payload["instrument_context"],
            "evidence": [deepcopy(item) for item in payload["evidence"] if item["id"] in retained],
            "report": {key: deepcopy(value) for key, value in report.items() if key != "analyst"},
        }
        return output
    if kind in {StageKind.RESEARCH_DEBATE, StageKind.RISK_DEBATE}:
        parts = stage_id.split(".")
        debate = payload["research_debate"] if kind is StageKind.RESEARCH_DEBATE else payload["risk_debate"]
        turn = next(item for item in debate if item["round"] == int(parts[1]) and item["speaker"] == stage["role"])
        return {key: deepcopy(value) for key, value in turn.items() if key not in {"round", "speaker"}}
    if kind is StageKind.RESEARCH_MANAGER:
        return deepcopy(payload["research_decision"])
    if kind is StageKind.TRADER:
        return deepcopy(payload["trader_decision"])
    return {
        "risk_decision": deepcopy(payload["risk_decision"]),
        "portfolio_decision": deepcopy(payload["portfolio_decision"]),
        "final_trade_decision": payload["final_trade_decision"],
        "warnings": deepcopy(payload.get("warnings", [])),
    }


def replay(path: Path, state_root: Path, upstream_path: Path | None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbol = payload["request"]["symbol"]
    state_dir = state_root / symbol.replace("/", "_")
    memory = DecisionMemoryStore(state_dir / "decision-memory.sqlite3")
    coordinator = HostRunCoordinator(LifecycleStore(state_dir), RunStore(state_dir), memory_store=memory)
    control = coordinator.create(_request(payload))
    run_id = control["run_id"]
    next_stage = coordinator.start(run_id, control["revision"])
    while next_stage["stage"] is not None:
        stage = next_stage["stage"]
        attempt = next_stage["attempt"]
        output = _stage_output(payload, stage)
        output_digest = hashlib.sha256(
            json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        receipt = coordinator.append_receipts(
            run_id,
            [
                {
                    "receipt_id": f"{run_id}:{stage['id']}:{attempt}",
                    "kind": "stage_started",
                    "stage_id": stage["id"],
                    "attempt": attempt,
                    "safe_summary": f"Matrix host started {stage['role']}.",
                },
                {
                    "receipt_id": f"{run_id}:{stage['id']}:{attempt}:completed",
                    "kind": "stage_completed",
                    "stage_id": stage["id"],
                    "attempt": attempt,
                    "output_digest": output_digest,
                    "safe_summary": f"Matrix host completed {stage['role']}.",
                },
            ],
            next_stage["control"]["revision"],
        )
        next_stage = coordinator.commit_stage(
            run_id,
            stage["id"],
            output,
            receipt["control"]["revision"],
            attempt=attempt,
        )
    result, events = coordinator.finalize(run_id, next_stage["control"]["revision"])
    conformance = evaluate_conformance(result, events, upstream_path=upstream_path)
    export = export_run_bundle(
        result,
        events,
        state_dir / "exports" / run_id,
        lifecycle_log=coordinator.lifecycle_log(run_id),
    )
    restarted_store = RunStore(state_dir)
    assert restarted_store.get_result(run_id) is not None
    validation = _lifecycle_smoke_validation(
        result,
        events,
        conformance,
        upstream_required=upstream_path is not None,
    )
    if not validation["passed"]:
        raise RuntimeError(f"lifecycle smoke validation failed: {json.dumps(validation, sort_keys=True)}")
    return {
        "symbol": symbol,
        "run_id": run_id,
        "signal": result.processed_signal,
        "stages": len(result.topology.stages),
        "events": len(events),
        "memory_entries": len(memory.recall(symbol).same_symbol),
        "exported_files": len(export.files),
        "lifecycle_smoke_passed": True,
        "lifecycle_validation": validation,
        "conformance": conformance.to_dict(),
        "restart_rehydrated": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", nargs="+", type=Path)
    parser.add_argument("--upstream-path", type=Path)
    parser.add_argument("--state-dir", type=Path, help="Keep durable run state instead of using a temporary tree")
    args = parser.parse_args()
    if args.state_dir is not None:
        summaries = [replay(path, args.state_dir, args.upstream_path) for path in args.submission]
    else:
        with tempfile.TemporaryDirectory(prefix="tradingagents-lifecycle-matrix-") as temporary:
            summaries = [replay(path, Path(temporary), args.upstream_path) for path in args.submission]
    print(json.dumps({"ok": True, "runs": summaries}, indent=2))


if __name__ == "__main__":
    main()
