"""Strict JSON serialization for persisted run contracts."""

from __future__ import annotations

import json
import types
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Literal, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from .contracts import SCHEMA_VERSION, RunEvent, RunResult

_T = TypeVar("_T")
_TYPE_MARKER = "__tradingrearchagents_json_type__"


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _json_object(payload: str | bytes | bytearray, name: str) -> Mapping[str, object]:
    try:
        value = json.loads(payload)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _validate_schema(value: Mapping[str, object], name: str) -> None:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{name}.schema_version must be {SCHEMA_VERSION}")


def _encode_dataclass(value: object) -> dict[str, object]:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError(f"expected dataclass instance, got {type(value).__name__}")
    hints = get_type_hints(type(value))
    return {item.name: _encode_value(hints[item.name], getattr(value, item.name)) for item in fields(cast(Any, value))}


def _encode_any(value: object) -> object:
    if isinstance(value, tuple):
        return {_TYPE_MARKER: "tuple", "items": [_encode_any(item) for item in value]}
    if isinstance(value, list):
        return [_encode_any(item) for item in value]
    if isinstance(value, Mapping):
        encoded = {str(key): _encode_any(item) for key, item in value.items()}
        if _TYPE_MARKER in encoded:
            return {_TYPE_MARKER: "mapping", "items": [[key, item] for key, item in encoded.items()]}
        return encoded
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _encode_value(expected: object, value: object) -> object:
    if expected is Any:
        return _encode_any(value)
    origin = get_origin(expected)
    args = get_args(expected)
    if origin in {Union, types.UnionType}:
        for option in args:
            try:
                return _encode_value(option, value)
            except (TypeError, ValueError):
                continue
        raise TypeError(f"value does not match persisted type {expected}")
    if origin is tuple:
        if not isinstance(value, tuple):
            raise TypeError(f"expected tuple, got {type(value).__name__}")
        item_type = args[0] if args else Any
        return [_encode_value(item_type, item) for item in value]
    if origin is list:
        if not isinstance(value, list):
            raise TypeError(f"expected list, got {type(value).__name__}")
        item_type = args[0] if args else Any
        return [_encode_value(item_type, item) for item in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError(f"expected dict, got {type(value).__name__}")
        key_type, item_type = args or (str, Any)
        return {str(_encode_value(key_type, key)): _encode_value(item_type, item) for key, item in value.items()}
    if isinstance(expected, type) and is_dataclass(expected):
        return _encode_dataclass(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _decode_any(value: object, path: str) -> object:
    if isinstance(value, list):
        return [_decode_any(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        marker = value.get(_TYPE_MARKER)
        if marker == "tuple" and set(value) == {_TYPE_MARKER, "items"} and isinstance(value["items"], list):
            return tuple(_decode_any(item, f"{path}.items[{index}]") for index, item in enumerate(value["items"]))
        if marker == "mapping" and set(value) == {_TYPE_MARKER, "items"} and isinstance(value["items"], list):
            restored: dict[str, object] = {}
            for index, pair in enumerate(value["items"]):
                if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str):
                    raise ValueError(f"{path}.items[{index}] must be a string-keyed pair")
                restored[pair[0]] = _decode_any(pair[1], f"{path}.{pair[0]}")
            return restored
        if marker is not None:
            raise ValueError(f"{path} contains an invalid JSON type marker")
        return {key: _decode_any(item, f"{path}.{key}") for key, item in value.items()}
    return value


def _decode_dataclass(cls: type[_T], value: object, path: str) -> _T:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    field_by_name = {item.name: item for item in fields(cast(Any, cls))}
    unknown = sorted(set(value) - set(field_by_name))
    if unknown:
        raise ValueError(f"{path} contains unsupported fields: {unknown}")
    schema = value.get("schema_version")
    if schema is not None and schema != SCHEMA_VERSION:
        raise ValueError(f"{path}.schema_version must be {SCHEMA_VERSION}")
    hints = get_type_hints(cls)
    kwargs: dict[str, object] = {}
    for item in field_by_name.values():
        if not item.init or item.name not in value:
            continue
        kwargs[item.name] = _decode_value(hints[item.name], value[item.name], f"{path}.{item.name}")
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {path}: {exc}") from exc


def _decode_value(expected: object, value: object, path: str) -> object:
    if expected is Any:
        return _decode_any(value, path)
    origin = get_origin(expected)
    args = get_args(expected)
    if origin is Literal:
        if value not in args or (isinstance(value, bool) and not any(isinstance(item, bool) for item in args)):
            raise ValueError(f"{path} has an unsupported value")
        return value
    if origin in {Union, types.UnionType}:
        for option in args:
            try:
                return _decode_value(option, value, path)
            except ValueError:
                continue
        raise ValueError(f"{path} has an invalid type")
    if origin is tuple:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        item_type = args[0] if args else Any
        return tuple(_decode_value(item_type, item, f"{path}[{index}]") for index, item in enumerate(value))
    if origin is list:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        item_type = args[0] if args else Any
        return [_decode_value(item_type, item, f"{path}[{index}]") for index, item in enumerate(value)]
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        key_type, item_type = args or (str, Any)
        return {
            _decode_value(key_type, key, f"{path}.<key>"): _decode_value(item_type, item, f"{path}.{key}")
            for key, item in value.items()
        }
    if isinstance(expected, type) and is_dataclass(expected):
        return _decode_dataclass(expected, value, path)
    if isinstance(expected, type) and issubclass(expected, Enum):
        try:
            return expected(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} has an unsupported value") from exc
    if expected is type(None):
        if value is not None:
            raise ValueError(f"{path} must be null")
        return None
    if expected is float:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"{path} must be a number")
        return float(value)
    if expected is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path} must be an integer")
        return value
    if expected is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be a boolean")
        return value
    if expected is str:
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        return value
    raise ValueError(f"{path} uses an unsupported persisted type")


def serialize_run_result(result: RunResult) -> str:
    """Serialize a completed run result as deterministic, non-pickle JSON."""
    if not isinstance(result, RunResult):
        raise TypeError("result must be a RunResult")
    return _json_text(_encode_dataclass(result))


def deserialize_run_result(payload: str | bytes | bytearray) -> RunResult:
    """Deserialize and validate a run result from JSON."""
    value = _json_object(payload, "run result")
    _validate_schema(value, "run result")
    return _decode_dataclass(RunResult, value, "run result")


def serialize_run_event(event: RunEvent) -> str:
    """Serialize one run event as deterministic JSON."""
    if not isinstance(event, RunEvent):
        raise TypeError("event must be a RunEvent")
    return _json_text(_encode_dataclass(event))


def deserialize_run_event(payload: str | bytes | bytearray) -> RunEvent:
    """Deserialize and validate one run event from JSON."""
    value = _json_object(payload, "run event")
    _validate_schema(value, "run event")
    return _decode_dataclass(RunEvent, value, "run event")


def serialize_run_events(events: tuple[RunEvent, ...]) -> str:
    """Serialize an immutable event stream as a JSON array."""
    if not isinstance(events, tuple) or not all(isinstance(event, RunEvent) for event in events):
        raise TypeError("events must be a tuple of RunEvent values")
    return _json_text([_encode_dataclass(event) for event in events])


def deserialize_run_events(payload: str | bytes | bytearray) -> tuple[RunEvent, ...]:
    """Deserialize and validate an immutable event stream from JSON."""
    try:
        value = json.loads(payload)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("run events must be valid JSON") from exc
    if not isinstance(value, list):
        raise ValueError("run events must be a JSON array")
    events: list[RunEvent] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"run events[{index}] must be an object")
        _validate_schema(item, f"run events[{index}]")
        events.append(_decode_dataclass(RunEvent, item, f"run events[{index}]"))
    return tuple(events)
