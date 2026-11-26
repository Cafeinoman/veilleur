# SPDX-License-Identifier: EUPL-1.2
"""Provided notifiers (spec EF-52): `ntfy` and `webhook`, one module each. A notification carries counts, never
content.

Notifiers post to addresses set by the administrator (a local ntfy server is usual), so they do not go through the
collectors' SSRF guard; they never follow redirections.

The names below stay importable from this package (ADR-0028), whatever module holds them.
"""

from veilleur.adapters.notifiers.common import TIMEOUT, NotificationFailed, Poster, message, post
from veilleur.adapters.notifiers.ntfy import NtfyNotifier
from veilleur.adapters.notifiers.webhook import SIGNATURE_HEADER, WebhookNotifier, sign

__all__ = [
    "SIGNATURE_HEADER",
    "TIMEOUT",
    "NotificationFailed",
    "NtfyNotifier",
    "Poster",
    "WebhookNotifier",
    "message",
    "post",
    "sign",
]
