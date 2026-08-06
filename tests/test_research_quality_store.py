from __future__ import annotations

import json

import pytest
from company_analytics_fixtures import complete_analytics_submission

from stock_research_agents.company_analytics import (
    get_company_research_quality,
    quality_projection_for_result,
    submit_company_analytics,
)
from stock_research_agents.company_analytics_v1 import CompanyAnalyticsSubmissionV1
from stock_research_agents.research_quality_v1 import OutcomeObservation, QualityStore
from stock_research_agents.store import RunStore


def _outcome(forecast_id: str, *, correction: bool = False) -> OutcomeObservation:
    return OutcomeObservation(
        "research-quality.v1",
        "outcome.corrected" if correction else "outcome.initial",
        forecast_id,
        "2027-08-02T00:00:00Z",
        "2027-08-02T00:05:00Z",
        "2027-08-02T00:10:00Z",
        "resolved",
        False if correction else True,
        None,
        None,
        None,
        ("outcome.document",),
        "host-owned primary-source resolver",
        "outcome.initial" if correction else None,
    )


def test_quality_store_persists_append_only_corrections_and_scorecards(tmp_path) -> None:
    submission = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("META"))
    store = QualityStore(tmp_path / "quality")
    store.register(submission.quality_receipt, submission.forecasts)
    forecast = submission.forecasts[0]

    initial = store.append_outcome(_outcome(forecast.forecast_id))
    corrected = store.append_outcome(_outcome(forecast.forecast_id, correction=True))

    assert initial.status == "scored"
    assert corrected.observation_id == "outcome.corrected"
    assert initial.metrics[0].value != corrected.metrics[0].value
    projection = QualityStore(tmp_path / "quality").projection(submission.run_card.run_id)
    assert projection is not None
    assert len(projection["outcome_ledgers"][0]["observations"]) == 2  # type: ignore[index]
    assert projection["scorecards"][0]["observation_id"] == "outcome.corrected"  # type: ignore[index]


def test_quality_store_registration_and_outcome_append_are_idempotent(tmp_path) -> None:
    submission = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("ORCL"))
    store = QualityStore(tmp_path / "quality")
    store.register(submission.quality_receipt, submission.forecasts)
    store.register(submission.quality_receipt, submission.forecasts)
    observation = _outcome(submission.forecasts[0].forecast_id)

    assert store.append_outcome(observation) == store.append_outcome(observation)
    projection = store.projection(submission.run_card.run_id)
    assert projection is not None
    assert len(projection["outcome_ledgers"][0]["observations"]) == 1  # type: ignore[index]


def test_staged_quality_registration_is_hidden_until_publish_and_recovers(tmp_path) -> None:
    submission = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("META"))
    path = tmp_path / "quality"
    store = QualityStore(path)
    store.stage_registration(submission.quality_receipt, submission.forecasts)

    assert store.projection(submission.run_card.run_id) is None
    assert store.is_published(submission.run_card.run_id) is False

    restarted = QualityStore(path)
    restarted.publish_registration(submission.run_card.run_id)
    assert restarted.is_published(submission.run_card.run_id) is True
    assert restarted.projection(submission.run_card.run_id) is not None


def test_analytics_result_publish_failure_leaves_quality_registration_hidden(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = complete_analytics_submission("META")
    submission = CompanyAnalyticsSubmissionV1.from_dict(payload)
    run_store = RunStore(tmp_path / "runs")
    quality_store = QualityStore(tmp_path / "quality")

    def fail_publish(run_id: str):
        raise OSError(f"injected result publication failure for {run_id}")

    monkeypatch.setattr(run_store, "publish_staged", fail_publish)
    with pytest.raises(OSError, match="injected result publication failure"):
        submit_company_analytics(payload, store=run_store, quality_store=quality_store)

    assert run_store.get_result(submission.run_card.run_id) is None
    assert quality_store.projection(submission.run_card.run_id) is None
    assert quality_store.is_published(submission.run_card.run_id) is False


def test_completed_artifacts_project_quality_without_registration_after_publish_interruption(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = complete_analytics_submission("META")
    submission = CompanyAnalyticsSubmissionV1.from_dict(payload)
    run_store = RunStore(tmp_path / "runs")
    quality_store = QualityStore(tmp_path / "quality")
    original_publish = quality_store.publish_registration

    def fail_quality_publish(run_id: str):
        raise OSError(f"injected quality publication failure for {run_id}")

    monkeypatch.setattr(quality_store, "publish_registration", fail_quality_publish)
    with pytest.raises(OSError, match="injected quality publication failure"):
        submit_company_analytics(payload, store=run_store, quality_store=quality_store)

    result = run_store.get_result(submission.run_card.run_id)
    assert result is not None
    assert quality_store.projection(submission.run_card.run_id) is None

    monkeypatch.setattr(quality_store, "publish_registration", original_publish)
    projection = quality_projection_for_result(result, quality_store=quality_store)
    assert projection is not None
    assert quality_store.is_published(submission.run_card.run_id) is False


def test_read_only_quality_fallback_does_not_write_registration_state(tmp_path) -> None:
    payload = complete_analytics_submission("META")
    submission = CompanyAnalyticsSubmissionV1.from_dict(payload)
    run_store = RunStore(tmp_path / "runs")
    result, _ = submit_company_analytics(payload, store=run_store, quality_store=QualityStore())
    quality_path = tmp_path / "read-only-quality"
    quality_store = QualityStore(quality_path)

    view_projection = quality_projection_for_result(result, quality_store=quality_store)
    query_projection = get_company_research_quality(
        submission.run_card.run_id,
        quality_store=quality_store,
        run_store=run_store,
    )

    assert view_projection == query_projection["research_quality"]
    assert view_projection is not None
    assert view_projection["receipt"] == submission.quality_receipt.to_dict()
    assert quality_store.projection(submission.run_card.run_id) is None
    assert quality_store.is_published(submission.run_card.run_id) is False
    assert quality_path.exists() is False


def test_unnamespaced_local_registration_is_rejected(tmp_path) -> None:
    submission = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("META"))
    state_dir = tmp_path / "quality"
    registration_dir = state_dir / "registrations"
    registration_dir.mkdir(parents=True)
    forecast = submission.forecasts[0].to_dict()
    forecast["forecast_id"] = "unnamespaced.forecast.primary"
    path = registration_dir / f"{submission.run_card.run_id}.json"
    path.write_text(
        json.dumps({"receipt": submission.quality_receipt.to_dict(), "forecasts": [forecast]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="globally namespaced by run_id"):
        QualityStore(state_dir).projection(submission.run_card.run_id)


def test_run_namespaces_allow_same_forecast_suffix_across_quality_runs(tmp_path) -> None:
    meta = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("META"))
    oracle = CompanyAnalyticsSubmissionV1.from_dict(complete_analytics_submission("ORCL"))
    store = QualityStore(tmp_path / "quality")

    store.register(meta.quality_receipt, meta.forecasts)
    store.register(oracle.quality_receipt, oracle.forecasts)

    assert store.projection(meta.run_card.run_id) is not None
    assert store.projection(oracle.run_card.run_id) is not None
    assert meta.forecasts[0].forecast_id.endswith(".forecast.meta.primary")
    assert oracle.forecasts[0].forecast_id.endswith(".forecast.orcl.primary")
