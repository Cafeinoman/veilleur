# SPDX-License-Identifier: EUPL-1.2
"""What the provided filters share: the fields they look at and how they fold text."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator, Sequence
from typing import Any

from veilleur.core.ports.plugins import FilterItem

MAX_TEXT = 20_000
"""Characters of each field that a filter looks at."""
FIELDS = {
    "type": "array",
    "description": "fields to look at (default: every text field)",
    "items": {"type": "string", "minLength": 1, "maxLength": 100},
    "minItems": 1,
    "maxItems": 50,
    "uniqueItems": True,
}
"""Schema of the `fields` parameter."""


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
