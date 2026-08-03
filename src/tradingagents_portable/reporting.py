"""Canonical, side-effect-free report artifacts for every executor.

The upstream CLI presents five ordered groups.  This module preserves that
information model in memory so MCP, a dashboard, or another harness can render
the same report without requiring filesystem writes.
"""

from __future__ import annotations

from dataclasses import dataclass
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
            )
        ),
    )
    result_descriptor = Artifact(
        id="data.run_result",
        kind="structured_result_descriptor",
        title="Structured run result",
        media_type="application/json",
        content={
            "run_id": result.run_id,
            "representation": "RunResult",
            "availability": f"/api/runs/{result.run_id}/result",
            "storage": "in_memory_run_store",
            "disk_write_declared": False,
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
            "storage": "in_memory_run_store",
            "disk_write_declared": False,
        },
    )
    return (*report_groups, complete, result_descriptor, events_descriptor)


def report_groups(artifacts: tuple[Artifact, ...]) -> list[dict[str, Any]]:
    """Return JSON-safe report groups in canonical ordinal order."""
    groups = [artifact.content for artifact in artifacts if artifact.kind == "report_group"]
    return sorted((dict(group) for group in groups if isinstance(group, dict)), key=lambda item: item["ordinal"])
