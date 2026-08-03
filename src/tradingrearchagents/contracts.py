"""Side-effect-free wire contracts for tradingrearchagents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Literal, Never
from urllib.parse import urlsplit

SCHEMA_VERSION = "2026-08-03"
PROTOTYPE_NOTICE = (
    "Prototype research output only. Not financial advice and never an order, "
    "broker instruction, or authorization to trade."
)

SAFE_LEGACY_CONFIG_KEYS = frozenset(
    {
        "anthropic_effort",
        "backend_url",
        "deep_think_llm",
        "google_thinking_level",
        "llm_max_retries",
        "llm_provider",
        "openai_reasoning_effort",
        "output_language",
        "quick_think_llm",
        "report_output_path",
        "temperature",
    }
)
SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "credential",
    "password",
    "private_key",
    "privatekey",
)
SECRET_KEY_WORDS = frozenset({"bearer", "cookie", "secret", "token"})


class FrozenConfig(dict[str, Any]):
    """JSON-compatible immutable mapping for validated public execution config."""

    @staticmethod
    def _immutable(*_: object, **__: object) -> Never:
        raise TypeError("legacy_config is immutable; construct a new RunRequest")

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __deepcopy__(self, memo: dict[int, object]) -> FrozenConfig:
        del memo
        return type(self)(self)


def reject_secret_shaped_keys(value: object, path: tuple[str, ...] = ()) -> None:
    """Reject credential-shaped mapping keys at any nesting depth."""
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            words = set(key.split("_"))
            authorization_header = key in {
                "authorization",
                "authorization_header",
                "http_authorization",
                "http_authorization_header",
            } or key.startswith("authorization_")
            if (
                any(marker in key for marker in SECRET_KEY_MARKERS)
                or bool(words & SECRET_KEY_WORDS)
                or authorization_header
            ):
                location = ".".join((*path, str(raw_key)))
                raise ValueError(f"credential-shaped config key is forbidden: {location}")
            reject_secret_shaped_keys(nested, (*path, str(raw_key)))
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            reject_secret_shaped_keys(nested, (*path, str(index)))


def sanitize_legacy_config(config: Mapping[str, object] | None) -> dict[str, object]:
    """Return the executor-safe public config accepted by every API surface."""
    candidate = dict(config or {})
    reject_secret_shaped_keys(candidate)
    unsupported = sorted(set(candidate) - SAFE_LEGACY_CONFIG_KEYS)
    if unsupported:
        raise ValueError(f"unsupported legacy config keys: {unsupported}")
    sanitized = {key: value for key, value in candidate.items() if value is not None}
    for key, value in sanitized.items():
        if isinstance(value, Mapping | list | tuple | set):
            raise ValueError(f"legacy config value for {key} must be a scalar")
        if isinstance(value, str) and (not value.strip() or len(value) > 512 or "\n" in value or "\r" in value):
            raise ValueError(f"legacy config value for {key} must be a short, non-empty single-line string")
    backend_url = sanitized.get("backend_url")
    if isinstance(backend_url, str):
        parsed = urlsplit(backend_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("backend_url must be an http(s) URL without userinfo, query parameters, or a fragment")
    retries = sanitized.get("llm_max_retries")
    if retries is not None and (not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= 20):
        raise ValueError("llm_max_retries must be an integer between 0 and 20")
    temperature = sanitized.get("temperature")
    if temperature is not None and (
        not isinstance(temperature, int | float) or isinstance(temperature, bool) or not 0 <= temperature <= 2
    ):
        raise ValueError("temperature must be a number between 0 and 2")
    report_output_path = sanitized.get("report_output_path")
    if report_output_path is not None and not isinstance(report_output_path, str):
        raise ValueError("report_output_path must be a path string")
    return sanitized


class WireEnum(StrEnum):
    pass


class RunStatus(WireEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EventKind(WireEnum):
    RUN = "run"
    STAGE = "stage"
    EVIDENCE = "evidence"
    DEBATE = "debate"
    DECISION = "decision"
    ARTIFACT = "artifact"
    WARNING = "warning"


class StageKind(WireEnum):
    ANALYST = "analyst"
    RESEARCH_DEBATE = "research_debate"
    RESEARCH_MANAGER = "research_manager"
    TRADER = "trader"
    RISK_DEBATE = "risk_debate"
    PORTFOLIO = "portfolio"


class SupportLevel(WireEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    OPTIONAL = "optional"
    UNAVAILABLE = "unavailable"
    PROHIBITED = "prohibited"


@dataclass(frozen=True, slots=True)
class Contract:
    schema_version: str = field(default=SCHEMA_VERSION, init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RunRequest(Contract):
    symbol: str = "ORCL"
    as_of_date: str = "2026-07-03"
    asset_type: Literal["stock", "crypto"] = "stock"
    analysts: tuple[str, ...] = ("market", "social", "news", "fundamentals")
    debate_rounds: int = 1
    risk_rounds: int = 1
    output_language: str = "English"
    executor: Literal["fixture", "host_native", "legacy"] = "fixture"
    checkpoint_enabled: bool = False
    legacy_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol or len(symbol) > 32 or not all(c.isalnum() or c in "._-^=" for c in symbol):
            raise ValueError("symbol must be a non-empty market identifier")
        object.__setattr__(self, "symbol", symbol)
        parsed_as_of_date = date.fromisoformat(self.as_of_date)
        if parsed_as_of_date > date.today():
            raise ValueError("as_of_date cannot be in the future")
        if self.asset_type not in {"stock", "crypto"}:
            raise ValueError("asset_type must be 'stock' or 'crypto'")
        allowed = {"market", "social", "news", "fundamentals"}
        if not self.analysts or len(set(self.analysts)) != len(self.analysts):
            raise ValueError("analysts must be a non-empty unique sequence")
        unknown = set(self.analysts) - allowed
        if unknown:
            raise ValueError(f"unsupported analysts: {sorted(unknown)}")
        effective_analysts = tuple(
            analyst for analyst in self.analysts if not (self.asset_type == "crypto" and analyst == "fundamentals")
        )
        object.__setattr__(self, "analysts", effective_analysts)
        if not self.analysts:
            raise ValueError("crypto requests require at least one of market, social, or news")
        if not 1 <= self.debate_rounds <= 10 or not 1 <= self.risk_rounds <= 10:
            raise ValueError("debate_rounds and risk_rounds must be between 1 and 10")
        output_language = self.output_language.strip()
        if not output_language or len(output_language) > 64:
            raise ValueError("output_language must be between 1 and 64 characters")
        object.__setattr__(self, "output_language", output_language)
        if self.executor == "fixture" and self.symbol != "ORCL":
            raise ValueError("the deterministic fixture supports symbol ORCL only")
        object.__setattr__(self, "legacy_config", FrozenConfig(sanitize_legacy_config(self.legacy_config)))


@dataclass(frozen=True, slots=True)
class CapabilityFeature(Contract):
    name: str = ""
    level: SupportLevel = SupportLevel.SUPPORTED
    detail: str = ""


@dataclass(frozen=True, slots=True)
class FeatureCapabilityMatrix(Contract):
    capability: str = "tradingrearchagents"
    prototype: bool = True
    default_executor: str = "fixture"
    features: tuple[CapabilityFeature, ...] = ()
    runtime_readiness: dict[str, Any] = field(default_factory=dict)
    safety_notice: str = PROTOTYPE_NOTICE


@dataclass(frozen=True, slots=True)
class StageSpec(Contract):
    id: str = ""
    kind: StageKind = StageKind.ANALYST
    role: str = ""
    ordinal: int = 0
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowTopology(Contract):
    name: str = "legacy-full"
    analysts: tuple[str, ...] = ()
    debate_rounds: int = 1
    risk_rounds: int = 1
    stages: tuple[StageSpec, ...] = ()
    terminal_stage: str = "portfolio"


@dataclass(frozen=True, slots=True)
class Provenance(Contract):
    provider: str = ""
    source_type: str = ""
    source_uri: str | None = None
    retrieved_at: str = ""
    source_date: str | None = None
    fixture: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceItem(Contract):
    id: str = ""
    category: str = ""
    title: str = ""
    summary: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalystReport(Contract):
    analyst: str = ""
    thesis: str = ""
    evidence_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    content: str = ""


@dataclass(frozen=True, slots=True)
class ReportSections(Contract):
    """The four report fields emitted by the upstream AgentState."""

    market_report: str = ""
    sentiment_report: str = ""
    news_report: str = ""
    fundamentals_report: str = ""


@dataclass(frozen=True, slots=True)
class DebateSnapshot(Contract):
    """Lossless aggregate debate state; it does not pretend histories are turns."""

    history: str = ""
    role_histories: dict[str, str] = field(default_factory=dict)
    current_response: str = ""
    current_responses: dict[str, str] = field(default_factory=dict)
    judge_decision: str = ""
    count: int = 0


@dataclass(frozen=True, slots=True)
class DebateTurn(Contract):
    debate: Literal["research", "risk"] = "research"
    round: int = 1
    turn: int = 1
    speaker: str = ""
    position: str = ""
    responds_to: str | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchDecision(Contract):
    recommendation: Literal["buy", "overweight", "hold", "underweight", "sell", "unknown"] = "unknown"
    rationale: str = ""
    strategic_actions: str = ""
    raw_markdown: str = ""
    supporting_turns: tuple[int, ...] = ()
    confidence: float = 0.0
    projection_quality: Literal["structured", "parsed", "raw_markdown_only", "synthetic"] = "structured"

    @property
    def decision(self) -> str:
        """Backward-compatible display alias for pre-v2 callers."""
        return self.recommendation.title()

    def render_markdown(self) -> str:
        return "\n".join(
            (
                f"**Recommendation**: {self.recommendation.title()}",
                "",
                f"**Rationale**: {self.rationale}",
                "",
                f"**Strategic Actions**: {self.strategic_actions}",
            )
        )


@dataclass(frozen=True, slots=True)
class TraderDecision(Contract):
    action: Literal["buy", "hold", "sell", "unknown"] = "unknown"
    reasoning: str = ""
    entry_price: float | None = None
    stop_loss: float | None = None
    position_sizing: str | None = None
    raw_markdown: str = ""
    executable: bool = False
    execution_authority: Literal["none"] = "none"
    submitted: bool = False
    caveats: tuple[str, ...] = ()
    projection_quality: Literal["structured", "parsed", "raw_markdown_only", "synthetic"] = "structured"

    def __post_init__(self) -> None:
        if self.executable or self.submitted or self.execution_authority != "none":
            raise ValueError("trader output cannot carry execution authority or a submitted order")

    @property
    def stance(self) -> str:
        """Backward-compatible display alias for pre-v2 callers."""
        return self.action

    @property
    def plan(self) -> str:
        """Backward-compatible raw plan alias for pre-v2 callers."""
        return self.raw_markdown or self.reasoning

    def render_markdown(self) -> str:
        parts = [f"**Action**: {self.action.title()}", "", f"**Reasoning**: {self.reasoning}"]
        if self.entry_price is not None:
            parts.extend(("", f"**Entry Price**: {self.entry_price}"))
        if self.stop_loss is not None:
            parts.extend(("", f"**Stop Loss**: {self.stop_loss}"))
        if self.position_sizing:
            parts.extend(("", f"**Position Sizing**: {self.position_sizing}"))
        parts.extend(("", f"FINAL TRANSACTION PROPOSAL: **{self.action.upper()}**"))
        return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class RiskDecision(Contract):
    risk_level: Literal["low", "moderate", "high", "unknown"] = "unknown"
    constraints: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PortfolioDecision(Contract):
    rating: Literal["buy", "overweight", "hold", "underweight", "sell", "unknown"] = "unknown"
    executive_summary: str = ""
    investment_thesis: str = ""
    price_target: float | None = None
    time_horizon: str | None = None
    raw_markdown: str = ""
    executable: bool = False
    execution_authority: Literal["none"] = "none"
    submitted: bool = False
    disclaimer: str = PROTOTYPE_NOTICE
    projection_quality: Literal["structured", "parsed", "raw_markdown_only", "synthetic"] = "structured"

    def __post_init__(self) -> None:
        if self.executable or self.submitted or self.execution_authority != "none":
            raise ValueError("portfolio output cannot carry execution authority or a submitted order")

    @property
    def action(self) -> str:
        """Backward-compatible display alias for pre-v2 callers."""
        return self.rating

    @property
    def summary(self) -> str:
        """Backward-compatible summary alias for pre-v2 callers."""
        return self.executive_summary

    def render_markdown(self) -> str:
        parts = [
            f"**Rating**: {self.rating.title()}",
            "",
            f"**Executive Summary**: {self.executive_summary}",
            "",
            f"**Investment Thesis**: {self.investment_thesis}",
        ]
        if self.price_target is not None:
            parts.extend(("", f"**Price Target**: {self.price_target}"))
        if self.time_horizon:
            parts.extend(("", f"**Time Horizon**: {self.time_horizon}"))
        return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class ExecutionConfig(Contract):
    """Non-secret execution settings safe to persist and show in a UI."""

    executor: Literal["fixture", "host_native", "legacy"] = "fixture"
    llm_provider: str | None = None
    deep_model: str | None = None
    quick_model: str | None = None
    backend_url: str | None = None
    output_language: str | None = None
    temperature: float | None = None
    max_retries: int | None = None
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    data_vendors: tuple[str, ...] = ()
    checkpoint_enabled: bool = False
    max_debate_rounds: int = 1
    max_risk_discuss_rounds: int = 1


@dataclass(frozen=True, slots=True)
class PersistenceMetadata(Contract):
    decision_memory_enabled: bool = True
    run_logging_enabled: bool = True
    checkpoint_enabled: bool = False
    writes_expected: bool = False
    outputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CapabilityMetadata(Contract):
    executor: Literal["fixture", "host_native", "legacy"] = "fixture"
    observation_mode: Literal["fixture", "host_native_submission", "legacy_post_run"] = "fixture"
    deterministic: bool = True
    live_data: bool = False
    external_credentials_required: bool = False
    portable_boundary_credentials_required: bool = False
    host_tool_auth: Literal["not_applicable", "host_owned_unknown", "environment_owned"] = "not_applicable"
    upstream_business_logic: bool = False


@dataclass(frozen=True, slots=True)
class InstrumentIdentity(Contract):
    """Safe display identity copied from the completed upstream state."""

    requested_symbol: str = ""
    company_of_interest: str = ""
    trade_date: str = ""
    asset_type: Literal["stock", "crypto"] = "stock"
    instrument_context: str = ""


@dataclass(frozen=True, slots=True)
class Artifact(Contract):
    id: str = ""
    kind: str = ""
    title: str = ""
    media_type: str = "application/json"
    content: Any = None


@dataclass(frozen=True, slots=True)
class RunEvent(Contract):
    id: str = ""
    run_id: str = ""
    sequence: int = 0
    timestamp: str = ""
    kind: EventKind = EventKind.RUN
    stage_id: str | None = None
    status: str = ""
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunResult(Contract):
    run_id: str = ""
    status: RunStatus = RunStatus.COMPLETED
    request: RunRequest = field(default_factory=RunRequest)
    instrument: InstrumentIdentity = field(default_factory=InstrumentIdentity)
    topology: WorkflowTopology = field(default_factory=WorkflowTopology)
    evidence: tuple[EvidenceItem, ...] = ()
    analyst_reports: tuple[AnalystReport, ...] = ()
    report_sections: ReportSections = field(default_factory=ReportSections)
    research_debate: tuple[DebateTurn, ...] = ()
    research_debate_snapshot: DebateSnapshot = field(default_factory=DebateSnapshot)
    research_decision: ResearchDecision = field(default_factory=ResearchDecision)
    trader_decision: TraderDecision = field(default_factory=TraderDecision)
    risk_debate: tuple[DebateTurn, ...] = ()
    risk_debate_snapshot: DebateSnapshot = field(default_factory=DebateSnapshot)
    risk_decision: RiskDecision = field(default_factory=RiskDecision)
    portfolio_decision: PortfolioDecision = field(default_factory=PortfolioDecision)
    investment_plan: str = ""
    trader_investment_plan: str = ""
    portfolio_manager_decision: str = ""
    final_trade_decision: str = ""
    processed_signal: str = ""
    execution_config: ExecutionConfig = field(default_factory=ExecutionConfig)
    persistence: PersistenceMetadata = field(default_factory=PersistenceMetadata)
    capability: CapabilityMetadata = field(default_factory=CapabilityMetadata)
    artifacts: tuple[Artifact, ...] = ()
    warnings: tuple[str, ...] = ()
    started_at: str = ""
    completed_at: str = ""
    prototype_notice: str = PROTOTYPE_NOTICE


@dataclass(frozen=True, slots=True)
class SetupGuidance(Contract):
    code: str = "legacy_executor_unavailable"
    message: str = ""
    steps: tuple[str, ...] = ()
    retryable: bool = False
