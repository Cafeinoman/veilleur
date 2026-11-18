# SPDX-License-Identifier: EUPL-1.2
"""Collector of the NixOS tests: one item per line of a file of the test machine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from veilleur.core.domain.model import Collected, CollectedItem
from veilleur.core.ports.http import HttpClient


class VmSourceCollector:
    name = "vm_source"
    follows_client_urls = False
    schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string", "maxLength": 200}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def collect(self, params: Mapping[str, Any], since: datetime | None, http: HttpClient) -> Collected:
        lines = Path(params["path"]).read_text("utf-8").split()
        return Collected(tuple(CollectedItem({"line": line}, key=line) for line in lines), complete=True)
