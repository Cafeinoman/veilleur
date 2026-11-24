# SPDX-License-Identifier: EUPL-1.2
"""Provided filters (spec EF-20): `keywords`, `regex` and `dedup`, one module each.

`keywords` and `regex` look at designated fields (by default every text field), insensitive to case and, at will,
to accents; they keep the matching items, or leave them out with `"exclude": true`. `dedup` keeps one item per value
of designated fields, among the items of the subscription's collection (which gathers successive collections):
an entry published again under another key is reported once.

The names below stay importable from this package (ADR-0028), whatever module holds them.
"""

from veilleur.adapters.filters.common import MAX_TEXT, fold, texts
from veilleur.adapters.filters.dedup import DedupFilter
from veilleur.adapters.filters.keywords import KeywordsFilter
from veilleur.adapters.filters.regex import Pattern, RegexFilter, compile_pattern

__all__ = [
    "MAX_TEXT",
    "DedupFilter",
    "KeywordsFilter",
    "Pattern",
    "RegexFilter",
    "compile_pattern",
    "fold",
    "texts",
]
