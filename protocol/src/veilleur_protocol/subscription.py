# SPDX-License-Identifier: EUPL-1.2
"""Subscription documents sent by a receiving tool (specification §7.6), sealed with the subscription key.

The envelope number is the version the change is based on (0 to create the subscription), so that the server can
refuse a change based on an outdated version, and nobody can replay a sealed body under another version.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import strict_json
from .envelope import OVERHEAD, Header, Kind, open_envelope, seal
from .errors import BAD_SUBSCRIPTION, ProtocolError

MAX_SUBSCRIPTION = 1_000_000
"""Largest subscription envelope: the request body limit of the HTTP interface (cahier ES-11)."""
MAX_DOCUMENT = MAX_SUBSCRIPTION - OVERHEAD


def seal_subscription(
    secret: bytes, uid: str, base_version: int, document: Mapping[str, Any], *, nonce: bytes | None = None
) -> bytes:
    """Body of `PUT /v1/subscriptions/{uid}`. `nonce` is for test vectors only.

    Raises `ValueError` for a document the server would refuse: not JSON (NaN, infinities) or over `MAX_DOCUMENT`.
    """
    plain = strict_json.dumps(dict(document))
    if len(plain) > MAX_DOCUMENT:
        raise ValueError(f"a subscription document is at most {MAX_DOCUMENT} bytes")
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
