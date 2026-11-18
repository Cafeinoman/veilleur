# SPDX-License-Identifier: EUPL-1.2
"""Provided filters (cahier EF-20): `keywords`, `regex` and `dedup`.

`keywords` and `regex` look at designated fields (by default every text field), insensitive to case and, at will,
to accents; they keep the matching items, or leave them out with `"exclude": true`. `dedup` keeps one item per value
of designated fields, among the items of the subscription's collection (which gathers successive collections):
an entry published again under another key is reported once.
"""

from __future__ import annotations

import importlib
import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from veilleur.core.ports.plugins import FilterItem

MAX_TEXT = 20_000
"""Characters of each field that a filter looks at."""
_FIELDS = {
    "type": "array",
    "description": "fields to look at (default: every text field)",
    "items": {"type": "string", "minLength": 1, "maxLength": 100},
    "minItems": 1,
    "maxItems": 50,
    "uniqueItems": True,
}


def fold(text: str, *, case: bool, accents: bool) -> str:
    """`text` without case (if `case` is False) and without accents (if `accents` is False)."""
    if not accents:
        text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return text if case else text.casefold()


def _texts(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for element in value:
            yield from _texts(element)
    elif isinstance(value, dict):
        for element in value.values():
            yield from _texts(element)


def texts(item: FilterItem, fields: Sequence[str] | None) -> list[str]:
    """Text of the designated fields (strings, and strings inside lists and objects), each cut to `MAX_TEXT`."""
    values = item.fields.values() if not fields else [item.fields[f] for f in fields if f in item.fields]
    return [text[:MAX_TEXT] for value in values for text in _texts(value)]


class KeywordsFilter:
    name = "keywords"
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "Keywords",
        "properties": {
            "words": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
                "minItems": 1,
                "maxItems": 100,
            },
            "fields": _FIELDS,
            "match": {"enum": ["any", "all"], "default": "any"},
            "exclude": {"type": "boolean", "default": False},
            "case_sensitive": {"type": "boolean", "default": False},
            "accent_sensitive": {"type": "boolean", "default": True},
        },
        "required": ["words"],
        "additionalProperties": False,
    }

    def apply(self, item: FilterItem, params: Mapping[str, Any]) -> FilterItem | None:
        case, accents = params.get("case_sensitive", False), params.get("accent_sensitive", True)
        haystack = "\n".join(fold(t, case=case, accents=accents) for t in texts(item, params.get("fields")))
        found = [fold(word, case=case, accents=accents) in haystack for word in params["words"]]
        matched = all(found) if params.get("match", "any") == "all" else any(found)
        return item if matched != params.get("exclude", False) else None


_parser: Any = importlib.import_module("re._parser")
_constants: Any = importlib.import_module("re._constants")
_REPEATS = {_constants.MAX_REPEAT, _constants.MIN_REPEAT, getattr(_constants, "POSSESSIVE_REPEAT", None)} - {None}
_REFERENCES = {_constants.GROUPREF, _constants.GROUPREF_EXISTS}


def _risky(pattern: Any, outer: str = "") -> bool:
    """True for what may backtrack catastrophically: a back-reference; a repetition inside another repetition when
    either is unbounded (`(a+)+`, `(.*a){20}`); an alternation inside an unbounded repetition (`(a|ab)*`).
    `outer` is "" outside any repetition, otherwise "bounded" or "unbounded"."""
    for op, argument in pattern:
        if op in _REFERENCES:
            return True
        if op in _REPEATS:
            _low, high, body = argument
            unbounded = high == _constants.MAXREPEAT or high > 100
            if high > 1 and (outer == "unbounded" or (outer == "bounded" and unbounded)):
                return True
            inner = outer if high <= 1 else ("unbounded" if unbounded or outer == "unbounded" else "bounded")
            if _risky(body, inner):
                return True
        elif op is _constants.BRANCH:
            if outer == "unbounded" or any(_risky(branch, outer) for branch in argument[1]):
                return True
        elif op is _constants.SUBPATTERN:
            if _risky(argument[-1], outer):
                return True
        elif op is getattr(_constants, "ATOMIC_GROUP", object()):
            if _risky(argument, outer):
                return True
        elif op in (_constants.ASSERT, _constants.ASSERT_NOT) and _risky(argument[1], outer):
            return True
    return False


def compile_pattern(pattern: str, *, case: bool) -> re.Pattern[str]:
    """Compile a pattern of the `regex` filter; raise `ValueError` for a malformed or risky one."""
    if len(pattern) > 500:
        raise ValueError("pattern too long")
    try:
        if _risky(_parser.parse(pattern)):
            raise ValueError("risky pattern")
        return re.compile(pattern, 0 if case else re.IGNORECASE)
    except (re.error, RecursionError, OverflowError) as exc:
        raise ValueError("malformed pattern") from exc


class RegexFilter:
    """Regular expressions (Python syntax). Patterns that may backtrack catastrophically are refused (see `_risky`):
    back-references, nested repetitions when one is unbounded (`(a+)+`), an alternation inside an unbounded
    repetition (`(a|b)*`: write `[ab]*`)."""

    name = "regex"
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "Regular expression",
        "properties": {
            "pattern": {"type": "string", "minLength": 1, "maxLength": 500},
            "fields": _FIELDS,
            "exclude": {"type": "boolean", "default": False},
            "case_sensitive": {"type": "boolean", "default": False},
            "accent_sensitive": {"type": "boolean", "default": True},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self._compiled: dict[tuple[str, bool, bool], re.Pattern[str]] = {}

    def check_params(self, params: Mapping[str, Any]) -> str | None:
        try:
            self._pattern(params)
        except ValueError:
            return "/pattern"
        return None

    def _pattern(self, params: Mapping[str, Any]) -> re.Pattern[str]:
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


class DedupFilter:
    """Keeps the first item (by key) of each group of items whose designated fields have equal values (case and
    white space aside). An item missing every designated field is kept."""

    name = "dedup"
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "Deduplication",
        "properties": {
            "fields": {**_FIELDS, "description": "fields whose values make two items the same"},
            "by_url": {"type": "boolean", "description": "the item's address makes two items the same"},
        },
        "additionalProperties": False,
    }

    def check_params(self, params: Mapping[str, Any]) -> str | None:
        return None if params.get("fields") or params.get("by_url") else "/fields"

    def apply(self, item: FilterItem, params: Mapping[str, Any]) -> FilterItem | None:
        return item

    @staticmethod
    def _signature(item: FilterItem, params: Mapping[str, Any]) -> tuple[str, ...] | None:
        parts: list[str] = []
        if params.get("by_url"):
            parts.append(item.url or "")
        for name in params.get("fields") or ():
            value = item.fields.get(name)
            parts.append(" ".join(str(value).split()).casefold() if value is not None else "")
        return tuple(parts) if any(parts) else None

    def select(self, items: Sequence[FilterItem], params: Mapping[str, Any]) -> Sequence[FilterItem]:
        seen: set[tuple[str, ...]] = set()
        kept = []
        for item in items:
            signature = self._signature(item, params)
            if signature is not None:
                if signature in seen:
                    continue
                seen.add(signature)
            kept.append(item)
        return kept
