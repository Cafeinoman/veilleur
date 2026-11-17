# SPDX-License-Identifier: EUPL-1.2
"""Veilleur protocol 1.0 (normative specification: `docs/en/protocol.md`).

Standalone: it depends on `pycryptodomex` only, never on the Veilleur server.
"""

from __future__ import annotations

from .auth import SignedHeaders, parse_authorization, request_scope, sign_request, verify_request
from .encoding import b64u_decode, b64u_encode, format_time, new_key_id, new_uid, parse_time
from .envelope import PACKAGE_KINDS, Header, Kind, read_header
from .errors import CODES, ProtocolError
from .items import Change, Item, encode_items, parse_items
from .keys import Usage, derive_key, new_secret
from .package import (
    DEFAULT_LIMITS,
    PROTOCOL_VERSION,
    Limits,
    OpenedPackage,
    PackageContent,
    Rotation,
    make_rotation,
    open_package,
    seal_package,
    verify_rotation,
)
from .pairing import Ntfy, PairingCode, decode_pairing_code
from .signing import SigningKey
from .subscription import open_subscription, seal_subscription

__all__ = [
    "CODES",
    "DEFAULT_LIMITS",
    "PACKAGE_KINDS",
    "PROTOCOL_VERSION",
    "Change",
    "Header",
    "Item",
    "Kind",
    "Limits",
    "Ntfy",
    "OpenedPackage",
    "PackageContent",
    "PairingCode",
    "ProtocolError",
    "Rotation",
    "SignedHeaders",
    "SigningKey",
    "Usage",
    "b64u_decode",
    "b64u_encode",
    "decode_pairing_code",
    "derive_key",
    "encode_items",
    "format_time",
    "make_rotation",
    "new_key_id",
    "new_secret",
    "new_uid",
    "open_package",
    "open_subscription",
    "parse_authorization",
    "parse_items",
    "parse_time",
    "read_header",
    "request_scope",
    "seal_package",
    "seal_subscription",
    "sign_request",
    "verify_request",
    "verify_rotation",
]
