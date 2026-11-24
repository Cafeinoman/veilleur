# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G1, second round: cases the first round did not cover.

Written from docs/en/protocol.md (normative) and the spec (ES-03, ES-04, ES-07, ES-13). No network, no disk.
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import time
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest

from veilleur_protocol import (
    Change,
    Item,
    Kind,
    ProtocolError,
    SigningKey,
    b64u_encode,
    decode_pairing_code,
    encode_items,
    open_package,
    parse_items,
)
from veilleur_protocol.envelope import Header, seal
from veilleur_protocol.package import PackageContent, manifest_bytes

SECRET = hashlib.sha256(b"verif2 secret").digest()
UID = "11223344556677889900aabbccddeeff"
KEY_ID = "0011223344556677"
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
KEY = SigningKey(hashlib.sha256(b"verif2 server key").digest())
OTHER = SigningKey(hashlib.sha256(b"verif2 other key").digest())
HASH = "a" * 64
# Order of the Ed25519 base point (RFC 8032 §5.1).
L = 2**252 + 27742317777372353535851937790883648493


def _items() -> bytes:
    return encode_items([Item("a", Change.NEW, HASH, {"x": 1}, NOW, None)])


def _content() -> PackageContent:
    return PackageContent(UID, 1, Kind.DELTA, NOW, NOW, None, _items())


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buffer.getvalue()


def _entries(files: dict[str, bytes], key: SigningKey = KEY, signature: bytes | None = None) -> list[tuple[str, bytes]]:
    manifest = manifest_bytes(_content(), files)
    return [("manifest.json", manifest), ("manifest.sig", signature or key.sign(manifest)), *files.items()]


def _seal(plain: bytes) -> bytes:
    return seal(SECRET, Header(UID, 1, Kind.DELTA), plain)


def _open(data: bytes, trusted: list[bytes] | None = None) -> Any:
    return open_package(data, secret=SECRET, uid=UID, trusted_keys=trusted or [KEY.public_key])


def _code(data: bytes, trusted: list[bytes] | None = None) -> str:
    """Code of the refusal. Any exception other than ProtocolError is a failure of the reader's contract."""
    try:
        _open(data, trusted)
    except ProtocolError as error:
        return error.code
    except Exception as exc:
        pytest.fail(f"the reader raised {type(exc).__name__}: {exc} (expected a ProtocolError)")
    pytest.fail("the reader accepted the package")


def _item_line(**members: Any) -> bytes:
    document: dict[str, Any] = {
        "key": "k",
        "change": "new",
        "hash": HASH,
        "fields": {},
        "fetched_at": "2026-11-17T06:00:00Z",
        "url": None,
    }
    document.update(members)
    return json.dumps(document, separators=(",", ":")).encode() + b"\n"


# --- §7.4 items.jsonl: malformed members must give bad_items, never another exception -----------------------------


@pytest.mark.parametrize("change", [[], {}, ["new"], {"new": 1}], ids=["list", "object", "list-new", "object-new"])
def test_items_change_of_the_wrong_json_type_is_bad_items(change: object) -> None:
    """§7.4: `change` is the string new|changed|gone; §10.2 step 10: otherwise bad_items."""
    try:
        parse_items(_item_line(change=change))
    except ProtocolError as error:
        assert error.code == "bad_items"
        return
    except Exception as exc:
        pytest.fail(f"parse_items raised {type(exc).__name__}: {exc}")
    pytest.fail("accepted")


def test_signed_package_with_an_array_as_change_is_bad_items() -> None:
    """§10.2 step 10 / ES-13: the reader only ever refuses with a ProtocolError, even on signed content."""
    sealed = _seal(_zip(_entries({"items.jsonl": _item_line(change=["new"])})))
    assert _code(sealed) == "bad_items"


# --- §10.2 step 6: local header must match the central directory --------------------------------------------------


def _patch_local_header(archive: bytes, name: str, offset: int, fmt: str, value: int) -> bytes:
    data = bytearray(archive)
    start = 0
    while (start := data.find(b"PK\x03\x04", start)) != -1:
        length = struct.unpack_from("<H", data, start + 26)[0]
        if data[start + 30 : start + 30 + length] == name.encode():
            struct.pack_into(fmt, data, start + offset, value)
            return bytes(data)
        start += 4
    raise AssertionError(name)


def test_untouched_archive_is_accepted() -> None:
    """Control for the next tests: the archive built here opens."""
    assert _open(_seal(_zip(_entries({"items.jsonl": _items()})))).items[0].key == "a"


@pytest.mark.parametrize(
    ("field", "offset", "fmt", "value"),
    [
        ("compression method", 8, "<H", 8),
        ("CRC-32", 14, "<I", 0xDEADBEEF),
        ("compressed size", 18, "<I", 1),
        ("uncompressed size", 22, "<I", 1),
        ("encryption flag", 6, "<H", 1),
    ],
)
def test_a_local_header_that_differs_from_the_central_directory_is_bad_archive(
    field: str, offset: int, fmt: str, value: int
) -> None:
    """§10.2 step 6: "a local header that does not match the central directory [...] are bad_archive".

    Only the local header of items.jsonl is changed; the central directory, the data and the manifest are intact.
    """
    archive = _patch_local_header(_zip(_entries({"items.jsonl": _items()})), "items.jsonl", offset, fmt, value)
    assert _code(_seal(archive)) == "bad_archive", field


# --- §6.3 rotation statements --------------------------------------------------------------------------------------


def _rotation(document: object, signer: SigningKey = KEY, raw: bytes | None = None) -> dict[str, bytes]:
    statement = raw if raw is not None else json.dumps(document, separators=(",", ":")).encode()
    return {"items.jsonl": _items(), "rotation.json": statement, "rotation.sig": signer.sign(statement)}


def _statement(**changes: object) -> dict[str, object]:
    document: dict[str, object] = {
        "protocol": "1.0",
        "old_key": b64u_encode(KEY.public_key),
        "new_key": b64u_encode(OTHER.public_key),
        "issued_at": "2026-11-17T06:00:00Z",
    }
    document.update(changes)
    return document


@pytest.mark.parametrize(
    ("name", "files"),
    [
        ("future major", lambda: _rotation(_statement(protocol="2.0"))),
        ("not an object", lambda: _rotation(["x"])),
        ("short key", lambda: _rotation(_statement(new_key=b64u_encode(bytes(31))))),
        ("padded key", lambda: _rotation(_statement(new_key=b64u_encode(OTHER.public_key) + "="))),
        ("bad date", lambda: _rotation(_statement(issued_at="2026-11-17"))),
        ("missing new_key", lambda: _rotation({k: v for k, v in _statement().items() if k != "new_key"})),
        (
            "duplicate member",
            lambda: _rotation(
                None,
                raw=json.dumps(_statement()).encode()[:-1]
                + b',"new_key":"'
                + b64u_encode(KEY.public_key).encode()
                + b'"}',
            ),
        ),
        ("signed by the incoming key", lambda: _rotation(_statement(), signer=OTHER)),
    ],
)
def test_malformed_rotation_statements_are_bad_rotation(name: str, files: Any) -> None:
    """§6.3, §10.2 step 7: a present rotation statement must be well-formed and signed by old_key."""
    assert _code(_seal(_zip(_entries(files(), key=OTHER)))) == "bad_rotation", name


def test_well_formed_rotation_is_adopted() -> None:
    """Control: the same statement, well-formed, lets the reader adopt OTHER."""
    opened = _open(_seal(_zip(_entries(_rotation(_statement()), key=OTHER))))
    assert opened.signer == OTHER.public_key and opened.rotation is not None


# --- ES-04 pure Ed25519 (RFC 8032): non-canonical signatures -------------------------------------------------------


def test_signature_with_s_plus_l_is_refused() -> None:
    """ES-04 / RFC 8032 §5.1.7: S must be lower than L; a malleated signature (S + L) is bad_signature."""
    files = {"items.jsonl": _items()}
    manifest = manifest_bytes(_content(), files)
    signature = KEY.sign(manifest)
    s = int.from_bytes(signature[32:], "little") + L
    assert s < 2**256
    malleated = signature[:32] + s.to_bytes(32, "little")
    assert _code(_seal(_zip(_entries(files, signature=malleated)))) == "bad_signature"


# --- §3 pairing code -----------------------------------------------------------------------------------------------


def _pairing(**changes: object) -> str:
    document: dict[str, object] = {
        "v": 1,
        "server": "https://veille.example.org",
        "key_id": KEY_ID,
        "secret": b64u_encode(SECRET),
        "sign_key": b64u_encode(KEY.public_key),
    }
    document.update(changes)
    return "VEIL1:" + b64u_encode(json.dumps(document, separators=(",", ":")).encode())


def test_pairing_control_is_accepted() -> None:
    assert decode_pairing_code(_pairing()).server == "https://veille.example.org"
    assert decode_pairing_code(_pairing(server="https://veille.example.org:8443/")).key_id == KEY_ID


@pytest.mark.parametrize(
    "server",
    ["https://veille.example.org:", "https:veille.example.org", "https:///veille.example.org", "folder:x", "folder"],
)
def test_pairing_server_not_of_the_form_https_host_port(server: str) -> None:
    """§3: server is `https://host[:port]` or exactly `folder:`."""
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(_pairing(server=server))
    assert error.value.code == "bad_pairing_code"


def test_pairing_ntfy_null_is_not_an_object() -> None:
    """§3: `ntfy` is an optional *object*; a code that does not satisfy the table is refused."""
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(_pairing(ntfy=None))
    assert error.value.code == "bad_pairing_code"


def test_pairing_errors_never_carry_the_secret() -> None:
    """ES-09 / §3: the code holds the secret; an error message about it must not repeat it."""
    secret_text = b64u_encode(SECRET)
    token = "tk_verif2_token"
    for changes in (
        {"server": "http://x.example.org"},
        {"key_id": "XYZ"},
        {"sign_key": secret_text + "A"},
        {"ntfy": {"url": "http://n.example.org", "topic": "t", "token": token}},
        {"ntfy": {"url": "https://n.example.org", "topic": "", "token": token}},
    ):
        with pytest.raises(ProtocolError) as error:
            decode_pairing_code(_pairing(**changes))
        chain: list[BaseException] = []
        current: BaseException | None = error.value
        while current is not None:
            chain.append(current)
            current = current.__cause__ or current.__context__
        for exc in chain:
            assert secret_text not in str(exc) and token not in str(exc), changes


# --- ES-07 / §10.2 step 5: a huge central directory -----------------------------------------------------------------


def _central_directory_only(count: int) -> bytes:
    """An archive of `count` entries named `x`, with no local data: only the central directory and its end."""
    entry = struct.pack("<4s6H3I5H2I", b"PK\x01\x02", 20, 20, 0, 0, 0, 0x21, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0) + b"x"
    directory = entry * count
    end = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, count & 0xFFFF, count & 0xFFFF, len(directory), 0, 0)
    if count > 0xFFFF:
        zip64_end = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, len(directory), 0)
        locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, len(directory), 1)
        end = (
            zip64_end
            + locator
            + struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
        )
    return directory + end


def test_too_many_files_is_found_without_parsing_a_huge_directory() -> None:
    """§10.2 step 5 ("from its central directory, entry by entry") and ES-07: the count limit (32) must be enforced
    cheaply. A 64 MiB envelope can hold about 1.4 million directory entries; the reader must not build them all."""
    count = 1_000_000
    sealed = _seal(_central_directory_only(count))
    assert len(sealed) < 64 * 1024 * 1024
    started = time.perf_counter()
    code = _code(sealed)
    elapsed = time.perf_counter() - started
    assert code in ("too_many_files", "bad_archive")
    assert elapsed < 1.0, f"{elapsed:.1f} s to refuse {count} directory entries"


# --- Both implementations must agree (§12): the independent checker on the same input -----------------------------


def test_independent_checker_and_library_agree_on_an_array_as_change() -> None:
    """§12: the vectors are checked by two implementations; on the same items.jsonl they must give the same code."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "tools" / "check_vectors.py"
    spec = importlib.util.spec_from_file_location("verif_check_vectors", path)
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    line = _item_line(change=["new"])
    with pytest.raises(checker.Refused) as independent:
        checker.check_items(line)
    assert independent.value.code == "bad_items"
    try:
        parse_items(line)
    except ProtocolError as error:
        assert error.code == independent.value.code
        return
    except Exception as exc:
        pytest.fail(f"library raised {type(exc).__name__} where the independent checker says bad_items")


# --- ES-13: random data that reaches the signed parsers (steps 8 to 10) --------------------------------------------


def _random_json(generator: Any, depth: int = 0) -> object:
    choice = generator.randrange(9 if depth < 2 else 6)
    if choice == 0:
        return None
    if choice == 1:
        return generator.random() < 0.5
    if choice == 2:
        return generator.randrange(-(2**70), 2**70)
    if choice == 3:
        return generator.random() * 10 ** generator.randrange(-5, 5)
    if choice == 4:
        return generator.choice(["", "new", "gone", "1.0", "delta", UID, "2026-11-17T06:00:00Z", HASH, "x" * 70])
    if choice == 5:
        return "".join(chr(generator.randrange(32, 0x2FF)) for _ in range(generator.randrange(0, 8)))
    if choice in (6, 7):
        return [_random_json(generator, depth + 1) for _ in range(generator.randrange(0, 3))]
    return {str(i): _random_json(generator, depth + 1) for i in range(generator.randrange(0, 3))}


def test_signed_random_manifests_and_items_only_raise_protocol_errors() -> None:
    """ES-13 / §10.2 steps 8 to 10: properly signed manifests and items with random member values give a ProtocolError
    or a valid package, never another exception."""
    import random

    generator = random.Random(20261117)
    good_items = _items()
    item_members = ("key", "change", "hash", "fields", "fetched_at", "url")
    manifest_members = ("protocol", "uid", "seq", "kind", "created_at", "period", "files", "sources")
    crashes: list[str] = []
    for _ in range(600):
        line = json.loads(good_items)
        line[generator.choice(item_members)] = _random_json(generator)
        items = json.dumps(line).encode() + b"\n"
        files = {"items.jsonl": items}
        manifest_document = json.loads(manifest_bytes(_content(), files))
        if generator.random() < 0.5:
            manifest_document[generator.choice(manifest_members)] = _random_json(generator)
        manifest = json.dumps(manifest_document).encode()
        entries = [("manifest.json", manifest), ("manifest.sig", KEY.sign(manifest)), *files.items()]
        try:
            _open(_seal(_zip(entries)))
        except ProtocolError:
            pass
        except Exception as exc:
            crashes.append(f"{type(exc).__name__}: {exc}")
    assert not crashes, sorted(set(crashes))
