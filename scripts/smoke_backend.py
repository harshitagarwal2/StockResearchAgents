"""Deterministic company-analytics backend smoke check used before MCP."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from company_analytics_fixtures import complete_analytics_submission  # noqa: E402

from stock_research_agents.company_analytics import submit_company_analytics  # noqa: E402
from stock_research_agents.company_analytics_v1 import canonical_stage_ids  # noqa: E402
from stock_research_agents.research_quality_v1 import QualityStore  # noqa: E402
from stock_research_agents.store import RunStore  # noqa: E402


def main() -> None:
    result, events = submit_company_analytics(
        complete_analytics_submission("ORCL"),
        store=RunStore(),
        quality_store=QualityStore(),
    )
    assert result.status.value == "completed"
    assert result.schema_version == "company-analytics-result.v1"
    assert tuple(stage.stage_id for stage in result.submission.run_card.stages) == canonical_stage_ids()
    assert result.non_executable is True
    assert events[-1].status == "completed"
    print(f"ok run={result.run_id} stages={len(result.submission.run_card.stages)} events={len(events)}")


if __name__ == "__main__":
    main()
