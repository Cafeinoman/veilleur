# SPDX-License-Identifier: EUPL-1.2
"""Request authentication (specification §8).

    Authorization: Veilleur <key_id>:<base64url(HMAC-SHA256(A, string to sign))>
    X-Veilleur-Date: 2026-11-17T06:00:00Z

    string to sign = METHOD "\\n" path-and-query "\\n" X-Veilleur-Date "\\n" hex(SHA-256(body))

A is the authentication key of the request's scope: the subscription named in the path (`/v1/subscriptions/{uid}…`),
otherwise the whole pairing.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .encoding import b64u_decode, b64u_encode, format_time, is_key_id, is_uid, parse_time
from .errors import BAD_AUTHORIZATION, BAD_DATE, STALE_DATE, ProtocolError
from .keys import Usage, derive_key

SCHEME = "Veilleur"
DATE_HEADER = "X-Veilleur-Date"
TOLERANCE = timedelta(minutes=5)
MAC_BYTES = 32

_AUTHORIZATION = re.compile(r"Veilleur ([0-9a-f]{16}):([A-Za-z0-9_-]{43})")
_SUBSCRIPTION_PATH = re.compile(r"/v1/subscriptions/([^/?#]*)(?:[/?]|$)")
_METHOD = re.compile(r"[A-Z]+")


@dataclass(frozen=True)
class SignedHeaders:
    authorization: str
    date: str


def request_scope(path_and_query: str) -> str | None:
    """uid of the subscription a request is about, or None for a pairing-wide request."""
    match = _SUBSCRIPTION_PATH.match(path_and_query)
    if match is None:
        return None
    if not is_uid(match.group(1)):
        raise ProtocolError(BAD_AUTHORIZATION, "malformed subscription uid in the path")
    return match.group(1)


def string_to_sign(method: str, path_and_query: str, date: str, body: bytes) -> bytes:
    if not _METHOD.fullmatch(method):
        raise ProtocolError(BAD_AUTHORIZATION, "method in upper case")
    if not path_and_query.startswith("/") or not path_and_query.isascii() or "\n" in path_and_query:
        raise ProtocolError(BAD_AUTHORIZATION, "path and query as sent, ASCII, starting with /")
    return "\n".join((method, path_and_query, date, hashlib.sha256(body).hexdigest())).encode("ascii")


def _mac(secret: bytes, method: str, path_and_query: str, date: str, body: bytes) -> bytes:
    key = derive_key(secret, Usage.AUTH, request_scope(path_and_query))
    return hmac.digest(key, string_to_sign(method, path_and_query, date, body), "sha256")


def sign_request(
    secret: bytes, key_id: str, method: str, path_and_query: str, body: bytes, now: datetime
) -> SignedHeaders:
    """Headers authenticating one request, sent at `now`."""
    if not is_key_id(key_id):
        raise ValueError("key_id is 16 lowercase hexadecimal digits")
    date = format_time(now)
    mac = _mac(secret, method, path_and_query, date, body)
    return SignedHeaders(f"{SCHEME} {key_id}:{b64u_encode(mac)}", date)


def parse_authorization(header: str | None) -> tuple[str, bytes]:
    """`key_id` and MAC of an `Authorization` header; the server looks the secret up by `key_id`."""
    match = _AUTHORIZATION.fullmatch(header or "")
    if match is None:
        raise ProtocolError(BAD_AUTHORIZATION, "expected 'Veilleur <key_id>:<mac>'")
    try:
        return match.group(1), b64u_decode(match.group(2))
    except ProtocolError as exc:
        raise ProtocolError(BAD_AUTHORIZATION, "MAC is not canonical base64url") from exc


def verify_request(
    secret: bytes,
    method: str,
    path_and_query: str,
    body: bytes,
    *,
    authorization: str | None,
    date: str | None,
    now: datetime,
) -> str:
    """Check a request; return its `key_id`. In the order of §8: the header (MAC included), the date, the MAC."""
    key_id, mac = parse_authorization(authorization)
    try:
        sent = parse_time(date)
    except ProtocolError as exc:
        raise ProtocolError(BAD_DATE, f"{DATE_HEADER} looks like 2026-11-17T06:00:00Z") from exc
    if abs(now - sent) > TOLERANCE:
        raise ProtocolError(STALE_DATE, "request date outside the 5-minute tolerance")
    assert date is not None
    expected = _mac(secret, method, path_and_query, date, body)
    if not hmac.compare_digest(expected, mac):
        raise ProtocolError(BAD_AUTHORIZATION, "MAC mismatch")
    return key_id
