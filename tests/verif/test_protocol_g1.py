# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G1 (protocol 1.0), written from docs/en/protocol.md and the cahier (ES-02 to ES-07).

Every test states the specification clause it checks. No network, no disk writes by the reader.
"""

from __future__ import annotations

import base64
import builtins
import contextlib
import hashlib
import hmac
import io
import json
import os
import random
import struct
import tempfile
import warnings
import zipfile
import zlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from veilleur_protocol import (
    Change,
    Item,
    Kind,
    Limits,
    Ntfy,
    PackageContent,
    PairingCode,
    ProtocolError,
    SigningKey,
    b64u_decode,
    decode_pairing_code,
    encode_items,
    make_rotation,
    open_package,
    open_subscription,
    parse_items,
    parse_time,
    request_scope,
    seal_package,
    seal_subscription,
    sign_request,
    verify_request,
)
from veilleur_protocol.envelope import Header, read_header, seal
from veilleur_protocol.package import manifest_bytes

SECRET = hashlib.sha256(b"verif secret").digest()
UID = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
OTHER_UID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
KEY_ID = "fedcba9876543210"
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
KEY = SigningKey(hashlib.sha256(b"verif server key").digest())
STRANGER = SigningKey(hashlib.sha256(b"verif stranger").digest())
MiB = 1024 * 1024


def _item(key: str, change: Change = Change.NEW) -> Item:
    return Item(key, change, hashlib.sha256(key.encode()).hexdigest(), {"k": key}, NOW, None)


ITEMS = encode_items([_item("a"), _item("b", Change.GONE)])


def _content(**extra: Any) -> PackageContent:
    values: dict[str, Any] = {
        "uid": UID,
        "seq": 1,
        "kind": Kind.DELTA,
        "created_at": NOW,
        "period_to": NOW,
        "period_from": None,
        "items": ITEMS,
    }
    values.update(extra)
    return PackageContent(**values)


def _zip(entries: list[tuple[str, bytes]], compression: int = zipfile.ZIP_STORED) -> bytes:
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in entries:
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = compression
                archive.writestr(info, data)
    return buffer.getvalue()


def _manifest(contents: dict[str, bytes], **changes: Any) -> bytes:
    document = json.loads(manifest_bytes(_content(), contents))
    document.update(changes)
    return json.dumps(document).encode()


def _signed(
    contents: dict[str, bytes], key: SigningKey = KEY, manifest: bytes | None = None, **changes: Any
) -> list[tuple[str, bytes]]:
    data = _manifest(contents, **changes) if manifest is None else manifest
    return [("manifest.json", data), ("manifest.sig", key.sign(data)), *contents.items()]


def _seal(plain: bytes, seq: int = 1, kind: Kind = Kind.DELTA, uid: str = UID) -> bytes:
    return seal(SECRET, Header(uid, seq, kind), plain)


def _code(data: bytes, **options: Any) -> str:
    options.setdefault("trusted_keys", [KEY.public_key])
    with pytest.raises(ProtocolError) as error:
        open_package(data, secret=SECRET, uid=UID, **options)
    return error.value.code


def _open(data: bytes, **options: Any) -> Any:
    options.setdefault("trusted_keys", [KEY.public_key])
    return open_package(data, secret=SECRET, uid=UID, **options)


def _hkdf(secret: bytes, salt: bytes, info: bytes) -> bytes:
    prk = hmac.new(salt or bytes(32), secret, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# --- §5 Envelope -------------------------------------------------------------------------------------------------


def test_envelope_header_layout_and_kind_bytes() -> None:
    """§5: 30-byte header, kind bytes 0x01 0x02 0x03 0x10, 24-byte nonce, 16-byte tag."""
    for kind, byte in ((Kind.DELTA, 1), (Kind.STATE, 2), (Kind.HISTORY, 3), (Kind.SUBSCRIPTION, 0x10)):
        sealed = seal(SECRET, Header(UID, 2**63 - 1, kind), b"abc")
        assert sealed[:4] == b"VEIL" and sealed[4] == 1
        assert sealed[5:21] == bytes.fromhex(UID)
        assert sealed[21:29] == struct.pack(">Q", 2**63 - 1)
        assert sealed[29] == byte
        assert len(sealed) == 30 + 24 + 3 + 16


def test_seq_of_2_pow_63_is_refused_both_ways() -> None:
    """§5: seq is lower than 2^63; §10.2 step 2: seq >= 2^63 is bad_envelope."""
    with pytest.raises(ValueError):
        Header(UID, 2**63, Kind.DELTA).encode()
    sealed = bytearray(_seal(b"x"))
    sealed[21:29] = struct.pack(">Q", 2**63)
    with pytest.raises(ProtocolError) as error:
        read_header(bytes(sealed))
    assert error.value.code == "bad_envelope"


def test_every_header_byte_is_authenticated() -> None:
    """§5: the whole header is the associated data; changing uid, seq or kind makes decryption fail."""
    archive = _zip(_signed({"items.jsonl": ITEMS}))
    sealed = _seal(archive, seq=5)
    for position in range(5, 29):
        altered = bytearray(sealed)
        altered[position] ^= 0x01
        header = read_header(bytes(altered))
        with pytest.raises(ProtocolError) as error:
            open_package(bytes(altered), secret=SECRET, uid=header.uid, trusted_keys=[KEY.public_key])
        assert error.value.code == "decryption_failed", position
    as_state = sealed[:29] + bytes([2]) + sealed[30:]
    assert _code(as_state) == "decryption_failed"


def test_a_70_byte_envelope_passes_step_2() -> None:
    """§10.2 step 2: shorter than 70 bytes is bad_envelope; 70 bytes (empty plaintext) is a valid envelope."""
    sealed = _seal(b"")
    assert len(sealed) == 70
    assert _code(sealed) == "bad_archive"
    assert _code(sealed[:69]) == "bad_envelope"


# --- §10.2 Order of the checks -----------------------------------------------------------------------------------


def test_order_envelope_steps_1_to_4() -> None:
    """§10.2 steps 1 to 4: the first failing check, in the specified order, gives the code."""
    good = _seal(_zip(_signed({"items.jsonl": ITEMS})), seq=3)
    # 1 before 2: too large and bad magic.
    assert _code(b"XXXX" + good[4:], limits=Limits(max_package=len(good) - 1)) == "too_large"
    # 2: magic before version.
    assert _code(b"XXXX\x02" + good[5:]) == "bad_envelope"
    # 2: version before unknown kind; step 2 before step 3 (uid).
    other = bytearray(good)
    other[4] = 2
    other[29] = 0x7F
    other[5:21] = bytes.fromhex(OTHER_UID)
    assert _code(bytes(other)) == "unsupported_version"
    # 2 before 3: seq out of range and other uid.
    other = bytearray(good)
    other[21:29] = struct.pack(">Q", 2**64 - 1)
    other[5:21] = bytes.fromhex(OTHER_UID)
    assert _code(bytes(other)) == "bad_envelope"
    # 3: uid before kind before seq.
    foreign = seal(SECRET, Header(OTHER_UID, 3, Kind.HISTORY), b"x")
    assert _code(foreign, kinds={Kind.DELTA}, seq=4) == "uid_mismatch"
    assert _code(good, kinds={Kind.STATE}, seq=4) == "kind_mismatch"
    # 3 before 4: seq mismatch on an altered ciphertext.
    altered = good[:-1] + bytes([good[-1] ^ 1])
    assert _code(altered, seq=4) == "seq_mismatch"


def test_order_archive_step_5() -> None:
    """§10.2 step 5: count, then entry by entry (name, duplicate/encryption/method, size), then total, then missing."""
    many = [(f"report.x{i}", b"") for i in range(32)] + [("../evil", b"")]
    assert _code(_seal(_zip(many))) == "too_many_files"
    assert _code(_seal(_zip([("evil", b""), ("items.jsonl", b""), ("items.jsonl", b"")]))) == "unexpected_file"
    assert _code(_seal(_zip([("items.jsonl", b""), ("items.jsonl", b""), ("evil", b"")]))) == "bad_archive"
    big = [("report.txt", bytes(2000)), ("evil", b"")]
    assert _code(_seal(_zip(big)), limits=Limits(max_file=1000)) == "file_too_large"
    # file_too_large before missing_file; too_large (sum) before missing_file.
    assert _code(_seal(_zip([("report.txt", bytes(2000))])), limits=Limits(max_file=1000)) == "file_too_large"
    two = [("report.a", bytes(600)), ("report.b", bytes(600))]
    assert _code(_seal(_zip(two)), limits=Limits(max_file=1000, max_total=1000)) == "too_large"
    stored_method_9 = bytearray(_zip(_signed({"items.jsonl": ITEMS})))
    for signature, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        start = stored_method_9.find(signature)
        struct.pack_into("<H", stored_method_9, start + offset, 9)
    assert _code(_seal(bytes(stored_method_9))) == "bad_archive"


def test_order_signature_before_manifest() -> None:
    """§10.2 steps 7 then 8: an unsigned manifest is bad_signature even if the manifest is also malformed."""
    files = {"items.jsonl": ITEMS}
    assert _code(_seal(_zip(_signed(files, key=STRANGER, protocol="2.0", uid=OTHER_UID)))) == "bad_signature"
    assert _code(_seal(_zip(_signed(files, key=STRANGER, manifest=b"[]")))) == "bad_signature"


def test_order_bad_rotation_before_a_trusted_signature() -> None:
    """§10.2 step 7: a rotation statement, if present, must be well-formed and signed, even if the manifest is fine."""
    rotation = make_rotation(STRANGER, KEY.public_key, NOW)
    files = {"items.jsonl": ITEMS, "rotation.json": rotation.statement, "rotation.sig": bytes(64)}
    assert _code(_seal(_zip(_signed(files)))) == "bad_rotation"


def test_order_within_the_manifest() -> None:
    """§10.2 step 8: protocol before uid/seq/kind; malformed members before listed-but-absent files."""
    files = {"items.jsonl": ITEMS}
    assert _code(_seal(_zip(_signed(files, protocol="2.0", uid=OTHER_UID)))) == "unsupported_version"
    absent = {"items.jsonl": hashlib.sha256(ITEMS).hexdigest(), "report.md": "0" * 64}
    assert _code(_seal(_zip(_signed(files, files=absent, created_at="soon")))) == "bad_manifest"
    assert _code(_seal(_zip(_signed(files, kind="history")))) == "bad_manifest"


def test_order_hash_before_items() -> None:
    """§10.2 steps 9 then 10: items that do not match their hash are hash_mismatch, not bad_items."""
    unsorted = encode_items([_item("b")]) + encode_items([_item("a")])
    manifest = _manifest({"items.jsonl": ITEMS})
    entries = [("manifest.json", manifest), ("manifest.sig", KEY.sign(manifest)), ("items.jsonl", unsorted)]
    assert _code(_seal(_zip(entries))) == "hash_mismatch"
    assert _code(_seal(_zip(_signed({"items.jsonl": unsorted})))) == "bad_items"


# --- §10.1 Limits, §7.1 archive ----------------------------------------------------------------------------------


def test_default_limits() -> None:
    """§10.1 / ES-07: 64 MiB envelope, 32 files, 64 MiB per file, 128 MiB in total."""
    assert Limits() == Limits(max_package=64 * MiB, max_files=32, max_file=64 * MiB, max_total=128 * MiB)


def test_32_files_are_accepted_33_are_not() -> None:
    """ES-07: 32 files at most."""
    renderings = {f"report.r{i}": b"x" for i in range(29)}
    package = _seal(_zip(_signed({"items.jsonl": ITEMS, **renderings})))
    assert len(_open(package).renderings) == 29
    renderings["report.r29"] = b"x"
    assert _code(_seal(_zip(_signed({"items.jsonl": ITEMS, **renderings})))) == "too_many_files"


def test_fixed_file_limits() -> None:
    """§10.1: manifest.json 1 MiB, rotation.json 4096 bytes, signatures 64 bytes, whatever max_file says."""
    sig65 = [("manifest.json", b"{}"), ("manifest.sig", bytes(65)), ("items.jsonl", ITEMS)]
    assert _code(_seal(_zip(sig65))) == "file_too_large"
    huge_manifest = [("manifest.json", b" " * (MiB + 1)), ("manifest.sig", bytes(64)), ("items.jsonl", ITEMS)]
    assert _code(_seal(_zip(huge_manifest))) == "file_too_large"
    rotation = [("rotation.json", b" " * 4097), ("rotation.sig", bytes(64)), *_signed({"items.jsonl": ITEMS})]
    assert _code(_seal(_zip(rotation))) == "file_too_large"


def test_names_from_7_1() -> None:
    """§7.1: only listed names at the root; report.<ext> with ext in [a-z0-9]{1,16}."""
    accepted = {"items.jsonl": ITEMS, "report.abcdefghij012345": b"x"}
    assert "report.abcdefghij012345" in _open(_seal(_zip(_signed(accepted)))).renderings
    for name in ("report.abcdefghij0123456", "report.m-d", "./report.md", "report.md/", "report.md\\x", "Report.md"):
        assert _code(_seal(_zip([*_signed({"items.jsonl": ITEMS}), (name, b"")]))) == "unexpected_file", name


def test_a_file_whose_real_size_exceeds_the_declared_one_is_bad_archive() -> None:
    """§10.2 step 6: a size differing from the declared one is bad_archive (even if the CRC fits the prefix)."""
    real, declared = b"x" * 5000, b"x" * 100
    manifest = _manifest({"items.jsonl": ITEMS, "report.txt": declared})
    entries = [("manifest.json", manifest), ("manifest.sig", KEY.sign(manifest)), ("items.jsonl", ITEMS)]
    archive = bytearray(_zip([*entries, ("report.txt", real)], zipfile.ZIP_DEFLATED))
    crc = zlib.crc32(declared)
    headers = ((b"PK\x03\x04", 14, 22, 26, 30), (b"PK\x01\x02", 16, 24, 28, 46))
    for signature, crc_at, size_at, name_len_at, name_at in headers:
        start = 0
        while (start := archive.find(signature, start)) != -1:
            length = struct.unpack_from("<H", archive, start + name_len_at)[0]
            if archive[start + name_at : start + name_at + length] == b"report.txt":
                struct.pack_into("<I", archive, start + crc_at, crc)
                struct.pack_into("<I", archive, start + size_at, len(declared))
            start += 4
    assert _code(_seal(bytes(archive))) == "bad_archive"


# --- §6.3 Key rotation -------------------------------------------------------------------------------------------


def _rotation_files(document: dict[str, Any], signer: SigningKey) -> dict[str, bytes]:
    statement = json.dumps(document).encode()
    return {"items.jsonl": ITEMS, "rotation.json": statement, "rotation.sig": signer.sign(statement)}


def test_rotation_protocol_must_be_the_string_1_0() -> None:
    """§6.3: rotation.json member `protocol` is the string "1.0" (bad_rotation otherwise)."""
    document = {
        "protocol": 1.0,
        "old_key": _b64u(KEY.public_key),
        "new_key": _b64u(STRANGER.public_key),
        "issued_at": "2026-11-17T06:00:00Z",
    }
    assert _code(_seal(_zip(_signed(_rotation_files(document, KEY), key=STRANGER)))) == "bad_rotation"


def test_rotation_with_an_untrusted_old_key_does_not_matter_when_a_trusted_key_signs() -> None:
    """§10.2 step 7: a trusted signature is accepted; nothing is adopted."""
    rotation = make_rotation(STRANGER, KEY.public_key, NOW)
    files = {"items.jsonl": ITEMS, "rotation.json": rotation.statement, "rotation.sig": rotation.signature}
    opened = _open(_seal(_zip(_signed(files))))
    assert opened.rotation is None and opened.signer == KEY.public_key


def test_rotation_adoption_is_not_transitive() -> None:
    """§6.3: a reader adopts new_key only from a statement by a key it trusts (no chain through an untrusted key)."""
    middle = SigningKey(hashlib.sha256(b"verif middle").digest())
    last = SigningKey(hashlib.sha256(b"verif last").digest())
    rotation = make_rotation(middle, last.public_key, NOW)
    sealed = seal_package(SECRET, last, _content(rotation=rotation))
    assert _code(sealed) == "bad_signature"


# --- §8 Request authentication -----------------------------------------------------------------------------------


def test_request_mac_follows_the_specification() -> None:
    """§8 / ES-06: exact string to sign, scope key, base64url without padding (independent computation)."""
    cases = [("GET", "/v1/collectors", b"", None), ("PUT", f"/v1/subscriptions/{UID}?x=%2F", b"\x00body", UID)]
    for method, path, body, scope in cases:
        headers = sign_request(SECRET, KEY_ID, method, path, body, NOW)
        message = f"{method}\n{path}\n2026-11-17T06:00:00Z\n{hashlib.sha256(body).hexdigest()}".encode()
        key = _hkdf(SECRET, b"" if scope is None else bytes.fromhex(scope), b"veilleur-auth")
        assert headers.authorization == f"Veilleur {KEY_ID}:{_b64u(hmac.new(key, message, hashlib.sha256).digest())}"
        assert headers.date == "2026-11-17T06:00:00Z"


@pytest.mark.parametrize(
    ("path", "scope"),
    [
        ("/v1/collectors", None),
        ("/v1/subscriptions", None),
        ("/v1/subscriptionsx/" + UID, None),
        (f"/v1/subscriptions/{UID}", UID),
        (f"/v1/subscriptions/{UID}/", UID),
        (f"/v1/subscriptions/{UID}?after=1", UID),
    ],
)
def test_request_scope(path: str, scope: str | None) -> None:
    """§8: subscription scope when the path starts with /v1/subscriptions/<uid> then /, ? or the end."""
    assert request_scope(path) == scope


@pytest.mark.parametrize(
    "path",
    ["/v1/subscriptions/", f"/v1/subscriptions/{UID.upper()}", f"/v1/subscriptions/{UID}x", "/v1/subscriptions/?a"],
)
def test_malformed_uid_in_the_path_is_refused(path: str) -> None:
    """§8: a malformed uid in the subscription position is refused."""
    with pytest.raises(ProtocolError):
        request_scope(path)


def _verify(date: str | None, authorization: str | None, now: datetime = NOW) -> str:
    path = f"/v1/subscriptions/{UID}"
    with pytest.raises(ProtocolError) as error:
        verify_request(SECRET, "GET", path, b"", authorization=authorization, date=date, now=now)
    return error.value.code


def test_malformed_dates_are_bad_date() -> None:
    """§2 timestamp format exactly YYYY-MM-DDTHH:MM:SSZ; §11 bad_date for a malformed X-Veilleur-Date."""
    auth = sign_request(SECRET, KEY_ID, "GET", f"/v1/subscriptions/{UID}", b"", NOW).authorization
    for date in (
        "2026-11-17T06:00:00z",
        "2026-11-17 06:00:00Z",
        "2026-11-17T06:00:00+00:00",
        "",
        "2026-11-17T24:00:00Z",
    ):
        assert _verify(date, auth) == "bad_date", date


def test_non_ascii_digits_in_the_date_are_bad_date() -> None:
    """§2: exactly YYYY-MM-DDTHH:MM:SSZ; a date with non-ASCII digits must be refused as bad_date, not crash."""
    auth = sign_request(SECRET, KEY_ID, "GET", f"/v1/subscriptions/{UID}", b"", NOW).authorization
    fullwidth = "".join(chr(0xFF10 + int(d)) for d in "2026") + "-11-17T06:00:00Z"  # fullwidth digits
    try:
        code = _verify(fullwidth, auth)
    except Exception as exc:  # pragma: no cover - reported as a defect
        pytest.fail(f"verify_request raised {type(exc).__name__}: {exc}")
    assert code == "bad_date"


def test_parse_time_refuses_non_ascii_digits() -> None:
    """§2: timestamps are ASCII YYYY-MM-DDTHH:MM:SSZ."""
    with pytest.raises(ProtocolError):
        parse_time("".join(chr(0x0660 + int(d)) for d in "2026") + "-11-17T06:00:00Z")  # Arabic-Indic digits


def test_malformed_authorization_is_bad_authorization() -> None:
    """§11: missing or malformed Authorization is bad_authorization (including non-canonical base64url MAC)."""
    path = f"/v1/subscriptions/{UID}"
    auth = sign_request(SECRET, KEY_ID, "GET", path, b"", NOW).authorization
    date = "2026-11-17T06:00:00Z"
    mac = auth.split(":", 1)[1]
    last = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    non_canonical = mac[:-1] + last[last.index(mac[-1]) ^ 1]
    for bad in (
        auth + "=",
        auth.replace(KEY_ID, KEY_ID.upper()),
        f"Veilleur {KEY_ID}: {mac}",
        f"Veilleur  {KEY_ID}:{mac}",
        f"Veilleur {KEY_ID}:{non_canonical}",
        "",
    ):
        assert _verify(date, bad) == "bad_authorization", bad


def test_date_tolerance_is_five_minutes_both_ways() -> None:
    """§8 / ES-06: ±5 minutes accepted, beyond refused with stale_date, checked before the MAC."""
    path = "/v1/collectors"
    headers = sign_request(SECRET, KEY_ID, "GET", path, b"", NOW)
    for delta in (timedelta(minutes=5), -timedelta(minutes=5)):
        verify_request(
            SECRET, "GET", path, b"", authorization=headers.authorization, date=headers.date, now=NOW + delta
        )
    wrong_mac = f"Veilleur {KEY_ID}:{'A' * 43}"
    for delta in (timedelta(minutes=5, seconds=1), -timedelta(minutes=5, seconds=1)):
        with pytest.raises(ProtocolError) as error:
            verify_request(SECRET, "GET", path, b"", authorization=wrong_mac, date=headers.date, now=NOW + delta)
        assert error.value.code == "stale_date"


def test_pairing_wide_key_does_not_open_a_subscription_request() -> None:
    """ES-02: the pairing-scope auth key is not a subscription-scope key."""
    collectors = sign_request(SECRET, KEY_ID, "GET", "/v1/collectors", b"", NOW)
    path = f"/v1/subscriptions/{UID}"
    key = _hkdf(SECRET, b"", b"veilleur-auth")
    message = f"GET\n{path}\n{collectors.date}\n{hashlib.sha256(b'').hexdigest()}".encode()
    forged = f"Veilleur {KEY_ID}:{_b64u(hmac.new(key, message, hashlib.sha256).digest())}"
    assert _verify(collectors.date, forged) == "bad_authorization"


# --- §3 Pairing code ---------------------------------------------------------------------------------------------


def _pairing(document: dict[str, Any]) -> str:
    return "VEIL1:" + _b64u(json.dumps(document, separators=(",", ":")).encode())


def _pairing_document(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "v": 1,
        "server": "https://veille.example.org",
        "key_id": KEY_ID,
        "secret": _b64u(SECRET),
        "sign_key": _b64u(KEY.public_key),
    }
    document.update(changes)
    return document


def test_pairing_unknown_members_are_ignored() -> None:
    """§3: unknown members MUST be ignored."""
    code = decode_pairing_code(_pairing(_pairing_document(future={"x": [1, 2]}, label="desk 3")))
    assert code.secret == SECRET and code.sign_key == KEY.public_key


@pytest.mark.parametrize("v", [True, 1.0, "1", 2, None])
def test_pairing_v_is_the_integer_1(v: object) -> None:
    """§3: `v` is the integer 1; anything else is bad_pairing_code."""
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(_pairing(_pairing_document(v=v)))
    assert error.value.code == "bad_pairing_code"


@pytest.mark.parametrize(
    "server",
    [
        "https://veille.example.org?",
        "https://veille.example.org#",
        "https://veille.example.org//",
        "https://@veille.example.org",
        "HTTPS://veille.example.org/x",
        "https://veille.example.org:443/a",
    ],
)
def test_pairing_server_is_a_bare_origin(server: str) -> None:
    """§3: origin https://host[:port], no user information, path, query or fragment; a single trailing / tolerated."""
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(_pairing(_pairing_document(server=server)))
    assert error.value.code == "bad_pairing_code"


def test_pairing_ntfy_member() -> None:
    """§3: ntfy = {url: https URL, topic: non-empty string, token: optional non-empty string}."""
    ok = decode_pairing_code(_pairing(_pairing_document(ntfy={"url": "https://ntfy.example.net/x", "topic": "t"})))
    assert ok.ntfy == Ntfy("https://ntfy.example.net/x", "t", None)
    bad: list[object] = [
        {"url": "http://ntfy.example.net", "topic": "t"},
        {"url": "https://ntfy.example.net", "topic": ""},
        {"url": "https://ntfy.example.net", "topic": "t", "token": ""},
        {"url": "https://ntfy.example.net", "topic": "t", "token": 5},
        {"topic": "t"},
        [],
    ]
    for ntfy in bad:
        with pytest.raises(ProtocolError) as error:
            decode_pairing_code(_pairing(_pairing_document(ntfy=ntfy)))
        assert error.value.code == "bad_pairing_code", ntfy


def test_pairing_code_length_limit_is_4096_characters() -> None:
    """§3: refuse a code longer than 4096 characters (white space around it is ignored)."""

    def code_of_length(length: int) -> str:
        for padding in range(4000):
            text = _pairing(_pairing_document(pad="a" * padding))
            if len(text) == length:
                return text
        raise AssertionError(length)

    exact = code_of_length(4096)
    assert decode_pairing_code(f"\n  {exact}  \n").key_id == KEY_ID
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(code_of_length(4097))
    assert error.value.code == "bad_pairing_code"


def test_pairing_duplicate_member_names_are_refused() -> None:
    """§2: JSON objects have unique member names; §3: a code not satisfying the format is bad_pairing_code."""
    raw = (
        '{"v":1,"server":"https://veille.example.org","key_id":"'
        + KEY_ID
        + '","secret":"'
        + _b64u(bytes(32))
        + '","secret":"'
        + _b64u(SECRET)
        + '","sign_key":"'
        + _b64u(KEY.public_key)
        + '"}'
    )
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code("VEIL1:" + _b64u(raw.encode()))
    assert error.value.code == "bad_pairing_code"


def test_secrets_never_appear_in_representations() -> None:
    """§3 / ES-09: the pairing code holds secrets (pairing secret, ntfy token); reprs must not show them."""
    token = "tk_verif_secret_token"
    code = PairingCode(
        "https://veille.example.org", KEY_ID, SECRET, KEY.public_key, Ntfy("https://n.example.org", "t", token)
    )
    for text in (repr(code), str(code)):
        assert SECRET.hex() not in text and _b64u(SECRET) not in text and token not in text
    assert token not in repr(code.ntfy)
    assert KEY.seed.hex() not in repr(KEY) and KEY.seed.hex() not in str(KEY)


# --- §7.4 items.jsonl --------------------------------------------------------------------------------------------


def test_items_are_ordered_by_code_point_not_utf16() -> None:
    """§7.4: strictly increasing Unicode code points (U+FFFF < U+10000, although UTF-16 orders them the other way)."""
    low, high = chr(0xFFFF), chr(0x10000)
    data = encode_items([_item(high), _item(low)])
    assert [i.key for i in parse_items(data)] == [low, high]
    reversed_lines = b"".join(reversed(data.splitlines(keepends=True)))
    with pytest.raises(ProtocolError) as error:
        parse_items(reversed_lines)
    assert error.value.code == "bad_items"


@pytest.mark.parametrize(
    "line",
    [
        b"\n",
        b'{"change":"new","fetched_at":"2026-11-17T06:00:00Z","fields":{},"hash":"' + b"a" * 64 + b'","key":"k"}\n',
        b'{"change":"new","fetched_at":"2026-11-17T06:00:00Z","fields":[],"hash":"'
        + b"a" * 64
        + b'","key":"k","url":null}\n',
        b'{"change":"new","fetched_at":"2026-11-17T06:00:00Z","fields":{},"hash":"'
        + b"A" * 64
        + b'","key":"k","url":null}\n',
        b'{"change":"new","fetched_at":"2026-11-17T06:00:00Z","fields":{},"hash":"'
        + b"a" * 64
        + b'","key":"","url":null}\n',
        b'{"change":"new","fetched_at":"2026-11-17T06:00:00Z","fields":{},"hash":"'
        + b"a" * 64
        + b'","key":"k","url":1}\n',
    ],
)
def test_malformed_item_lines(line: bytes) -> None:
    """§7.4: no empty line; url present (string or null); fields an object; lowercase hex hash; non-empty key."""
    with pytest.raises(ProtocolError) as error:
        parse_items(line)
    assert error.value.code == "bad_items"


# --- §7.6 Subscription documents ---------------------------------------------------------------------------------


def test_subscription_base_version_and_kind() -> None:
    """§7.6: seq = base version (0 to create); a package envelope is not a subscription and vice versa."""
    body = seal_subscription(SECRET, UID, 0, {"collector": "rss"})
    assert read_header(body).kind is Kind.SUBSCRIPTION and read_header(body).seq == 0
    assert open_subscription(SECRET, UID, body) == (0, {"collector": "rss"})
    package = seal_package(SECRET, KEY, _content())
    with pytest.raises(ProtocolError) as error:
        open_subscription(SECRET, UID, package)
    assert error.value.code == "kind_mismatch"
    assert _code(body) == "kind_mismatch"


@pytest.mark.parametrize("plain", [b"[]", b'"x"', b"\xef\xbb\xbf{}", b"{", b"\xff"])
def test_subscription_plaintext_not_an_object(plain: bytes) -> None:
    """§10.2 last paragraph: a plaintext that is not a JSON object is bad_subscription."""
    body = seal(SECRET, Header(UID, 0, Kind.SUBSCRIPTION), plain)
    with pytest.raises(ProtocolError) as error:
        open_subscription(SECRET, UID, body)
    assert error.value.code == "bad_subscription"


@pytest.mark.parametrize(
    "plain", [b'{"n":' + b"9" * 5000 + b"}", b'{"n":NaN}', b'{"n":Infinity}'], ids=["huge-int", "nan", "infinity"]
)
def test_subscription_plaintext_that_is_not_rfc8259_json(plain: bytes) -> None:
    """§2 (RFC 8259 JSON) and §10.2: a paired client controls this plaintext; the server must get bad_subscription,
    never another exception."""
    body = seal(SECRET, Header(UID, 0, Kind.SUBSCRIPTION), plain)
    try:
        with pytest.raises(ProtocolError) as error:
            open_subscription(SECRET, UID, body)
    except ProtocolError:
        raise
    except Exception as exc:
        pytest.fail(f"open_subscription raised {type(exc).__name__}: {exc}")
    assert error.value.code == "bad_subscription"


# --- ES-07: nothing in clear on disk -----------------------------------------------------------------------------


@pytest.fixture
def no_disk(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*args: object, **kwargs: object) -> Any:
        raise AssertionError(f"disk access: {args!r}")

    for target, name in (
        (builtins, "open"),
        (io, "open"),
        (os, "open"),
        (tempfile, "mkstemp"),
        (tempfile, "NamedTemporaryFile"),
        (tempfile, "TemporaryFile"),
        (tempfile, "SpooledTemporaryFile"),
        (tempfile, "mkdtemp"),
    ):
        monkeypatch.setattr(target, name, refuse)
    yield


def test_the_reader_writes_nothing_to_disk(no_disk: None) -> None:
    """ES-07 / §10.1: the reference reader keeps decrypted data in memory."""
    rotation = make_rotation(KEY, STRANGER.public_key, NOW)
    sealed = seal_package(SECRET, STRANGER, _content(renderings={"report.md": b"# r"}, rotation=rotation))
    opened = _open(sealed)
    assert opened.rotation is not None and opened.renderings == {"report.md": b"# r"}
    body = seal_subscription(SECRET, UID, 1, {"a": 1})
    assert open_subscription(SECRET, UID, body) == (1, {"a": 1})


# --- ES-13: random data ------------------------------------------------------------------------------------------


def test_random_envelopes_and_headers_only_raise_protocol_errors() -> None:
    """ES-13: random damage to the envelope header and size only ever gives a ProtocolError."""
    generator = random.Random(1117)
    good = seal_package(SECRET, KEY, _content())
    for _ in range(2000):
        data = bytearray(good[: generator.randrange(0, 120)] if generator.random() < 0.3 else good)
        for _ in range(generator.randint(1, 4)):
            if data:
                data[generator.randrange(min(len(data), 30))] = generator.randrange(256)
        with contextlib.suppress(ProtocolError):
            _open(bytes(data))


def test_random_text_only_raises_protocol_errors() -> None:
    """ES-13 spirit: pairing codes, authorization headers and dates from an attacker give ProtocolError only."""
    generator = random.Random(1118)
    alphabet = 'VEIL1:Veilur AZaz09-_=+/{}"\\\n\t' + chr(0xE9) + chr(0xFF10) + chr(0x0660)
    for _ in range(3000):
        text = "".join(generator.choice(alphabet) for _ in range(generator.randrange(0, 80)))
        _clean(decode_pairing_code, text)
        _clean(decode_pairing_code, "VEIL1:" + _b64u(text.encode()))
        _clean(b64u_decode, text)
        _clean(verify_request, SECRET, "GET", "/v1/collectors", b"", authorization=text, date=text, now=NOW)
        auth = f"Veilleur {KEY_ID}:{'A' * 43}"
        _clean(verify_request, SECRET, "GET", "/v1/collectors", b"", authorization=auth, date=text, now=NOW)


def _clean(function: Callable[..., object], *args: object, **kwargs: object) -> None:
    with contextlib.suppress(ProtocolError):
        function(*args, **kwargs)


def test_signed_items_with_huge_numbers_only_raise_protocol_errors() -> None:
    """ES-13 / the reader's contract (test_the_reader_only_ever_raises_protocol_errors): signed content too."""
    items = (
        b'{"change":"new","fetched_at":"2026-11-17T06:00:00Z","fields":{"n":'
        + b"9" * 5000
        + b'},"hash":"'
        + b"a" * 64
        + b'","key":"k","url":null}\n'
    )
    sealed = _seal(_zip(_signed({"items.jsonl": items})))
    try:
        code = _code(sealed)
    except Exception as exc:
        pytest.fail(f"open_package raised {type(exc).__name__}: {exc}")
    assert code == "bad_items"
