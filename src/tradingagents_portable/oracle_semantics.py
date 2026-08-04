"""Credential-free semantic differential against the pinned upstream checkout.

The oracle intentionally probes only stable, observable contracts.  It never
constructs an upstream graph, model client, provider client, or browser session.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import subprocess
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal, get_args, get_type_hints

from .conformance import PINNED_UPSTREAM_REVISION, upstream_revision
from .contracts import PortfolioDecision, ReportSections, ResearchDecision, TraderDecision
from .instruments import normalize_instrument_symbol
from .topology import build_legacy_topology

ORACLE_PROJECTION_SCHEMA = "tradingagents.observable-projection.v1"
ORACLE_REPORT_SCHEMA = "tradingagents.semantic-differential.v1"

_REPORT_FIELDS = ("market_report", "sentiment_report", "news_report", "fundamentals_report")
_RESEARCH_FIELDS = ("recommendation", "rationale", "strategic_actions")
_TRADER_FIELDS = ("action", "reasoning", "entry_price", "stop_loss", "position_sizing")
_PORTFOLIO_FIELDS = ("rating", "executive_summary", "investment_thesis", "price_target", "time_horizon")


@dataclass(frozen=True, slots=True)
class OracleCase:
    case_id: str
    analysts: tuple[str, ...]
    debate_rounds: int
    risk_rounds: int
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id or not self.analysts or not self.symbols:
            raise ValueError("oracle cases require an ID, analysts, and symbols")
        if len(set(self.analysts)) != len(self.analysts):
            raise ValueError("oracle analysts must be unique")
        if self.debate_rounds < 1 or self.risk_rounds < 1:
            raise ValueError("oracle round counts must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "analysts": list(self.analysts),
            "debate_rounds": self.debate_rounds,
            "risk_rounds": self.risk_rounds,
            "symbols": list(self.symbols),
        }


DEFAULT_ORACLE_CASES = (
    OracleCase(
        "full-one-round",
        ("market", "social", "news", "fundamentals"),
        1,
        1,
        ("ORCL", "QQQ", "BTCUSD", "EURUSD", "XAUUSD"),
    ),
    OracleCase("reordered-two-rounds", ("news", "market", "fundamentals"), 2, 2, ("META", "ETHUSDT")),
    OracleCase("minimal", ("fundamentals",), 1, 1, ("ACME",)),
)


@dataclass(frozen=True, slots=True)
class ObservableProjectionV1:
    implementation: Literal["upstream", "portable"]
    revision: str
    case_id: str
    selected_analysts: tuple[str, ...]
    normalized_symbols: dict[str, str]
    stage_ids: tuple[str, ...]
    research_turn_count: int
    risk_turn_count: int
    report_fields: tuple[str, ...]
    research_decision_fields: tuple[str, ...]
    trader_decision_fields: tuple[str, ...]
    portfolio_decision_fields: tuple[str, ...]
    research_rating_vocabulary: tuple[str, ...]
    trader_action_vocabulary: tuple[str, ...]
    processed_signal_vocabulary: tuple[str, ...]
    terminal_status: Literal["completed"] = "completed"
    non_execution: bool = True
    schema_id: str = ORACLE_PROJECTION_SCHEMA

    def semantic_dict(self) -> dict[str, object]:
        """Return fields compared across implementations, excluding provenance."""
        return {
            "schema_id": self.schema_id,
            "case_id": self.case_id,
            "selected_analysts": list(self.selected_analysts),
            "normalized_symbols": dict(sorted(self.normalized_symbols.items())),
            "stage_ids": list(self.stage_ids),
            "research_turn_count": self.research_turn_count,
            "risk_turn_count": self.risk_turn_count,
            "report_fields": list(self.report_fields),
            "research_decision_fields": list(self.research_decision_fields),
            "trader_decision_fields": list(self.trader_decision_fields),
            "portfolio_decision_fields": list(self.portfolio_decision_fields),
            "research_rating_vocabulary": list(self.research_rating_vocabulary),
            "trader_action_vocabulary": list(self.trader_action_vocabulary),
            "processed_signal_vocabulary": list(self.processed_signal_vocabulary),
            "terminal_status": self.terminal_status,
            "non_execution": self.non_execution,
        }

    def to_dict(self) -> dict[str, object]:
        return {"implementation": self.implementation, "revision": self.revision, **self.semantic_dict()}


@dataclass(frozen=True, slots=True)
class SemanticDifference:
    pointer: str
    upstream: object
    portable: object

    def to_dict(self) -> dict[str, object]:
        return {"pointer": self.pointer, "upstream": self.upstream, "portable": self.portable}


@dataclass(frozen=True, slots=True)
class SemanticDifferentialReport:
    upstream_revision: str
    portable_revision: str
    cases: tuple[dict[str, object], ...]
    differences: tuple[SemanticDifference, ...]
    case_digest: str
    comparator_digest: str
    portable_worktree_dirty: bool
    schema_id: str = ORACLE_REPORT_SCHEMA

    @property
    def passed(self) -> bool:
        return not self.differences

    @property
    def release_evidence_eligible(self) -> bool:
        return self.passed and not self.portable_worktree_dirty

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_id": self.schema_id,
            "passed": self.passed,
            "upstream_revision": self.upstream_revision,
            "portable_revision": self.portable_revision,
            "case_digest": self.case_digest,
            "comparator_digest": self.comparator_digest,
            "portable_worktree_dirty": self.portable_worktree_dirty,
            "release_evidence_eligible": self.release_evidence_eligible,
            "cases": list(self.cases),
            "differences": [item.to_dict() for item in self.differences],
            "scope": {
                "included": [
                    "analyst_order",
                    "debate_and_risk_cardinality",
                    "decision_shapes_and_vocabularies",
                    "report_fields",
                    "processed_signal_vocabulary",
                    "symbol_normalization",
                    "terminal_non_execution",
                ],
                "excluded": [
                    "generated_prose",
                    "prompts",
                    "timestamps",
                    "provider_choice",
                    "model_reasoning",
                    "langgraph_internals",
                ],
            },
        }


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _git_revision(root: Path) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed git invocation and explicit repository path
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    revision = completed.stdout.strip().lower()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise ValueError("portable checkout returned an invalid git revision")
    return revision


def _git_worktree_dirty(root: Path) -> bool:
    completed = subprocess.run(  # noqa: S603 - fixed git invocation and explicit repository path
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return bool(completed.stdout.strip())


def _literal_vocabulary(contract: type[object], field_name: str) -> tuple[str, ...]:
    values = tuple(str(item) for item in get_args(get_type_hints(contract)[field_name]))
    return tuple(value for value in values if value != "unknown")


def portable_observable_projection(
    case: OracleCase,
    *,
    portable_root: str | Path,
) -> ObservableProjectionV1:
    topology = build_legacy_topology(case.analysts, case.debate_rounds, case.risk_rounds)
    report_fields = tuple(item.name for item in fields(ReportSections) if item.name in _REPORT_FIELDS)
    research_fields = tuple(item.name for item in fields(ResearchDecision) if item.name in _RESEARCH_FIELDS)
    trader_fields = tuple(item.name for item in fields(TraderDecision) if item.name in _TRADER_FIELDS)
    portfolio_fields = tuple(item.name for item in fields(PortfolioDecision) if item.name in _PORTFOLIO_FIELDS)
    return ObservableProjectionV1(
        implementation="portable",
        revision=_git_revision(Path(portable_root).resolve()),
        case_id=case.case_id,
        selected_analysts=topology.analysts,
        normalized_symbols={symbol: normalize_instrument_symbol(symbol) for symbol in case.symbols},
        stage_ids=tuple(stage.id for stage in topology.stages),
        research_turn_count=2 * topology.debate_rounds,
        risk_turn_count=3 * topology.risk_rounds,
        report_fields=report_fields,
        research_decision_fields=research_fields,
        trader_decision_fields=trader_fields,
        portfolio_decision_fields=portfolio_fields,
        research_rating_vocabulary=_literal_vocabulary(ResearchDecision, "recommendation"),
        trader_action_vocabulary=_literal_vocabulary(TraderDecision, "action"),
        processed_signal_vocabulary=_literal_vocabulary(PortfolioDecision, "rating"),
    )


def _activate_upstream(root: Path) -> None:
    root_string = str(root)
    sys.path[:] = [item for item in sys.path if item != root_string]
    sys.path.insert(0, root_string)
    loaded = sys.modules.get("tradingagents")
    loaded_file = getattr(loaded, "__file__", None) if loaded is not None else None
    if loaded_file is not None and not Path(loaded_file).resolve().is_relative_to(root):
        for name in tuple(sys.modules):
            if name == "tradingagents" or name.startswith("tradingagents."):
                del sys.modules[name]
        importlib.invalidate_caches()


def _upstream_stage_ids(case: OracleCase, plan: Any, conditional_logic: Any) -> tuple[str, ...]:
    analyst_keys = tuple(str(spec.key) for spec in plan.specs)
    stages = [f"analyst.{key}" for key in analyst_keys]
    current_response = ""
    research_slugs: list[str] = []
    for count in range(0, 2 * case.debate_rounds + 1):
        target = conditional_logic.should_continue_debate(
            {"investment_debate_state": {"count": count, "current_response": current_response}}
        )
        if target == "Research Manager":
            break
        slug = "bull" if target == "Bull Researcher" else "bear"
        research_slugs.append(slug)
        current_response = target
    stages.extend(f"research.{index // 2 + 1}.{slug}" for index, slug in enumerate(research_slugs))
    stages.extend(("research.manager", "trader"))
    latest_speaker = ""
    risk_slugs: list[str] = []
    risk_map = {
        "Aggressive Analyst": "aggressive",
        "Conservative Analyst": "conservative",
        "Neutral Analyst": "neutral",
    }
    for count in range(0, 3 * case.risk_rounds + 1):
        target = conditional_logic.should_continue_risk_analysis(
            {"risk_debate_state": {"count": count, "latest_speaker": latest_speaker}}
        )
        if target == "Portfolio Manager":
            break
        risk_slugs.append(risk_map[target])
        latest_speaker = target
    stages.extend(f"risk.{index // 3 + 1}.{slug}" for index, slug in enumerate(risk_slugs))
    stages.append("portfolio")
    return tuple(stages)


def upstream_observable_projection(case: OracleCase, *, upstream_path: str | Path) -> ObservableProjectionV1:
    root = Path(upstream_path).expanduser().resolve()
    revision = upstream_revision(root)
    if revision != PINNED_UPSTREAM_REVISION:
        raise ValueError(f"upstream pin mismatch: expected {PINNED_UPSTREAM_REVISION}; found {revision}")
    _activate_upstream(root)
    analyst_module = importlib.import_module("tradingagents.graph.analyst_execution")
    conditional_module = importlib.import_module("tradingagents.graph.conditional_logic")
    state_module = importlib.import_module("tradingagents.agents.utils.agent_states")
    schema_module = importlib.import_module("tradingagents.agents.schemas")
    rating_module = importlib.import_module("tradingagents.agents.utils.rating")
    symbol_module = importlib.import_module("tradingagents.dataflows.symbol_utils")
    graph_module = importlib.import_module("tradingagents.graph.trading_graph")

    plan = analyst_module.build_analyst_execution_plan(case.analysts)
    conditional_logic = conditional_module.ConditionalLogic(case.debate_rounds, case.risk_rounds)
    stage_ids = _upstream_stage_ids(case, plan, conditional_logic)
    annotations = getattr(state_module.AgentState, "__annotations__", {})
    report_fields = tuple(name for name in _REPORT_FIELDS if name in annotations)
    research_fields = tuple(name for name in _RESEARCH_FIELDS if name in schema_module.ResearchPlan.model_fields)
    trader_fields = tuple(name for name in _TRADER_FIELDS if name in schema_module.TraderProposal.model_fields)
    portfolio_fields = tuple(name for name in _PORTFOLIO_FIELDS if name in schema_module.PortfolioDecision.model_fields)
    rating_values = tuple(str(value).lower() for value in rating_module.RATINGS_5_TIER)
    parsed_values = tuple(
        str(rating_module.parse_rating(f"**Rating**: {value}")).lower() for value in rating_module.RATINGS_5_TIER
    )
    propagate_source = inspect.getsource(graph_module.TradingAgentsGraph.propagate)
    run_graph_source = inspect.getsource(graph_module.TradingAgentsGraph._run_graph)
    terminal_return = (
        "return self._run_graph" in propagate_source
        and "return final_state" in run_graph_source
        and "process_signal" in run_graph_source
    )
    if not terminal_return:
        raise ValueError("pinned upstream terminal-return contract is no longer recognizable")
    decision_names = set(research_fields) | set(trader_fields) | set(portfolio_fields)
    execution_fields = {"order", "broker", "submitted", "execution_authority", "executable"}
    return ObservableProjectionV1(
        implementation="upstream",
        revision=revision,
        case_id=case.case_id,
        selected_analysts=tuple(str(spec.key) for spec in plan.specs),
        normalized_symbols={symbol: str(symbol_module.normalize_symbol(symbol)) for symbol in case.symbols},
        stage_ids=stage_ids,
        research_turn_count=len(
            tuple(stage for stage in stage_ids if stage.startswith("research.") and stage != "research.manager")
        ),
        risk_turn_count=len(tuple(stage for stage in stage_ids if stage.startswith("risk."))),
        report_fields=report_fields,
        research_decision_fields=research_fields,
        trader_decision_fields=trader_fields,
        portfolio_decision_fields=portfolio_fields,
        research_rating_vocabulary=rating_values,
        trader_action_vocabulary=tuple(str(item.value).lower() for item in schema_module.TraderAction),
        processed_signal_vocabulary=parsed_values,
        terminal_status="completed",
        non_execution=not bool(decision_names & execution_fields),
    )


def _differences(upstream: object, portable: object, pointer: str = "") -> list[SemanticDifference]:
    if isinstance(upstream, dict) and isinstance(portable, dict):
        output: list[SemanticDifference] = []
        for key in sorted(set(upstream) | set(portable)):
            child = f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}"
            if key not in upstream:
                output.append(SemanticDifference(child, None, portable[key]))
            elif key not in portable:
                output.append(SemanticDifference(child, upstream[key], None))
            else:
                output.extend(_differences(upstream[key], portable[key], child))
        return output
    if isinstance(upstream, list) and isinstance(portable, list):
        if upstream == portable:
            return []
        return [SemanticDifference(pointer or "/", upstream, portable)]
    return [] if upstream == portable else [SemanticDifference(pointer or "/", upstream, portable)]


def compare_observable_projections(
    upstream: ObservableProjectionV1,
    portable: ObservableProjectionV1,
) -> tuple[SemanticDifference, ...]:
    if upstream.implementation != "upstream" or portable.implementation != "portable":
        raise ValueError("semantic comparison requires upstream and portable projections")
    return tuple(_differences(upstream.semantic_dict(), portable.semantic_dict()))


def run_semantic_differential(
    *,
    upstream_path: str | Path,
    portable_root: str | Path,
    cases: tuple[OracleCase, ...] = DEFAULT_ORACLE_CASES,
) -> SemanticDifferentialReport:
    case_records: list[dict[str, object]] = []
    all_differences: list[SemanticDifference] = []
    upstream_revision_value: str | None = None
    portable_revision_value: str | None = None
    for case in cases:
        upstream = upstream_observable_projection(case, upstream_path=upstream_path)
        portable = portable_observable_projection(case, portable_root=portable_root)
        upstream_revision_value = upstream.revision
        portable_revision_value = portable.revision
        differences = compare_observable_projections(upstream, portable)
        all_differences.extend(
            SemanticDifference(f"/cases/{case.case_id}{item.pointer}", item.upstream, item.portable)
            for item in differences
        )
        case_records.append(
            {
                "case": case.to_dict(),
                "upstream_projection": upstream.to_dict(),
                "portable_projection": portable.to_dict(),
                "passed": not differences,
            }
        )
    case_digest = hashlib.sha256(_canonical([case.to_dict() for case in cases])).hexdigest()
    comparator_payload = {
        "schema_id": ORACLE_REPORT_SCHEMA,
        "case_digest": case_digest,
        "cases": case_records,
        "differences": [item.to_dict() for item in all_differences],
    }
    comparator_digest = hashlib.sha256(_canonical(comparator_payload)).hexdigest()
    if upstream_revision_value is None or portable_revision_value is None:
        raise ValueError("semantic differential requires at least one case")
    portable_dirty = _git_worktree_dirty(Path(portable_root).resolve())
    return SemanticDifferentialReport(
        upstream_revision=upstream_revision_value,
        portable_revision=portable_revision_value,
        cases=tuple(case_records),
        differences=tuple(all_differences),
        case_digest=case_digest,
        comparator_digest=comparator_digest,
        portable_worktree_dirty=portable_dirty,
    )
