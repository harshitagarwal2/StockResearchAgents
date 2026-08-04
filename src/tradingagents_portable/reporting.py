"""Canonical, side-effect-free report artifacts for every executor.

The upstream CLI presents five ordered groups.  This module preserves that
information model in memory so MCP, the Research Dossier Viewer, or another harness can render
the same report without requiring filesystem writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .contracts import Artifact, RunResult


@dataclass(frozen=True, slots=True)
class _ReportPart:
    key: str
    title: str
    content: str


def _present(*parts: _ReportPart) -> tuple[_ReportPart, ...]:
    return tuple(part for part in parts if part.content)


def _group_markdown(heading: str, parts: tuple[_ReportPart, ...]) -> str:
    body = "\n\n".join(f"### {part.title}\n{part.content}" for part in parts)
    return f"## {heading}\n\n{body}" if body else ""


def _group_artifact(*, ordinal: int, slug: str, title: str, parts: tuple[_ReportPart, ...]) -> Artifact | None:
    if not parts:
        return None
    heading = f"{('I', 'II', 'III', 'IV', 'V')[ordinal - 1]}. {title}"
    return Artifact(
        id=f"report.group.{ordinal}.{slug}",
        kind="report_group",
        title=heading,
        media_type="application/vnd.tradingagents.report-group+json",
        content={
            "ordinal": ordinal,
            "slug": slug,
            "heading": heading,
            "sections": [{"key": part.key, "title": part.title, "content": part.content} for part in parts],
            "markdown": _group_markdown(heading, parts),
            "storage": "in_memory",
        },
    )


def _source_window(values: tuple[str, ...], *, timestamps: bool = False) -> dict[str, object]:
    """Describe retained timestamps without implying a host query window."""
    ordered = tuple(sorted(set(values)))
    if timestamps:
        try:
            parsed = tuple((datetime.fromisoformat(value.replace("Z", "+00:00")), value) for value in ordered)
            if any(timestamp.tzinfo is None for timestamp, _value in parsed):
                raise ValueError("timestamps must include an offset")
        except ValueError:
            pass
        else:
            ordered = tuple(value for _timestamp, value in sorted(parsed, key=lambda item: item[0].astimezone(UTC)))
    return {
        "count": len(ordered),
        "earliest": ordered[0] if ordered else None,
        "latest": ordered[-1] if ordered else None,
    }


def _report_provenance(result: RunResult) -> dict[str, object]:
    """Produce a safe report-side index of evidence each analyst retained.

    A completed portable result does not attest to every retrieval attempt or
    host tool argument.  This receipt deliberately reports only retained
    evidence and its supplied provenance so an export cannot masquerade as a
    complete query log.
    """
    evidence_by_id = {item.id: item for item in result.evidence}
    analysts: list[dict[str, object]] = []
    for report in result.analyst_reports:
        retained = tuple(
            evidence_by_id[evidence_id] for evidence_id in report.evidence_ids if evidence_id in evidence_by_id
        )
        missing_evidence_ids = tuple(
            evidence_id for evidence_id in report.evidence_ids if evidence_id not in evidence_by_id
        )
        source_dates = tuple(item.provenance.source_date for item in retained if item.provenance.source_date)
        retrieved_at = tuple(item.provenance.retrieved_at for item in retained if item.provenance.retrieved_at)
        analysts.append(
            {
                "analyst": report.analyst,
                "retained_evidence_count": len(retained),
                "missing_evidence_ids": list(missing_evidence_ids),
                "retained_source_date_range": _source_window(source_dates),
                "retained_retrieval_time_range": _source_window(retrieved_at, timestamps=True),
                "evidence": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "category": item.category,
                        "provider": item.provenance.provider or None,
                        "source_uri": item.provenance.source_uri,
                        "source_date": item.provenance.source_date,
                        "retrieved_at": item.provenance.retrieved_at or None,
                        "limitations": list(item.limitations),
                    }
                    for item in retained
                ],
            }
        )
    return {
        "schema_version": "report-provenance.v1",
        "basis": "retained_evidence_only",
        "host_tool_call_ledger_available": False,
        "analysts": analysts,
    }


def _report_provenance_markdown(provenance: dict[str, object]) -> str:
    """Render audit metadata separately from analyst prose and source bodies."""
    sections = [
        "## Retained evidence provenance",
        "",
        (
            "This section records only evidence retained in the completed result. It is not a complete host "
            "tool-call log or a claim that every source query used the displayed date range."
        ),
    ]
    analysts = provenance["analysts"]
    if not isinstance(analysts, list):
        return "\n".join(sections)
    for analyst in analysts:
        if not isinstance(analyst, dict):
            continue
        source_window = analyst.get("retained_source_date_range")
        retrieval_window = analyst.get("retained_retrieval_time_range")
        source_start = source_window.get("earliest") if isinstance(source_window, dict) else None
        source_end = source_window.get("latest") if isinstance(source_window, dict) else None
        retrieval_start = retrieval_window.get("earliest") if isinstance(retrieval_window, dict) else None
        retrieval_end = retrieval_window.get("latest") if isinstance(retrieval_window, dict) else None
        sections.extend(
            (
                "",
                f"### {str(analyst.get('analyst', 'Analyst')).title()} analyst",
                f"- Retained evidence: {analyst.get('retained_evidence_count', 0)} record(s)",
                f"- Retained source-date range: {source_start or 'not declared'} to {source_end or 'not declared'}",
                (
                    "- Retained retrieval-time range: "
                    f"{retrieval_start or 'not declared'} to {retrieval_end or 'not declared'}"
                ),
            )
        )
        evidence = analyst.get("evidence")
        missing_evidence_ids = analyst.get("missing_evidence_ids")
        if isinstance(missing_evidence_ids, list):
            sections.extend(f"- Missing retained evidence reference: {item}" for item in missing_evidence_ids)
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if not isinstance(item, dict):
                continue
            source = item.get("source_uri") or "source URI not retained"
            sections.append(
                "- "
                f"[{item.get('id', 'evidence')}] {item.get('title', 'Untitled source')} — "
                f"provider: {item.get('provider') or 'not declared'}; "
                f"source date: {item.get('source_date') or 'not declared'}; "
                f"retrieved: {item.get('retrieved_at') or 'not declared'}; "
                f"source: {source}"
            )
    return "\n".join(sections)


def _decision_consistency(result: RunResult) -> dict[str, object]:
    """Compare canonical structured decisions without interpreting model prose.

    A portfolio/risk stage may legitimately override an earlier research or
    trader stance.  Divergence therefore requests review; it is never treated
    as an executable instruction or silently normalized away.
    """
    action_by_rating = {
        "buy": "buy",
        "overweight": "buy",
        "hold": "hold",
        "underweight": "sell",
        "sell": "sell",
        "unknown": "unknown",
    }
    research_rating = result.research_decision.recommendation
    trader_action = result.trader_decision.action
    portfolio_rating = result.portfolio_decision.rating
    expected_trader_action = action_by_rating[portfolio_rating]
    review_reasons: list[str] = []
    if research_rating != portfolio_rating:
        review_reasons.append("The portfolio rating differs from the research-manager rating.")
    if trader_action != expected_trader_action:
        review_reasons.append("The trader action differs from the portfolio rating's directional mapping.")
    if result.processed_signal != portfolio_rating.upper():
        review_reasons.append("The processed signal differs from the canonical portfolio rating.")
    return {
        "schema_version": "decision-consistency.v1",
        "basis": "structured_fields_only",
        "research_rating": research_rating,
        "trader_action": trader_action,
        "portfolio_rating": portfolio_rating,
        "expected_trader_action_from_portfolio_rating": expected_trader_action,
        "processed_signal": result.processed_signal,
        "review_required": bool(review_reasons),
        "review_reasons": review_reasons,
        "non_executable": True,
    }


def _decision_consistency_markdown(receipt: dict[str, object]) -> str:
    status = "review required" if receipt["review_required"] else "consistent"
    reasons = receipt["review_reasons"]
    lines = [
        "## Decision consistency",
        "",
        f"- Structured consistency status: {status}",
        f"- Research rating: {receipt['research_rating']}",
        f"- Trader action: {receipt['trader_action']}",
        f"- Portfolio rating: {receipt['portfolio_rating']}",
        f"- Expected trader action for portfolio rating: {receipt['expected_trader_action_from_portfolio_rating']}",
        (
            "- This is a non-executable analytical consistency receipt; it does not interpret free-form prose "
            "or authorize an order."
        ),
    ]
    if isinstance(reasons, list):
        lines.extend(f"- Review: {reason}" for reason in reasons)
    return "\n".join(lines)


def build_report_artifacts(result: RunResult) -> tuple[Artifact, ...]:
    """Build the exact five CLI report groups plus a consolidated report.

    Empty optional sections are omitted inside a group.  No artifact represents
    a file unless a caller separately and explicitly writes it.
    """
    reports = result.report_sections
    research = result.research_debate_snapshot
    risk = result.risk_debate_snapshot
    portfolio_text = result.portfolio_manager_decision or risk.judge_decision

    groups = (
        _group_artifact(
            ordinal=1,
            slug="analysts",
            title="Analyst Team Reports",
            parts=_present(
                _ReportPart("market", "Market Analyst", reports.market_report),
                _ReportPart("sentiment", "Sentiment Analyst", reports.sentiment_report),
                _ReportPart("news", "News Analyst", reports.news_report),
                _ReportPart("fundamentals", "Fundamentals Analyst", reports.fundamentals_report),
            ),
        ),
        _group_artifact(
            ordinal=2,
            slug="research",
            title="Research Team Decision",
            parts=_present(
                _ReportPart("bull", "Bull Researcher", research.role_histories.get("bull", "")),
                _ReportPart("bear", "Bear Researcher", research.role_histories.get("bear", "")),
                _ReportPart(
                    "manager",
                    "Research Manager",
                    research.judge_decision or result.investment_plan,
                ),
            ),
        ),
        _group_artifact(
            ordinal=3,
            slug="trading",
            title="Trading Team Plan",
            parts=_present(_ReportPart("trader", "Trader", result.trader_investment_plan)),
        ),
        _group_artifact(
            ordinal=4,
            slug="risk",
            title="Risk Management Team Decision",
            parts=_present(
                _ReportPart("aggressive", "Aggressive Analyst", risk.role_histories.get("aggressive", "")),
                _ReportPart("conservative", "Conservative Analyst", risk.role_histories.get("conservative", "")),
                _ReportPart("neutral", "Neutral Analyst", risk.role_histories.get("neutral", "")),
            ),
        ),
        _group_artifact(
            ordinal=5,
            slug="portfolio",
            title="Portfolio Manager Decision",
            parts=_present(_ReportPart("portfolio", "Portfolio Manager", portfolio_text)),
        ),
    )
    report_groups = tuple(group for group in groups if group is not None)
    consolidated_sections = [
        str(group.content["markdown"])
        for group in report_groups
        if isinstance(group.content, dict) and group.content.get("markdown")
    ]
    provenance = _report_provenance(result)
    consistency = _decision_consistency(result)
    provenance_artifact = Artifact(
        id="report.provenance",
        kind="report_provenance",
        title="Retained evidence provenance",
        media_type="application/vnd.tradingagents.report-provenance+json",
        content={**provenance, "markdown": _report_provenance_markdown(provenance)},
    )
    consistency_artifact = Artifact(
        id="analysis.decision_consistency",
        kind="decision_consistency.v1",
        title="Decision consistency receipt",
        media_type="application/vnd.tradingagents.decision-consistency+json",
        content=consistency,
    )
    complete = Artifact(
        id="report.complete",
        kind="complete_report",
        title=f"Trading Analysis Report: {result.request.symbol}",
        media_type="text/markdown",
        content="\n\n".join(
            (
                f"# Trading Analysis Report: {result.request.symbol}",
                f"Analysis date: {result.request.as_of_date}",
                *consolidated_sections,
                _report_provenance_markdown(provenance),
                _decision_consistency_markdown(consistency),
            )
        ),
    )
    durable_storage = result.persistence.writes_expected
    storage = "durable_run_store" if durable_storage else "in_memory_run_store"
    result_descriptor = Artifact(
        id="data.run_result",
        kind="structured_result_descriptor",
        title="Structured run result",
        media_type="application/json",
        content={
            "run_id": result.run_id,
            "representation": "RunResult",
            "availability": f"/api/runs/{result.run_id}/result",
            "storage": storage,
            "disk_write_declared": durable_storage,
        },
    )
    events_descriptor = Artifact(
        id="data.run_events",
        kind="structured_events_descriptor",
        title="Structured run events",
        media_type="application/json",
        content={
            "run_id": result.run_id,
            "representation": "RunEvent[]",
            "availability": f"/api/runs/{result.run_id}/events",
            "storage": storage,
            "disk_write_declared": durable_storage,
        },
    )
    return (*report_groups, provenance_artifact, consistency_artifact, complete, result_descriptor, events_descriptor)


def report_groups(artifacts: tuple[Artifact, ...]) -> list[dict[str, Any]]:
    """Return JSON-safe report groups in canonical ordinal order."""
    groups = [artifact.content for artifact in artifacts if artifact.kind == "report_group"]
    return sorted((dict(group) for group in groups if isinstance(group, dict)), key=lambda item: item["ordinal"])
