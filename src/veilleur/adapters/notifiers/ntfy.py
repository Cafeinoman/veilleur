# SPDX-License-Identifier: EUPL-1.2
"""The `ntfy` notifier."""

from __future__ import annotations

from dataclasses import dataclass, field

from veilleur.adapters.notifiers.common import Poster, check, message, post
from veilleur.core.ports.plugins import NotificationTarget, RoundCounts


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
        check(self.poster(f"{self.url.rstrip('/')}/{target.topic}", body, headers))
