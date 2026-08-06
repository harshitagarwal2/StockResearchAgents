"""Deterministic report projections for completed company analytics results.

The report layer formats already-validated contract data. It does not infer new
research conclusions or depend on any executor-specific model output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .company_analytics_v1 import CompanyAnalyticsResultV1
from .contracts import Artifact


def _json_markdown(value: object) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n```"


def _section(title: str, value: object) -> dict[str, object]:
    return {"title": title, "content": value}


def _group_artifact(
    *,
    ordinal: int,
    slug: str,
    title: str,
    sections: Sequence[Mapping[str, object]],
) -> Artifact:
    normalized = [dict(section) for section in sections]
    markdown_parts = [f"## {title}"]
    for section in normalized:
        section_title = str(section["title"])
        content = section.get("content")
        rendered = content if isinstance(content, str) else _json_markdown(content)
        markdown_parts.extend((f"### {section_title}", rendered))
    return Artifact(
        id=f"report.{ordinal}.{slug}",
        kind="report_group",
        title=title,
        media_type="application/vnd.stockresearchagents.report-group+json",
        content={
            "ordinal": ordinal,
            "slug": slug,
            "title": title,
            "sections": normalized,
            "markdown": "\n\n".join(markdown_parts),
        },
    )


def _source_provenance(result: CompanyAnalyticsResultV1) -> dict[str, object]:
    dossier = result.submission.company_research.dossier
    documents = [document.to_dict() for document in dossier.documents]
    return {
        "schema_version": "report-provenance.v1",
        "run_id": result.run_id,
        "as_of_at": dossier.as_of_at,
        "completed_at": dossier.completed_at,
        "document_count": len(documents),
        "claim_count": len(dossier.claims),
        "calculation_count": len(dossier.calculations),
        "documents": documents,
        "source_lineage": result.submission.source_lineage.to_dict(),
    }


def build_report_artifacts(result: CompanyAnalyticsResultV1) -> tuple[Artifact, ...]:
    """Project one completed analytics result into five stable report groups."""
    if not isinstance(result, CompanyAnalyticsResultV1):
        raise TypeError("result must be a CompanyAnalyticsResultV1")

    submission = result.submission
    research = submission.company_research
    dossier = research.dossier
    identity = dossier.identity.to_dict()

    groups = (
        _group_artifact(
            ordinal=1,
            slug="executive-summary",
            title="Executive Summary",
            sections=(
                _section("Company", identity),
                _section("Research conclusion", dossier.executive_summary),
                _section("Analytical rating", {"recommendation": dossier.recommendation, "non_executable": True}),
            ),
        ),
        _group_artifact(
            ordinal=2,
            slug="evidence-and-claims",
            title="Evidence and Claims",
            sections=(
                _section("Source documents", [item.to_dict() for item in dossier.documents]),
                _section("Claims", [item.to_dict() for item in dossier.claims]),
                _section("Structured challenge", [item.to_dict() for item in dossier.arguments]),
                _section("Coverage", [item.to_dict() for item in dossier.coverage]),
            ),
        ),
        _group_artifact(
            ordinal=3,
            slug="analytics-and-valuation",
            title="Analytics and Valuation",
            sections=(
                _section("Metrics", [item.to_dict() for item in dossier.metrics]),
                _section("Valuation cases", [item.to_dict() for item in dossier.valuations]),
                _section("Deterministic analytics", submission.analytics_bundle.to_dict()),
            ),
        ),
        _group_artifact(
            ordinal=4,
            slug="risks-and-counterevidence",
            title="Risks and Counterevidence",
            sections=(
                _section("Risk scenarios", [item.to_dict() for item in dossier.risks]),
                _section("Counterevidence", [item.to_dict() for item in dossier.arguments]),
                _section("Limitations", list(dict.fromkeys((*dossier.limitations, *result.warnings)))),
            ),
        ),
        _group_artifact(
            ordinal=5,
            slug="monitoring-and-quality",
            title="Monitoring and Quality",
            sections=(
                _section("Monitoring conditions", [item.to_dict() for item in dossier.monitoring]),
                _section("Evaluation", dossier.evaluation.to_dict()),
                _section("Research quality", submission.quality_receipt.to_dict()),
                _section("Forecasts", [item.to_dict() for item in submission.forecasts]),
                _section("Run card", submission.run_card.to_dict()),
            ),
        ),
    )

    provenance = _source_provenance(result)
    provenance_artifact = Artifact(
        id="report.provenance",
        kind="report_provenance.v1",
        title="Retained source provenance",
        media_type="application/vnd.stockresearchagents.report-provenance.v1+json",
        content=provenance,
    )
    complete = Artifact(
        id="report.complete",
        kind="complete_report",
        title=f"Company Analytics Report: {identity['symbol']}",
        media_type="text/markdown",
        content="\n\n".join(
            (
                f"# Company Analytics Report: {identity['symbol']}",
                f"Point-in-time cutoff: {dossier.as_of_at}",
                *(str(group.content["markdown"]) for group in groups if isinstance(group.content, dict)),
            )
        ),
    )
    result_descriptor = Artifact(
        id="data.company-analytics-result.v1",
        kind="structured_result_descriptor",
        title="Structured company analytics result",
        media_type="application/json",
        content={
            "run_id": result.run_id,
            "representation": "CompanyAnalyticsResultV1",
            "schema_version": result.schema_version,
            "availability": f"/api/runs/{result.run_id}/result",
        },
    )
    events_descriptor = Artifact(
        id="data.run-events.v1",
        kind="structured_events_descriptor",
        title="Structured run events",
        media_type="application/json",
        content={
            "run_id": result.run_id,
            "representation": "RunEvent[]",
            "availability": f"/api/runs/{result.run_id}/events",
        },
    )
    return (*groups, provenance_artifact, complete, result_descriptor, events_descriptor)


def report_groups(artifacts: tuple[Artifact, ...]) -> list[dict[str, Any]]:
    """Return JSON-safe report groups in canonical ordinal order."""
    groups = [artifact.content for artifact in artifacts if artifact.kind == "report_group"]
    return sorted((dict(group) for group in groups if isinstance(group, dict)), key=lambda item: int(item["ordinal"]))
