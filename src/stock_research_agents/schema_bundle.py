"""Self-contained JSON Schema bundles for StockResearchAgents integrations.

The checked-in component schemas remain useful for human inspection.  Hosts,
however, need one document that can be transported without a schema registry or
filesystem-relative reference resolution.  This module builds that document and
derives the analytics record shapes from the same immutable dataclasses used by
the Python parser, preventing the two structural contracts from drifting.
"""

from __future__ import annotations

import copy
import json
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from stock_research_agents.analytics_v1 import AnalyticsBundleV1
from stock_research_agents.company_analytics_v1.source_lineage import SourceLineageCrosswalkV1
from stock_research_agents.research_contracts import StrictModel

_WORKFLOW_DIRECTORY = Path(__file__).resolve().parent / "workflow"
_ANALYTICS_SCHEMA_ID = "https://stock-research-agents.local/schemas/company-analytics-submission.v1.json"
_COMPONENT_FILES = {
    "company-research-submission.v1.schema.json": "company_research_submission_v1",
    "analytics-bundle.v1.schema.json": "analytics_bundle_v1",
    "research-lab.v1.schema.json": "research_lab_v1",
    "research-quality.v1.schema.json": "research_quality_v1",
    "source-lineage-crosswalk.v1.schema.json": "source_lineage_crosswalk_v1",
}
_ID_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_DIGEST_PATTERN = "^[a-f0-9]{64}$"
_TIMEZONE_PATTERN = "T.*(?:Z|[+-][0-9]{2}:[0-9]{2})$"


def _read_schema(filename: str) -> dict[str, Any]:
    return json.loads((_WORKFLOW_DIRECTORY / filename).read_text(encoding="utf-8"))


def _field_constraints(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Add only constraints shared by every Python contract using the field name."""
    if schema.get("type") == "string":
        if name == "run_id" or name.endswith("_id"):
            schema["pattern"] = _ID_PATTERN
        elif name.endswith("_sha256") or name.endswith("_digest"):
            schema["pattern"] = _DIGEST_PATTERN
        elif name.endswith("_at"):
            schema.update({"format": "date-time", "pattern": _TIMEZONE_PATTERN})
        elif name in {"start_date", "end_date"}:
            schema["format"] = "date"
    if schema.get("type") == "array":
        schema["maxItems"] = 512
        if name.endswith("_ids"):
            schema["uniqueItems"] = True
    if name in {"canonical_uri", "terms_uri"}:
        candidates = [schema, *schema.get("anyOf", [])]
        for candidate in candidates:
            if candidate.get("type") == "string":
                candidate.update({"format": "uri", "pattern": "^https://", "maxLength": 2_048})
    return schema


def _type_schema(annotation: object, definitions: dict[str, Any]) -> dict[str, Any]:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Literal:
        values = list(arguments)
        return {"const": values[0]} if len(values) == 1 else {"enum": values}
    if origin is tuple:
        item_type = arguments[0] if arguments else Any
        return {"type": "array", "items": _type_schema(item_type, definitions), "maxItems": 512}
    if origin in {Union, UnionType}:
        non_null = [candidate for candidate in arguments if candidate is not type(None)]
        if len(non_null) == 1 and len(arguments) == 2:
            return {"anyOf": [_type_schema(non_null[0], definitions), {"type": "null"}]}
        return {"anyOf": [_type_schema(candidate, definitions) for candidate in arguments]}
    if isinstance(annotation, type) and issubclass(annotation, StrictModel):
        _define_model(annotation, definitions)
        return {"$ref": f"#/$defs/{annotation.__name__}"}
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is Any:
        return {}
    raise TypeError(f"unsupported analytics schema annotation: {annotation!r}")


def _define_model(model: type[StrictModel], definitions: dict[str, Any]) -> None:
    name = model.__name__
    if name in definitions:
        return
    if not is_dataclass(model):
        raise TypeError(f"analytics schema model is not a dataclass: {model!r}")
    definitions[name] = {}
    hints = get_type_hints(model)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields(model):
        properties[field.name] = _field_constraints(field.name, _type_schema(hints[field.name], definitions))
        if field.default is MISSING and field.default_factory is MISSING:
            required.append(field.name)
    definitions[name] = {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def build_analytics_bundle_v1_schema() -> dict[str, Any]:
    """Return a typed analytics-bundle.v1 schema derived from strict models."""
    definitions: dict[str, Any] = {}
    _define_model(AnalyticsBundleV1, definitions)
    root = definitions.pop("AnalyticsBundleV1")
    root.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://stock-research-agents.local/schemas/analytics-bundle.v1.json",
            "title": "Deterministic analytics bundle v1",
            "$defs": definitions,
        }
    )
    return root


def build_source_lineage_crosswalk_v1_schema() -> dict[str, Any]:
    """Return the typed provider-neutral inward source-lineage schema."""
    definitions: dict[str, Any] = {}
    _define_model(SourceLineageCrosswalkV1, definitions)
    root = definitions.pop("SourceLineageCrosswalkV1")
    root.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://stock-research-agents.local/schemas/source-lineage-crosswalk.v1.json",
            "title": "Provider-neutral inward source lineage crosswalk v1",
            "$defs": definitions,
        }
    )
    root["properties"]["bindings"]["minItems"] = 1
    return root


def _rewrite_references(value: object, *, document_key: str) -> object:
    if isinstance(value, list):
        return [_rewrite_references(item, document_key=document_key) for item in value]
    if not isinstance(value, dict):
        return value
    rewritten: dict[str, Any] = {}
    for key, nested in value.items():
        if key == "$id":
            continue
        if key == "$ref" and isinstance(nested, str):
            if nested.startswith("#"):
                rewritten[key] = f"#/$defs/documents/{document_key}{nested[1:]}"
                continue
            filename, separator, fragment = nested.partition("#")
            target = _COMPONENT_FILES.get(filename)
            if target is None:
                raise ValueError(f"analytics schema contains an unsupported external reference: {nested}")
            suffix = fragment if separator else ""
            rewritten[key] = f"#/$defs/documents/{target}{suffix}"
            continue
        rewritten[key] = _rewrite_references(nested, document_key=document_key)
    return rewritten


def load_company_analytics_submission_v1_schema_bundle() -> dict[str, Any]:
    """Load one transportable analytics schema whose references are all root-local."""
    root = _read_schema("company-analytics-submission.v1.schema.json")
    documents: dict[str, Any] = {}
    for filename, document_key in _COMPONENT_FILES.items():
        component = (
            build_analytics_bundle_v1_schema()
            if filename == "analytics-bundle.v1.schema.json"
            else build_source_lineage_crosswalk_v1_schema()
            if filename == "source-lineage-crosswalk.v1.schema.json"
            else _read_schema(filename)
        )
        documents[document_key] = _rewrite_references(component, document_key=document_key)
    bundle = _rewrite_references(root, document_key="company_analytics_submission_v1")
    if not isinstance(bundle, dict):  # pragma: no cover - root is a checked-in object
        raise TypeError("company-analytics-submission.v1 schema must be an object")
    bundle["$id"] = _ANALYTICS_SCHEMA_ID
    existing_definitions = bundle.setdefault("$defs", {})
    if not isinstance(existing_definitions, dict):
        raise ValueError("company-analytics-submission.v1 $defs must be an object")
    existing_definitions["documents"] = documents
    return copy.deepcopy(bundle)


__all__ = [
    "build_analytics_bundle_v1_schema",
    "build_source_lineage_crosswalk_v1_schema",
    "load_company_analytics_submission_v1_schema_bundle",
]
