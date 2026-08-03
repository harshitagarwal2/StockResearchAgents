"""Non-interactive CLI for fixture, upstream research, and final-result UI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from .conformance import conformance_digest, evaluate_conformance
from .contracts import RunRequest
from .dashboard import create_dashboard_server
from .errors import CapabilitySetupError
from .export import export_run_bundle
from .fixture import run_fixture
from .host_native import prepare_host_run, submit_host_run
from .legacy import LegacyTradingAgentsAdapter
from .lifecycle import HOST_RUN_COORDINATOR, is_lifecycle_run_id
from .view import build_run_view


def _add_research_command(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    research = commands.add_parser(
        "research",
        help="Research any upstream-supported market symbol through TradingAgentsGraph",
        description=(
            "Run the complete upstream TradingAgentsGraph non-interactively. SUBJECT follows the upstream CLI's "
            "Yahoo-style symbol format (for example AAPL, 0700.HK, ^GSPC, EURUSD=X, GC=F, or BTC-USD). "
            "Provider credentials are read only from the environment."
        ),
    )
    research.add_argument("subject", help="Company/instrument market symbol")
    research.add_argument("--date", dest="as_of_date", default=date.today().isoformat())
    research.add_argument("--asset-type", choices=("auto", "stock", "crypto"), default="auto")
    research.add_argument(
        "--analyst",
        action="append",
        dest="analysts",
        choices=("market", "social", "news", "fundamentals"),
        help="Repeat to select analysts; defaults to all compatible analysts",
    )
    research.add_argument("--debate-rounds", type=int, default=None)
    research.add_argument("--risk-rounds", type=int, default=None)
    research.add_argument("--provider", dest="llm_provider")
    research.add_argument("--quick-model", dest="quick_think_llm")
    research.add_argument("--deep-model", dest="deep_think_llm")
    research.add_argument("--backend-url")
    research.add_argument("--output-language")
    research.add_argument("--temperature", type=float)
    research.add_argument("--max-retries", dest="llm_max_retries", type=int)
    research.add_argument("--google-thinking-level")
    research.add_argument("--reasoning-effort", dest="openai_reasoning_effort")
    research.add_argument("--anthropic-effort")
    checkpoint = research.add_mutually_exclusive_group()
    checkpoint.add_argument("--checkpoint", dest="checkpoint_enabled", action="store_true")
    checkpoint.add_argument("--no-checkpoint", dest="checkpoint_enabled", action="store_false")
    research.set_defaults(checkpoint_enabled=None)
    research.add_argument(
        "--clear-checkpoints",
        action="store_true",
        help="Delegate upstream cleanup of all checkpoint files in its configured cache directory, then exit",
    )
    research.add_argument("--legacy-path", help="Upstream TradingAgents checkout/package root")
    research.add_argument("--report-output", help="Write the upstream markdown report tree to this path")
    research.add_argument("--output", help="Write the complete normalized JSON result to this file instead of stdout")
    research.add_argument(
        "--dashboard",
        action="store_true",
        help="After completion, serve the stored final result on a read-only loopback dashboard",
    )
    research.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    research.add_argument("--port", default=8765, type=int)


def _add_host_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    plan = commands.add_parser(
        "host-plan",
        help="Emit a credential-free workflow plan for the active agent harness",
    )
    plan.add_argument("subject", help="Company/instrument market symbol")
    plan.add_argument("--date", dest="as_of_date", default=date.today().isoformat())
    plan.add_argument("--asset-type", choices=("stock", "crypto"), default="stock")
    plan.add_argument(
        "--analyst",
        action="append",
        dest="analysts",
        choices=("market", "social", "news", "fundamentals"),
    )
    plan.add_argument("--debate-rounds", type=int, default=1)
    plan.add_argument("--risk-rounds", type=int, default=1)
    plan.add_argument("--output-language", default="English")
    plan.add_argument("--output")

    host_import = commands.add_parser(
        "host-import",
        help="Validate completed host stage outputs and publish the final dossier",
    )
    host_import.add_argument("--input", required=True, help="Complete host-native JSON submission")
    host_import.add_argument("--output", help="Write the complete normalized JSON response")
    host_import.add_argument(
        "--dashboard",
        action="store_true",
        help="After successful import, serve only the completed dossier on loopback",
    )
    host_import.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    host_import.add_argument("--port", default=8765, type=int)

    host_init = commands.add_parser(
        "host-init",
        help="Create a durable credential-free run for this host harness",
    )
    host_init.add_argument("subject", nargs="?", help="Company/instrument market symbol")
    host_init.add_argument("--date", dest="as_of_date", default=date.today().isoformat())
    host_init.add_argument("--asset-type", choices=("stock", "crypto"), default="stock")
    host_init.add_argument(
        "--analyst",
        action="append",
        dest="analysts",
        choices=("market", "social", "news", "fundamentals"),
    )
    host_init.add_argument("--debate-rounds", type=int, default=1)
    host_init.add_argument("--risk-rounds", type=int, default=1)
    host_init.add_argument("--output-language", default="English")
    host_init.add_argument("--no-decision-memory", dest="decision_memory_enabled", action="store_false")
    host_init.add_argument("--interactive", action="store_true")
    host_init.add_argument("--output")

    def revision_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("run_id")
        command.add_argument("--revision", required=True, type=int)
        command.add_argument("--output")
        return command

    revision_command("host-start", "Start a prepared durable host run")
    receipts = revision_command("host-receipts", "Append safe live stage/tool receipts")
    receipts.add_argument("--input", required=True, help="JSON array or object containing receipts")
    commit = revision_command("host-stage-commit", "Checkpoint one completed stage and get the next")
    commit.add_argument("stage_id")
    commit.add_argument("--input", required=True, help="Stage output JSON object")
    commit.add_argument("--attempt", type=int)
    pause = revision_command("host-pause", "Pause at the next portable stage boundary")
    pause.add_argument("--reason", required=True)
    revision_command("host-resume", "Resume from the first incomplete stage boundary")
    revision_command("host-finalize", "Validate and publish the completed durable dossier")

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
    cancel_ack.add_argument("--host-receipt-id", required=True)
    export = commands.add_parser("run-export", help="Write reports, result, events, logs, and a digest manifest")
    export.add_argument("run_id")
    export.add_argument("--destination", required=True)
    export.add_argument("--overwrite", action="store_true")
    export.add_argument("--output")
    conformance = commands.add_parser(
        "run-conformance",
        help="Validate portable invariants and optionally verify pinned upstream checkout identity",
    )
    conformance.add_argument("run_id")
    conformance.add_argument("--upstream-path")
    conformance.add_argument("--output")

    memory_query = commands.add_parser("memory-query", help="Recall bounded same/cross-symbol decision memory")
    memory_query.add_argument("symbol")
    memory_query.add_argument("--same-symbol-limit", type=int, default=5)
    memory_query.add_argument("--cross-symbol-limit", type=int, default=3)
    memory_query.add_argument("--output")
    memory_outcome = commands.add_parser("memory-outcome", help="Append a host-observed outcome and reflection")
    target = memory_outcome.add_mutually_exclusive_group(required=True)
    target.add_argument("--memory-id")
    target.add_argument("--run-id")
    memory_outcome.add_argument("--input", required=True, help="JSON object with outcome, reflection, observed_at")
    memory_outcome.add_argument("--output")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tradingagents-portable",
        description="Harness-neutral research capability; never an order executor.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture", help="Run the deterministic ORCL fixture")
    fixture.add_argument("--date", default="2026-07-03", dest="as_of_date")
    fixture.add_argument("--analyst", action="append", dest="analysts")
    fixture.add_argument("--debate-rounds", type=int, default=1)
    fixture.add_argument("--risk-rounds", type=int, default=1)
    fixture.add_argument("--events", action="store_true", help="Include rich events in JSON output")

    _add_research_command(commands)
    _add_host_commands(commands)

    dashboard = commands.add_parser("dashboard", help="Serve the packaged dossier and JSON APIs on loopback")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", default=8765, type=int)
    dashboard.add_argument("--fixture", action="store_true", help="Seed the default ORCL fixture before serving")
    dashboard.add_argument("--date", default="2026-07-03", dest="as_of_date")
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


def _serve_dashboard(host: str, port: int, run_id: str | None = None) -> None:
    server = create_dashboard_server(host, port)
    bound_host = str(server.server_address[0])
    bound_port = int(server.server_address[1])
    suffix = f"?run={run_id}" if run_id else ""
    print(f"TradingAgents Portable dashboard: http://{bound_host}:{bound_port}/{suffix}")
    print("Final research projection only; not financial advice. Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _research(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    adapter = LegacyTradingAgentsAdapter(args.legacy_path)
    if args.clear_checkpoints:
        try:
            cleared = adapter.clear_checkpoints()
        except CapabilitySetupError as exc:
            _emit(exc.to_dict(), args.output)
            return 2
        _emit({"ok": True, "cleared_checkpoints": cleared}, args.output)
        return 0

    try:
        canonical_symbol, asset_type = adapter.resolve_subject(args.subject, args.asset_type)
        defaults = adapter.defaults()
        as_of = date.fromisoformat(args.as_of_date)
        if as_of > date.today():
            parser.error("research date cannot be in the future")
        default_analysts = (
            ("market", "social", "news") if asset_type == "crypto" else ("market", "social", "news", "fundamentals")
        )
        analysts = tuple(args.analysts or default_analysts)
        public_config: dict[str, Any] = {
            key: value
            for key, value in {
                "llm_provider": args.llm_provider,
                "quick_think_llm": args.quick_think_llm,
                "deep_think_llm": args.deep_think_llm,
                "backend_url": args.backend_url,
                "output_language": args.output_language,
                "temperature": args.temperature,
                "llm_max_retries": args.llm_max_retries,
                "google_thinking_level": args.google_thinking_level,
                "openai_reasoning_effort": args.openai_reasoning_effort,
                "anthropic_effort": args.anthropic_effort,
                "report_output_path": args.report_output,
            }.items()
            if value is not None
        }
        request = RunRequest(
            symbol=canonical_symbol,
            as_of_date=args.as_of_date,
            asset_type=asset_type,
            analysts=analysts,
            debate_rounds=(
                args.debate_rounds if args.debate_rounds is not None else int(defaults["max_debate_rounds"])
            ),
            risk_rounds=args.risk_rounds if args.risk_rounds is not None else int(defaults["max_risk_discuss_rounds"]),
            executor="legacy",
            checkpoint_enabled=(
                args.checkpoint_enabled
                if args.checkpoint_enabled is not None
                else bool(defaults.get("checkpoint_enabled", False))
            ),
            legacy_config=public_config,
        )
        result, events = adapter.run(request)
    except CapabilitySetupError as exc:
        _emit(exc.to_dict(), args.output)
        return 2
    except (KeyError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "invalid_research_setup",
                    "message": str(exc),
                    "steps": ["Check the symbol, date, upstream path, and non-secret model/provider options."],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "upstream_execution_failed",
                    "message": f"Upstream TradingAgents execution failed ({type(exc).__name__}).",
                    "steps": [
                        "Verify the selected LLM and data-provider credentials are present in the environment.",
                        "Verify the upstream package and provider SDKs are installed in this Python environment.",
                        "Retry with the same non-secret CLI configuration after correcting the runtime setup.",
                    ],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 1

    payload = {
        "ok": True,
        "result": result.to_dict(),
        "view": build_run_view(result, events).to_dict(),
        "events": [event.to_dict() for event in events],
    }
    _emit(payload, args.output)
    if args.dashboard:
        _serve_dashboard(args.host, args.port, result.run_id)
    return 0


def _host_plan(args: argparse.Namespace) -> int:
    default_analysts = (
        ("market", "social", "news") if args.asset_type == "crypto" else ("market", "social", "news", "fundamentals")
    )
    try:
        request = RunRequest(
            symbol=args.subject,
            as_of_date=args.as_of_date,
            asset_type=args.asset_type,
            analysts=tuple(args.analysts or default_analysts),
            debate_rounds=args.debate_rounds,
            risk_rounds=args.risk_rounds,
            output_language=args.output_language,
            executor="host_native",
        )
    except (TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "invalid_host_request",
                    "message": str(exc),
                    "steps": [
                        "Use a valid market symbol and an ISO analysis date no later than today.",
                        "Select one or more supported analysts and between 1 and 10 debate rounds.",
                    ],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2
    _emit(prepare_host_run(request), args.output)
    return 0


def _host_import(args: argparse.Namespace) -> int:
    try:
        source = Path(args.input).expanduser()
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("host-native submission root must be a JSON object")
        result, events = submit_host_run(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "invalid_host_submission",
                    "message": str(exc),
                    "steps": [
                        "Generate the canonical plan with host-plan.",
                        "Submit every configured analyst, debate, manager, trader, risk, and portfolio output.",
                        "Do not include API keys, tokens, passwords, provider config, "
                        "or executable trade instructions.",
                    ],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2
    response = {
        "ok": True,
        "result": result.to_dict(),
        "view": build_run_view(result, events).to_dict(),
        "events": [event.to_dict() for event in events],
    }
    _emit(response, args.output)
    if args.dashboard:
        _serve_dashboard(args.host, args.port, result.run_id)
    return 0


def _read_json(path: str) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _interactive_host_values(args: argparse.Namespace) -> None:
    default_symbol = args.subject or "ORCL"
    args.subject = input(f"Symbol [{default_symbol}]: ").strip() or default_symbol
    args.as_of_date = input(f"Analysis date [{args.as_of_date}]: ").strip() or args.as_of_date
    args.asset_type = input(f"Asset type stock/crypto [{args.asset_type}]: ").strip() or args.asset_type
    default_analysts = "market,social,news" + (",fundamentals" if args.asset_type == "stock" else "")
    selected = input(f"Analysts, comma-separated [{default_analysts}]: ").strip() or default_analysts
    args.analysts = [item.strip() for item in selected.split(",") if item.strip()]
    debate = input(f"Research debate rounds [{args.debate_rounds}]: ").strip()
    risk = input(f"Risk debate rounds [{args.risk_rounds}]: ").strip()
    language = input(f"Output language [{args.output_language}]: ").strip()
    args.debate_rounds = int(debate) if debate else args.debate_rounds
    args.risk_rounds = int(risk) if risk else args.risk_rounds
    args.output_language = language or args.output_language


def _host_init(args: argparse.Namespace) -> int:
    try:
        if args.interactive:
            _interactive_host_values(args)
        if not args.subject:
            raise ValueError("subject is required unless --interactive is used")
        default_analysts = (
            ("market", "social", "news")
            if args.asset_type == "crypto"
            else ("market", "social", "news", "fundamentals")
        )
        request = RunRequest(
            symbol=args.subject,
            as_of_date=args.as_of_date,
            asset_type=args.asset_type,
            analysts=tuple(args.analysts or default_analysts),
            debate_rounds=args.debate_rounds,
            risk_rounds=args.risk_rounds,
            output_language=args.output_language,
            executor="host_native",
        )
        control = HOST_RUN_COORDINATOR.create(
            request,
            decision_memory_enabled=args.decision_memory_enabled,
        )
        _emit({"ok": True, "control": control}, args.output)
        return 0
    except (EOFError, OSError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "guidance": {
                    "code": "invalid_lifecycle_request",
                    "message": str(exc),
                    "steps": ["Check the portable request fields; no provider API key is accepted."],
                    "retryable": True,
                },
            },
            args.output,
        )
        return 2


def _publication_control(run_id: str) -> dict[str, object] | None:
    if not is_lifecycle_run_id(run_id):
        return None
    try:
        return HOST_RUN_COORDINATOR.control(run_id)
    except KeyError:
        return None


def _lifecycle_command(args: argparse.Namespace) -> int:
    try:
        if args.command == "host-start":
            response = HOST_RUN_COORDINATOR.start(args.run_id, args.revision)
        elif args.command == "host-receipts":
            payload = _read_json(args.input)
            receipts = payload.get("receipts") if isinstance(payload, dict) else payload
            if not isinstance(receipts, list):
                raise ValueError("receipt input must be an array or an object containing a receipts array")
            response = HOST_RUN_COORDINATOR.append_receipts(args.run_id, receipts, args.revision)
        elif args.command == "host-stage-commit":
            payload = _read_json(args.input)
            if not isinstance(payload, dict):
                raise ValueError("stage output input must be a JSON object")
            response = HOST_RUN_COORDINATOR.commit_stage(
                args.run_id,
                args.stage_id,
                payload,
                args.revision,
                attempt=args.attempt,
            )
        elif args.command == "host-pause":
            response = {"ok": True, "control": HOST_RUN_COORDINATOR.pause(args.run_id, args.revision, args.reason)}
        elif args.command == "host-resume":
            response = HOST_RUN_COORDINATOR.resume(args.run_id, args.revision)
        elif args.command == "host-finalize":
            result, events = HOST_RUN_COORDINATOR.finalize(args.run_id, args.revision)
            response = {
                "ok": True,
                "result": result.to_dict(),
                "events": [event.to_dict() for event in events],
                "view": build_run_view(result, events).to_dict(),
                "dashboard_path": f"/?run={result.run_id}",
            }
        elif args.command == "run-control":
            response = {"ok": True, "control": HOST_RUN_COORDINATOR.control(args.run_id)}
        elif args.command == "run-events":
            response = HOST_RUN_COORDINATOR.poll_events(
                args.run_id,
                after_sequence=args.after_sequence,
                limit=args.limit,
            )
        elif args.command == "run-cancel":
            response = {
                "ok": True,
                "control": HOST_RUN_COORDINATOR.request_cancel(args.run_id, args.revision, args.reason),
            }
        elif args.command == "run-cancel-ack":
            response = {
                "ok": True,
                "control": HOST_RUN_COORDINATOR.acknowledge_cancel(
                    args.run_id,
                    args.revision,
                    args.host_receipt_id,
                ),
            }
        elif args.command == "run-export":
            publication_control = _publication_control(args.run_id)
            if publication_control is not None and (
                publication_control["status"] != "completed" or publication_control["publication_pending"]
            ):
                raise ValueError(f"run publication is not complete: {args.run_id}")
            export_result = HOST_RUN_COORDINATOR.result_store.get_result(args.run_id)
            export_events = HOST_RUN_COORDINATOR.result_store.get_events(args.run_id)
            if export_result is None or export_events is None:
                raise ValueError(f"completed run not found: {args.run_id}")
            if is_lifecycle_run_id(args.run_id):
                try:
                    lifecycle_log = HOST_RUN_COORDINATOR.lifecycle_log(args.run_id)
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
        elif args.command == "run-conformance":
            publication_control = _publication_control(args.run_id)
            if publication_control is not None and (
                publication_control["status"] != "completed" or publication_control["publication_pending"]
            ):
                raise ValueError(f"run publication is not complete: {args.run_id}")
            conformance_result = HOST_RUN_COORDINATOR.result_store.get_result(args.run_id)
            conformance_events = HOST_RUN_COORDINATOR.result_store.get_events(args.run_id)
            if conformance_result is None or conformance_events is None:
                raise ValueError(f"completed run not found: {args.run_id}")
            report = evaluate_conformance(
                conformance_result,
                conformance_events,
                upstream_path=args.upstream_path,
            )
            response = {
                "ok": report.passed,
                "conformance": report.to_dict(),
                "digest": conformance_digest(report),
            }
        elif args.command == "memory-query":
            recall = HOST_RUN_COORDINATOR.decision_memory().recall(
                args.symbol,
                same_symbol_limit=args.same_symbol_limit,
                cross_symbol_limit=args.cross_symbol_limit,
            )
            response = {"ok": True, "recall": recall.to_dict()}
        elif args.command == "memory-outcome":
            payload = _read_json(args.input)
            if not isinstance(payload, dict) or "outcome" not in payload or "reflection" not in payload:
                raise ValueError("memory outcome input must contain outcome and reflection")
            memory_receipt = HOST_RUN_COORDINATOR.decision_memory().append_outcome(
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
    if args.command == "fixture":
        request = RunRequest(
            as_of_date=args.as_of_date,
            analysts=tuple(args.analysts or ("market", "social", "news", "fundamentals")),
            debate_rounds=args.debate_rounds,
            risk_rounds=args.risk_rounds,
        )
        result, events = run_fixture(request)
        payload: dict[str, object] = {"ok": True, "result": result.to_dict()}
        if args.events:
            payload["events"] = [event.to_dict() for event in events]
        _emit(payload)
        return 0

    if args.command == "research":
        return _research(args, parser)

    if args.command == "host-plan":
        return _host_plan(args)

    if args.command == "host-import":
        return _host_import(args)

    if args.command == "host-init":
        return _host_init(args)

    lifecycle_commands = {
        "host-start",
        "host-receipts",
        "host-stage-commit",
        "host-pause",
        "host-resume",
        "host-finalize",
        "run-control",
        "run-events",
        "run-cancel",
        "run-cancel-ack",
        "run-export",
        "run-conformance",
        "memory-query",
        "memory-outcome",
    }
    if args.command in lifecycle_commands:
        return _lifecycle_command(args)

    if args.command == "dashboard" and args.fixture:
        run_fixture(RunRequest(as_of_date=args.as_of_date))
    _serve_dashboard(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
