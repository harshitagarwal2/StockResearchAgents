"""Optional thin adapter over upstream TradingAgentsGraph.

No upstream business logic is copied here. Imports and filesystem-producing
legacy behavior occur only after an explicit ``run`` call.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import (
    EventKind,
    RunEvent,
    RunRequest,
    RunResult,
    SetupGuidance,
)
from .errors import CapabilitySetupError
from .projection import LegacyStateProjector
from .store import RUN_STORE, RunStore
from .topology import build_legacy_topology


def _stage_output_observed(stage_id: str, result: RunResult) -> bool:
    """Return whether the frozen legacy state contains output for a logical stage."""
    if stage_id.startswith("analyst."):
        analyst = stage_id.removeprefix("analyst.")
        return any(report.analyst == analyst and bool(report.content) for report in result.analyst_reports)
    if stage_id.startswith("research.") and stage_id != "research.manager":
        role = stage_id.rsplit(".", 1)[-1]
        return bool(result.research_debate_snapshot.role_histories.get(role))
    if stage_id == "research.manager":
        return bool(result.investment_plan)
    if stage_id == "trader":
        return bool(result.trader_investment_plan)
    if stage_id.startswith("risk."):
        role = stage_id.rsplit(".", 1)[-1]
        snapshot = result.risk_debate_snapshot
        return bool(snapshot.role_histories.get(role) or snapshot.current_responses.get(role))
    if stage_id == "portfolio":
        return bool(result.portfolio_manager_decision or result.final_trade_decision)
    return False


class LegacyTradingAgentsAdapter:
    def __init__(self, legacy_path: str | None = None, store: RunStore = RUN_STORE):
        self.legacy_path = legacy_path or os.environ.get("TRADINGAGENTS_LEGACY_PATH")
        self.store = store

    def _activate_legacy_path(self) -> None:
        if self.legacy_path:
            root = Path(self.legacy_path).expanduser().resolve()
            if not (root / "tradingagents").is_dir():
                raise self._setup_error(f"Configured legacy path does not contain tradingagents/: {root}")
            root_string = str(root)
            if root_string not in sys.path:
                sys.path.insert(0, root_string)

    def _load(self) -> tuple[type[Any], dict[str, Any]]:
        self._activate_legacy_path()
        try:
            graph_module = importlib.import_module("tradingagents.graph.trading_graph")
            config_module = importlib.import_module("tradingagents.default_config")
        except (ImportError, ModuleNotFoundError) as exc:
            raise self._setup_error(f"TradingAgentsGraph could not be imported: {exc}") from exc
        return graph_module.TradingAgentsGraph, dict(config_module.DEFAULT_CONFIG)

    def defaults(self) -> dict[str, Any]:
        """Return upstream defaults after its normal environment overlay."""
        _, defaults = self._load()
        return defaults

    def resolve_subject(self, subject: str, asset_type: str = "auto") -> tuple[str, str]:
        """Apply the same canonical-symbol and crypto detection boundary as upstream CLI."""
        self._activate_legacy_path()
        raw = subject.strip()
        try:
            symbol_module = importlib.import_module("tradingagents.dataflows.symbol_utils")
            canonical = str(symbol_module.normalize_symbol(raw))
        except Exception:
            canonical = raw.upper()
        resolved_type = asset_type
        if asset_type == "auto":
            resolved_type = "crypto" if canonical.endswith(("-USD", "-USDT", "-USDC", "-BTC", "-ETH")) else "stock"
        if resolved_type not in {"stock", "crypto"}:
            raise ValueError("asset_type must be 'auto', 'stock', or 'crypto'")
        return canonical, resolved_type

    def clear_checkpoints(self) -> int:
        """Delegate the upstream CLI's scoped checkpoint cleanup helper."""
        defaults = self.defaults()
        try:
            module = importlib.import_module("tradingagents.graph.checkpointer")
            clear_all = module.clear_all_checkpoints
        except (ImportError, ModuleNotFoundError, AttributeError) as exc:
            raise self._setup_error(f"Upstream checkpoint cleanup is unavailable: {exc}") from exc
        return int(clear_all(defaults["data_cache_dir"]))

    @staticmethod
    def _setup_error(message: str) -> CapabilitySetupError:
        return CapabilitySetupError(
            SetupGuidance(
                message=message,
                steps=(
                    "Install the upstream TradingAgents package, or set "
                    "TRADINGAGENTS_LEGACY_PATH to its repository root.",
                    "Configure the upstream LLM/data-provider credentials required by its selected config.",
                    "Pass legacy_config explicitly for any provider or output-directory overrides.",
                    "Enable checkpoint_enabled only when resume behavior is intentionally requested.",
                ),
                retryable=True,
            )
        )

    def run(self, request: RunRequest) -> tuple[RunResult, tuple[RunEvent, ...]]:
        graph_class, defaults = self._load()
        request = replace(request, executor="legacy")
        report_output = request.legacy_config.get("report_output_path")
        adapter_config = {key: value for key, value in request.legacy_config.items() if key != "report_output_path"}
        config = {**defaults, **adapter_config}
        # Preserve upstream's distinction: decision/report persistence may occur,
        # but checkpoint resume is never implied and remains explicit opt-in.
        config["checkpoint_enabled"] = bool(request.checkpoint_enabled)
        config["max_debate_rounds"] = request.debate_rounds
        config["max_risk_discuss_rounds"] = request.risk_rounds
        graph = graph_class(
            selected_analysts=request.analysts,
            debug=False,
            config=config,
            callbacks=None,
        )
        started = datetime.now(UTC)
        final_state, signal = graph.propagate(
            request.symbol,
            request.as_of_date,
            asset_type=request.asset_type,
        )
        if report_output:
            graph.save_reports(final_state, request.symbol, save_path=report_output)
        completed = datetime.now(UTC)
        run_id = "legacy-" + uuid4().hex[:12]
        topology = build_legacy_topology(request.analysts, request.debate_rounds, request.risk_rounds)
        result = LegacyStateProjector().project(
            run_id=run_id,
            request=request,
            final_state=final_state,
            processed_signal=signal,
            config=config,
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            report_output_path=str(report_output) if report_output else None,
        )
        events: list[RunEvent] = [
            RunEvent(
                id=f"{run_id}:0001",
                run_id=run_id,
                sequence=1,
                timestamp=started.isoformat(),
                kind=EventKind.RUN,
                status="running",
                message="Legacy TradingAgentsGraph execution started.",
                data={"checkpoint_enabled": request.checkpoint_enabled},
            )
        ]
        for index, stage in enumerate(topology.stages, start=2):
            observed = _stage_output_observed(stage.id, result)
            events.append(
                RunEvent(
                    id=f"{run_id}:{index:04d}",
                    run_id=run_id,
                    sequence=index,
                    timestamp=completed.isoformat(),
                    kind=EventKind.STAGE,
                    stage_id=stage.id,
                    status="completed" if observed else "unobserved",
                    message=(
                        f"{stage.role} output observed in completed legacy graph state."
                        if observed
                        else f"{stage.role} output was not observable in completed legacy graph state."
                    ),
                    data={"observability": "post_run_projection", "output_observed": observed},
                )
            )
        events.append(
            RunEvent(
                id=f"{run_id}:{len(events) + 1:04d}",
                run_id=run_id,
                sequence=len(events) + 1,
                timestamp=completed.isoformat(),
                kind=EventKind.RUN,
                status="completed",
                message="Legacy TradingAgentsGraph execution completed.",
            )
        )
        frozen = tuple(events)
        self.store.put(result, frozen)
        return result, frozen
