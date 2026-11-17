# SPDX-License-Identifier: EUPL-1.2
"""Encodings, key derivation, envelope, signatures, against published vectors and libsodium."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

import pytest
from nacl import bindings
from nacl.exceptions import CryptoError

from conftest import SECRET, UID
from veilleur_protocol import ProtocolError, SigningKey, Usage, derive_key
from veilleur_protocol.encoding import b64u_decode, b64u_encode, format_time, new_key_id, new_uid, parse_time
from veilleur_protocol.envelope import Header, Kind, open_envelope, read_header, seal
from veilleur_protocol.signing import verify


@pytest.mark.parametrize("data", [b"", b"f", b"fo", b"foo", b"\xff\xfe\xfd", bytes(range(256))])
def test_base64url_round_trip(data: bytes) -> None:
    text = b64u_encode(data)
    assert "=" not in text and "+" not in text and "/" not in text
    assert b64u_decode(text) == data


@pytest.mark.parametrize("text", ["Zg==", "Zh", "Z", "a+b/", "ab cd", "é"])
def test_base64url_refuses_padding_other_alphabets_and_non_canonical_forms(text: str) -> None:
    with pytest.raises(ProtocolError) as error:
        b64u_decode(text)
    assert error.value.code == "bad_encoding"


def test_identifiers_and_timestamps() -> None:
    assert len(new_key_id()) == 16 and len(new_uid()) == 32
    moment = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
    assert format_time(moment) == "2026-11-17T06:00:00Z"
    assert parse_time("2026-11-17T06:00:00Z") == moment
    for bad in ("2026-11-17T06:00:00", "2026-11-17T06:00:00.5Z", "2026-02-30T06:00:00Z", 12):
        with pytest.raises(ProtocolError):
            parse_time(bad)


def _hkdf(secret: bytes, salt: bytes, info: bytes) -> bytes:
    prk = hmac.new(salt or bytes(32), secret, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def test_key_derivation_is_rfc5869_hkdf_sha256() -> None:
    for usage in Usage:
        assert derive_key(SECRET, usage, UID) == _hkdf(SECRET, bytes.fromhex(UID), usage.value.encode())
    assert derive_key(SECRET, Usage.AUTH, None) == _hkdf(SECRET, b"", b"veilleur-auth")


def test_each_key_serves_one_use_and_one_scope() -> None:
    keys = {derive_key(SECRET, usage, UID) for usage in Usage}
    keys |= {derive_key(SECRET, usage, "ff" * 16) for usage in Usage}
    keys.add(derive_key(SECRET, Usage.AUTH, None))
    assert len(keys) == 7
    with pytest.raises(ValueError):
        derive_key(SECRET, Usage.REPORT, None)
    with pytest.raises(ValueError):
        derive_key(SECRET[:16], Usage.AUTH, None)


def test_xchacha20_poly1305_matches_the_published_vector() -> None:
    """draft-irtf-cfrg-xchacha-03, appendix A.3.1, through the envelope's cipher."""
    from Cryptodome.Cipher import ChaCha20_Poly1305

    plaintext = (
        b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, "
        b"sunscreen would be it."
    )
    cipher = ChaCha20_Poly1305.new(key=bytes(range(0x80, 0xA0)), nonce=bytes(range(0x40, 0x58)))
    cipher.update(bytes.fromhex("50515253c0c1c2c3c4c5c6c7"))
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    assert ciphertext.hex().startswith("bd6d179d3e83d43b9576579493c0e939572a1700252bfaccbed2902c21396cbb")
    assert tag.hex() == "c0875924c1c7987947deafd8780acf49"


def test_envelope_layout_and_libsodium_agreement() -> None:
    nonce = bytes(range(24))
    sealed = seal(SECRET, Header(UID, 7, Kind.STATE), b"plain", nonce=nonce)
    assert sealed[:5] == b"VEIL\x01"
    assert sealed[5:21] == bytes.fromhex(UID)
    assert sealed[21:29] == (7).to_bytes(8, "big")
    assert sealed[29] == 2
    assert sealed[30:54] == nonce
    assert read_header(sealed) == Header(UID, 7, Kind.STATE)
    plain = bindings.crypto_aead_xchacha20poly1305_ietf_decrypt(
        sealed[54:], sealed[:30], nonce, derive_key(SECRET, Usage.REPORT, UID)
    )
    assert plain == b"plain"
    header, opened = open_envelope(SECRET, sealed, uid=UID, kinds=frozenset({Kind.STATE}), seq=7, max_size=1000)
    assert (header.seq, opened) == (7, b"plain")


def test_subscription_envelopes_use_their_own_key() -> None:
    sealed = seal(SECRET, Header(UID, 0, Kind.SUBSCRIPTION), b"{}")
    with pytest.raises(CryptoError):
        bindings.crypto_aead_xchacha20poly1305_ietf_decrypt(
            sealed[54:], sealed[:30], sealed[30:54], derive_key(SECRET, Usage.REPORT, UID)
        )


def test_nonces_are_random() -> None:
    a = seal(SECRET, Header(UID, 1, Kind.DELTA), b"x")
    b = seal(SECRET, Header(UID, 1, Kind.DELTA), b"x")
    assert a[30:54] != b[30:54]


def test_ed25519_matches_rfc8032_test_1() -> None:
    key = SigningKey(bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
    assert key.public_key.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    signature = key.sign(b"")
    assert signature.hex() == (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    assert verify(key.public_key, b"", signature)
    assert not verify(key.public_key, b"x", signature)
    assert not verify(key.public_key, b"", signature[:63])
    assert not verify(bytes(32), b"", signature)
    assert key.seed.hex() not in repr(key)
