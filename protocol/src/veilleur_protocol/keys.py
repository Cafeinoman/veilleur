# SPDX-License-Identifier: EUPL-1.2
"""Key derivation (specification §4): HKDF-SHA256 from the pairing secret, one key per use and per scope."""

from __future__ import annotations

import secrets
from enum import Enum

from Cryptodome.Hash import SHA256
from Cryptodome.Protocol.KDF import HKDF

from .encoding import uid_bytes

SECRET_BYTES = 32
KEY_BYTES = 32


class Usage(Enum):
    """What a derived key is for; the value is the HKDF `info` label."""

    REPORT = "veilleur-report"
    SUBSCRIPTION = "veilleur-subscription"
    AUTH = "veilleur-auth"


def new_secret() -> bytes:
    """A new pairing secret."""
    return secrets.token_bytes(SECRET_BYTES)


def derive_key(secret: bytes, usage: Usage, uid: str | None) -> bytes:
    """Key for `usage`, in the scope of subscription `uid`, or of the whole pairing when `uid` is None.

    Report and subscription keys always have a subscription scope. The salt is the 16 bytes of the uid, or empty for
    the pairing scope.
    """
    if len(secret) != SECRET_BYTES:
        raise ValueError("a pairing secret is 32 bytes")
    if uid is None and usage is not Usage.AUTH:
        raise ValueError(f"{usage.value} keys belong to one subscription")
    salt = b"" if uid is None else uid_bytes(uid)
    key = HKDF(secret, KEY_BYTES, salt, SHA256, context=usage.value.encode("ascii"))
    assert isinstance(key, bytes)
    return key
