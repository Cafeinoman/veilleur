# SPDX-License-Identifier: EUPL-1.2
"""Provided notifiers (cahier EF-52): `ntfy` and `webhook`. A notification carries counts, never content.

Notifiers post to addresses set by the administrator (a local ntfy server is usual), so they do not go through the
collectors' SSRF guard; they never follow redirections.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from veilleur import __version__, i18n
from veilleur.core.ports.plugins import NotificationTarget, RoundCounts

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


def _check(status: int) -> None:
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


@dataclass
class NtfyNotifier:
    """Publishes to the pairing's topic on an ntfy server (`<url>/<topic>`), with an access token if given."""

    url: str
    token: str | None = field(default=None, repr=False)
    language: str = "en"
    poster: Poster = post
    name: str = "ntfy"

    def notify(self, target: NotificationTarget, counts: RoundCounts) -> None:
        headers = {"Title": "Veilleur", "Tags": "mag", "Content-Type": "text/plain; charset=utf-8"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = message(counts, self.language).encode("utf-8")
        _check(self.poster(f"{self.url.rstrip('/')}/{target.topic}", body, headers))


SIGNATURE_HEADER = "X-Veilleur-Signature"


def sign(key: bytes, body: bytes) -> str:
    """Value of the `X-Veilleur-Signature` header: `sha256=` and the hexadecimal HMAC-SHA256 of the body."""
    return "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()


@dataclass
class WebhookNotifier:
    """POSTs a JSON document signed with HMAC-SHA256 under the webhook's own key:

        {"event": "round", "topic": ..., "reports": n, "new_items": n, "failing_sources": n, "sent_at": ...}

    `sent_at` (UTC) lets the receiver refuse an old notification sent again.
    """

    url: str
    key: bytes = field(repr=False)
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    poster: Poster = post
    name: str = "webhook"

    def notify(self, target: NotificationTarget, counts: RoundCounts) -> None:
        document = {
            "event": "round",
            "topic": target.topic,
            "reports": counts.reports,
            "new_items": counts.new_items,
            "failing_sources": counts.failing_sources,
            "sent_at": self.now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
        headers = {"Content-Type": "application/json", SIGNATURE_HEADER: sign(self.key, body)}
        _check(self.poster(self.url, body, headers))
