# SPDX-License-Identifier: EUPL-1.2
"""Envelope (specification §5): header, then XChaCha20-Poly1305 with the header as associated data.

    header     = "VEIL" | version (1 byte) | uid (16 bytes) | seq (8 bytes, big-endian) | kind (1 byte)
    envelope   = header | nonce (24 bytes) | ciphertext | tag (16 bytes)

The header travels in clear so that a package found in a folder says what it is; it is authenticated, so a package
can be neither replayed under another number or kind nor passed off as another subscription's.
"""

from __future__ import annotations

import secrets
import struct
from dataclasses import dataclass
from enum import Enum

from Cryptodome.Cipher import ChaCha20_Poly1305

from .encoding import uid_bytes
from .errors import (
    BAD_ENVELOPE,
    DECRYPTION_FAILED,
    KIND_MISMATCH,
    SEQ_MISMATCH,
    TOO_LARGE,
    UID_MISMATCH,
    UNSUPPORTED_VERSION,
    ProtocolError,
)
from .keys import Usage, derive_key

MAGIC = b"VEIL"
VERSION = 1
NONCE_BYTES = 24
TAG_BYTES = 16
_HEADER = struct.Struct(">4sB16sQB")
HEADER_BYTES = _HEADER.size
OVERHEAD = HEADER_BYTES + NONCE_BYTES + TAG_BYTES
MAX_SEQ = 2**63 - 1


class Kind(Enum):
    """What an envelope holds. The value is the stable identifier; `code` is the header byte."""

    DELTA = "delta"
    STATE = "state"
    HISTORY = "history"
    SUBSCRIPTION = "subscription"

    @property
    def code(self) -> int:
        return _CODES[self]

    @property
    def usage(self) -> Usage:
        return Usage.SUBSCRIPTION if self is Kind.SUBSCRIPTION else Usage.REPORT


_CODES = {Kind.DELTA: 1, Kind.STATE: 2, Kind.HISTORY: 3, Kind.SUBSCRIPTION: 16}
_KINDS = {code: kind for kind, code in _CODES.items()}
PACKAGE_KINDS = frozenset({Kind.DELTA, Kind.STATE, Kind.HISTORY})


@dataclass(frozen=True)
class Header:
    uid: str
    seq: int
    kind: Kind

    def encode(self) -> bytes:
        if not 0 <= self.seq <= MAX_SEQ:
            raise ValueError("seq is between 0 and 2**63 - 1")
        return _HEADER.pack(MAGIC, VERSION, uid_bytes(self.uid), self.seq, self.kind.code)


def read_header(envelope: bytes) -> Header:
    """Header of an envelope, without opening it."""
    if len(envelope) < OVERHEAD:
        raise ProtocolError(BAD_ENVELOPE, "too short")
    magic, version, uid, seq, code = _HEADER.unpack_from(envelope)
    if magic != MAGIC:
        raise ProtocolError(BAD_ENVELOPE, "not a Veilleur envelope")
    if version != VERSION:
        raise ProtocolError(UNSUPPORTED_VERSION, f"envelope version {version}")
    if seq > MAX_SEQ:
        raise ProtocolError(BAD_ENVELOPE, "seq out of range")
    kind = _KINDS.get(code)
    if kind is None:
        raise ProtocolError(BAD_ENVELOPE, f"unknown kind {code}")
    return Header(uid.hex(), seq, kind)


def seal(secret: bytes, header: Header, plaintext: bytes, *, nonce: bytes | None = None) -> bytes:
    """Encrypt `plaintext` for the subscription and kind named in `header`. `nonce` is for test vectors only."""
    if nonce is None:
        nonce = secrets.token_bytes(NONCE_BYTES)
    if len(nonce) != NONCE_BYTES:
        raise ValueError("the nonce is 24 bytes")
    head = header.encode()
    cipher = ChaCha20_Poly1305.new(key=derive_key(secret, header.kind.usage, header.uid), nonce=nonce)
    cipher.update(head)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return head + nonce + ciphertext + tag


def open_envelope(
    secret: bytes,
    envelope: bytes,
    *,
    uid: str,
    kinds: frozenset[Kind],
    seq: int | None = None,
    max_size: int,
) -> tuple[Header, bytes]:
    """Check the header against what is expected, then decrypt. `seq=None` accepts any number."""
    if len(envelope) > max_size:
        raise ProtocolError(TOO_LARGE, f"envelope larger than {max_size} bytes")
    header = read_header(envelope)
    if header.uid != uid:
        raise ProtocolError(UID_MISMATCH, "envelope for another subscription")
    if header.kind not in kinds:
        raise ProtocolError(KIND_MISMATCH, f"unexpected kind {header.kind.value}")
    if seq is not None and header.seq != seq:
        raise ProtocolError(SEQ_MISMATCH, f"envelope number {header.seq}, expected {seq}")
    nonce = envelope[HEADER_BYTES : HEADER_BYTES + NONCE_BYTES]
    body = envelope[HEADER_BYTES + NONCE_BYTES : -TAG_BYTES]
    tag = envelope[-TAG_BYTES:]
    cipher = ChaCha20_Poly1305.new(key=derive_key(secret, header.kind.usage, header.uid), nonce=nonce)
    cipher.update(envelope[:HEADER_BYTES])
    try:
        plaintext = cipher.decrypt_and_verify(body, tag)
    except ValueError as exc:
        raise ProtocolError(DECRYPTION_FAILED, "authentication failed") from exc
    return header, plaintext
