"""Replay completed host submissions through every durable lifecycle boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from tradingrearchagents.conformance import evaluate_conformance
from tradingrearchagents.contracts import RunRequest, StageKind
from tradingrearchagents.export import export_run_bundle
from tradingrearchagents.lifecycle import HostRunCoordinator, LifecycleStore
from tradingrearchagents.memory import DecisionMemoryStore
from tradingrearchagents.store import RunStore


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
    assert conformance.passed
    return {
        "symbol": symbol,
        "run_id": run_id,
        "signal": result.processed_signal,
        "stages": len(result.topology.stages),
        "events": len(events),
        "memory_entries": len(memory.recall(symbol).same_symbol),
        "exported_files": len(export.files),
        "conformance": conformance.passed,
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
