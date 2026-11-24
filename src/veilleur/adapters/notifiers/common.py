# SPDX-License-Identifier: EUPL-1.2
"""What the provided notifiers share: the POST without redirection and the text of a notification."""

from __future__ import annotations

import http.client
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

from veilleur import __version__, i18n
from veilleur.core.ports.plugins import RoundCounts

TIMEOUT = 10.0
Poster = Callable[[str, bytes, Mapping[str, str]], int]
"""Sends a POST and returns its status; raises `OSError` on failure."""


class NotificationFailed(Exception):
    pass


def post(url: str, body: bytes, headers: Mapping[str, str]) -> int:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise NotificationFailed("address")
    connection_class = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(parts.hostname, parts.port, timeout=TIMEOUT)
    try:
        target = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        connection.request("POST", target, body=body, headers={**headers, "User-Agent": f"Veilleur/{__version__}"})
        response = connection.getresponse()
        response.read(65536)
        return response.status
    except (http.client.HTTPException, ValueError) as exc:
        raise OSError(type(exc).__name__) from exc
    finally:
        connection.close()


def check(status: int) -> None:
    """Raise `NotificationFailed` unless `status` is a success."""
    if not 200 <= status < 300:
        raise NotificationFailed(f"status {status}")


def message(counts: RoundCounts, language: str) -> str:
    """The text of a notification, in `language`: counts only."""
    t = i18n.translations(language)
    parts = [
        t.ngettext("{count} new report", "{count} new reports", counts.reports).format(count=counts.reports),
        t.ngettext("{count} new item", "{count} new items", counts.new_items).format(count=counts.new_items),
    ]
    if counts.failing_sources:
        parts.append(
            t.ngettext(
                "{count} source failing for more than two days",
                "{count} sources failing for more than two days",
                counts.failing_sources,
            ).format(count=counts.failing_sources)
        )
    return ", ".join(parts)
