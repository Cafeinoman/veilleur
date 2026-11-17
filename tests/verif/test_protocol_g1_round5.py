# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G1, fifth round.

Written from docs/en/protocol.md (normative) and the cahier (ES-07, ES-13, §7.3). Targets: archives that §7.1 and
§10.2 step 5 forbid but that the vectors do not cover, checked against both implementations (§12: the independent one
is "written from this document" and must refuse what must be refused, with the same code); hosts of §3; writers that
produce what readers refuse. No network, no disk.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import zipfile
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from veilleur_protocol import (
    Change,
    Item,
    Kind,
    PairingCode,
    ProtocolError,
    SigningKey,
    b64u_encode,
    decode_pairing_code,
    encode_items,
    open_package,
    seal_package,
)
from veilleur_protocol.envelope import Header, seal
from veilleur_protocol.package import PackageContent, manifest_bytes

ROOT = Path(__file__).resolve().parents[2]
SECRET = hashlib.sha256(b"verif5 secret").digest()
UID = "5566778899aabbccddeeff0011223344"
KEY_ID = "8877665544332211"
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
KEY = SigningKey(hashlib.sha256(b"verif5 server key").digest())
HASH = "e" * 64


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verif5_check_vectors", ROOT / "tools" / "check_vectors.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _checker()


# --- A hand-made zip writer, so that central and local headers can be set independently ----------------------------


def _zip(
    entries: list[tuple[str | bytes, bytes]],
    *,
    flags: dict[str, int] | None = None,
    local_names: dict[str, bytes] | None = None,
    announced: int | None = None,
) -> bytes:
    """Stored entries. `flags` sets the general purpose flags (local and central alike), `local_names` the name in a
    local header, `announced` the number of entries in the end record (both disk counters)."""
    flags = flags or {}
    local_names = local_names or {}
    local = b""
    central = b""
    for name, data in entries:
        raw_name = name.encode("ascii") if isinstance(name, str) else name
        key = raw_name.decode("ascii")
        flag = flags.get(key, 0)
        crc = zlib.crc32(data)
        local_name = local_names.get(key, raw_name)
        offset = len(local)
        local += struct.pack(
            "<4sHHHHHIIIHH", b"PK\x03\x04", 20, flag, 0, 0, 0x21, crc, len(data), len(data), len(local_name), 0
        )
        local += local_name + data
        central += struct.pack(
            "<4sHHHHHHIIIHHHHHII",
            b"PK\x01\x02",
            20,
            20,
            flag,
            0,
            0,
            0x21,
            crc,
            len(data),
            len(data),
            len(raw_name),
            0,
            0,
            0,
            0,
            0,
            offset,
        )
        central += raw_name
    count = len(entries) if announced is None else announced
    end = struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, count, count, len(central), len(local), 0)
    return local + central + end


def _items() -> bytes:
    return encode_items([Item("a", Change.NEW, HASH, {"x": 1}, NOW, None)])


def _content(items: bytes | None = None) -> PackageContent:
    return PackageContent(UID, 1, Kind.DELTA, NOW, NOW, None, _items() if items is None else items)


def _signed(files: dict[str, bytes]) -> list[tuple[str | bytes, bytes]]:
    """manifest.json, manifest.sig, then `files`, all listed in a manifest signed by KEY."""
    manifest = manifest_bytes(_content(files.get("items.jsonl")), files)
    return [("manifest.json", manifest), ("manifest.sig", KEY.sign(manifest)), *files.items()]


def _envelope(plain: bytes) -> bytes:
    return seal(SECRET, Header(UID, 1, Kind.DELTA), plain)


def _library(envelope: bytes) -> str | None:
    """Code of the reference reader's refusal, or None if it accepts."""
    try:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key], seq=1)
    except ProtocolError as error:
        return error.code
    return None


def _independent(envelope: bytes) -> str | None:
    """Code of the independent implementation's refusal (tools/check_vectors.py), or None if it accepts."""
    case: dict[str, Any] = {
        "secret": SECRET.hex(),
        "envelope": envelope.hex(),
        "uid": UID,
        "seq": 1,
        "trusted_keys": [KEY.public_key.hex()],
    }
    try:
        CHECKER.open_package(case)
    except CHECKER.Refused as refusal:
        code: str = refusal.code
        return code
    return None


def test_the_hand_made_writer_gives_an_archive_both_implementations_accept() -> None:
    """Control: without any of the defects below, both readers accept the archive."""
    envelope = _envelope(_zip(_signed({"items.jsonl": _items(), "report.md": b"# r\n"})))
    assert _library(envelope) is None
    assert _independent(envelope) is None


# --- §7.1 and §10.2 step 5: archives both implementations must refuse ------------------------------------------------


def _with_flag(flag: int) -> bytes:
    files = {"items.jsonl": _items()}
    return _envelope(_zip(_signed(files), flags={"items.jsonl": flag}))


def _announcing(count: int) -> bytes:
    files = {"items.jsonl": _items(), "report.md": b"# r\n"}
    return _envelope(_zip(_signed(files), announced=count))


def _nul_in_central_name() -> bytes:
    # The central directory says "report.a\0", the local header "report.a"; the manifest lists "report.a".
    manifest_files = {"items.jsonl": _items(), "report.a": b"# r\n"}
    entries = _signed(manifest_files)
    entries[-1] = (b"report.a\x00", b"# r\n")
    return _envelope(_zip(entries, local_names={"report.a\x00": b"report.a"}))


CASES: dict[str, tuple[Callable[[], bytes], str]] = {
    # §7.1: "without data descriptors (general purpose flags limited to bits 1, 2 and 11)".
    "data descriptor flag (bit 3)": (lambda: _with_flag(0x0008), "bad_archive"),
    "strong encryption flag (bit 6)": (lambda: _with_flag(0x0040), "bad_archive"),
    "reserved flag (bit 13)": (lambda: _with_flag(0x2000), "bad_archive"),
    # §10.2 step 5: "entries that do not fill the central directory exactly: bad_archive".
    "end record announces fewer entries than the directory holds": (lambda: _announcing(3), "bad_archive"),
    "end record announces more entries than the directory holds": (lambda: _announcing(5), "bad_archive"),
    # §10.2 step 5: "the record announces more entries than the limit: too_many_files, before parsing the directory".
    "end record announces 33 entries, the directory holds 4": (lambda: _announcing(33), "too_many_files"),
    # §10.2 step 5: "a name not allowed by §7.1: unexpected_file"; §7.1: local header carries the same name.
    "NUL in a central directory name": (_nul_in_central_name, "unexpected_file"),
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_reference_reader_refuses_forbidden_archives(name: str) -> None:
    build, code = CASES[name]
    assert _library(build()) == code


@pytest.mark.parametrize("name", list(CASES))
def test_the_independent_implementation_refuses_forbidden_archives_with_the_same_code(name: str) -> None:
    """§12: the vectors are "checked by an independent one written from this document"; plan G1: a second,
    independent implementation of the checks. It must refuse what §7.1 and §10.2 refuse, with the same code, or the
    cross-check proves nothing for these rules."""
    build, code = CASES[name]
    envelope = build()
    assert _library(envelope) == code
    got = _independent(envelope)
    assert got == code, f"tools/check_vectors.py: {got or 'accepted'} instead of {code}"


# --- §3: hosts ------------------------------------------------------------------------------------------------------


def _pairing_text(server: str) -> str:
    document = {
        "v": 1,
        "server": server,
        "key_id": KEY_ID,
        "secret": b64u_encode(SECRET),
        "sign_key": b64u_encode(KEY.public_key),
    }
    return "VEIL1:" + b64u_encode(json.dumps(document, separators=(",", ":"), sort_keys=True).encode())


@pytest.mark.parametrize("server", ["https://[fe80::1%eth0]", "https://[fe80::1%25eth0]:8443"])
def test_both_implementations_refuse_an_ipv6_zone_identifier(server: str) -> None:
    """§3: `host` is "an IPv6 address in brackets"; `server` an origin `https://host[:port]`. A zone identifier names
    an interface of the receiving machine, not an address of the server; the reference refuses it, and §12 requires
    the independent implementation to agree."""
    text = _pairing_text(server)
    with pytest.raises(ProtocolError) as caught:
        decode_pairing_code(text)
    assert caught.value.code == "bad_pairing_code"
    try:
        CHECKER.decode_pairing(text)
    except CHECKER.Refused as refusal:
        assert refusal.code == "bad_pairing_code"
        return
    pytest.fail(f"tools/check_vectors.py accepts the server {server!r}, the reference refuses it")


def test_the_reference_accepts_a_plain_bracketed_ipv6_origin() -> None:
    """Control for the test above: an IPv6 address in brackets is a valid host (§3)."""
    code = decode_pairing_code(_pairing_text("https://[2001:db8::1]:8443"))
    assert code.server == "https://[2001:db8::1]:8443"
    assert isinstance(code, PairingCode)


# --- Writers must not produce what readers refuse ---------------------------------------------------------------------


def test_package_writer_with_a_boolean_seq_does_not_emit_a_package_its_reader_refuses() -> None:
    """§10.2 step 8: `seq` is "an integer, not a boolean", or bad_manifest. `seq=True` passes the writer's range check
    (`True` is an int for Python and for mypy) and is packed as 1 in the header, while the manifest says `true`: the
    server would deliver a package every reader refuses. The writer must raise instead."""
    content = PackageContent(UID, True, Kind.DELTA, NOW, NOW, None, _items())
    try:
        envelope = seal_package(SECRET, KEY, content)
    except (ValueError, TypeError):
        return
    try:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key], seq=1)
    except ProtocolError as error:
        pytest.fail(f"seal_package(seq=True) produced a package the reader refuses ({error.code})")


def test_package_writer_refuses_items_with_nan_as_its_docstring_says() -> None:
    """`seal_package` documents: "Raises ValueError for a package a reader with the default limits would refuse (...,
    NaN or infinity in the items ...)". Its `items` argument is bytes; NaN there makes every reader answer bad_items
    (§2, §10.2 step 10)."""
    line = (
        b'{"change":"new","fetched_at":"2026-11-17T06:00:00Z","fields":{"x":NaN},"hash":"' + HASH.encode() + b'",'
        b'"key":"a","url":null}\n'
    )
    content = _content(line)
    try:
        envelope = seal_package(SECRET, KEY, content)
    except ValueError:
        return
    code = _library_seq(envelope)
    pytest.fail(f"seal_package sealed items with NaN; the reader refuses the package ({code})")


def _library_seq(envelope: bytes) -> str | None:
    try:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key], seq=1)
    except ProtocolError as error:
        return error.code
    return None


# --- §7.4: an empty items.jsonl means no item, whatever the compression ---------------------------------------------


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_an_empty_items_file_opens_with_either_compression(compression: int) -> None:
    content = _content(b"")
    envelope = seal_package(SECRET, KEY, content, compression=compression)
    opened = open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key], seq=1)
    assert opened.items == []
    assert _independent(envelope) is None
