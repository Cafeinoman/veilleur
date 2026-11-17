# SPDX-License-Identifier: EUPL-1.2
"""Text encodings of the protocol: base64url, identifiers, timestamps (specification §2)."""

from __future__ import annotations

import base64
import binascii
import re
import secrets
from datetime import UTC, datetime

from .errors import BAD_ENCODING, ProtocolError

KEY_ID_BYTES = 8
UID_BYTES = 16

_B64U = re.compile(r"[A-Za-z0-9_-]*")
_KEY_ID = re.compile(rf"[0-9a-f]{{{2 * KEY_ID_BYTES}}}")
_UID = re.compile(rf"[0-9a-f]{{{2 * UID_BYTES}}}")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")  # ASCII digits only
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def b64u_encode(data: bytes) -> str:
    """base64url (RFC 4648 §5) without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    """Strict inverse of `b64u_encode`: no padding, no other character, canonical form only."""
    if not isinstance(text, str) or not _B64U.fullmatch(text) or len(text) % 4 == 1:
        raise ProtocolError(BAD_ENCODING, "not unpadded base64url")
    try:
        data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError(BAD_ENCODING, "not unpadded base64url") from exc
    if b64u_encode(data) != text:
        raise ProtocolError(BAD_ENCODING, "non-canonical base64url")
    return data


def new_key_id() -> str:
    """Random pairing identifier: 8 bytes, lowercase hexadecimal."""
    return secrets.token_hex(KEY_ID_BYTES)


def new_uid() -> str:
    """Random subscription identifier: 16 bytes, lowercase hexadecimal."""
    return secrets.token_hex(UID_BYTES)


def is_key_id(value: object) -> bool:
    return isinstance(value, str) and _KEY_ID.fullmatch(value) is not None


def is_uid(value: object) -> bool:
    return isinstance(value, str) and _UID.fullmatch(value) is not None


def uid_bytes(uid: str) -> bytes:
    if not is_uid(uid):
        raise ProtocolError(BAD_ENCODING, "a uid is 32 lowercase hexadecimal digits")
    return bytes.fromhex(uid)


def format_time(moment: datetime) -> str:
    """UTC timestamp to the second: `2026-11-17T06:00:00Z`."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).strftime(_TIME_FORMAT)


def parse_time(text: object) -> datetime:
    """Strict inverse of `format_time`."""
    if not isinstance(text, str) or not _TIME.fullmatch(text):
        raise ProtocolError(BAD_ENCODING, "timestamps look like 2026-11-17T06:00:00Z")
    try:
        return datetime.strptime(text, _TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise ProtocolError(BAD_ENCODING, "invalid timestamp") from exc
