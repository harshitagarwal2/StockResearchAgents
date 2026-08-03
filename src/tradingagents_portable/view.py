"""Lossless dashboard-oriented projection of a portable run."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .contracts import EvidenceItem, RunEvent, RunResult
from .reporting import report_groups

SOURCE_QUALITY_VOCABULARY = frozenset(
    {
        "primary_regulatory",
        "primary_company",
        "primary_agency",
        "primary_partner",
        "established_market_data",
        "reputable_journalism",
        "aggregator_discovery",
        "public_discussion",
        "synthetic_fixture",
        "unknown",
    }
)


@dataclass(frozen=True, slots=True)
class RunView:
    """UI-ready representation that keeps decisions and signal distinct."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload


def _badge(label: str, value: object, tone: str, detail: str) -> dict[str, object]:
    return {"label": label, "value": value, "tone": tone, "detail": detail}


def _safe_web_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    safe = (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and not hostname.endswith(".invalid")
    )
    return value if safe else None


def _timestamp_extreme(values: list[str], *, latest: bool) -> str | None:
    parsed: list[tuple[str, datetime]] = []
    for value in values:
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        parsed.append((value, timestamp.astimezone(UTC)))
    if not parsed:
        return None
    chooser = max if latest else min
    return chooser(parsed, key=lambda item: item[1])[0]


def _date_distance_days(earlier: str | None, later: str | None) -> int | None:
    if earlier is None or later is None:
        return None
    try:
        return (datetime.fromisoformat(later).date() - datetime.fromisoformat(earlier).date()).days
    except ValueError:
        return None


def _evidence_context(item: EvidenceItem) -> dict[str, str]:
    return {"evidence_id": item.id, "category": item.category}


def _normalize_records(item: EvidenceItem, key: str, text_key: str) -> list[dict[str, Any]]:
    value = item.values.get(key)
    if not isinstance(value, list | tuple):
        return []

    records: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, str):
            record: dict[str, Any] = {text_key: entry}
        elif isinstance(entry, Mapping):
            record = {str(field): field_value for field, field_value in entry.items()}
        else:
            continue
        record.update(_evidence_context(item))
        records.append(record)
    return records


def _normalize_metrics(item: EvidenceItem) -> list[dict[str, Any]]:
    value = item.values.get("metrics")
    records: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for name, metric_value in value.items():
            if isinstance(metric_value, Mapping):
                record = {str(field): field_value for field, field_value in metric_value.items()}
                record.setdefault("name", str(name))
            else:
                record = {"name": str(name), "value": metric_value}
            record.update(_evidence_context(item))
            records.append(record)
    elif isinstance(value, list | tuple):
        for metric in value:
            if not isinstance(metric, Mapping):
                continue
            record = {str(field): field_value for field, field_value in metric.items()}
            record.update(_evidence_context(item))
            records.append(record)
    return records


def _source_quality(item: EvidenceItem) -> str:
    value = item.values.get("source_quality")
    if item.provenance.fixture:
        return "synthetic_fixture"
    return value if isinstance(value, str) and value in SOURCE_QUALITY_VOCABULARY else "unknown"


def _has_unrecognized_source_quality(item: EvidenceItem) -> bool:
    value = item.values.get("source_quality")
    return (
        not item.provenance.fixture
        and isinstance(value, str)
        and bool(value.strip())
        and value not in SOURCE_QUALITY_VOCABULARY
    )


def _intelligence_projection(result: RunResult) -> dict[str, Any]:
    source_qualities = Counter(_source_quality(item) for item in result.evidence)
    categories = Counter(item.category for item in result.evidence)
    providers = Counter(item.provenance.provider or "unknown" for item in result.evidence)
    source_types = Counter(item.provenance.source_type or "unknown" for item in result.evidence)
    source_urls = [
        source_url for item in result.evidence if (source_url := _safe_web_url(item.provenance.source_uri)) is not None
    ]
    source_dates = [item.provenance.source_date for item in result.evidence if item.provenance.source_date]
    retrieved_dates = [item.provenance.retrieved_at for item in result.evidence if item.provenance.retrieved_at]
    oldest_source_date = min(source_dates, default=None)
    latest_source_date = max(source_dates, default=None)

    news: list[dict[str, Any]] = []
    for item in result.evidence:
        for article in _normalize_records(item, "articles", "headline"):
            if article.get("source_quality") not in SOURCE_QUALITY_VOCABULARY:
                article["source_quality"] = _source_quality(item)
            for url_key in ("url", "source_url"):
                if url_key in article:
                    safe_url = _safe_web_url(article[url_key])
                    if safe_url is None:
                        article.pop(url_key)
                    else:
                        article[url_key] = safe_url
                        source_urls.append(safe_url)
            news.append(article)

    risk_register = [record for item in result.evidence for record in _normalize_records(item, "risks", "risk")]
    risk_register.extend(
        {"risk": constraint, "source": "risk_decision.constraints"} for constraint in result.risk_decision.constraints
    )
    unknowns = [record for item in result.evidence for record in _normalize_records(item, "unknowns", "unknown")]
    unknowns.extend(
        {"unknown": unresolved, "source": "risk_decision.unresolved"} for unresolved in result.risk_decision.unresolved
    )
    monitoring_conditions = [
        record for item in result.evidence for record in _normalize_records(item, "monitoring_conditions", "condition")
    ]

    return {
        "coverage": {
            "evidence_count": len(result.evidence),
            "analyst_count": len(result.analyst_reports),
            "limitation_count": sum(len(item.limitations) for item in result.evidence),
            "source_url_count": len(source_urls),
            "dated_source_count": len(source_dates),
            "source_quality_buckets": dict(sorted(source_qualities.items())),
            "unrecognized_source_quality_count": sum(
                _has_unrecognized_source_quality(item) for item in result.evidence
            ),
        },
        "source_mix": {
            "categories": dict(sorted(categories.items())),
            "providers": dict(sorted(providers.items())),
            "source_types": dict(sorted(source_types.items())),
        },
        "freshness": {
            "cutoff": result.request.as_of_date,
            "oldest_source_date": oldest_source_date,
            "latest_source_date": latest_source_date,
            "source_history_days": _date_distance_days(oldest_source_date, latest_source_date),
            "latest_source_lag_days": _date_distance_days(latest_source_date, result.request.as_of_date),
            "oldest_retrieved_at": _timestamp_extreme(retrieved_dates, latest=False),
            "latest_retrieved_at": _timestamp_extreme(retrieved_dates, latest=True),
        },
        "evidence_metrics": [record for item in result.evidence for record in _normalize_metrics(item)],
        "news": news,
        "catalysts": [
            record for item in result.evidence for record in _normalize_records(item, "catalysts", "catalyst")
        ],
        "risk_register": risk_register,
        "conflicts": [
            record for item in result.evidence for record in _normalize_records(item, "conflicts", "conflict")
        ],
        "unknowns": unknowns,
        "monitoring_conditions": monitoring_conditions,
    }


def build_run_view(result: RunResult, events: tuple[RunEvent, ...]) -> RunView:
    """Expose every RunResult section without collapsing its meanings."""
    persistence = result.persistence.to_dict()
    capability = result.capability.to_dict()
    checkpoint = result.persistence.checkpoint_enabled
    completed = result.status.value == "completed"
    artifacts = [artifact.to_dict() for artifact in result.artifacts]
    artifact_ids = {artifact.id for artifact in result.artifacts}
    request = result.request.to_dict()
    # Adapter configuration may contain provider credentials.  The view keeps
    # the field visible while never reflecting its values.
    request["legacy_config"] = {
        "configured": bool(result.request.legacy_config),
        "keys": sorted(result.request.legacy_config),
        "values_redacted": bool(result.request.legacy_config),
    }

    payload: dict[str, Any] = {
        "schema_version": result.schema_version,
        "ok": True,
        "run_id": result.run_id,
        "overview": {
            "symbol": result.request.symbol,
            "company_of_interest": result.instrument.company_of_interest or result.request.symbol,
            "instrument_context": result.instrument.instrument_context,
            "as_of_date": result.request.as_of_date,
            "trade_date": result.instrument.trade_date or result.request.as_of_date,
            "asset_type": result.request.asset_type,
            "status": result.status.value,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "prototype_notice": result.prototype_notice,
            "warnings": list(result.warnings),
        },
        "request": request,
        "execution_config": result.execution_config.to_dict(),
        "topology": result.topology.to_dict(),
        "evidence": [item.to_dict() for item in result.evidence],
        "intelligence": _intelligence_projection(result),
        "analyst_reports": [report.to_dict() for report in result.analyst_reports],
        "report_sections": result.report_sections.to_dict(),
        "reports": {
            "groups": report_groups(result.artifacts),
            "complete_artifact_id": "report.complete" if "report.complete" in artifact_ids else None,
        },
        "debates": {
            "research": {
                "turns": [turn.to_dict() for turn in result.research_debate],
                "snapshot": result.research_debate_snapshot.to_dict(),
            },
            "risk": {
                "turns": [turn.to_dict() for turn in result.risk_debate],
                "snapshot": result.risk_debate_snapshot.to_dict(),
            },
        },
        "decisions": {
            "research": result.research_decision.to_dict(),
            "trader": result.trader_decision.to_dict(),
            "risk": result.risk_decision.to_dict(),
            "portfolio": result.portfolio_decision.to_dict(),
        },
        "outputs": {
            "investment_plan": result.investment_plan,
            "trader_investment_plan": result.trader_investment_plan,
            "portfolio_manager_decision": result.portfolio_manager_decision,
            "final_trade_decision": result.final_trade_decision,
        },
        "signal": {
            "processed_signal": result.processed_signal,
            "source": "portfolio_rating",
            "meaning": "Derived from the Portfolio Manager rating; it is research output, never an order.",
            "executable": False,
            "execution_authority": "none",
            "submitted": False,
        },
        "persistence": {
            "metadata": persistence,
            "badges": [
                _badge("Decision memory", result.persistence.decision_memory_enabled, "info", "Executor behavior"),
                _badge("Run logging", result.persistence.run_logging_enabled, "info", "Executor behavior"),
                _badge(
                    "Checkpoint resume",
                    checkpoint,
                    "enabled" if checkpoint else "muted",
                    "Opt-in; disabled by default",
                ),
                _badge(
                    "Writes expected",
                    result.persistence.writes_expected,
                    "warning" if result.persistence.writes_expected else "safe",
                    ", ".join(result.persistence.outputs) or "No declared outputs",
                ),
            ],
        },
        "capability": {
            "metadata": capability,
            "badges": [
                _badge("Executor", result.capability.executor, "info", result.capability.observation_mode),
                _badge("Deterministic", result.capability.deterministic, "safe", "Replay characteristic"),
                _badge("Live data", result.capability.live_data, "warning", "Data-source characteristic"),
                _badge(
                    "Portable boundary credentials",
                    result.capability.portable_boundary_credentials_required,
                    "warning" if result.capability.portable_boundary_credentials_required else "safe",
                    "The portable host-plan/import boundary never accepts credentials",
                ),
                _badge("Host tool auth", result.capability.host_tool_auth, "info", "Owned by the selected harness"),
                _badge("Execution authority", "none", "safe", "No broker or order surface exists"),
            ],
        },
        "events": [event.to_dict() for event in events],
        "artifacts": artifacts,
        "actions": [
            {
                "id": "view_complete_report",
                "available": "report.complete" in artifact_ids,
                "reason": "Available from the canonical in-memory report bundle."
                if "report.complete" in artifact_ids
                else "No complete-report artifact was produced.",
            },
            {
                "id": "resume",
                "available": checkpoint and not completed,
                "reason": "Resume requires an opted-in checkpoint and an incomplete run."
                if not (checkpoint and not completed)
                else "An incomplete checkpoint-enabled run can be resumed by its executor.",
            },
            {
                "id": "cancel",
                "available": not completed,
                "reason": "Completed runs cannot be cancelled." if completed else "Run is still active.",
            },
        ],
    }
    return RunView(payload)
