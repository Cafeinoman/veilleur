# SPDX-License-Identifier: EUPL-1.2
"""The `regex` filter, on RE2."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any, Protocol

from veilleur.adapters.filters.common import FIELDS, fold, texts
from veilleur.core.ports.plugins import FilterItem


class Pattern(Protocol):
    def search(self, text: str) -> object | None: ...


_re2: Any = importlib.import_module("re2")  # google-re2 ships no type information


def compile_pattern(pattern: str, *, case: bool) -> Pattern:
    """Compile a pattern of the `regex` filter with RE2, whose search time is linear in the text: no pattern can
    backtrack, catastrophically or not. Raise `ValueError` for a malformed one, or one RE2 does not support
    (back-references, look-around)."""
    if len(pattern) > 500:
        raise ValueError("pattern too long")
    options = _re2.Options()
    options.case_sensitive = case
    options.log_errors = False
    options.max_mem = 8 << 20
    try:
        compiled: Pattern = _re2.compile(pattern, options)
    except _re2.error as exc:
        raise ValueError("malformed pattern") from exc
    return compiled


class RegexFilter:
    """Regular expressions in RE2 syntax (Python's, without back-references nor look-around), searched in linear
    time: a receiving tool cannot stall the round with a pattern."""

    name = "regex"
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "Regular expression",
        "properties": {
            "pattern": {"type": "string", "minLength": 1, "maxLength": 500},
            "fields": FIELDS,
            "exclude": {"type": "boolean", "default": False},
            "case_sensitive": {"type": "boolean", "default": False},
            "accent_sensitive": {"type": "boolean", "default": True},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self._compiled: dict[tuple[str, bool, bool], Pattern] = {}

    def check_params(self, params: Mapping[str, Any]) -> str | None:
        try:
            self._pattern(params)
        except ValueError:
            return "/pattern"
        return None

    def _pattern(self, params: Mapping[str, Any]) -> Pattern:
        case, accents = params.get("case_sensitive", False), params.get("accent_sensitive", True)
        key = (params["pattern"], case, accents)
        if key not in self._compiled:
            source = params["pattern"] if accents else fold(params["pattern"], case=True, accents=False)
            self._compiled[key] = compile_pattern(source, case=case)
        return self._compiled[key]

    def apply(self, item: FilterItem, params: Mapping[str, Any]) -> FilterItem | None:
        pattern = self._pattern(params)
        accents = params.get("accent_sensitive", True)
        candidates = texts(item, params.get("fields"))
        matched = any(pattern.search(t if accents else fold(t, case=True, accents=False)) for t in candidates)
        return item if matched != params.get("exclude", False) else None
