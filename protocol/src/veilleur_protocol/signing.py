# SPDX-License-Identifier: EUPL-1.2
"""Server signing key: pure Ed25519 (RFC 8032), raw 32-byte keys, 64-byte signatures (specification §6)."""

from __future__ import annotations

import secrets

from Cryptodome.PublicKey.ECC import EccKey
from Cryptodome.Signature import eddsa

SEED_BYTES = 32
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64


class SigningKey:
    """The server's private signing key, kept as its 32-byte seed."""

    def __init__(self, seed: bytes) -> None:
        if len(seed) != SEED_BYTES:
            raise ValueError("an Ed25519 seed is 32 bytes")
        self.seed = seed
        self._key: EccKey = eddsa.import_private_key(seed)
        self.public_key: bytes = self._key.public_key().export_key(format="raw")

    @classmethod
    def generate(cls) -> SigningKey:
        return cls(secrets.token_bytes(SEED_BYTES))

    def sign(self, message: bytes) -> bytes:
        signature = eddsa.new(self._key, "rfc8032").sign(message)
        assert isinstance(signature, bytes)
        return signature

    def __repr__(self) -> str:
        return f"SigningKey(public_key={self.public_key.hex()})"


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True if `signature` is a valid Ed25519 signature of `message` by `public_key`."""
    if len(public_key) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:
        return False
    try:
        key = eddsa.import_public_key(public_key)
        eddsa.new(key, "rfc8032").verify(message, signature)
    except ValueError:
        return False
    return True
