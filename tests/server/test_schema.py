# SPDX-License-Identifier: EUPL-1.2
"""Validation of plugin parameters (subset of JSON Schema)."""

from __future__ import annotations

from typing import Any

import pytest

from veilleur.core.domain.schema import check_schema, validate

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "pattern": "^https://", "maxLength": 20},
        "count": {"type": "integer", "minimum": 1, "maximum": 10},
        "ratio": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
        "mode": {"enum": ["a", "b"]},
        "tags": {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 2, "uniqueItems": True},
        "flag": {"type": "boolean"},
        "nested": {"type": "object", "additionalProperties": {"type": "integer"}},
        "fixed": {"const": 1},
        "maybe": {"type": ["string", "null"]},
    },
    "required": ["url"],
    "additionalProperties": False,
}


@pytest.mark.parametrize(
    "value",
    [
        {"url": "https://a"},
        {"url": "https://a", "count": 3, "ratio": 0.5, "mode": "a", "tags": ["x", "y"], "flag": True},
        {"url": "https://a", "nested": {"k": 1}, "fixed": 1, "maybe": None, "count": 2.0},
    ],
)
def test_valid(value: Any) -> None:
    check_schema(SCHEMA)
    assert validate(value, SCHEMA) is None


@pytest.mark.parametrize(
    ("value", "path", "keyword"),
    [
        ([], "", "type"),
        ({}, "/url", "required"),
        ({"url": "http://a"}, "/url", "pattern"),
        ({"url": "https://" + "a" * 20}, "/url", "maxLength"),
        ({"url": "https://a", "count": 0}, "/count", "minimum"),
        ({"url": "https://a", "count": 11}, "/count", "maximum"),
        ({"url": "https://a", "count": True}, "/count", "type"),
        ({"url": "https://a", "count": 1.5}, "/count", "type"),
        ({"url": "https://a", "ratio": 1}, "/ratio", "exclusiveMaximum"),
        ({"url": "https://a", "ratio": 0}, "/ratio", "exclusiveMinimum"),
        ({"url": "https://a", "mode": "c"}, "/mode", "enum"),
        ({"url": "https://a", "tags": ["x", "x"]}, "/tags", "uniqueItems"),
        ({"url": "https://a", "tags": ["x", "y", "z"]}, "/tags", "maxItems"),
        ({"url": "https://a", "tags": [""]}, "/tags/0", "minLength"),
        ({"url": "https://a", "flag": 1}, "/flag", "type"),
        ({"url": "https://a", "nested": {"a/b": "x"}}, "/nested/a~1b", "type"),
        ({"url": "https://a", "fixed": True}, "/fixed", "const"),
        ({"url": "https://a", "other": 1}, "/other", "additionalProperties"),
    ],
)
def test_violations(value: Any, path: str, keyword: str) -> None:
    violation = validate(value, SCHEMA)
    assert violation is not None and (violation.path, violation.keyword) == (path, keyword)


@pytest.mark.parametrize(
    "schema",
    [
        [],
        {"type": "date"},
        {"oneOf": []},
        {"properties": {"x": {"$ref": "#"}}},
        {"pattern": "("},
        {"minLength": -1},
        {"required": "x"},
        {"enum": "x"},
    ],
)
def test_unsupported_schemas(schema: Any) -> None:
    with pytest.raises(ValueError):
        check_schema(schema)
