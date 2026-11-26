# SPDX-License-Identifier: EUPL-1.2
"""The `webhook` notifier."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from veilleur.adapters.notifiers.common import Poster, check, post
from veilleur.core.ports.plugins import NotificationTarget, RoundCounts

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
        check(self.poster(self.url, body, headers))
