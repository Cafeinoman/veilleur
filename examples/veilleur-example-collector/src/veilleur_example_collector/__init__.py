# SPDX-License-Identifier: EUPL-1.2
"""Example collector `text_lines`: one item per non-empty line of a plain-text file.

A plugin is maintained outside Veilleur's repository; this one only shows the contract (cahier EF-01):
- a `name` equal to its entry point name, a JSON `schema` of its parameters (a subset of JSON Schema);
- `follows_client_urls`: True, since the parameters name an address (refused to receiving tools by default);
- `collect(params, since, http)`: network access through `http` only, failures raised as `CollectorError`
  with a stable code, never with detail.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from veilleur.core.domain.errors import CollectorError
from veilleur.core.domain.model import Collected, CollectedItem
from veilleur.core.ports.http import HttpClient

MAX_LINES = 1000


class TextLinesCollector:
    name = "text_lines"
    follows_client_urls = True
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "Lines of a text file",
        "properties": {
            "url": {"type": "string", "pattern": r"^https?://[^\s]+$", "maxLength": 2048},
            "prefix": {"type": "string", "maxLength": 100, "description": "keep only the lines starting with this"},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def collect(self, params: Mapping[str, Any], since: datetime | None, http: HttpClient) -> Collected:
        response = http.get(params["url"], accept=("text/plain",))
        try:
            text = response.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CollectorError("not_utf8") from exc
        prefix = params.get("prefix", "")
        lines = [line.strip() for line in text.splitlines() if line.strip().startswith(prefix) and line.strip()]
        items = tuple(
            # The key is the hash of the line: an edited line is a new item, and the old one goes.
            CollectedItem({"line": line}, key=hashlib.sha256(line.encode()).hexdigest()[:32])
            for line in lines[:MAX_LINES]
        )
        return Collected(items, complete=len(lines) <= MAX_LINES)
