from __future__ import annotations

from collections.abc import Callable

import pytest
from research_submission_fixtures import complete_research_submission

from stock_research_agents.research_conformance import validate_research_dossier
from stock_research_agents.research_contracts import parse_company_research_submission_v1

Payload = dict[str, object]
Mutation = Callable[[Payload], None]


def _dossier(payload: Payload) -> dict[str, object]:
    dossier = payload["dossier"]
    assert isinstance(dossier, dict)
    return dossier


def _request(payload: Payload) -> dict[str, object]:
    request = payload["request"]
    assert isinstance(request, dict)
    return request


def _set_identity(payload: Payload, **changes: object) -> None:
    for container in (_request(payload), _dossier(payload)):
        identity = container["identity"]
        assert isinstance(identity, dict)
        identity.update(changes)


def _set_document_and_metric_vintages_to_cutoff(payload: Payload) -> None:
    dossier = _dossier(payload)
    dossier["documents"][0]["temporal"].update(
        observed_at="2026-07-31T20:00:00Z",
        published_at="2026-07-31T20:00:00Z",
        available_at="2026-07-31T20:00:00Z",
        retrieved_at="2026-07-31T20:00:00Z",
    )
    for metric in dossier["metrics"]:
        metric["as_of_at"] = "2026-07-31T20:00:00Z"


def _set_calculation(
    payload: Payload,
    *,
    operation: str,
    formula: str,
    input_indexes: tuple[int, ...],
    result: float,
    rounding_digits: int | None = 12,
    tolerance: float = 1e-9,
) -> None:
    dossier = _dossier(payload)
    metrics = dossier["metrics"]
    calculations = dossier["calculations"]
    valuations = dossier["valuations"]
    assert isinstance(metrics, list)
    assert isinstance(calculations, list)
    assert isinstance(valuations, list)
    metric_ids = [metrics[index]["id"] for index in input_indexes]
    calculations[0].update(
        operation=operation,
        formula=formula.format(*metric_ids),
        input_metric_ids=metric_ids,
        result=result,
        rounding_digits=rounding_digits,
        tolerance=tolerance,
    )
    metrics[2]["value"] = result
    valuations[0]["fair_value"] = result
    valuations[0]["sensitivity_cells"][0]["fair_value"] = result


@pytest.mark.parametrize(
    ("case", "mutate", "message"),
    [
        (
            "request-dossier-cutoff",
            lambda payload: _request(payload).update(cutoff_at="2026-07-31T21:00:00Z"),
            "exactly match",
        ),
        (
            "request-dossier-identity",
            lambda payload: _request(payload)["identity"].update(symbol="DIFFERENT"),
            "identity must exactly match",
        ),
        (
            "document-dossier-cutoff",
            lambda payload: _dossier(payload)["documents"][0]["temporal"].update(cutoff_at="2026-07-31T19:59:59Z"),
            "different research cutoff",
        ),
    ],
)
def test_host_submission_rejects_exact_boundary_mismatch(case: str, mutate: Mutation, message: str) -> None:
    payload = complete_research_submission("ORCL")
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize(
    ("case", "mutate", "message"),
    [
        (
            "document",
            lambda payload: _dossier(payload)["documents"][0]["temporal"].update(available_at="2026-07-31T20:00:01Z"),
            "available by cutoff",
        ),
        (
            "filing",
            lambda payload: _dossier(payload)["filings"][0].update(filed_at="2026-07-31T20:00:01Z"),
            "filing .* unavailable",
        ),
        (
            "transcript",
            lambda payload: _dossier(payload)["transcripts"][0].update(event_at="2026-07-31T20:00:01Z"),
            "transcript .* after",
        ),
        (
            "factor",
            lambda payload: _dossier(payload)["factors"][0].update(as_of_at="2026-07-31T20:00:01Z"),
            "factor .* leaks",
        ),
        (
            "historical-event",
            lambda payload: _dossier(payload)["events"][0].update(occurred_at="2026-07-31T20:00:01Z"),
            "historical event .* after",
        ),
        (
            "prior-outcome",
            lambda payload: _dossier(payload)["prior_outcomes"][0].update(evaluated_at="2026-07-31T20:00:01Z"),
            "prior outcome .* unavailable",
        ),
    ],
)
def test_temporal_records_reject_one_microstep_after_cutoff(case: str, mutate: Mutation, message: str) -> None:
    payload = complete_research_submission("ORCL")
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        (
            "document",
            _set_document_and_metric_vintages_to_cutoff,
        ),
        ("filing", lambda payload: _dossier(payload)["filings"][0].update(filed_at="2026-07-31T20:00:00Z")),
        (
            "transcript",
            lambda payload: _dossier(payload)["transcripts"][0].update(event_at="2026-07-31T20:00:00Z"),
        ),
        ("factor", lambda payload: _dossier(payload)["factors"][0].update(as_of_at="2026-07-31T20:00:00Z")),
        (
            "historical-event",
            lambda payload: _dossier(payload)["events"][0].update(occurred_at="2026-07-31T20:00:00Z"),
        ),
        (
            "prior-outcome",
            lambda payload: _dossier(payload)["prior_outcomes"][0].update(evaluated_at="2026-07-31T20:00:00Z"),
        ),
    ],
)
def test_temporal_records_accept_exact_cutoff(case: str, mutate: Mutation) -> None:
    payload = complete_research_submission("ORCL")
    mutate(payload)

    parsed = parse_company_research_submission_v1(payload)

    assert parsed.dossier.as_of_at == "2026-07-31T20:00:00Z"


def test_host_submission_rejects_omitted_planned_coverage_dimension() -> None:
    payload = complete_research_submission("META")
    _dossier(payload)["coverage"].pop()

    with pytest.raises(ValueError, match="coverage omits planned dimensions"):
        parse_company_research_submission_v1(payload)


def test_claim_rejects_entitlement_blocked_only_grounding() -> None:
    payload = complete_research_submission("ORCL")
    dossier = _dossier(payload)
    blocked_id = next(
        document["id"]
        for document in dossier["documents"]
        if document["entitlement"]["access"] == "entitlement_blocked"
    )
    dossier["claims"][0]["evidence_document_ids"] = [blocked_id]
    dossier["claims"][0]["metric_ids"] = []

    with pytest.raises(ValueError, match="accessible source document"):
        parse_company_research_submission_v1(payload)


def test_metric_rejects_entitlement_blocked_only_grounding() -> None:
    payload = complete_research_submission("ORCL")
    dossier = _dossier(payload)
    blocked_id = next(
        document["id"]
        for document in dossier["documents"]
        if document["entitlement"]["access"] == "entitlement_blocked"
    )
    dossier["metrics"][0]["source_document_ids"] = [blocked_id]

    with pytest.raises(ValueError, match="accessible source document"):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize(
    ("collection", "mutate"),
    [
        (
            "calculation",
            lambda d: d["calculations"][0].update(input_metric_ids=["missing-metric", d["metrics"][1]["id"]]),
        ),
        ("metric", lambda d: d["metrics"][0].update(source_document_ids=["missing-document"])),
        ("claim", lambda d: d["claims"][0].update(metric_ids=["missing-metric"])),
        ("argument", lambda d: d["arguments"][0].update(claim_ids=["missing-claim"])),
        ("filing", lambda d: d["filings"][0].update(document_id="missing-document")),
        ("filing-change", lambda d: d["filing_changes"][0].update(metric_ids=["missing-metric"])),
        ("transcript", lambda d: d["transcripts"][0].update(guidance_claim_ids=["missing-claim"])),
        ("guidance", lambda d: d["guidance"][0].update(claim_id="missing-claim")),
        ("peer", lambda d: d["peers"][0].update(metric_ids=["missing-metric"])),
        ("factor", lambda d: d["factors"][0].update(history_document_ids=["missing-document"])),
        ("valuation", lambda d: d["valuations"][0].update(calculation_ids=["missing-calculation"])),
        ("event", lambda d: d["events"][0].update(entity_ids=["missing-entity"])),
        ("risk", lambda d: d["risks"][0].update(trigger_metric_ids=["missing-metric"])),
        ("monitoring", lambda d: d["monitoring"][0].update(related_ids=["missing-research-id"])),
        ("prior-outcome", lambda d: d["prior_outcomes"][0].update(forecast_claim_id="missing-claim")),
        ("evaluation", lambda d: d["evaluation"]["checks"][0].update(calculation_ids=["missing-calculation"])),
        ("coverage", lambda d: d["coverage"][0].update(source_document_ids=["missing-document"])),
        ("research-delta", lambda d: d["research_delta"].update(changed_valuation_ids=["missing-valuation"])),
        ("portfolio-impact", lambda d: d["portfolio_impact"].update(metric_ids=["missing-metric"])),
    ],
)
def test_major_collection_references_reject_unknown_identifiers(
    collection: str, mutate: Callable[[dict[str, object]], None]
) -> None:
    payload = complete_research_submission("BASE")
    mutate(_dossier(payload))

    with pytest.raises(ValueError, match="references unknown"):
        parse_company_research_submission_v1(payload)


@pytest.mark.parametrize(
    ("operation", "formula", "input_indexes", "result"),
    [
        ("add", "{0} + {1}", (0, 1), 25.0),
        ("subtract", "{0} - {1}", (0, 1), -15.0),
        ("divide", "{0} / {1}", (0, 1), 0.25),
        ("sum", "{0} + {1}", (0, 1), 25.0),
        ("average", "({0} + {1}) / 2", (0, 1), 12.5),
        ("identity", "{0}", (0,), 5.0),
    ],
)
def test_supported_calculation_expressions_are_reproducible(
    operation: str, formula: str, input_indexes: tuple[int, ...], result: float
) -> None:
    payload = complete_research_submission("BASE")
    _set_calculation(
        payload,
        operation=operation,
        formula=formula,
        input_indexes=input_indexes,
        result=result,
    )

    parsed = parse_company_research_submission_v1(payload)
    report = validate_research_dossier(parsed.dossier.to_dict())

    assert report.passed, report.to_dict()


def test_typed_multiply_operation_supports_a_declared_scale_constant() -> None:
    payload = complete_research_submission("BASE")
    dossier = _dossier(payload)
    calculation = dossier["calculations"][0]
    calculated_metric = dossier["metrics"][2]
    valuation = dossier["valuations"][0]
    scaled_result = calculation["result"] * 2
    calculation["formula"] = f"{calculation['formula']} * scale"
    calculation["constants"] = [{"name": "scale", "value": 2.0}]
    calculation["result"] = scaled_result
    calculated_metric["value"] = scaled_result
    valuation["fair_value"] = scaled_result
    valuation["sensitivity_cells"][0]["fair_value"] = scaled_result

    parsed = parse_company_research_submission_v1(payload)
    report = validate_research_dossier(parsed.dossier.to_dict())

    assert report.passed, report.to_dict()


def test_identity_operation_rejects_a_unary_transformation() -> None:
    payload = complete_research_submission("BASE")
    _set_calculation(
        payload,
        operation="identity",
        formula="-({0})",
        input_indexes=(0,),
        result=-5.0,
    )

    report = validate_research_dossier(_dossier(payload))

    assert any(issue.path == "$.calculations[0].result" for issue in report.issues)


def test_average_operation_requires_sum_divided_by_the_declared_input_count() -> None:
    payload = complete_research_submission("BASE")
    _set_calculation(
        payload,
        operation="average",
        formula="({0} + {1}) / 3",
        input_indexes=(0, 1),
        result=25.0 / 3.0,
    )

    report = validate_research_dossier(_dossier(payload))

    assert any(issue.path == "$.calculations[0].result" for issue in report.issues)


@pytest.mark.parametrize(
    ("case", "result", "rounding_digits", "tolerance"),
    [
        ("declared-rounding", 1.67, 2, 1e-9),
        ("declared-tolerance", 1.671, 12, 0.005),
    ],
)
def test_calculation_recomputation_honors_declared_rounding_and_tolerance(
    case: str, result: float, rounding_digits: int, tolerance: float
) -> None:
    payload = complete_research_submission("BASE")
    _dossier(payload)["metrics"][1]["value"] = 3.0
    _set_calculation(
        payload,
        operation="divide",
        formula="{0} / {1}",
        input_indexes=(0, 1),
        result=result,
        rounding_digits=rounding_digits,
        tolerance=tolerance,
    )

    report = validate_research_dossier(_dossier(payload))

    assert report.passed, report.to_dict()


@pytest.mark.parametrize(
    ("case", "formula", "result"),
    [
        ("division-by-zero", "{0} / 0", 0.0),
        ("unsupported-identifier", "{0} + unbound", 5.0),
        ("exponent-bound", "{0} ** 11", 48_828_125.0),
        ("non-finite-result", "{0}", float("inf")),
    ],
)
def test_unsafe_calculation_expressions_fail_reproducibility(case: str, formula: str, result: float) -> None:
    payload = complete_research_submission("ORCL")
    _set_calculation(
        payload,
        operation="identity",
        formula=formula,
        input_indexes=(0,),
        result=result,
    )

    report = validate_research_dossier(_dossier(payload))

    assert any(issue.check == "reproducibility" for issue in report.issues), report.to_dict()


@pytest.mark.parametrize(
    ("symbol", "asset_type"),
    [
        ("BRK.B", "equity"),
        ("BTC-USD", "crypto"),
        ("1234", "equity"),
        ("ETHUSD", "crypto"),
        ("VTI", "fund"),
        ("A" * 32, "equity"),
    ],
)
def test_portable_identity_accepts_bounded_harness_symbols(symbol: str, asset_type: str) -> None:
    payload = complete_research_submission("BASE")
    _set_identity(
        payload,
        symbol=symbol,
        asset_type=asset_type,
        instrument_id=f"{asset_type}:fixture:instrument-1",
        exchange="CRYPTO" if asset_type == "crypto" else "NASDAQ",
        cik=None if asset_type == "crypto" else "0000000001",
    )

    parsed = parse_company_research_submission_v1(payload)

    assert parsed.request.identity.symbol == symbol
    assert parsed.request.identity.asset_type == asset_type


@pytest.mark.parametrize("symbol", ["BAD SYMBOL", " META", "META\n", "株", "A" * 33])
def test_portable_identity_rejects_ambiguous_or_overlong_symbols(symbol: str) -> None:
    payload = complete_research_submission("BASE")
    _set_identity(payload, symbol=symbol)

    with pytest.raises(ValueError, match="identity.symbol"):
        parse_company_research_submission_v1(payload)
