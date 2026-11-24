# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G1, fourth round.

Written from docs/en/protocol.md (normative) and the spec (ES-07, ES-13, §7.3). Targets: writers that still produce
what readers refuse, rules of §2, §3 and §8 read literally, and the agreement of the two implementations (§12) outside
the cases the vectors cover. No network, no disk.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import struct
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
    Ntfy,
    PairingCode,
    ProtocolError,
    SigningKey,
    b64u_encode,
    decode_pairing_code,
    encode_items,
    open_package,
    parse_items,
    request_scope,
)
from veilleur_protocol.envelope import Header, seal
from veilleur_protocol.package import PackageContent, manifest_bytes

ROOT = Path(__file__).resolve().parents[2]
SECRET = hashlib.sha256(b"verif4 secret").digest()
UID = "44556677889900aabbccddeeff112233"
KEY_ID = "1122334455667788"
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
KEY = SigningKey(hashlib.sha256(b"verif4 server key").digest())
HASH = "d" * 64


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verif4_check_vectors", ROOT / "tools" / "check_vectors.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _checker()


# --- Writers must only produce what readers accept (§7.4) -----------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"fields": ["not", "an", "object"]},
        {"fields": None},
        {"url": 42},
        {"url": {"href": "https://example.org/"}},
    ],
    ids=["fields-list", "fields-null", "url-int", "url-object"],
)
def test_items_writer_never_emits_an_item_its_reader_refuses(changes: dict[str, Any]) -> None:
    """§7.4: `fields` is an object, `url` a string or null. Fields come from collectors (third-party plug-ins, EF-01);
    `encode_items` checks `key` and `hash` but must also refuse what makes every receiving tool answer bad_items,
    rather than let the server seal a package nobody can read."""
    values: dict[str, Any] = {"key": "a", "change": Change.NEW, "hash": HASH, "fields": {}, "fetched_at": NOW}
    values["url"] = None
    values.update(changes)
    try:
        data = encode_items([Item(**values)])
    except ValueError:
        return
    try:
        parse_items(data)
    except ProtocolError as error:
        pytest.fail(f"encode_items produced {data!r}, which parse_items refuses ({error.code})")


# --- §3: pairing code -------------------------------------------------------------------------------------------------


def test_pairing_writer_never_emits_a_code_its_reader_refuses() -> None:
    """§3: a reader MUST refuse a code longer than 4096 characters. `PairingCode.encode` must not produce one (a long
    ntfy topic or token is enough), or the code shown once to the member is unusable."""
    code = PairingCode(
        server="https://veille.example.org",
        key_id=KEY_ID,
        secret=SECRET,
        sign_key=KEY.public_key,
        ntfy=Ntfy("https://ntfy.example.org", "t" * 3500, "k" * 100),
    )
    try:
        text = code.encode()
    except (ValueError, ProtocolError):
        return
    try:
        decode_pairing_code(text)
    except ProtocolError as error:
        pytest.fail(f"encode() produced a {len(text)}-character code that decode_pairing_code refuses ({error.code})")


def test_pairing_code_json_has_sorted_member_names() -> None:
    """§2: "Writers produce compact JSON (no insignificant white space) with sorted member names." The pairing code is
    written JSON like the others."""
    code = PairingCode(
        server="https://veille.example.org",
        key_id=KEY_ID,
        secret=SECRET,
        sign_key=KEY.public_key,
        ntfy=Ntfy("https://ntfy.example.org", "topic", "token"),
    ).encode()
    payload = code[len("VEIL1:") :]
    text = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    document = json.loads(text)
    assert text == json.dumps(document, sort_keys=True, separators=(",", ":")), text


def _pairing(**changes: Any) -> str:
    document: dict[str, Any] = {
        "v": 1,
        "server": "https://veille.example.org",
        "key_id": KEY_ID,
        "secret": b64u_encode(SECRET),
        "sign_key": b64u_encode(KEY.public_key),
    }
    document.update(changes)
    return "VEIL1:" + b64u_encode(json.dumps(document, separators=(",", ":")).encode())


def test_pairing_ntfy_token_null_is_not_a_string() -> None:
    """§3: `ntfy` is `{"url", "topic", "token": optional non-empty string}`. An optional member is absent or a
    non-empty string; `null` is neither (the library already refuses `"ntfy": null` for the same reason)."""
    code = _pairing(ntfy={"url": "https://ntfy.example.org", "topic": "t", "token": None})
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(code)
    assert error.value.code == "bad_pairing_code"


def _outcomes(code: str) -> tuple[str, str]:
    try:
        decode_pairing_code(code)
        library = "accepted"
    except ProtocolError as error:
        library = error.code
    try:
        CHECKER.decode_pairing(code)
        independent = "accepted"
    except CHECKER.Refused as refused:
        independent = refused.code
    return library, independent


@pytest.mark.parametrize(
    "code",
    [
        _pairing(ntfy={"url": "https://ntfy.example.org/#fragment", "topic": "t"}),
        _pairing(ntfy={"url": "https://ntfy.example.org:0/", "topic": "t"}),
        _pairing(ntfy={"url": "https://ntfy.example.org/", "topic": 7}),
        _pairing(ntfy={"url": "https://ntfy.example.org/", "topic": "t", "token": ""}),
        _pairing(ntfy={"url": "https://ntfy.example.org/", "topic": "t", "token": 5}),
        _pairing(padding="x" * 4000),
    ],
    ids=["ntfy-fragment", "ntfy-port-0", "ntfy-topic-int", "ntfy-token-empty", "ntfy-token-int", "over-4096"],
)
def test_both_implementations_agree_on_pairing_codes(code: str) -> None:
    """§12: the independent implementation is "written from this document". On these codes §3 is explicit (ntfy URL
    form, non-empty string members, 4096 characters), the library refuses them, and no refusal vector covers them."""
    library, independent = _outcomes(code)
    assert library == independent, f"library {library}, independent implementation {independent}"


# --- §8: scope of the authentication key -----------------------------------------------------------------------------


def test_request_scope_follows_the_letter_of_section_8() -> None:
    """§8: the scope is the subscription "when the path starts with /v1/subscriptions/<uid> followed by /, ? or its
    end"; otherwise the pairing. A `#` is none of the three."""
    assert request_scope(f"/v1/subscriptions/{UID}#x") is None


# --- §10.2 step 5, §12: an archive both implementations read the same way --------------------------------------------


def _package_with_gap_before_end_record(gap: bytes) -> bytes:
    items = encode_items([Item("a", Change.NEW, HASH, {"x": 1}, NOW, None)])
    content = PackageContent(UID, 1, Kind.DELTA, NOW, NOW, None, items)
    manifest = manifest_bytes(content, {"items.jsonl": items})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in [("manifest.json", manifest), ("manifest.sig", KEY.sign(manifest)), ("items.jsonl", items)]:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            archive.writestr(info, data)
    plain = buffer.getvalue()
    assert struct.unpack_from("<H", plain, len(plain) - 2)[0] == 0  # no comment: the end record is the last 22 bytes
    plain = plain[:-22] + gap + plain[-22:]
    return seal(SECRET, Header(UID, 1, Kind.DELTA), plain)


def test_both_implementations_agree_on_bytes_between_the_directory_and_the_end_record() -> None:
    """§10.2 step 5 refuses a central directory "out of the archive" but says nothing of bytes between the directory
    and the end record. The library reads offsets as absolute; Python's zipfile (used by the independent
    implementation) shifts them by the gap. Two readers of one signed archive must not disagree on what it is."""
    envelope = _package_with_gap_before_end_record(b"\x00" * 46)
    try:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key], seq=1)
        library = "accepted"
    except ProtocolError as error:
        library = error.code
    case = {
        "secret": SECRET.hex(),
        "envelope": envelope.hex(),
        "uid": UID,
        "seq": 1,
        "trusted_keys": [KEY.public_key.hex()],
    }
    try:
        CHECKER.open_package(case)
        independent = "accepted"
    except CHECKER.Refused as refused:
        independent = refused.code
    assert library == independent, f"library {library}, independent implementation {independent}"
