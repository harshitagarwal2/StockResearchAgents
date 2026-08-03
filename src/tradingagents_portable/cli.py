"""Non-interactive CLI for fixture, upstream research, and final-result UI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from .contracts import RunRequest
from .dashboard import create_dashboard_server
from .errors import CapabilitySetupError
from .fixture import run_fixture
from .legacy import LegacyTradingAgentsAdapter
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
    bound_host, bound_port = server.server_address[:2]
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

    if args.fixture:
        run_fixture(RunRequest(as_of_date=args.as_of_date))
    _serve_dashboard(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
