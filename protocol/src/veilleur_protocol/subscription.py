# SPDX-License-Identifier: EUPL-1.2
"""Subscription documents sent by a receiving tool (specification §7.6), sealed with the subscription key.

The envelope number is the version the change is based on (0 to create the subscription), so that the server can
refuse a change based on an outdated version, and nobody can replay a sealed body under another version.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from . import strict_json
from .envelope import Header, Kind, open_envelope, seal
from .errors import BAD_SUBSCRIPTION, ProtocolError

MAX_SUBSCRIPTION = 1024 * 1024


def seal_subscription(
    secret: bytes, uid: str, base_version: int, document: Mapping[str, Any], *, nonce: bytes | None = None
) -> bytes:
    """Body of `PUT /v1/subscriptions/{uid}`. `nonce` is for test vectors only."""
    plain = json.dumps(dict(document), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return seal(secret, Header(uid, base_version, Kind.SUBSCRIPTION), plain, nonce=nonce)


def open_subscription(secret: bytes, uid: str, body: bytes) -> tuple[int, dict[str, Any]]:
    """Base version and document of a sealed subscription body for `uid`."""
    header, plain = open_envelope(
        secret, body, uid=uid, kinds=frozenset({Kind.SUBSCRIPTION}), max_size=MAX_SUBSCRIPTION
    )
    try:
        document = strict_json.loads(plain)
    except strict_json.InvalidJson as exc:
        raise ProtocolError(BAD_SUBSCRIPTION, "not UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ProtocolError(BAD_SUBSCRIPTION, "not an object")
    return header.seq, document
