from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from company_analytics_fixtures import complete_v4_submission
from jsonschema import Draft202012Validator, FormatChecker

from tradingagents_portable.company_analytics_v1 import HostSubmissionV4
from tradingagents_portable.schema_bundle import (
    build_analytics_bundle_v1_schema,
    build_source_lineage_crosswalk_v1_schema,
    load_host_submission_v4_schema_bundle,
)


def _json_submission() -> dict[str, Any]:
    return json.loads(json.dumps(complete_v4_submission()))


def _schema_accepts(payload: object) -> bool:
    return not _schema_errors(payload)


def _schema_errors(payload: object) -> list[str]:
    validator = Draft202012Validator(load_host_submission_v4_schema_bundle(), format_checker=FormatChecker())
    return [
        f"{'.'.join(str(item) for item in error.absolute_path)}: {error.message}"
        for error in validator.iter_errors(payload)
    ]


def _parser_accepts(payload: object) -> bool:
    try:
        HostSubmissionV4.from_dict(payload)
    except (TypeError, ValueError):
        return False
    return True


def _all_refs(value: object) -> list[str]:
    if isinstance(value, list):
        return [reference for item in value for reference in _all_refs(item)]
    if not isinstance(value, dict):
        return []
    references = [value["$ref"]] if isinstance(value.get("$ref"), str) else []
    return references + [reference for item in value.values() for reference in _all_refs(item)]


def _unknown_fact_field(payload: dict[str, Any]) -> None:
    payload["analytics_bundle"]["facts"][0]["unpublished_metric"] = "1"


def _wrong_fact_scale_type(payload: dict[str, Any]) -> None:
    payload["analytics_bundle"]["facts"][0]["scale"] = "0"


def _missing_fact_period(payload: dict[str, Any]) -> None:
    del payload["analytics_bundle"]["facts"][0]["period"]


def _wrong_source_license_shape(payload: dict[str, Any]) -> None:
    payload["analytics_bundle"]["source_licenses"][0]["retention_days"] = "forever"


def _wrong_source_lineage_digest(payload: dict[str, Any]) -> None:
    payload["source_lineage"]["bindings"][0]["content_sha256"] = "not-a-digest"


def _unknown_bundle_field(payload: dict[str, Any]) -> None:
    payload["analytics_bundle"]["raw_provider_response"] = "forbidden"


def _wrong_collection_type(payload: dict[str, Any]) -> None:
    payload["analytics_bundle"]["ratios"] = {}


def _blocked_redistributable_transcript(payload: dict[str, Any]) -> None:
    documents = payload["company_research"]["dossier"]["documents"]
    transcript = next(document for document in documents if document["kind"] == "transcript")
    transcript["entitlement"].update(
        access="entitlement_blocked", redistributable=True, limitation="Access unavailable."
    )


def _non_redistributable_transcript_extract(payload: dict[str, Any]) -> None:
    documents = payload["company_research"]["dossier"]["documents"]
    transcript = next(document for document in documents if document["kind"] == "transcript")
    transcript["entitlement"].update(access="licensed", redistributable=False, limitation="Reference only.")


@pytest.mark.parametrize(
    "mutate",
    [
        _unknown_fact_field,
        _wrong_fact_scale_type,
        _missing_fact_period,
        _wrong_source_license_shape,
        _wrong_source_lineage_digest,
        _unknown_bundle_field,
        _wrong_collection_type,
        _blocked_redistributable_transcript,
        _non_redistributable_transcript_extract,
    ],
)
def test_bundled_schema_and_python_parser_have_structural_corpus_parity(mutate: Any) -> None:
    payload = _json_submission()
    assert _schema_accepts(payload), _schema_errors(payload)
    assert _parser_accepts(payload)

    invalid = deepcopy(payload)
    mutate(invalid)

    assert not _schema_accepts(invalid)
    assert not _parser_accepts(invalid)


def test_v4_parser_rejects_restricted_transcript_segments_beyond_schema_expressiveness() -> None:
    payload = _json_submission()
    documents = payload["company_research"]["dossier"]["documents"]
    transcript_document = next(document for document in documents if document["kind"] == "transcript")
    transcript_document["entitlement"].update(access="licensed", redistributable=False, limitation="Reference only.")
    transcript_document["extract"] = None
    payload["company_research"]["request"]["research_plan"]["coverage_dimensions"][0]["entitlement_policy"] = (
        "host_entitled_allowed"
    )

    # JSON Schema cannot join transcript.document_id to its source in the documents array.
    assert _schema_accepts(payload), _schema_errors(payload)
    with pytest.raises(ValueError, match="cannot include segment extracts.*non-redistributable"):
        HostSubmissionV4.from_dict(payload)


def test_v4_bundle_is_self_contained_and_analytics_collections_are_typed() -> None:
    bundle = load_host_submission_v4_schema_bundle()
    assert bundle["$id"] == "https://tradingagents-portable.local/schemas/host-submission.v4.json"
    assert all(reference.startswith("#/") for reference in _all_refs(bundle))

    analytics = bundle["$defs"]["documents"]["analytics_bundle_v1"]
    collection_names = {
        "facts",
        "statement_snapshots",
        "restatements",
        "ratios",
        "calculation_receipts",
        "dcf_models",
        "dcf_valuations",
        "reverse_dcf_results",
        "comparable_observations",
        "comparable_valuations",
        "analyst_opinions",
        "estimates",
        "consensus",
        "ownership",
        "insider_transactions",
        "short_interest",
        "datasets",
        "splits",
        "factors",
        "experiment_specs",
        "experiments",
        "catalysts",
        "event_clusters",
        "source_licenses",
    }
    for name in collection_names:
        items = analytics["properties"][name]["items"]
        assert set(items) == {"$ref"}, name
        assert items["$ref"].startswith("#/$defs/documents/analytics_bundle_v1/$defs/")


def test_typed_analytics_component_has_no_unconstrained_record_items() -> None:
    schema = build_analytics_bundle_v1_schema()
    for name, property_schema in schema["properties"].items():
        if property_schema.get("type") == "array" and name != "limitations":
            assert property_schema["items"].get("$ref"), name


def test_source_lineage_component_is_typed_and_included_in_self_contained_v4() -> None:
    schema = build_source_lineage_crosswalk_v1_schema()
    assert schema["properties"]["bindings"]["minItems"] == 1
    assert schema["properties"]["bindings"]["items"]["$ref"] == "#/$defs/SourceLineageBindingV1"

    bundle = load_host_submission_v4_schema_bundle()
    assert bundle["properties"]["source_lineage"]["$ref"].startswith("#/$defs/documents/")
    assert "source_lineage_crosswalk_v1" in bundle["$defs"]["documents"]


def test_forecast_run_prefix_remains_a_python_cross_field_invariant() -> None:
    payload = _json_submission()
    payload["forecasts"][0]["forecast_id"] = "forecast.detached"

    # Portable Draft 2020-12 cannot express a $data-style prefix equality.
    assert _schema_accepts(payload)
    assert not _parser_accepts(payload)
