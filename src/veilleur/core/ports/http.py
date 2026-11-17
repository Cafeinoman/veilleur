# SPDX-License-Identifier: EUPL-1.2
"""The server's HTTP client, the only way a collector reaches the network (cahier EF-06, ES-08)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class HttpResponse:
    status: int
    url: str
    """Final address, after redirections."""
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


class HttpClient(Protocol):
    def get(self, url: str, *, accept: Sequence[str] = ()) -> HttpResponse:
        """Fetch `url`. Raise `CollectorError` (for example `network_unavailable`) when it cannot."""
        ...
