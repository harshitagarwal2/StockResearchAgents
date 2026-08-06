"""Non-interactive CLI for standalone research workflows and result viewing."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .company_analytics import (
    get_company_research_quality,
    prepare_company_analytics,
    record_company_forecast_outcome,
    submit_company_analytics,
)
from .company_analytics_v1 import CompanyAnalyticsResultV1
from .company_lifecycle import (
    COMPANY_ANALYTICS_COORDINATOR,
    publication_lifecycle_run_id,
    require_completed_publication,
)
from .conformance import evaluate_validation, validation_digest
from .export import export_run_bundle
from .report_server import create_report_server, present_completed_run
from .research_quality_v1 import OutcomeObservation
from .semantics import build_completed_run_semantics
from .store import RUN_STORE, RunStore
from .view import build_run_view


def _add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    analytics_plan = commands.add_parser(
        "analytics-plan",
        help="Validate a company request and emit the complete company-analytics v1 workflow",
    )
    analytics_plan.add_argument("--input", required=True, help="CompanyResearchRequest JSON")
    analytics_plan.add_argument("--pack", default="initiating-coverage.v1", help="Versioned research pack ID")
    analytics_plan.add_argument(
        "--execution-mode",
        choices=("native", "sequential", "import"),
        default="sequential",
    )
    analytics_plan.add_argument("--output")

    analytics_import = commands.add_parser(
        "analytics-import",
        help="Validate and atomically publish a completed company-analytics-submission.v1 analytics bundle",
    )
    analytics_import.add_argument("--input", required=True, help="Complete company-analytics-submission.v1 JSON")
    analytics_import.add_argument("--output")
    analytics_import.add_argument("--report", action="store_true")
    analytics_import.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    analytics_import.add_argument("--port", default=8765, type=int)

    analytics_init = commands.add_parser(
        "analytics-init",
        help="Create a durable 26-stage company-analytics run for the calling harness",
    )
    analytics_init.add_argument("--input", required=True, help="CompanyResearchRequest JSON")
    analytics_init.add_argument("--pack", default="initiating-coverage.v1", help="Versioned research pack ID")
    analytics_init.add_argument(
        "--execution-mode",
        choices=("native", "sequential", "import"),
        default="sequential",
    )
    analytics_init.add_argument("--no-decision-memory", dest="decision_memory_enabled", action="store_false")
    analytics_init.add_argument("--output")

    quality_outcome = commands.add_parser(
        "quality-outcome",
        help="Append a resolved forecast outcome or correction and persist its scorecard",
    )
    quality_outcome.add_argument("--input", required=True, help="OutcomeObservation JSON")
    quality_outcome.add_argument("--output")

    quality_show = commands.add_parser(
        "quality-show",
        help="Show forecasts, append-only outcomes, and deterministic scorecards for a completed run",
    )
    quality_show.add_argument("run_id")
    quality_show.add_argument("--output")

    def revision_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("run_id")
        command.add_argument("--revision", required=True, type=int)
        command.add_argument("--output")
        return command

    revision_command("run-start", "Start a prepared durable analytics run")
    receipts = revision_command("run-receipts", "Append safe live stage/tool receipts")
    receipts.add_argument("--input", required=True, help="JSON array or object containing receipts")
    commit = revision_command("run-stage-commit", "Checkpoint one completed stage and get the next")
    commit.add_argument("stage_id")
    commit.add_argument("--input", required=True, help="Stage output JSON object")
    commit.add_argument("--attempt", type=int)
    pause = revision_command("run-pause", "Pause at the next analytics stage boundary")
    pause.add_argument("--reason", required=True)
    revision_command("run-resume", "Resume from the first incomplete stage boundary")
    revision_command("run-finalize", "Validate and publish the completed durable analytics result")

    control = commands.add_parser("run-control", help="Show durable run status, revision, checkpoint, and next stage")
    control.add_argument("run_id")
    control.add_argument("--output")
    events = commands.add_parser("run-events", help="Read lifecycle events after a monotonic cursor")
    events.add_argument("run_id")
    events.add_argument("--after", dest="after_sequence", type=int, default=0)
    events.add_argument("--limit", type=int, default=100)
    events.add_argument("--output")
    cancel = revision_command("run-cancel", "Request cooperative cancellation")
    cancel.add_argument("--reason", required=True)
    cancel_ack = revision_command("run-cancel-ack", "Acknowledge that the host stopped in-flight work")
    cancel_ack.add_argument("--execution-receipt-id", required=True)
    export = commands.add_parser("run-export", help="Write reports, result, events, logs, and a digest manifest")
    export.add_argument("run_id")
    export.add_argument("--destination", required=True)
    export.add_argument("--overwrite", action="store_true")
    export.add_argument("--output")
    validation = commands.add_parser(
        "run-validate",
        help="Validate the stored run against standalone result and event invariants",
    )
    validation.add_argument("run_id")
    validation.add_argument("--output")
    semantics = commands.add_parser(
        "run-semantics",
        help="Emit the canonical transport-neutral semantics of a completed run",
    )
    semantics.add_argument("run_id")
    semantics.add_argument("--output")

    memory_query = commands.add_parser("memory-query", help="Recall bounded same/cross-symbol decision memory")
    memory_query.add_argument("symbol")
    memory_query.add_argument("--same-symbol-limit", type=int, default=5)
    memory_query.add_argument("--cross-symbol-limit", type=int, default=3)
    memory_query.add_argument("--cutoff-at", help="Exact timezone-aware historical availability cutoff")
    memory_query.add_argument("--output")
    memory_outcome = commands.add_parser("memory-outcome", help="Append an externally observed outcome and reflection")
    target = memory_outcome.add_mutually_exclusive_group(required=True)
    target.add_argument("--memory-id")
    target.add_argument("--run-id")
    memory_outcome.add_argument("--input", required=True, help="JSON object with outcome, reflection, observed_at")
    memory_outcome.add_argument("--output")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-research-agents",
        description="Harness-neutral research capability; never an order executor.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    _add_commands(commands)

    viewer = commands.add_parser("report", help="Serve the completed Research Dossier Viewer on loopback")
    viewer.add_argument("--host", default="127.0.0.1")
    viewer.add_argument("--port", default=8765, type=int)
    return parser


def _emit(payload: dict[str, object], output: str | None = None) -> None:
    rendered = json.dumps(payload, default=str, indent=2)
    if output is None:
        print(rendered)
        return
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")
    print(f"Complete normalized result: {path.resolve()}")


def _completed_publication_payload(
    result: Any,
    events: tuple[Any, ...],
    *,
    store: RunStore | None = None,
    coordinator: Any = None,
    foreground_report: bool = False,
) -> dict[str, object]:
    """Return one generic completed result plus its presentation receipt."""
    publication_store = RUN_STORE if store is None else store
    presentation = present_completed_run(
        result.run_id,
        publication_store,
        coordinator=coordinator,
        mode="path_only" if foreground_report else None,
    )
    return {
        "ok": True,
        "result": result.to_dict(),
        "view": build_run_view(result, events).to_dict(),
        "events": [event.to_dict() for event in events],
        "presentation": presentation,
    }


def _serve_report(host: str, port: int, run_id: str | None = None) -> None:
    server = create_report_server(host, port)
    bound_host = str(server.server_address[0])
    bound_port = int(server.server_address[1])
    suffix = f"?run={run_id}" if run_id else ""
    print(f"StockResearchAgents Research Dossier Viewer: http://{bound_host}:{bound_port}/{suffix}")
    print("Final research projection only; not financial advice. Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _analytics_plan(args: argparse.Namespace) -> int:
    try:
        payload = _read_json(args.input)
        if not isinstance(payload, dict):
            raise ValueError("company analytics request root must be a JSON object")
        response = prepare_company_analytics(
            payload,
            research_pack_id=args.pack,
            execution_mode=args.execution_mode,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "invalid_company_analytics_request",
                    "message": str(exc),
                    "steps": [
                        "Use the CompanyResearchRequest contract and select a catalogued research pack.",
                        "Keep web sessions, provider credentials, raw documents, and experiment code in the host.",
                    ],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2
    _emit(response, args.output)
    return 0


def _analytics_import(args: argparse.Namespace) -> int:
    try:
        payload = _read_json(args.input)
        if not isinstance(payload, dict):
            raise ValueError("company analytics submission root must be a JSON object")
        result, events = submit_company_analytics(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "invalid_company_analytics_submission",
                    "message": str(exc),
                    "steps": [
                        "Generate and follow analytics-plan with the same research pack.",
                        "Submit the unchanged research dossier plus completed analytics, run-card, hypothesis, "
                        "and quality sidecars.",
                        "Do not include credentials, raw source bodies, generated executable code, or order fields.",
                    ],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2
    response = _completed_publication_payload(result, events, foreground_report=args.report)
    _emit(response, args.output)
    if args.report:
        _serve_report(args.host, args.port, result.run_id)
    return 0


def _quality_command(args: argparse.Namespace) -> int:
    try:
        if args.command == "quality-outcome":
            observation = OutcomeObservation.from_dict(_read_json(args.input))
            require_completed_publication(
                observation.forecast_id.split(".", 1)[0],
                RUN_STORE,
                COMPANY_ANALYTICS_COORDINATOR,
            )
            response = record_company_forecast_outcome(observation)
        else:
            run_id = require_completed_publication(args.run_id, RUN_STORE, COMPANY_ANALYTICS_COORDINATOR)
            response = get_company_research_quality(run_id)
        _emit(response, args.output)
        return 0
    except (KeyError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "research_quality_operation_failed",
                    "message": str(exc),
                    "steps": [
                        "Import the completed analytics publication before recording outcomes.",
                        "Corrections must append and supersede exactly the current active observation.",
                    ],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2


def _read_json(path: str) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _analytics_init(args: argparse.Namespace) -> int:
    try:
        payload = _read_json(args.input)
        if not isinstance(payload, dict):
            raise ValueError("company analytics request must be a JSON object")
        control = COMPANY_ANALYTICS_COORDINATOR.create(
            payload,
            research_pack_id=args.pack,
            decision_memory_enabled=args.decision_memory_enabled,
            execution_mode=args.execution_mode,
        )
        _emit({"ok": True, "control": control}, args.output)
        return 0
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "invalid_company_analytics_lifecycle_request",
                    "message": str(exc),
                    "steps": ["Validate the request and pack with analytics-plan; no provider API key is accepted."],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2


def _lifecycle_command(args: argparse.Namespace) -> int:
    try:
        coordinator = COMPANY_ANALYTICS_COORDINATOR
        if args.command == "run-start":
            response = coordinator.start(args.run_id, args.revision)
        elif args.command == "run-receipts":
            payload = _read_json(args.input)
            receipts = payload.get("receipts") if isinstance(payload, dict) else payload
            if not isinstance(receipts, list):
                raise ValueError("receipt input must be an array or an object containing a receipts array")
            response = coordinator.append_receipts(args.run_id, receipts, args.revision)
        elif args.command == "run-stage-commit":
            payload = _read_json(args.input)
            if not isinstance(payload, dict):
                raise ValueError("stage output input must be a JSON object")
            response = coordinator.commit_stage(
                args.run_id,
                args.stage_id,
                payload,
                args.revision,
                attempt=args.attempt,
            )
        elif args.command == "run-pause":
            response = {"ok": True, "control": coordinator.pause(args.run_id, args.revision, args.reason)}
        elif args.command == "run-resume":
            response = coordinator.resume(args.run_id, args.revision)
        elif args.command == "run-finalize":
            result, events = coordinator.finalize(args.run_id, args.revision)
            response = _completed_publication_payload(
                result,
                events,
                store=getattr(coordinator, "result_store", RUN_STORE),
                coordinator=coordinator,
            )
        elif args.command == "run-control":
            response = {"ok": True, "control": coordinator.control(args.run_id)}
        elif args.command == "run-events":
            response = coordinator.poll_events(
                args.run_id,
                after_sequence=args.after_sequence,
                limit=args.limit,
            )
        elif args.command == "run-cancel":
            response = {
                "ok": True,
                "control": coordinator.request_cancel(args.run_id, args.revision, args.reason),
            }
        elif args.command == "run-cancel-ack":
            response = {
                "ok": True,
                "control": coordinator.acknowledge_cancel(
                    args.run_id,
                    args.revision,
                    args.execution_receipt_id,
                ),
            }
        elif args.command == "run-export":
            run_id = require_completed_publication(args.run_id, RUN_STORE, coordinator)
            export_result = RUN_STORE.get_result(run_id)
            export_events = RUN_STORE.get_events(run_id)
            if not isinstance(export_result, CompanyAnalyticsResultV1) or export_events is None:
                raise ValueError(f"completed run not found: {run_id}")
            lifecycle_run_id = publication_lifecycle_run_id(export_events)
            if lifecycle_run_id is not None:
                try:
                    lifecycle_log = coordinator.lifecycle_log(lifecycle_run_id)
                except KeyError:
                    lifecycle_log = ()
            else:
                lifecycle_log = ()
            export_receipt = export_run_bundle(
                export_result,
                export_events,
                args.destination,
                lifecycle_log=lifecycle_log,
                overwrite=args.overwrite,
            )
            response = {"ok": True, "export": export_receipt.to_dict()}
        elif args.command == "run-validate":
            run_id = require_completed_publication(args.run_id, RUN_STORE, coordinator)
            validation_result = RUN_STORE.get_result(run_id)
            validation_events = RUN_STORE.get_events(run_id)
            if not isinstance(validation_result, CompanyAnalyticsResultV1) or validation_events is None:
                raise ValueError(f"completed run not found: {run_id}")
            report = evaluate_validation(validation_result, validation_events)
            response = {
                "ok": report.passed,
                "validation": report.to_dict(),
                "digest": validation_digest(report),
            }
        elif args.command == "run-semantics":
            run_id = require_completed_publication(args.run_id, RUN_STORE, coordinator)
            semantics_result = RUN_STORE.get_result(run_id)
            semantics_events = RUN_STORE.get_events(run_id)
            if not isinstance(semantics_result, CompanyAnalyticsResultV1) or semantics_events is None:
                raise ValueError(f"completed run not found: {run_id}")
            response = build_completed_run_semantics(semantics_result, semantics_events).to_dict()
        elif args.command == "memory-query":
            recall = coordinator.decision_memory().recall(
                args.symbol,
                same_symbol_limit=args.same_symbol_limit,
                cross_symbol_limit=args.cross_symbol_limit,
                cutoff_at=args.cutoff_at,
            )
            response = {"ok": True, "recall": recall.to_dict()}
        elif args.command == "memory-outcome":
            payload = _read_json(args.input)
            if not isinstance(payload, dict) or "outcome" not in payload or "reflection" not in payload:
                raise ValueError("memory outcome input must contain outcome and reflection")
            memory_receipt = coordinator.decision_memory().append_outcome(
                outcome=payload["outcome"],
                reflection=payload["reflection"],
                memory_id=args.memory_id,
                run_id=args.run_id,
                observed_at=payload.get("observed_at"),
            )
            response = {"ok": True, "memory_receipt": memory_receipt.to_dict()}
        else:  # pragma: no cover - dispatch is constrained by argparse
            raise ValueError(f"unsupported lifecycle command: {args.command}")
        _emit(response, args.output)
        return 0
    except (KeyError, OSError, json.JSONDecodeError, RuntimeError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "lifecycle_operation_failed",
                    "message": str(exc),
                    "steps": ["Refresh run-control, use its current revision, and retry the safe operation."],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "analytics-plan":
        return _analytics_plan(args)

    if args.command == "analytics-import":
        return _analytics_import(args)

    if args.command in {"quality-outcome", "quality-show"}:
        return _quality_command(args)

    if args.command == "analytics-init":
        return _analytics_init(args)

    lifecycle_commands = {
        "run-start",
        "run-receipts",
        "run-stage-commit",
        "run-pause",
        "run-resume",
        "run-finalize",
        "run-control",
        "run-events",
        "run-cancel",
        "run-cancel-ack",
        "run-export",
        "run-validate",
        "run-semantics",
        "memory-query",
        "memory-outcome",
    }
    if args.command in lifecycle_commands:
        return _lifecycle_command(args)

    _serve_report(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
