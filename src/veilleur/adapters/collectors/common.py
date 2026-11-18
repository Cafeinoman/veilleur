# SPDX-License-Identifier: EUPL-1.2
"""What the provided collectors share: the schema of an address, text normalisation, dates."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

URL_SCHEMA: dict[str, Any] = {
    "type": "string",
    "description": "http or https address",
    "pattern": r"^https?://[^\s]+$",
    "maxLength": 2048,
}
_SPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(text: str | None) -> str:
    """Text with white space collapsed and control characters removed."""
    if text is None:
        return ""
    return _SPACE.sub(" ", _CONTROL.sub("", text)).strip()


def iso_date(text: str | None) -> str | None:
    """A date of a feed (RFC 822 or ISO 8601) as `YYYY-MM-DDTHH:MM:SSZ`; the text as is if it is neither."""
    text = clean(text)
    if not text:
        return None
    parsed: datetime | None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
