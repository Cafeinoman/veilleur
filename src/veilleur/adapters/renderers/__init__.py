# SPDX-License-Identifier: EUPL-1.2
"""Provided renderings (spec EF-43): `markdown` and `html`, one module each, in the subscription's language.

Everything in a report comes from third-party sources, so every value is treated as hostile: it is cleaned of control
characters, escaped for its format, and only an `http(s)` address becomes a link. The HTML page holds no script and
loads nothing; its content security policy forbids both, should escaping ever fail.

A rendering is optional and derived: long values are shortened and a huge report is cut, `items.jsonl` holds it all.

The names below stay importable from this package (ADR-0028), whatever module holds them.
"""

from veilleur.adapters.renderers.common import MAX_TEXT, MAX_VALUE
from veilleur.adapters.renderers.html import HtmlRenderer
from veilleur.adapters.renderers.markdown import MarkdownRenderer

__all__ = ["MAX_TEXT", "MAX_VALUE", "HtmlRenderer", "MarkdownRenderer"]
