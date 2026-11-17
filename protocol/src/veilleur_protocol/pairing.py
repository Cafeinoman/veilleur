# SPDX-License-Identifier: EUPL-1.2
"""Pairing code (specification §3): `VEIL1:` followed by the base64url of a UTF-8 JSON object."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .encoding import b64u_decode, b64u_encode, is_key_id
from .errors import BAD_PAIRING_CODE, ProtocolError
from .keys import SECRET_BYTES
from .signing import PUBLIC_KEY_BYTES

PREFIX = "VEIL1:"
FOLDER = "folder:"
MAX_CODE_LENGTH = 4096


@dataclass(frozen=True)
class Ntfy:
    """Where the receiving tool listens for notifications."""

    url: str
    topic: str
    token: str | None = None


@dataclass(frozen=True)
class PairingCode:
    server: str
    """`https://host[:port]` without path, or `folder:` for delivery by folder only."""
    key_id: str
    secret: bytes
    sign_key: bytes
    ntfy: Ntfy | None = None

    def __post_init__(self) -> None:
        _check(self)

    def __repr__(self) -> str:
        return f"PairingCode(server={self.server!r}, key_id={self.key_id!r}, secret=<hidden>)"

    def encode(self) -> str:
        document: dict[str, Any] = {
            "v": 1,
            "server": self.server,
            "key_id": self.key_id,
            "secret": b64u_encode(self.secret),
            "sign_key": b64u_encode(self.sign_key),
        }
        if self.ntfy is not None:
            ntfy: dict[str, str] = {"url": self.ntfy.url, "topic": self.ntfy.topic}
            if self.ntfy.token is not None:
                ntfy["token"] = self.ntfy.token
            document["ntfy"] = ntfy
        text = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return PREFIX + b64u_encode(text)


def _https_origin(url: object) -> bool:
    if not isinstance(url, str) or not url.isascii() or any(c.isspace() for c in url):
        return False
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises on an invalid port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and parts.username is None
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
    )


def _https_url(url: object) -> bool:
    if not isinstance(url, str) or not url.isascii() or any(c.isspace() for c in url):
        return False
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and parts.username is None


def _check(code: PairingCode) -> None:
    if code.server != FOLDER and not _https_origin(code.server):
        raise ProtocolError(BAD_PAIRING_CODE, "server is an https origin or 'folder:'")
    if not is_key_id(code.key_id):
        raise ProtocolError(BAD_PAIRING_CODE, "key_id is 16 lowercase hexadecimal digits")
    if not isinstance(code.secret, bytes) or len(code.secret) != SECRET_BYTES:
        raise ProtocolError(BAD_PAIRING_CODE, "secret is 32 bytes")
    if not isinstance(code.sign_key, bytes) or len(code.sign_key) != PUBLIC_KEY_BYTES:
        raise ProtocolError(BAD_PAIRING_CODE, "sign_key is 32 bytes")
    if code.ntfy is not None:
        n = code.ntfy
        if not _https_url(n.url):
            raise ProtocolError(BAD_PAIRING_CODE, "ntfy.url is an https URL")
        if not isinstance(n.topic, str) or not n.topic:
            raise ProtocolError(BAD_PAIRING_CODE, "ntfy.topic is a non-empty string")
        if n.token is not None and (not isinstance(n.token, str) or not n.token):
            raise ProtocolError(BAD_PAIRING_CODE, "ntfy.token is a non-empty string")


def decode_pairing_code(text: str) -> PairingCode:
    """Parse and check a pairing code. Surrounding white space is ignored."""
    text = text.strip()
    if len(text) > MAX_CODE_LENGTH:
        raise ProtocolError(BAD_PAIRING_CODE, "too long")
    if not text.startswith(PREFIX):
        raise ProtocolError(BAD_PAIRING_CODE, f"does not start with {PREFIX}")
    try:
        document = json.loads(b64u_decode(text[len(PREFIX) :]).decode("utf-8"))
    except (ProtocolError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(BAD_PAIRING_CODE, "not base64url JSON") from exc
    if not isinstance(document, dict) or document.get("v") != 1:
        raise ProtocolError(BAD_PAIRING_CODE, "not a version 1 pairing code")
    ntfy = document.get("ntfy")
    if ntfy is not None and not isinstance(ntfy, dict):
        raise ProtocolError(BAD_PAIRING_CODE, "ntfy is an object")
    try:
        return PairingCode(
            server=document.get("server"),  # type: ignore[arg-type]
            key_id=document.get("key_id"),  # type: ignore[arg-type]
            secret=b64u_decode(document.get("secret")),  # type: ignore[arg-type]
            sign_key=b64u_decode(document.get("sign_key")),  # type: ignore[arg-type]
            ntfy=None if ntfy is None else Ntfy(ntfy.get("url"), ntfy.get("topic"), ntfy.get("token")),  # type: ignore[arg-type]
        )
    except ProtocolError as exc:
        raise ProtocolError(BAD_PAIRING_CODE, exc.detail) from exc
