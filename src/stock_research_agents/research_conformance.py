"""Deterministic semantic validation for dict-like company research dossiers."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import isfinite
from numbers import Real

from .contracts import reject_secret_shaped_keys

RESEARCH_CONFORMANCE_VERSION = "1.0.0"
_TIMESTAMP_KEYS = frozenset(
    {
        "as_of_at",
        "available_at",
        "availability_timestamp",
        "created_at",
        "event_at",
        "filed_at",
        "forecast_at",
        "observed_at",
        "published_at",
        "released_at",
    }
)
_REFERENCE_FIELDS = {
    "source_id": "document",
    "source_ids": "document",
    "source_document_ids": "document",
    "added_document_ids": "document",
    "document_ids": "document",
    "history_document_ids": "document",
    "outcome_document_ids": "document",
    "prior_document_id": "document",
    "current_document_id": "document",
    "document_id": "document",
    "evidence_id": "document",
    "evidence_ids": "document",
    "evidence_document_ids": "document",
    "counterevidence_document_ids": "document",
    "claim_id": "claim",
    "claim_ids": "claim",
    "counterclaim_ids": "claim",
    "guidance_claim_ids": "claim",
    "assumption_claim_ids": "claim",
    "checked_claim_ids": "claim",
    "changed_claim_ids": "claim",
    "assumption_ids": "claim",
    "forecast_claim_id": "claim",
    "metric_id": "metric",
    "metric_ids": "metric",
    "input_metric_ids": "metric",
    "trigger_metric_ids": "metric",
    "calculation_id": "calculation",
    "calculation_ids": "calculation",
    "checked_calculation_ids": "calculation",
    "valuation_id": "valuation",
    "valuation_ids": "valuation",
    "changed_valuation_ids": "valuation",
    "rebuttal_of": "argument",
}


@dataclass(frozen=True, slots=True)
class ResearchConformanceIssue:
    check: str
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "path": self.path, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ResearchConformanceReport:
    issues: tuple[ResearchConformanceIssue, ...]
    schema_version: str = RESEARCH_CONFORMANCE_VERSION

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _objects(value: object, path: str = "$") -> Iterable[tuple[str, Mapping[str, object]]]:
    if isinstance(value, Mapping):
        yield path, value
        for key, nested in value.items():
            yield from _objects(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, nested in enumerate(value):
            yield from _objects(nested, f"{path}[{index}]")


def _items(dossier: Mapping[str, object], *names: str) -> tuple[Mapping[str, object], ...]:
    for name in names:
        value = dossier.get(name)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _identifier(item: Mapping[str, object]) -> str | None:
    value = item.get("id", item.get("argument_id"))
    return value if isinstance(value, str) and value else None


def _parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(raw), datetime.max.time(), tzinfo=UTC)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _cutoff(dossier: Mapping[str, object]) -> datetime | None:
    for key in ("cutoff", "cutoff_at", "as_of", "as_of_at", "as_of_date", "research_cutoff"):
        parsed = _parse_instant(dossier.get(key))
        if parsed is not None:
            return parsed
    request = dossier.get("request")
    return _cutoff(request) if isinstance(request, Mapping) else None


def _refs(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _append(issues: list[ResearchConformanceIssue], check: str, path: str, detail: str) -> None:
    issues.append(ResearchConformanceIssue(check, path, detail))


def _validate_temporal(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    cutoff = _cutoff(dossier)
    completed = _parse_instant(dossier.get("completed_at"))
    if cutoff is None:
        _append(issues, "temporal_safety", "$", "an explicit valid research cutoff is required")
        return
    if completed is None or completed < cutoff:
        _append(issues, "temporal_safety", "$.completed_at", "a valid completion at or after cutoff is required")
        return
    for path, item in _objects(dossier):
        for key, value in item.items():
            normalized = str(key).lower()
            if normalized == "cutoff_at":
                instant = _parse_instant(value)
                if instant is None or instant != cutoff:
                    _append(issues, "temporal_safety", f"{path}.{key}", "nested cutoff must match dossier cutoff")
                continue
            if normalized in {"retrieved_at", "evaluated_at"}:
                instant = _parse_instant(value)
                if instant is None or instant > completed:
                    _append(issues, "temporal_safety", f"{path}.{key}", "operation occurred after dossier completion")
                continue
            if normalized == "period_end":
                instant = _parse_instant(value)
                if instant is None:
                    _append(issues, "temporal_safety", f"{path}.{key}", "economic period timestamp is invalid")
                elif item.get("basis") == "reported" and instant > cutoff:
                    _append(
                        issues,
                        "temporal_safety",
                        f"{path}.{key}",
                        "reported period ends after the cutoff",
                    )
                continue
            if normalized not in _TIMESTAMP_KEYS:
                if normalized == "occurred_at" and item.get("status") == "historical":
                    instant = _parse_instant(value)
                    if instant is None or instant > cutoff:
                        _append(
                            issues,
                            "temporal_safety",
                            f"{path}.{key}",
                            "historical event occurs after the cutoff",
                        )
                continue
            instant = _parse_instant(value)
            if instant is None:
                _append(issues, "temporal_safety", f"{path}.{key}", "availability timestamp is invalid")
            elif instant > cutoff:
                _append(issues, "temporal_safety", f"{path}.{key}", "information was unavailable at the cutoff")


def _validate_references(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    collections = {
        "document": (
            *_items(dossier, "documents"),
            *_items(dossier, "sources"),
            *_items(dossier, "evidence", "evidence_items"),
        ),
        "claim": _items(dossier, "claims"),
        "metric": _items(dossier, "metrics"),
        "calculation": _items(dossier, "calculations"),
        "valuation": _items(dossier, "valuations"),
        "argument": _items(dossier, "arguments", "debate", "debate_turns", "research_debate"),
    }
    identifiers = {kind: {_identifier(item) for item in items} - {None} for kind, items in collections.items()}
    for kind, items in collections.items():
        if len(identifiers[kind]) != len(items):
            _append(issues, "reference_integrity", f"$.{kind}s", "items require unique non-empty ids")
    for path, item in _objects(dossier):
        for field, kind in _REFERENCE_FIELDS.items():
            if field not in item:
                continue
            references = _refs(item[field])
            if references and any(reference not in identifiers[kind] for reference in references):
                _append(issues, "reference_integrity", f"{path}.{field}", f"unresolved {kind} reference")
        if "related_ids" in item:
            known_ids = set().union(*identifiers.values())
            for value in dossier.values():
                if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
                    known_ids.update(
                        identifier
                        for candidate in value
                        if isinstance(candidate, Mapping) and (identifier := _identifier(candidate)) is not None
                    )
            references = _refs(item["related_ids"])
            if not references or any(reference not in known_ids for reference in references):
                _append(issues, "reference_integrity", f"{path}.related_ids", "unresolved research reference")
    for index, claim in enumerate(collections["claim"]):
        grounded = (
            _refs(claim.get("evidence_ids"))
            or _refs(claim.get("source_ids"))
            or _refs(claim.get("evidence_document_ids"))
            or _refs(claim.get("metric_ids"))
        )
        if not grounded:
            _append(issues, "reference_integrity", f"$.claims[{index}]", "claim requires retained evidence or sources")


def _validate_metrics(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    for index, metric in enumerate(_items(dossier, "metrics")):
        path = f"$.metrics[{index}]"
        if not isinstance(metric.get("unit"), str) or not str(metric["unit"]).strip():
            _append(issues, "metric_semantics", f"{path}.unit", "metric unit is required")
        period = (
            metric.get("period") or metric.get("fiscal_period") or metric.get("period_end") or metric.get("as_of_date")
        )
        if not isinstance(period, str) or not period.strip():
            _append(issues, "metric_semantics", path, "metric period is required")
        value = metric.get("value")
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
            _append(issues, "metric_semantics", f"{path}.value", "metric value must be a finite numeric value")


def _reproducible(item: Mapping[str, object]) -> bool:
    formula = item.get("formula") or item.get("method")
    inputs = item.get("inputs") or item.get("input_metric_ids") or item.get("assumptions")
    result = item.get("result", item.get("value"))
    return (
        isinstance(formula, str)
        and bool(formula.strip())
        and isinstance(inputs, Mapping | list | tuple)
        and bool(inputs)
        and isinstance(result, Real)
        and not isinstance(result, bool)
        and isfinite(result)
    )


def _normalized_formula(
    formula: str,
    inputs: Mapping[str, float],
) -> tuple[ast.Expression, dict[str, float], frozenset[str]]:
    """Replace stable input IDs and return a bounded expression plus used lineage."""
    expression = formula
    environment: dict[str, float] = {}
    used_inputs: set[str] = set()
    for index, (input_id, value) in enumerate(sorted(inputs.items(), key=lambda pair: (-len(pair[0]), pair[0]))):
        variable = f"_input_{index}"
        pattern = rf"(?<![A-Za-z0-9._:-]){re.escape(input_id)}(?![A-Za-z0-9._:-])"
        expression, count = re.subn(pattern, variable, expression)
        if count:
            environment[variable] = value
            used_inputs.add(input_id)
    parsed = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(parsed)) > 128:
        raise ValueError("formula is too complex")
    return parsed, environment, frozenset(used_inputs)


def _formula_value(formula: str, inputs: Mapping[str, float]) -> float:
    """Evaluate a bounded arithmetic expression after replacing stable input IDs."""
    parsed, environment, _used_inputs = _normalized_formula(formula, inputs)

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
            value = float(node.value)
        elif isinstance(node, ast.Name) and node.id in environment:
            value = environment[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
            operand = evaluate(node.operand)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub | ast.Mult | ast.Div | ast.Pow):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.Div):
                value = left / right
            else:
                if abs(right) > 10 or abs(left) > 1e100:
                    raise ValueError("formula exponent is outside the safe bound")
                value = left**right
        else:
            raise ValueError("formula contains an unsupported operation or input")
        if not isfinite(value) or abs(value) > 1e300:
            raise ValueError("formula result is not a bounded finite number")
        return value

    return evaluate(parsed)


def _numeric_inputs(
    calculation: Mapping[str, object],
    metrics: Mapping[str, Mapping[str, object]],
) -> dict[str, float] | None:
    values: dict[str, float] = {}
    explicit = calculation.get("inputs")
    if isinstance(explicit, Mapping):
        for raw_id, raw_value in explicit.items():
            if isinstance(raw_value, bool) or not isinstance(raw_value, Real) or not isfinite(raw_value):
                return None
            values[str(raw_id)] = float(raw_value)
    constants = calculation.get("constants")
    if isinstance(constants, Sequence) and not isinstance(constants, str | bytes | bytearray):
        for constant in constants:
            if not isinstance(constant, Mapping):
                return None
            name = constant.get("name")
            value = constant.get("value")
            if (
                not isinstance(name, str)
                or not name
                or name in values
                or isinstance(value, bool)
                or not isinstance(value, Real)
                or not isfinite(value)
            ):
                return None
            values[name] = float(value)
    for metric_id in _refs(calculation.get("input_metric_ids")):
        metric = metrics.get(metric_id)
        value = metric.get("value") if metric is not None else None
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
            return None
        if metric_id in values:
            if abs(values[metric_id] - float(value)) > max(1e-12, abs(float(value)) * 1e-12):
                return None
            continue
        values[metric_id] = float(value)
    return values or None


def _matches_declared_result(calculation: Mapping[str, object], recomputed: float, declared: object) -> bool:
    if isinstance(declared, bool) or not isinstance(declared, Real) or not isfinite(declared):
        return False
    declared_value = float(declared)
    rounding_digits = calculation.get("rounding_digits")
    if rounding_digits is not None:
        if isinstance(rounding_digits, bool) or not isinstance(rounding_digits, int) or not 0 <= rounding_digits <= 12:
            return False
        recomputed = round(recomputed, rounding_digits)
    tolerance = calculation.get("tolerance")
    if tolerance is None:
        allowed_error = max(1e-9, abs(declared_value) * 1e-9)
    else:
        if isinstance(tolerance, bool) or not isinstance(tolerance, Real):
            return False
        tolerance_value = float(tolerance)
        if not 0 <= tolerance_value <= 1:
            return False
        # The research contract defines an absolute tolerance, applied after the
        # declared decimal rounding policy.
        allowed_error = tolerance_value
    return abs(recomputed - declared_value) <= allowed_error


def _operation_matches(
    calculation: Mapping[str, object],
    metrics: Mapping[str, Mapping[str, object]],
) -> bool:
    operation = calculation.get("operation")
    if operation is None:
        return True
    if not isinstance(operation, str):
        return False
    formula = calculation.get("formula")
    inputs = _numeric_inputs(calculation, metrics)
    if not isinstance(formula, str) or inputs is None:
        return False
    try:
        parsed, environment, used_inputs = _normalized_formula(formula, inputs)
    except (SyntaxError, ValueError):
        return False
    if used_inputs != frozenset(inputs):
        return False
    if any(isinstance(node, ast.UnaryOp) for node in ast.walk(parsed)):
        return False
    body = parsed.body
    operators = tuple(node.op for node in ast.walk(parsed) if isinstance(node, ast.BinOp))
    if operation == "identity":
        return isinstance(body, ast.Name) and body.id in environment and len(environment) == 1
    if operation in {"add", "sum"}:
        return (
            isinstance(body, ast.BinOp)
            and isinstance(body.op, ast.Add)
            and all(isinstance(operator, ast.Add) for operator in operators)
        )
    if operation == "subtract":
        return (
            isinstance(body, ast.BinOp)
            and isinstance(body.op, ast.Sub)
            and all(isinstance(operator, ast.Add | ast.Sub) for operator in operators)
        )
    if operation == "multiply":
        return (
            isinstance(body, ast.BinOp)
            and isinstance(body.op, ast.Mult)
            and all(isinstance(operator, ast.Mult) for operator in operators)
        )
    if operation == "divide":
        return (
            isinstance(body, ast.BinOp)
            and isinstance(body.op, ast.Div)
            and all(isinstance(operator, ast.Mult | ast.Div) for operator in operators)
        )
    if operation == "average":
        if not isinstance(body, ast.BinOp) or not isinstance(body.op, ast.Div):
            return False
        denominator = body.right
        if (
            not isinstance(denominator, ast.Constant)
            or isinstance(denominator.value, bool)
            or not isinstance(denominator.value, int | float)
            or float(denominator.value) != len(environment)
        ):
            return False

        def additive_names(node: ast.AST) -> tuple[str, ...] | None:
            if isinstance(node, ast.Name) and node.id in environment:
                return (node.id,)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                left = additive_names(node.left)
                right = additive_names(node.right)
                if left is not None and right is not None:
                    return (*left, *right)
            return None

        numerator_names = additive_names(body.left)
        return (
            numerator_names is not None
            and len(numerator_names) == len(environment)
            and frozenset(numerator_names) == frozenset(environment)
        )
    if operation == "discounted_cash_flow":
        return any(isinstance(operator, ast.Div) for operator in operators) and any(
            isinstance(operator, ast.Pow) for operator in operators
        )
    return False


def _validate_reproducibility(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    metrics: dict[str, Mapping[str, object]] = {}
    for item in _items(dossier, "metrics"):
        metric_id = _identifier(item)
        if metric_id is not None:
            metrics[metric_id] = item
    calculation_results: dict[str, float] = {}
    for collection in ("calculations", "valuations"):
        for index, item in enumerate(_items(dossier, collection)):
            if collection == "valuations" and _refs(item.get("calculation_ids") or item.get("calculation_id")):
                fair_value = item.get("fair_value", item.get("value"))
                calculation_ids = _refs(item.get("calculation_ids") or item.get("calculation_id"))
                if (
                    not isinstance(item.get("methodology"), str)
                    or not str(item["methodology"]).strip()
                    or not isinstance(item.get("currency"), str)
                    or not str(item["currency"]).strip()
                    or isinstance(fair_value, bool)
                    or not isinstance(fair_value, Real)
                    or not isfinite(fair_value)
                    or not _refs(item.get("input_metric_ids"))
                ):
                    _append(
                        issues,
                        "reproducibility",
                        f"$.valuations[{index}]",
                        "valuation requires methodology, currency, metric inputs, calculations, and fair value",
                    )
                elif not any(
                    calculation_id in calculation_results
                    and abs(calculation_results[calculation_id] - float(fair_value))
                    <= max(1e-9, abs(float(fair_value)) * 1e-9)
                    for calculation_id in calculation_ids
                ):
                    _append(
                        issues,
                        "reproducibility",
                        f"$.valuations[{index}].fair_value",
                        "valuation fair value does not match any referenced calculation result",
                    )
                sensitivities = item.get("sensitivity_outputs") or item.get("sensitivity_cells")
                if isinstance(sensitivities, Sequence) and not isinstance(sensitivities, str | bytes | bytearray):
                    for sensitivity_index, sensitivity in enumerate(sensitivities):
                        if not isinstance(sensitivity, Mapping):
                            _append(
                                issues,
                                "reproducibility",
                                f"$.valuations[{index}].sensitivity_outputs[{sensitivity_index}]",
                                "sensitivity output must be an object",
                            )
                            continue
                        calculation_ids = _refs(sensitivity.get("calculation_ids") or sensitivity.get("calculation_id"))
                        output = sensitivity.get("result", sensitivity.get("fair_value", sensitivity.get("value")))
                        expected_values = tuple(
                            calculation_results[calculation_id]
                            for calculation_id in calculation_ids
                            if calculation_id in calculation_results
                        )
                        if (
                            not expected_values
                            or isinstance(output, bool)
                            or not isinstance(output, Real)
                            or not isfinite(output)
                            or not any(
                                abs(expected - float(output)) <= max(1e-9, abs(float(output)) * 1e-9)
                                for expected in expected_values
                            )
                        ):
                            _append(
                                issues,
                                "reproducibility",
                                f"$.valuations[{index}].sensitivity_outputs[{sensitivity_index}]",
                                "sensitivity output does not match its calculation result",
                            )
                continue
            if not _reproducible(item):
                _append(
                    issues,
                    "reproducibility",
                    f"$.{collection}[{index}]",
                    "formula/method, explicit inputs, and a numeric result are required",
                )
            elif collection == "calculations" and (
                not isinstance(item.get("unit"), str)
                or not str(item["unit"]).strip()
                or ("deterministic" in item and item.get("deterministic") is not True)
            ):
                _append(
                    issues,
                    "reproducibility",
                    f"$.calculations[{index}]",
                    "calculation requires a result unit and must be deterministic",
                )
            else:
                calculation_id = _identifier(item)
                formula = item.get("formula")
                inputs = _numeric_inputs(item, metrics)
                result = item.get("result")
                try:
                    recomputed = (
                        _formula_value(formula, inputs) if isinstance(formula, str) and inputs is not None else None
                    )
                except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
                    recomputed = None
                if (
                    recomputed is None
                    or not _matches_declared_result(item, recomputed, result)
                    or not _operation_matches(item, metrics)
                ):
                    _append(
                        issues,
                        "reproducibility",
                        f"$.calculations[{index}].result",
                        "declared result does not match the safe deterministic formula",
                    )
                elif calculation_id is not None and isinstance(result, Real):
                    calculation_results[calculation_id] = float(result)


def _validate_entitlement_grounding(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    documents = _items(dossier, "documents")
    if not documents:
        return
    blocked: set[str] = set()
    accessible: set[str] = set()
    for document in documents:
        document_id = _identifier(document)
        entitlement = document.get("entitlement")
        if document_id is None or not isinstance(entitlement, Mapping):
            continue
        if entitlement.get("access") == "entitlement_blocked":
            blocked.add(document_id)
        else:
            accessible.add(document_id)
    if not blocked:
        return
    metric_sources: dict[str, tuple[str, ...]] = {}
    for index, metric in enumerate(_items(dossier, "metrics")):
        metric_id = _identifier(metric)
        source_ids = _refs(metric.get("source_document_ids"))
        if metric_id is not None:
            metric_sources[metric_id] = source_ids
        if metric.get("basis") != "assumption" and source_ids and not set(source_ids) & accessible:
            _append(
                issues,
                "entitlement_grounding",
                f"$.metrics[{index}].source_document_ids",
                "affirmative metrics require at least one accessible source document",
            )
    for index, claim in enumerate(_items(dossier, "claims")):
        claim_source_ids = set(_refs(claim.get("evidence_document_ids")))
        for metric_id in _refs(claim.get("metric_ids")):
            claim_source_ids.update(metric_sources.get(metric_id, ()))
        if claim_source_ids and not claim_source_ids & accessible:
            _append(
                issues,
                "entitlement_grounding",
                f"$.claims[{index}]",
                "affirmative claims require at least one accessible source document",
            )


def _validate_peers(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    for index, peer in enumerate(_items(dossier, "peers", "peer_set")):
        path = f"$.peers[{index}]"
        if not isinstance(peer.get("rationale"), str) or not str(peer["rationale"]).strip():
            _append(issues, "peer_methodology", f"{path}.rationale", "peer inclusion rationale is required")
        normalization = peer.get("normalization") or peer.get("normalization_method") or peer.get("methodology")
        if not isinstance(normalization, str | Mapping) or not normalization:
            _append(issues, "peer_methodology", f"{path}.normalization", "peer normalization is required")


def _validate_supersession(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    items = (
        *_items(dossier, "documents", "sources"),
        *_items(dossier, "evidence", "evidence_items"),
        *_items(dossier, "claims"),
    )
    ids = {_identifier(item) for item in items} - {None}
    edges: dict[str, tuple[str, ...]] = {}
    for item in items:
        item_id = _identifier(item)
        if item_id is None:
            continue
        targets = _refs(item.get("supersedes") or item.get("corrects") or item.get("supersedes_ids"))
        if any(target not in ids or target == item_id for target in targets):
            _append(
                issues,
                "supersession_integrity",
                f"$.*[{item_id}]",
                "supersession target is missing or self-referential",
            )
        edges[item_id] = targets
    for start in edges:
        seen: set[str] = set()
        current = start
        while edges.get(current):
            if current in seen:
                _append(issues, "supersession_integrity", f"$.*[{start}]", "supersession chain contains a cycle")
                break
            seen.add(current)
            current = edges[current][0]


def _validate_debate(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    turns = _items(dossier, "arguments", "debate", "debate_turns", "research_debate")
    argument_positions = {
        identifier: index for index, turn in enumerate(turns) if (identifier := _identifier(turn)) is not None
    }
    for index, turn in enumerate(turns):
        collection = "arguments" if "arguments" in dossier else "debate"
        path = f"$.{collection}[{index}]"
        if not _refs(turn.get("claim_ids")):
            _append(issues, "debate_grounding", f"{path}.claim_ids", "debate turn requires claim links")
        rebuttal = turn.get("rebuttal_of")
        if rebuttal is not None:
            target_index = argument_positions.get(rebuttal) if isinstance(rebuttal, str) else None
            target = turns[target_index] if target_index is not None else None
            if (
                target_index is None
                or target_index >= index
                or (isinstance(target, Mapping) and target.get("debate") != turn.get("debate"))
            ):
                _append(
                    issues,
                    "debate_grounding",
                    f"{path}.rebuttal_of",
                    "rebuttal must reference an earlier argument in the same debate",
                )
        semantic_sets: dict[str, tuple[str, ...]] = {}
        for field in ("concessions", "unresolved"):
            value = turn.get(field, ())
            if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
                _append(issues, "debate_grounding", f"{path}.{field}", f"{field} must be a list")
                continue
            entries = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
            if len(entries) != len(value) or len(entries) != len(set(entries)):
                _append(
                    issues,
                    "debate_grounding",
                    f"{path}.{field}",
                    f"{field} must contain unique non-empty statements",
                )
            semantic_sets[field] = entries
        if set(semantic_sets.get("concessions", ())) & set(semantic_sets.get("unresolved", ())):
            _append(
                issues,
                "debate_grounding",
                path,
                "the same issue cannot be both conceded and unresolved",
            )


def _validate_portfolio(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    forbidden_private = {"account_id", "account_number", "broker_account_id", "customer_id", "email", "full_name"}
    for path, item in _objects(dossier):
        for key, value in item.items():
            normalized = str(key).lower()
            if normalized in {"executable", "submitted", "order_submitted"} and value is not False:
                _append(
                    issues,
                    "portfolio_safety",
                    f"{path}.{key}",
                    "portfolio research must be explicitly non-executable",
                )
            if "portfolio" in path.lower() and normalized in forbidden_private:
                _append(issues, "portfolio_safety", f"{path}.{key}", "raw portfolio identity is forbidden")
    portfolio = dossier.get("portfolio_context") or dossier.get("portfolio")
    if isinstance(portfolio, Mapping):
        contract_safe = portfolio.get("non_executable") is True
        if not contract_safe:
            _append(issues, "portfolio_safety", "$.portfolio_context", "an explicit non-execution boundary is required")


def _validate_completeness(dossier: Mapping[str, object], issues: list[ResearchConformanceIssue]) -> None:
    coverage = dossier.get("completeness") or dossier.get("coverage")
    if coverage is None:
        _append(issues, "completeness_honesty", "$", "coverage/completeness declaration is required")
        return
    if isinstance(coverage, Sequence) and not isinstance(coverage, str | bytes | bytearray):
        if not coverage:
            _append(issues, "completeness_honesty", "$.coverage", "coverage declarations cannot be empty")
        for index, item in enumerate(coverage):
            path = f"$.coverage[{index}]"
            if not isinstance(item, Mapping):
                _append(issues, "completeness_honesty", path, "coverage item must be an object")
                continue
            status = item.get("status")
            limitation = item.get("limitation")
            source_ids = _refs(item.get("source_document_ids"))
            if status == "complete" and not source_ids:
                _append(issues, "completeness_honesty", path, "complete coverage requires retained sources")
            elif status != "complete" and (not isinstance(limitation, str) or not limitation.strip()):
                _append(issues, "completeness_honesty", path, "non-complete coverage requires a limitation")
        return
    if not isinstance(coverage, Mapping):
        _append(issues, "completeness_honesty", "$.coverage", "coverage declaration must be an object or list")
        return
    status = coverage.get("status")
    if status not in {"complete", "partial", "insufficient", "blocked", "unverified"}:
        _append(issues, "completeness_honesty", "$.coverage.status", "coverage status is invalid")
    gaps = coverage.get("gaps") or coverage.get("missing") or coverage.get("unknowns") or []
    if status == "complete" and isinstance(gaps, Sequence) and not isinstance(gaps, str) and gaps:
        _append(issues, "completeness_honesty", "$.coverage", "complete coverage cannot declare unresolved gaps")
    if status in {"partial", "insufficient", "blocked"} and not gaps:
        _append(issues, "completeness_honesty", "$.coverage", "incomplete coverage must disclose gaps")


def validate_research_dossier(dossier: Mapping[str, object]) -> ResearchConformanceReport:
    """Return all deterministic semantic violations in a research dossier mapping."""
    if not isinstance(dossier, Mapping):
        raise TypeError("dossier must be a mapping")
    issues: list[ResearchConformanceIssue] = []
    try:
        reject_secret_shaped_keys(dossier)
    except ValueError as exc:
        _append(issues, "credential_safety", "$", str(exc))
    _validate_temporal(dossier, issues)
    _validate_references(dossier, issues)
    _validate_metrics(dossier, issues)
    _validate_reproducibility(dossier, issues)
    _validate_entitlement_grounding(dossier, issues)
    _validate_peers(dossier, issues)
    _validate_supersession(dossier, issues)
    _validate_debate(dossier, issues)
    _validate_portfolio(dossier, issues)
    _validate_completeness(dossier, issues)
    return ResearchConformanceReport(tuple(issues))


def assert_research_dossier_conformant(dossier: Mapping[str, object]) -> None:
    """Raise a stable validation error when deterministic dossier checks fail."""
    report = validate_research_dossier(dossier)
    if not report.passed:
        detail = "; ".join(f"{issue.check} at {issue.path}: {issue.detail}" for issue in report.issues)
        raise ValueError(f"research dossier conformance failed: {detail}")
