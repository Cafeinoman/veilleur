# SPDX-License-Identifier: EUPL-1.2
"""Generate or check the protocol test vectors in `protocol/vectors/`.

    uv run python tools/protocol_vectors.py          # write the vectors
    uv run python tools/protocol_vectors.py --check  # fail if the library no longer produces them

Every input is fixed (secrets, seeds, nonces, dates) and archives are stored without compression, so the output is
reproducible. Binary values are lowercase hexadecimal.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import warnings
import zipfile
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    Usage,
    decode_pairing_code,
    derive_key,
    encode_items,
    format_time,
    make_rotation,
    open_package,
    seal_package,
    seal_subscription,
    sign_request,
    verify_request,
)
from veilleur_protocol import (
    b64u_encode as _b64u,
)
from veilleur_protocol.auth import request_scope, string_to_sign
from veilleur_protocol.envelope import Header, seal
from veilleur_protocol.package import build_archive, manifest_bytes

VECTORS = Path(__file__).resolve().parent.parent / "protocol" / "vectors"
JSON = dict[str, Any]


def _bytes(label: str, size: int = 32) -> bytes:
    """Fixed pseudo-random bytes, so that vectors are reproducible."""
    out = b""
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(f"veilleur test vector: {label}: {counter}".encode()).digest()
        counter += 1
    return out[:size]


SECRET = _bytes("pairing secret")
OTHER_SECRET = _bytes("other pairing secret")
KEY_ID = "0123456789abcdef"
UID = "00112233445566778899aabbccddeeff"
OTHER_UID = "ffeeddccbbaa99887766554433221100"
KEY_1 = SigningKey(_bytes("server signing key 1"))
KEY_2 = SigningKey(_bytes("server signing key 2"))
STRANGER = SigningKey(_bytes("unknown signing key"))
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
YESTERDAY = datetime(2026, 11, 16, 6, 0, 0, tzinfo=UTC)
SMALL = Limits(max_package=16384, max_files=32, max_file=2048, max_total=4096)


def _nonce(label: str) -> bytes:
    return _bytes("nonce " + label, 24)


def _limits(limits: Limits) -> JSON:
    return {
        "max_package": limits.max_package,
        "max_files": limits.max_files,
        "max_file": limits.max_file,
        "max_total": limits.max_total,
    }


ITEMS = [
    Item(
        "https://example.org/news/1",
        Change.NEW,
        hashlib.sha256(b"item 1").hexdigest(),
        {"title": "Première nouvelle", "summary": "Texte d'exemple."},
        NOW,
        "https://example.org/news/1",
    ),
    Item(
        "https://example.org/news/2",
        Change.CHANGED,
        hashlib.sha256(b"item 2").hexdigest(),
        {"title": "Second item", "tags": ["a", "b"]},
        NOW,
        "https://example.org/news/2",
    ),
    Item("source-id-3", Change.GONE, hashlib.sha256(b"item 3").hexdigest(), {"title": "Gone"}, NOW, None),
]
SOURCES = [{"id": "rss:example.org", "ok": True, "last_success": format_time(NOW), "error": None}]


def _content(seq: int, kind: Kind, **extra: Any) -> PackageContent:
    fields: JSON = {
        "uid": UID,
        "seq": seq,
        "kind": kind,
        "created_at": NOW,
        "period_to": NOW,
        "period_from": YESTERDAY,
        "items": encode_items(ITEMS),
        "renderings": {"report.md": "# Report\n\n- Première nouvelle\n".encode()},
        "sources": SOURCES,
    }
    fields.update(extra)
    return PackageContent(**fields)


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(buffer, "w") as archive:
        warnings.simplefilter("ignore")  # some refusal vectors hold a duplicate name on purpose
        for name, data in entries:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


# --- Vectors ----------------------------------------------------------------------------------------------------


def keys() -> JSON:
    cases = []
    for secret, uid in ((SECRET, UID), (SECRET, OTHER_UID), (SECRET, None), (OTHER_SECRET, UID)):
        for usage in Usage:
            if uid is None and usage is not Usage.AUTH:
                continue
            cases.append(
                {"secret": secret.hex(), "uid": uid, "info": usage.value, "key": derive_key(secret, usage, uid).hex()}
            )
    return {"description": "HKDF-SHA256(secret, salt = uid bytes or empty, info) -> 32 bytes", "cases": cases}


def pairing() -> JSON:
    codes = [
        PairingCode(
            "https://veille.example.org",
            KEY_ID,
            SECRET,
            KEY_1.public_key,
            Ntfy("https://ntfy.example.org", "veilleur-0123", "tk_example"),
        ),
        PairingCode("folder:", "fedcba9876543210", OTHER_SECRET, KEY_2.public_key),
        PairingCode("https://[2001:db8::1]:8443/", "0011223344556677", SECRET, KEY_2.public_key),
    ]
    cases = []
    for code in codes:
        cases.append(
            {
                "code": code.encode(),
                "server": code.server,
                "key_id": code.key_id,
                "secret": code.secret.hex(),
                "sign_key": code.sign_key.hex(),
                "ntfy": None
                if code.ntfy is None
                else {"url": code.ntfy.url, "topic": code.ntfy.topic, "token": code.ntfy.token},
            }
        )
    return {"description": "VEIL1: + base64url(UTF-8 JSON)", "cases": cases}


def requests() -> JSON:
    cases = []
    for method, path, body in (
        ("GET", "/v1/collectors", b""),
        ("GET", f"/v1/subscriptions/{UID}/reports?after=3", b""),
        (
            "PUT",
            f"/v1/subscriptions/{UID}",
            seal_subscription(SECRET, UID, 0, {"collector": "rss"}, nonce=_nonce("request")),
        ),
        ("DELETE", f"/v1/subscriptions/{OTHER_UID}", b""),
    ):
        headers = sign_request(SECRET, KEY_ID, method, path, body, NOW)
        cases.append(
            {
                "secret": SECRET.hex(),
                "key_id": KEY_ID,
                "method": method,
                "path_and_query": path,
                "body": body.hex(),
                "date": headers.date,
                "scope": request_scope(path),
                "string_to_sign": string_to_sign(method, path, headers.date, body).decode("ascii"),
                "authorization": headers.authorization,
            }
        )
    return {
        "description": "Authorization: Veilleur <key_id>:<base64url(HMAC-SHA256(A, string to sign))>",
        "cases": cases,
    }


def subscriptions() -> JSON:
    cases = []
    for version, document in (
        (0, {"collector": "rss", "params": {"url": "https://example.org/feed.xml"}}),
        (4, {"collector": "rss", "language": "fr"}),
    ):
        envelope = seal_subscription(SECRET, UID, version, document, nonce=_nonce(f"subscription {version}"))
        cases.append(
            {
                "secret": SECRET.hex(),
                "uid": UID,
                "base_version": version,
                "document": document,
                "envelope": envelope.hex(),
            }
        )
    return {"description": "Sealed subscription documents (kind subscription, seq = base version)", "cases": cases}


def _package_case(
    name: str, content: PackageContent, key: SigningKey, trusted: list[SigningKey | bytes], seq: int | None
) -> JSON:
    archive = build_archive(content, key, compression=zipfile.ZIP_STORED)
    envelope = seal(SECRET, Header(content.uid, content.seq, content.kind), archive, nonce=_nonce(name))
    trusted_keys = [k.public_key if isinstance(k, SigningKey) else k for k in trusted]
    opened = open_package(envelope, secret=SECRET, uid=UID, trusted_keys=trusted_keys, seq=seq)
    with zipfile.ZipFile(io.BytesIO(archive)) as plain:
        files = {n: plain.read(n) for n in plain.namelist()}
    return {
        "name": name,
        "secret": SECRET.hex(),
        "uid": UID,
        "seq": seq,
        "trusted_keys": [k.hex() for k in trusted_keys],
        "envelope": envelope.hex(),
        "archive": archive.hex(),
        "expected": {
            "kind": opened.kind.value,
            "seq": opened.seq,
            "files": {n: d.hex() for n, d in files.items()},
            "manifest": opened.manifest,
            "items": [json.loads(line) for line in content.items.splitlines()],
            "signer": opened.signer.hex(),
            "adopted_key": None if opened.rotation is None else opened.rotation.new_key.hex(),
        },
    }


def packages() -> JSON:
    rotation = make_rotation(KEY_1, KEY_2.public_key, YESTERDAY)
    return {
        "description": "Valid packages: envelope, plain archive, and what a reader must find in them",
        "cases": [
            _package_case("delta", _content(2, Kind.DELTA), KEY_1, [KEY_1], 2),
            _package_case("state", _content(1, Kind.STATE, period_from=None, renderings={}), KEY_1, [KEY_1], None),
            _package_case("history", _content(5, Kind.HISTORY, items=b""), KEY_1, [KEY_1], 5),
            _package_case("rotation adopted", _content(3, Kind.DELTA, rotation=rotation), KEY_2, [KEY_1], 3),
            _package_case("rotation already trusted", _content(3, Kind.DELTA, rotation=rotation), KEY_2, [KEY_2], 3),
        ],
    }


def _refusal(
    name: str,
    envelope: bytes,
    error: str,
    *,
    uid: str = UID,
    seq: int | None = 2,
    kinds: tuple[Kind, ...] = (Kind.DELTA, Kind.STATE, Kind.HISTORY),
    trusted: list[SigningKey] | None = None,
    limits: Limits | None = None,
) -> JSON:
    trusted_keys = [k.public_key for k in (trusted or [KEY_1])]
    try:
        open_package(
            envelope, secret=SECRET, uid=uid, trusted_keys=trusted_keys, seq=seq, kinds=kinds, limits=limits or Limits()
        )
    except ProtocolError as exc:
        if exc.code != error:
            raise AssertionError(f"{name}: expected {error}, got {exc.code} ({exc.detail})") from exc
    else:
        raise AssertionError(f"{name}: not refused")
    return {
        "name": name,
        "secret": SECRET.hex(),
        "uid": uid,
        "seq": seq,
        "kinds": [k.value for k in kinds],
        "trusted_keys": [k.hex() for k in trusted_keys],
        "limits": _limits(limits or Limits()),
        "envelope": envelope.hex(),
        "error": error,
    }


def _signed(
    entries: dict[str, bytes],
    manifest: JSON | None = None,
    key: SigningKey = KEY_1,
    extra: list[tuple[str, bytes]] | None = None,
) -> list[tuple[str, bytes]]:
    """Archive entries with a manifest listing `entries` (or the given manifest), signed by `key`."""
    content = _content(2, Kind.DELTA)
    data = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        if manifest
        else manifest_bytes(content, entries)
    )
    return [("manifest.json", data), ("manifest.sig", key.sign(data)), *entries.items(), *(extra or [])]


def _sealed(
    entries: list[tuple[str, bytes]],
    label: str,
    seq: int = 2,
    kind: Kind = Kind.DELTA,
    uid: str = UID,
    secret: bytes = SECRET,
) -> bytes:
    return seal(secret, Header(uid, seq, kind), _zip(entries), nonce=_nonce("refusal " + label))


def _manifest(**changes: Any) -> JSON:
    content = _content(2, Kind.DELTA)
    document: JSON = json.loads(manifest_bytes(content, {"items.jsonl": content.items}))
    document.update(changes)
    return document


def _manifest_text(items: bytes) -> bytes:
    return manifest_bytes(_content(2, Kind.DELTA), {"items.jsonl": items})


def _signed_manifest(manifest: bytes, items: bytes) -> list[tuple[str, bytes]]:
    return [("manifest.json", manifest), ("manifest.sig", KEY_1.sign(manifest)), ("items.jsonl", items)]


def _gap_before_end(items: bytes) -> bytes:
    """A valid archive with 16 bytes inserted before the end record: readers would disagree on the offsets."""
    plain = _zip(_signed({"items.jsonl": items}))
    end = plain.rfind(b"PK\x05\x06")
    return seal(SECRET, Header(UID, 2, Kind.DELTA), plain[:end] + bytes(16) + plain[end:], nonce=_nonce("refusal gap"))


def _longer_than_declared(items: bytes) -> bytes:
    """`report.txt` holds 5000 bytes, but its headers declare the first 100 (size and CRC), as the manifest does."""
    real, declared = b"x" * 5000, b"x" * 100
    files = {"items.jsonl": items, "report.txt": declared}
    manifest = manifest_bytes(_content(2, Kind.DELTA), files)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in (*_signed_manifest(manifest, items), ("report.txt", real)):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    plain = bytearray(buffer.getvalue())
    for signature, crc_at, size_at, name_length_at, name_at in (
        (b"PK\x03\x04", 14, 22, 26, 30),
        (b"PK\x01\x02", 16, 24, 28, 46),
    ):
        start = 0
        while (start := plain.find(signature, start)) != -1:
            length = int.from_bytes(plain[start + name_length_at : start + name_length_at + 2], "little")
            if plain[start + name_at : start + name_at + length] == b"report.txt":
                plain[start + crc_at : start + crc_at + 4] = zlib.crc32(declared).to_bytes(4, "little")
                plain[start + size_at : start + size_at + 4] = len(declared).to_bytes(4, "little")
            start += 4
    return seal(SECRET, Header(UID, 2, Kind.DELTA), bytes(plain), nonce=_nonce("refusal longer"))


def _local_crc_changed(items: bytes) -> bytes:
    """A valid archive, except that the local header of `items.jsonl` declares another CRC than the directory."""
    plain = bytearray(_zip(_signed({"items.jsonl": items})))
    at = plain.find(b"PK\x03\x04")
    while plain[at + 30 : at + 41] != b"items.jsonl":
        at = plain.find(b"PK\x03\x04", at + 4)
    plain[at + 14] ^= 0xFF
    return bytes(plain)


def _non_canonical(authorization: str) -> str:
    """Same MAC, but the unused low bits of its last base64url character set."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    return authorization[:-1] + alphabet[alphabet.index(authorization[-1]) | 1]


def refusals() -> JSON:
    good = seal_package(
        SECRET, KEY_1, _content(2, Kind.DELTA), compression=zipfile.ZIP_STORED, nonce=_nonce("refusal base")
    )
    items = encode_items(ITEMS)
    flipped = bytearray(good)
    flipped[-40] ^= 1
    other_seq = bytearray(good)
    other_seq[28] ^= 1  # last byte of the number in the header
    bad_magic = b"VEIX" + good[4:]
    version_2 = good[:4] + b"\x02" + good[5:]
    kind_99 = good[:29] + b"\x63" + good[30:]
    rotation_1_2 = make_rotation(KEY_1, KEY_2.public_key, YESTERDAY)
    rotation_x_2 = make_rotation(STRANGER, KEY_2.public_key, YESTERDAY)
    rot = {"rotation.json": rotation_1_2.statement, "rotation.sig": rotation_1_2.signature}
    many = {f"report.x{i}": b"" for i in range(30)}
    cases_packages = [
        _refusal("altered ciphertext", bytes(flipped), "decryption_failed"),
        _refusal(
            "other pairing",
            seal_package(OTHER_SECRET, KEY_1, _content(2, Kind.DELTA), nonce=_nonce("other pairing")),
            "decryption_failed",
        ),
        _refusal(
            "other subscription",
            seal_package(SECRET, KEY_1, _content(2, Kind.DELTA, uid=OTHER_UID), nonce=_nonce("other uid")),
            "uid_mismatch",
        ),
        _refusal("other number expected", good, "seq_mismatch", seq=3),
        _refusal("number changed in the header", bytes(other_seq), "decryption_failed", seq=None),
        _refusal("kind not expected", good, "kind_mismatch", kinds=(Kind.STATE,)),
        _refusal(
            "subscription envelope as a package",
            seal_subscription(SECRET, UID, 2, {}, nonce=_nonce("sub as package")),
            "kind_mismatch",
        ),
        _refusal("bad magic", bad_magic, "bad_envelope"),
        _refusal("future envelope version", version_2, "unsupported_version"),
        _refusal("unknown kind", kind_99, "bad_envelope"),
        _refusal("truncated", good[:60], "bad_envelope"),
        _refusal("package too large", good, "too_large", limits=Limits(max_package=len(good) - 1)),
        _refusal(
            "not a zip archive",
            seal(SECRET, Header(UID, 2, Kind.DELTA), b"not a zip", nonce=_nonce("not zip")),
            "bad_archive",
        ),
        _refusal(
            "path in a file name",
            _sealed(_signed({"items.jsonl": items}, extra=[("../items.jsonl", b"")]), "path"),
            "unexpected_file",
        ),
        _refusal(
            "directory in a file name",
            _sealed(_signed({"items.jsonl": items}, extra=[("sub/report.md", b"")]), "dir"),
            "unexpected_file",
        ),
        _refusal(
            "file not provided for",
            _sealed(_signed({"items.jsonl": items}, extra=[("run.sh", b"")]), "unexpected"),
            "unexpected_file",
        ),
        _refusal("too many files", _sealed(_signed({"items.jsonl": items, **many}), "many"), "too_many_files"),
        _refusal(
            "file too large",
            _sealed(_signed({"items.jsonl": items, "report.md": b"x" * 2100}), "big"),
            "file_too_large",
            limits=SMALL,
        ),
        _refusal(
            "content too large",
            _sealed(
                _signed(
                    {
                        "items.jsonl": items,
                        "report.md": b"x" * 1200,
                        "report.html": b"x" * 1200,
                        "report.txt": b"x" * 1200,
                    }
                ),
                "total",
            ),
            "too_large",
            limits=SMALL,
        ),
        _refusal(
            "duplicate file",
            _sealed(_signed({"items.jsonl": items}, extra=[("items.jsonl", items)]), "duplicate"),
            "bad_archive",
        ),
        _refusal("items missing", _sealed(_signed({}), "no items"), "missing_file"),
        _refusal(
            "signature missing", _sealed([("manifest.json", b"{}"), ("items.jsonl", items)], "no sig"), "missing_file"
        ),
        _refusal(
            "rotation without its signature",
            _sealed(_signed({"items.jsonl": items, "rotation.json": rotation_1_2.statement}), "half rotation"),
            "missing_file",
        ),
        _refusal(
            "untrusted signer", _sealed(_signed({"items.jsonl": items}, key=STRANGER), "stranger"), "bad_signature"
        ),
        _refusal(
            "manifest altered after signing",
            _sealed(
                [
                    (n, d.replace(b'"seq":2', b'"seq":2 ') if n == "manifest.json" else d)
                    for n, d in _signed({"items.jsonl": items})
                ],
                "altered manifest",
            ),
            "bad_signature",
        ),
        _refusal(
            "rotation from an untrusted key",
            _sealed(
                _signed(
                    {
                        "items.jsonl": items,
                        "rotation.json": rotation_x_2.statement,
                        "rotation.sig": rotation_x_2.signature,
                    },
                    key=KEY_2,
                ),
                "rot stranger",
            ),
            "bad_signature",
        ),
        _refusal(
            "rotation with a false signature",
            _sealed(
                _signed(
                    {
                        "items.jsonl": items,
                        "rotation.json": rotation_1_2.statement,
                        "rotation.sig": rotation_x_2.signature,
                    },
                    key=KEY_2,
                ),
                "rot sig",
            ),
            "bad_rotation",
        ),
        _refusal(
            "rotation to another key than the signer's",
            _sealed(_signed({"items.jsonl": items, **rot}, key=STRANGER), "rot other"),
            "bad_signature",
        ),
        _refusal(
            "manifest for another number",
            _sealed(_signed({"items.jsonl": items}, _manifest(seq=3)), "manifest seq"),
            "bad_manifest",
        ),
        _refusal(
            "manifest for another subscription",
            _sealed(_signed({"items.jsonl": items}, _manifest(uid=OTHER_UID)), "manifest uid"),
            "bad_manifest",
        ),
        _refusal(
            "future protocol",
            _sealed(_signed({"items.jsonl": items}, _manifest(protocol="2.0")), "protocol 2"),
            "unsupported_version",
        ),
        _refusal(
            "file listed but absent",
            _sealed(
                _signed(
                    {"items.jsonl": items},
                    _manifest(files={"items.jsonl": hashlib.sha256(items).hexdigest(), "report.md": "0" * 64}),
                ),
                "absent",
            ),
            "missing_file",
        ),
        _refusal(
            "file present but not listed",
            _sealed(_signed({"items.jsonl": items}, extra=[("report.md", b"# x\n")]), "unlisted"),
            "unexpected_file",
        ),
        _refusal(
            "file altered",
            _sealed(
                [(n, items[:-2] + b" \n" if n == "items.jsonl" else d) for n, d in _signed({"items.jsonl": items})],
                "altered items",
            ),
            "hash_mismatch",
        ),
        _refusal(
            "items not sorted",
            _sealed(_signed({"items.jsonl": b"".join(reversed(items.splitlines(keepends=True)))}), "unsorted"),
            "bad_items",
        ),
        _refusal(
            "NaN in an item",
            _sealed(_signed({"items.jsonl": items.replace(b'"tags":["a","b"]', b'"tags":NaN')}), "nan"),
            "bad_items",
        ),
        _refusal(
            "duplicate member in the manifest",
            _sealed(_signed_manifest(_manifest_text(items)[:-1] + b',"seq":2}', items), "duplicate member"),
            "bad_manifest",
        ),
        _refusal("file longer than declared", _longer_than_declared(items), "bad_archive"),
        _refusal(
            "local header differs from the central directory",
            seal(SECRET, Header(UID, 2, Kind.DELTA), _local_crc_changed(items), nonce=_nonce("refusal local")),
            "bad_archive",
        ),
        _refusal("bytes between the central directory and its end record", _gap_before_end(items), "bad_archive"),
        _refusal(
            "period without from",
            _sealed(_signed({"items.jsonl": items}, _manifest(period={"to": format_time(NOW)})), "period"),
            "bad_manifest",
        ),
        _refusal(
            "change of the wrong type",
            _sealed(_signed({"items.jsonl": items.replace(b'"change":"gone"', b'"change":["gone"]')}), "change"),
            "bad_items",
        ),
        _refusal(
            "number overflowing to infinity",
            _sealed(_signed({"items.jsonl": items.replace(b'"tags":["a","b"]', b'"tags":1e400')}), "inf"),
            "bad_items",
        ),
    ]
    cases_requests = []
    signed = sign_request(SECRET, KEY_ID, "GET", f"/v1/subscriptions/{UID}/state", b"", NOW)
    for name, method, path, body, authorization, date, now, error in (
        (
            "late request",
            "GET",
            f"/v1/subscriptions/{UID}/state",
            b"",
            signed.authorization,
            signed.date,
            "2026-11-17T06:05:01Z",
            "stale_date",
        ),
        (
            "request from the future",
            "GET",
            f"/v1/subscriptions/{UID}/state",
            b"",
            signed.authorization,
            signed.date,
            "2026-11-17T05:54:59Z",
            "stale_date",
        ),
        (
            "other path",
            "GET",
            f"/v1/subscriptions/{OTHER_UID}/state",
            b"",
            signed.authorization,
            signed.date,
            "2026-11-17T06:00:00Z",
            "bad_authorization",
        ),
        (
            "other method",
            "DELETE",
            f"/v1/subscriptions/{UID}/state",
            b"",
            signed.authorization,
            signed.date,
            "2026-11-17T06:00:00Z",
            "bad_authorization",
        ),
        (
            "other body",
            "GET",
            f"/v1/subscriptions/{UID}/state",
            b"x",
            signed.authorization,
            signed.date,
            "2026-11-17T06:00:00Z",
            "bad_authorization",
        ),
        (
            "malformed date",
            "GET",
            f"/v1/subscriptions/{UID}/state",
            b"",
            signed.authorization,
            "2026-11-17 06:00:00",
            "2026-11-17T06:00:00Z",
            "bad_date",
        ),
        (
            "other scheme",
            "GET",
            f"/v1/subscriptions/{UID}/state",
            b"",
            "Bearer abc",
            signed.date,
            "2026-11-17T06:00:00Z",
            "bad_authorization",
        ),
        (
            "uid in upper case in the path",
            "GET",
            f"/v1/subscriptions/{UID.upper()}/state",
            b"",
            signed.authorization,
            signed.date,
            "2026-11-17T06:00:00Z",
            "bad_authorization",
        ),
        (
            "non-canonical MAC",
            "GET",
            f"/v1/subscriptions/{UID}/state",
            b"",
            _non_canonical(signed.authorization),
            signed.date,
            "2026-11-17T06:00:00Z",
            "bad_authorization",
        ),
    ):
        try:
            verify_request(
                SECRET,
                method,
                path,
                body,
                authorization=authorization,
                date=date,
                now=datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC),
            )
        except ProtocolError as exc:
            assert exc.code == error, (name, exc.code)
        else:
            raise AssertionError(f"{name}: not refused")
        cases_requests.append(
            {
                "name": name,
                "secret": SECRET.hex(),
                "method": method,
                "path_and_query": path,
                "body": body.hex(),
                "authorization": authorization,
                "date": date,
                "now": now,
                "error": error,
            }
        )
    cases_pairing = []
    for name, code in (
        ("no prefix", "VEIL2:e30"),
        ("not base64url", "VEIL1:e30="),
        (
            "http server",
            "VEIL1:"
            + _b64(
                {
                    "v": 1,
                    "server": "http://veille.example.org",
                    "key_id": KEY_ID,
                    "secret": _b64u(SECRET),
                    "sign_key": _b64u(KEY_1.public_key),
                }
            ),
        ),
        (
            "short secret",
            "VEIL1:"
            + _b64(
                {
                    "v": 1,
                    "server": "folder:",
                    "key_id": KEY_ID,
                    "secret": _b64u(SECRET[:16]),
                    "sign_key": _b64u(KEY_1.public_key),
                }
            ),
        ),
        (
            "wrong version",
            "VEIL1:"
            + _b64(
                {
                    "v": 2,
                    "server": "folder:",
                    "key_id": KEY_ID,
                    "secret": _b64u(SECRET),
                    "sign_key": _b64u(KEY_1.public_key),
                }
            ),
        ),
        (
            "version as a boolean",
            "VEIL1:"
            + _b64(
                {
                    "v": True,
                    "server": "folder:",
                    "key_id": KEY_ID,
                    "secret": _b64u(SECRET),
                    "sign_key": _b64u(KEY_1.public_key),
                }
            ),
        ),
        (
            "server with an empty query",
            "VEIL1:"
            + _b64(
                {
                    "v": 1,
                    "server": "https://veille.example.org?",
                    "key_id": KEY_ID,
                    "secret": _b64u(SECRET),
                    "sign_key": _b64u(KEY_1.public_key),
                }
            ),
        ),
        (
            "ntfy null",
            "VEIL1:"
            + _b64(
                {
                    "v": 1,
                    "server": "folder:",
                    "key_id": KEY_ID,
                    "secret": _b64u(SECRET),
                    "sign_key": _b64u(KEY_1.public_key),
                    "ntfy": None,
                }
            ),
        ),
        *(
            (
                f"server {server}",
                "VEIL1:"
                + _b64(
                    {
                        "v": 1,
                        "server": server,
                        "key_id": KEY_ID,
                        "secret": _b64u(SECRET),
                        "sign_key": _b64u(KEY_1.public_key),
                    }
                ),
            )
            for server in (
                "https://veille.example.org\\evil",
                "https://veille.example.org:0",
                "https://veille.example.org:99999",
                "https://<veille>.example.org",
                "https://veille.example.org%2Fx",
                "https://010.0.0.1",
            )
        ),
        *(
            (
                f"ntfy {label}",
                "VEIL1:"
                + _b64(
                    {
                        "v": 1,
                        "server": "folder:",
                        "key_id": KEY_ID,
                        "secret": _b64u(SECRET),
                        "sign_key": _b64u(KEY_1.public_key),
                        "ntfy": ntfy,
                    }
                ),
            )
            for label, ntfy in (
                ("url with a fragment", {"url": "https://ntfy.example.org/a#b", "topic": "t"}),
                ("url with port 0", {"url": "https://ntfy.example.org:0/a", "topic": "t"}),
                ("topic not a string", {"url": "https://ntfy.example.org", "topic": 7}),
                ("empty token", {"url": "https://ntfy.example.org", "topic": "t", "token": ""}),
                ("token not a string", {"url": "https://ntfy.example.org", "topic": "t", "token": 7}),
                ("null token", {"url": "https://ntfy.example.org", "topic": "t", "token": None}),
            )
        ),
        (
            "longer than 4096 characters",
            "VEIL1:"
            + _b64(
                {
                    "v": 1,
                    "server": "folder:",
                    "key_id": KEY_ID,
                    "secret": _b64u(SECRET),
                    "sign_key": _b64u(KEY_1.public_key),
                    "padding": "x" * 3200,
                }
            ),
        ),
        (
            "colon without a port",
            "VEIL1:"
            + _b64(
                {
                    "v": 1,
                    "server": "https://veille.example.org:",
                    "key_id": KEY_ID,
                    "secret": _b64u(SECRET),
                    "sign_key": _b64u(KEY_1.public_key),
                }
            ),
        ),
        (
            "duplicate member",
            "VEIL1:"
            + _b64u(
                (
                    f'{{"v":1,"server":"folder:","key_id":"{KEY_ID}","secret":"{_b64u(bytes(32))}",'
                    f'"secret":"{_b64u(SECRET)}","sign_key":"{_b64u(KEY_1.public_key)}"}}'
                ).encode()
            ),
        ),
    ):
        try:
            decode_pairing_code(code)
        except ProtocolError as exc:
            assert exc.code == "bad_pairing_code"
        else:
            raise AssertionError(f"{name}: not refused")
        cases_pairing.append({"name": name, "code": code, "error": "bad_pairing_code"})
    return {
        "description": "Inputs a reader must refuse, and the error code it must report (specification §10)",
        "packages": cases_packages,
        "requests": cases_requests,
        "pairing_codes": cases_pairing,
    }


def _b64(document: JSON) -> str:
    return _b64u(json.dumps(document, separators=(",", ":")).encode())


GENERATORS: dict[str, Callable[[], JSON]] = {
    "keys.json": keys,
    "pairing.json": pairing,
    "requests.json": requests,
    "subscriptions.json": subscriptions,
    "packages.json": packages,
    "refusals.json": refusals,
}


def render(document: JSON) -> str:
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args(argv)
    stale = []
    for name, generate in GENERATORS.items():
        text = render(generate())
        path = VECTORS / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        print(f"stale vectors: {', '.join(stale)}; run tools/protocol_vectors.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
