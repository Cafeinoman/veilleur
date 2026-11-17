# SPDX-License-Identifier: EUPL-1.2
"""Independent verification of G1, seventh round.

Written from the specification (docs/en/protocol.md) only. Each test names the requirement it checks. A failing test
is a finding: the code was not changed to make it pass.

The plan's end condition for G1 is "vectors checked by both implementations": the two readers implement one normative
text, so on any input they must agree (same acceptance, same refusal code). Most tests here feed both the same input.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import io
import json
import random
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from veilleur_protocol import (
    Change,
    Item,
    Kind,
    Limits,
    PackageContent,
    PairingCode,
    ProtocolError,
    SigningKey,
    b64u_encode,
    decode_pairing_code,
    encode_items,
    format_time,
    make_rotation,
    open_package,
    verify_request,
)
from veilleur_protocol.envelope import Header, seal
from veilleur_protocol.package import build_archive

ROOT = Path(__file__).resolve().parents[2]
SECRET = hashlib.sha256(b"verif7 secret").digest()
UID = "77889900aabbccddeeff001122334455"
KEY_ID = "2233445566778899"
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
KEY = SigningKey(hashlib.sha256(b"verif7 server key").digest())
OLD_KEY = SigningKey(hashlib.sha256(b"verif7 outgoing key").digest())
HASH = "e" * 64
IDENTITY = bytes([1]) + bytes(31)
"""Encoding of the neutral point of edwards25519: a valid point (RFC 8032 §5.1.3 decodes it), of order 1."""


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verif7_check_vectors", ROOT / "tools" / "check_vectors.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _checker()


def _items(count: int = 2) -> bytes:
    return encode_items(
        [Item(f"k{n}", Change.NEW, HASH, {"n": n, "t": "é"}, NOW, f"https://example.org/{n}") for n in range(count)]
    )


def _content(**changes: Any) -> PackageContent:
    base: dict[str, Any] = {
        "uid": UID,
        "seq": 1,
        "kind": Kind.DELTA,
        "created_at": NOW,
        "period_to": NOW,
        "period_from": None,
        "items": _items(),
        "renderings": {"report.md": b"# report\n"},
        "sources": [{"id": "c1", "ok": True, "last_success": format_time(NOW), "error": None}],
    }
    base.update(changes)
    return PackageContent(**base)


def _envelope(plain: bytes) -> bytes:
    return seal(SECRET, Header(UID, 1, Kind.DELTA), plain)


def _reference(envelope: bytes, trusted: list[bytes], limits: Limits | None = None) -> str | None:
    """Code of the reference reader's refusal, or None if it accepts."""
    try:
        if limits is None:
            open_package(envelope, secret=SECRET, uid=UID, trusted_keys=trusted, seq=1)
        else:
            open_package(envelope, secret=SECRET, uid=UID, trusted_keys=trusted, seq=1, limits=limits)
    except ProtocolError as error:
        return error.code
    return None


def _independent(envelope: bytes, trusted: list[bytes], limits: Limits | None = None) -> str | None:
    """Code of the independent implementation's refusal (tools/check_vectors.py), or None if it accepts.

    Any exception other than its refusal propagates: a crash is a finding of its own.
    """
    case: dict[str, Any] = {
        "secret": SECRET.hex(),
        "envelope": envelope.hex(),
        "uid": UID,
        "seq": 1,
        "trusted_keys": [key.hex() for key in trusted],
    }
    if limits is not None:
        case["limits"] = {
            "max_package": limits.max_package,
            "max_files": limits.max_files,
            "max_file": limits.max_file,
            "max_total": limits.max_total,
        }
    try:
        CHECKER.open_package(case)
    except CHECKER.Refused as refusal:
        code: str = refusal.code
        return code
    return None


def _zip(files: list[tuple[str, bytes]], compression: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = compression
            archive.writestr(info, data)
    return buffer.getvalue()


# --- Both implementations agree on damaged archives (§10.2 steps 5, 6, 9) ----------------------------------------


def _mutate_bytes(data: bytes, generator: random.Random) -> bytes:
    buffer = bytearray(data)
    choice = generator.random()
    if choice < 0.55:
        for _ in range(generator.randint(1, 3)):
            position = generator.randrange(len(buffer))
            buffer[position] = generator.randrange(256)
    elif choice < 0.7:
        del buffer[generator.randrange(len(buffer)) :]
    elif choice < 0.85:
        position = generator.randrange(len(buffer))
        buffer[position:position] = bytes(generator.randrange(256) for _ in range(generator.randint(1, 8)))
    else:
        start = generator.randrange(len(buffer))
        end = min(len(buffer), start + generator.randint(1, 40))
        del buffer[start:end]
    return bytes(buffer)


def _base(name: str) -> tuple[bytes, list[bytes]]:
    """A valid plain archive and the keys a reader must trust to accept it."""
    if name == "rotation":
        content = _content(rotation=make_rotation(OLD_KEY, KEY.public_key, NOW))
        return build_archive(content, KEY, compression=zipfile.ZIP_DEFLATED), [OLD_KEY.public_key]
    compression = zipfile.ZIP_STORED if name == "stored" else zipfile.ZIP_DEFLATED
    return build_archive(_content(), KEY, compression=compression), [KEY.public_key]


@pytest.mark.parametrize("base", ["stored", "deflated", "rotation"])
def test_both_implementations_agree_on_randomly_damaged_archives(base: str) -> None:
    """§10.2 is normative and fixed-order: the reference and the independent reader give the same code for every
    damaged archive (sealed again, so that decryption passes and the archive checks are reached)."""
    plain, trusted = _base(base)
    assert _reference(_envelope(plain), trusted) is None
    assert _independent(_envelope(plain), trusted) is None
    generator = random.Random(f"verif7 {base}")
    disagreements: list[str] = []
    for _ in range(600):
        damaged = _mutate_bytes(plain, generator)
        envelope = _envelope(damaged)
        reference = _reference(envelope, trusted)
        try:
            independent = _independent(envelope, trusted)
        except Exception as exc:
            independent = f"crash {type(exc).__name__}: {exc}"
        if reference != independent:
            disagreements.append(f"reference {reference}, independent {independent}")
    assert not disagreements, f"{len(disagreements)} disagreements, for example: {disagreements[:5]}"


# --- Both implementations agree on signed but malformed manifests and items (§10.2 steps 8 to 10) ------------------


_POOL: list[Any] = [
    None,
    True,
    False,
    0,
    1,
    -1,
    2**63,
    1.5,
    "",
    "1.0",
    "1.01",
    "2.0",
    "1.",
    "x",
    UID,
    UID.upper(),
    "delta",
    "state",
    "2026-11-17T06:00:00Z",
    "2026-11-17T06:00:00",
    "2026-02-30T06:00:00Z",
    "0999-01-01T00:00:00Z",
    [],
    [{}],
    [1],
    {},
    {"from": None},
    {"to": "2026-11-17T06:00:00Z"},
    {"from": None, "to": "2026-11-17T06:00:00Z"},
    "new",
    "gone",
    HASH,
    HASH.upper(),
]


def _mutate_document(document: dict[str, Any], generator: random.Random) -> dict[str, Any]:
    changed = dict(document)
    for _ in range(generator.randint(1, 2)):
        name = generator.choice([*sorted(changed), "extra"])
        if generator.random() < 0.25 and name in changed:
            del changed[name]
        else:
            changed[name] = generator.choice(_POOL)
    return changed


def test_both_implementations_agree_on_signed_malformed_manifests_and_items() -> None:
    """Steps 8 to 10 with a valid signature: manifests and item lines with members of the wrong type, missing or extra,
    signed by the trusted key and with matching hashes. Both readers give the same code."""
    generator = random.Random("verif7 documents")
    base_items = [json.loads(line) for line in _items(3).splitlines()]
    disagreements: list[str] = []
    for round_number in range(500):
        lines = [dict(item) for item in base_items]
        if round_number % 2:
            index = generator.randrange(len(lines))
            lines[index] = _mutate_document(lines[index], generator)
        if generator.random() < 0.2:
            generator.shuffle(lines)
        items = b"".join(json.dumps(line, separators=(",", ":")).encode() + b"\n" for line in lines)
        files = {"items.jsonl": items}
        manifest: dict[str, Any] = {
            "protocol": "1.0",
            "uid": UID,
            "seq": 1,
            "kind": "delta",
            "created_at": format_time(NOW),
            "period": {"from": None, "to": format_time(NOW)},
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            "sources": [],
        }
        if round_number % 2 == 0:
            manifest = _mutate_document(manifest, generator)
        manifest_data = json.dumps(manifest, separators=(",", ":")).encode()
        plain = _zip(
            [("manifest.json", manifest_data), ("manifest.sig", KEY.sign(manifest_data)), *files.items()],
            zipfile.ZIP_STORED,
        )
        envelope = _envelope(plain)
        reference = _reference(envelope, [KEY.public_key])
        try:
            independent = _independent(envelope, [KEY.public_key])
        except Exception as exc:
            independent = f"crash {type(exc).__name__}: {exc}"
        if reference != independent:
            disagreements.append(f"reference {reference}, independent {independent}: {manifest_data[:160]!r}")
    assert not disagreements, f"{len(disagreements)} disagreements, for example: {disagreements[:3]}"


# --- §6.1 Ed25519 keys: a key that validates every message ---------------------------------------------------------


def _identity_signed_package() -> bytes:
    """A package whose manifest "signature" is R = neutral point, S = 0: valid under the neutral public key for any
    message, so anyone holding the pairing secret can make one without any server key."""
    content = _content()
    files = {"items.jsonl": content.items, "report.md": b"# forged\n"}
    manifest = json.dumps(
        {
            "protocol": "1.0",
            "uid": UID,
            "seq": 1,
            "kind": "delta",
            "created_at": format_time(NOW),
            "period": {"from": None, "to": format_time(NOW)},
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            "sources": [],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    plain = _zip(
        [("manifest.json", manifest), ("manifest.sig", IDENTITY + bytes(32)), *files.items()], zipfile.ZIP_STORED
    )
    return _envelope(plain)


def test_a_pairing_code_may_not_carry_the_neutral_point_as_sign_key() -> None:
    """Adapted by the author: this test first recorded that both decoders accepted the neutral point, the defect the
    next tests show. §6.1 now requires a key of the prime-order subgroup: both refuse the code, and nobody can make it.
    """
    document = {"v": 1, "server": "https://example.org", "key_id": KEY_ID}
    document |= {"secret": b64u_encode(SECRET), "sign_key": b64u_encode(IDENTITY)}
    code = "VEIL1:" + b64u_encode(json.dumps(document).encode())
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(code)
    assert error.value.code == "bad_pairing_code"
    with pytest.raises(CHECKER.Refused):
        CHECKER.decode_pairing(code)
    with pytest.raises(ProtocolError):
        PairingCode("https://example.org", KEY_ID, SECRET, IDENTITY)


def test_both_implementations_agree_on_a_manifest_signed_under_the_neutral_point() -> None:
    """§6.1, §10.2 step 7: pure Ed25519 (RFC 8032). The reference (pycryptodomex) accepts the forged signature, the
    independent one (libsodium, which refuses small-order keys) answers `bad_signature`: the two implementations of the
    normative text disagree, and the specification does not say which is right."""
    envelope = _identity_signed_package()
    reference = _reference(envelope, [IDENTITY])
    independent = _independent(envelope, [IDENTITY])
    assert reference == independent, f"reference {reference or 'accepts'}, independent {independent or 'accepts'}"


def test_the_reference_reader_does_not_accept_a_manifest_no_server_key_signed() -> None:
    """Threat model §3, "forging or altering a package": the Ed25519 signature is a defence against whoever holds the
    pairing secret. A trusted key that validates every message removes it; the reference reader accepts the forgery."""
    assert _reference(_identity_signed_package(), [IDENTITY]) == "bad_signature"


def test_the_rotation_writer_refuses_the_neutral_point_as_incoming_key() -> None:
    """Adapted by the author: this test first recorded that `make_rotation` signed the neutral point, which a reader
    would then adopt (§6.3). §6.1 now forbids such a key: the writer refuses it."""
    with pytest.raises(ValueError):
        make_rotation(OLD_KEY, IDENTITY, NOW)


# --- §8 request authentication: method in upper case -----------------------------------------------------------------


def _hand_mac(method: str, path: str, date: str, body: bytes) -> str:
    """MAC computed from §4 and §8 alone, with a pairing-wide key (empty salt)."""
    prk = hmac.new(bytes(32), SECRET, hashlib.sha256).digest()
    key = hmac.new(prk, b"veilleur-auth\x01", hashlib.sha256).digest()
    message = "\n".join((method, path, date, hashlib.sha256(body).hexdigest())).encode("utf-8")
    return f"Veilleur {KEY_ID}:{b64u_encode(hmac.new(key, message, hashlib.sha256).digest())}"


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/v1/collectors"), ("GET", "/v1/collectors\n2026"), ("GET", "/v1/collé")],
    ids=["lower-case method", "line feed in the path", "non-ASCII path"],
)
def test_both_request_verifiers_agree_on_requests_outside_section_8(method: str, path: str) -> None:
    """§8: `method` in upper case, `path-and-query` as sent on the request line. The reference refuses a request whose
    method or path cannot be signed (`bad_authorization`); the independent verifier must give the same answer."""
    date = format_time(NOW)
    authorization = _hand_mac(method, path, date, b"")
    try:
        verify_request(SECRET, method, path, b"", authorization=authorization, date=date, now=NOW)
        reference = None
    except ProtocolError as error:
        reference = error.code
    case = {
        "authorization": authorization,
        "date": date,
        "now": date,
        "secret": SECRET.hex(),
        "method": method,
        "path_and_query": path,
        "body": "",
    }
    try:
        CHECKER.verify_request(case)
        independent = None
    except CHECKER.Refused as refusal:
        independent = refusal.code
    assert reference == independent, f"reference {reference or 'accepts'}, independent {independent or 'accepts'}"


# --- §10.1 limits: a reader MAY lower them ---------------------------------------------------------------------------


def _padded_rotation_package(size: int) -> bytes:
    """A valid package whose `rotation.json` is padded with JSON white space to `size` bytes (still signed)."""
    statement = make_rotation(OLD_KEY, KEY.public_key, NOW).statement
    padded = statement[:-1] + b" " * (size - len(statement)) + b"}"
    assert len(padded) == size
    files = {"items.jsonl": _items(1), "rotation.json": padded, "rotation.sig": OLD_KEY.sign(padded)}
    manifest = json.dumps(
        {
            "protocol": "1.0",
            "uid": UID,
            "seq": 1,
            "kind": "delta",
            "created_at": format_time(NOW),
            "period": {"from": None, "to": format_time(NOW)},
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            "sources": [],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    plain = _zip(
        [("manifest.json", manifest), ("manifest.sig", KEY.sign(manifest)), *files.items()], zipfile.ZIP_STORED
    )
    return _envelope(plain)


def test_a_padded_rotation_statement_within_4096_bytes_is_accepted() -> None:
    """Control: 4090 bytes are within the fixed rotation.json limit, so both readers accept with the defaults."""
    envelope = _padded_rotation_package(4090)
    assert _reference(envelope, [OLD_KEY.public_key]) is None
    assert _independent(envelope, [OLD_KEY.public_key]) is None


def test_a_lowered_file_limit_also_bounds_rotation_json() -> None:
    """§10.1: "declared size of one file" may be lowered by the reader; `Limits.max_file` is documented as "what a
    reader accepts". With `max_file=4000`, a 4090-byte file is over it; `manifest.json` already takes the lower of
    the two limits (min(1 MiB, max_file)), `rotation.json` does not and is accepted."""
    limits = Limits(max_file=4000)
    envelope = _padded_rotation_package(4090)
    assert _reference(envelope, [OLD_KEY.public_key], limits) == "file_too_large"
