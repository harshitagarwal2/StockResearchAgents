from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import submit_company_analytics
from stock_research_agents.company_analytics_v1 import CompanyAnalyticsSubmissionV1
from stock_research_agents.presentation import ViewerDaemonPresenter
from stock_research_agents.research_quality_v1 import OutcomeObservation, QualityStore
from stock_research_agents.store import RunStore


def _append_outcome_in_child(quality_dir: str, payload: dict[str, object]) -> None:
    store = QualityStore(quality_dir)
    store.append_outcome(OutcomeObservation.from_dict(payload))


def _authenticated_view(presentation_url: str, run_id: str) -> dict[str, object]:
    parsed = urlsplit(presentation_url)
    token = parse_qs(parsed.fragment)["access_token"][0]
    request = Request(
        f"{parsed.scheme}://{parsed.netloc}/api/runs/{quote(run_id, safe='')}/view",
        headers={"X-StockResearchAgents-Viewer-Token": token},
    )
    with urlopen(request, timeout=5) as response:  # noqa: S310 - authenticated loopback URL
        payload = json.load(response)
    assert isinstance(payload, dict)
    return payload


def test_long_lived_viewer_reloads_analytics_quality_outcomes_written_by_another_process(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    run_store = RunStore(state_dir)
    quality_dir = state_dir / "quality"
    submission_payload = complete_analytics_submission("ADBE")
    submission = CompanyAnalyticsSubmissionV1.from_dict(submission_payload)
    result, _ = submit_company_analytics(
        submission_payload,
        store=run_store,
        quality_store=QualityStore(quality_dir),
    )
    presenter = ViewerDaemonPresenter(run_store, startup_timeout=8)

    try:
        link = presenter.present(result.run_id)
        assert link.status == "ready"
        assert link.url is not None
        initial = _authenticated_view(link.url, result.run_id)
        initial_history = initial["view"]["research_lab"]["quality_history"]  # type: ignore[index]
        assert initial_history["outcome_ledgers"][0]["observations"] == []  # type: ignore[index]

        outcome = OutcomeObservation(
            "research-quality.v1",
            "outcome.initial",
            submission.forecasts[0].forecast_id,
            "2027-08-02T00:00:00Z",
            "2027-08-02T00:05:00Z",
            "2027-08-02T00:10:00Z",
            "resolved",
            True,
            None,
            None,
            None,
            ("outcome.document",),
            "host-owned primary-source resolver",
            None,
        )
        process = multiprocessing.get_context("spawn").Process(
            target=_append_outcome_in_child,
            args=(str(quality_dir), outcome.to_dict()),
        )
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0

        refreshed = _authenticated_view(link.url, result.run_id)
        refreshed_history = refreshed["view"]["research_lab"]["quality_history"]  # type: ignore[index]
        assert len(refreshed_history["outcome_ledgers"][0]["observations"]) == 1  # type: ignore[index]
        assert refreshed_history["scorecards"][0]["observation_id"] == "outcome.initial"  # type: ignore[index]
    finally:
        presenter.stop(timeout=5)
