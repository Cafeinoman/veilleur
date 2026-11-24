# SPDX-License-Identifier: EUPL-1.2
"""The `dedup` filter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from veilleur.adapters.filters.common import FIELDS
from veilleur.core.ports.plugins import FilterItem


class DedupFilter:
    """Keeps the first item (by key) of each group of items whose designated fields have equal values (case and
    white space aside). An item missing every designated field is kept."""

    name = "dedup"
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "Deduplication",
        "properties": {
            "fields": {**FIELDS, "description": "fields whose values make two items the same"},
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
