# SPDX-License-Identifier: EUPL-1.2
"""The `keywords` filter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from veilleur.adapters.filters.common import FIELDS, fold, texts
from veilleur.core.ports.plugins import FilterItem


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
            "fields": FIELDS,
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
