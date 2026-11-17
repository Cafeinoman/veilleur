# SPDX-License-Identifier: EUPL-1.2
"""Validation of plugin parameters against their schema (cahier EF-01, EF-12).

Schemas are written in a subset of JSON Schema (draft 2020-12), enough for plugin parameters and without a
dependency: `type`, `properties`, `required`, `additionalProperties`, `enum`, `const`, `minLength`, `maxLength`,
`pattern`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `items`, `minItems`, `maxItems`,
`uniqueItems`, plus the annotations `title`, `description`, `default`, `examples`, `format` and `$schema`, which
change nothing. `check_schema` refuses any other keyword, so that a plugin never relies on a check that would not
happen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .model import canonical_json

_TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")
_VALIDATION = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "enum",
    "const",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
}
_ANNOTATIONS = {"title", "description", "default", "examples", "format", "$schema"}
MAX_DEPTH = 32


@dataclass(frozen=True)
class SchemaViolation:
    """Where a value fails its schema (`path` is a JSON pointer) and which keyword it fails."""

    path: str
    keyword: str


def check_schema(schema: Any, _depth: int = 0) -> None:
    """Raise `ValueError` if `schema` uses anything outside the supported subset."""
    if _depth > MAX_DEPTH:
        raise ValueError("schema nested too deeply")
    if not isinstance(schema, dict):
        raise ValueError("a schema is an object")
    unknown = set(schema) - _VALIDATION - _ANNOTATIONS
    if unknown:
        raise ValueError(f"unsupported schema keywords: {sorted(unknown)}")
    types = schema.get("type")
    if types is not None:
        listed = types if isinstance(types, list) else [types]
        if not listed or any(t not in _TYPES for t in listed):
            raise ValueError(f"unknown type {types!r}")
    for name, sub in schema.get("properties", {}).items():
        if not isinstance(name, str):
            raise ValueError("property names are strings")
        check_schema(sub, _depth + 1)
    additional = schema.get("additionalProperties", True)
    if not isinstance(additional, bool):
        check_schema(additional, _depth + 1)
    if "items" in schema:
        check_schema(schema["items"], _depth + 1)
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
        raise ValueError("required is a list of names")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError) as exc:
            raise ValueError("pattern is a regular expression") from exc
    for keyword in ("minLength", "maxLength", "minItems", "maxItems"):
        if keyword in schema and (type(schema[keyword]) is not int or schema[keyword] < 0):
            raise ValueError(f"{keyword} is a non-negative integer")
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise ValueError("enum is a list")


def _is_type(value: Any, name: str) -> bool:
    match name:
        case "object":
            return isinstance(value, dict)
        case "array":
            return isinstance(value, list)
        case "string":
            return isinstance(value, str)
        case "integer":
            return type(value) is int or (type(value) is float and value.is_integer())
        case "number":
            return type(value) in (int, float)
        case "boolean":
            return isinstance(value, bool)
        case _:
            return value is None


def _equal(a: Any, b: Any) -> bool:
    try:
        return canonical_json(a) == canonical_json(b) and _is_type(a, "boolean") == _is_type(b, "boolean")
    except ValueError:
        return False


def _out_of_bound(keyword: str, value: float, bound: float) -> bool:
    match keyword:
        case "minimum":
            return value < bound
        case "maximum":
            return value > bound
        case "exclusiveMinimum":
            return value <= bound
        case _:
            return value >= bound


def _pointer(path: str, part: str | int) -> str:
    return f"{path}/{str(part).replace('~', '~0').replace('/', '~1')}"


def validate(value: Any, schema: Mapping[str, Any], path: str = "") -> SchemaViolation | None:
    """The first violation of `schema` by `value`, or None if it is valid."""
    types = schema.get("type")
    if types is not None:
        listed = types if isinstance(types, list) else [types]
        if not any(_is_type(value, t) for t in listed):
            return SchemaViolation(path, "type")
    if "const" in schema and not _equal(value, schema["const"]):
        return SchemaViolation(path, "const")
    if "enum" in schema and not any(_equal(value, option) for option in schema["enum"]):
        return SchemaViolation(path, "enum")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return SchemaViolation(path, "minLength")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return SchemaViolation(path, "maxLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return SchemaViolation(path, "pattern")
    if type(value) in (int, float):
        for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            if keyword in schema and _out_of_bound(keyword, value, schema[keyword]):
                return SchemaViolation(path, keyword)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return SchemaViolation(path, "minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return SchemaViolation(path, "maxItems")
        if schema.get("uniqueItems") and any(_equal(a, b) for i, a in enumerate(value) for b in value[i + 1 :]):
            return SchemaViolation(path, "uniqueItems")
        if "items" in schema:
            for index, element in enumerate(value):
                if (violation := validate(element, schema["items"], _pointer(path, index))) is not None:
                    return violation
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                return SchemaViolation(_pointer(path, name), "required")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for name, element in value.items():
            if name in properties:
                sub = properties[name]
            elif additional is False:
                return SchemaViolation(_pointer(path, name), "additionalProperties")
            elif additional is True:
                continue
            else:
                sub = additional
            if (violation := validate(element, sub, _pointer(path, name))) is not None:
                return violation
    return None
