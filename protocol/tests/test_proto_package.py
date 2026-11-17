# SPDX-License-Identifier: EUPL-1.2
"""Sealing and opening packages; every refusal of the reader."""

from __future__ import annotations

import hashlib
import io
import json
import random
import struct
import zipfile

import pytest

from conftest import NOW, OTHER_UID, SECRET, UID, content, item
from veilleur_protocol import (
    Change,
    Kind,
    Limits,
    ProtocolError,
    SigningKey,
    encode_items,
    make_rotation,
    open_package,
    open_subscription,
    parse_items,
    seal_package,
    seal_subscription,
)
from veilleur_protocol.envelope import Header, seal
from veilleur_protocol.package import build_archive, manifest_bytes


def _code(data: bytes, key: SigningKey, **options: object) -> str:
    with pytest.raises(ProtocolError) as error:
        open_package(data, secret=SECRET, uid=UID, trusted_keys=[key.public_key], **options)  # type: ignore[arg-type]
    return error.value.code


def _zip(entries: list[tuple[str, bytes]], compression: int = zipfile.ZIP_STORED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def _signed(key: SigningKey, contents: dict[str, bytes], **manifest_changes: object) -> list[tuple[str, bytes]]:
    document = json.loads(manifest_bytes(content(), contents))
    document.update(manifest_changes)
    manifest = json.dumps(document).encode()
    return [("manifest.json", manifest), ("manifest.sig", key.sign(manifest)), *contents.items()]


def _sealed(entries: list[tuple[str, bytes]], seq: int = 1, compression: int = zipfile.ZIP_STORED) -> bytes:
    return seal(SECRET, Header(UID, seq, Kind.DELTA), _zip(entries, compression))


ITEMS = encode_items([item("a"), item("b")])


def test_round_trip(key: SigningKey) -> None:
    sealed = seal_package(SECRET, key, content(seq=4))
    opened = open_package(sealed, secret=SECRET, uid=UID, trusted_keys=[key.public_key], seq=4)
    assert (opened.uid, opened.seq, opened.kind) == (UID, 4, Kind.DELTA)
    assert [i.key for i in opened.items] == ["a", "b"]
    assert opened.items[1].change is Change.GONE
    assert opened.renderings == {"report.md": b"# Report\n", "report.html": b"<p>Report</p>"}
    assert opened.signer == key.public_key and opened.rotation is None
    assert opened.manifest["protocol"] == "1.0"
    assert opened.manifest["sources"] == [{"id": "rss:example.org", "ok": True}]
    assert opened.manifest["period"] == {"from": None, "to": "2026-11-17T06:00:00Z"}


def test_folder_reading_takes_the_number_from_the_envelope(key: SigningKey) -> None:
    sealed = seal_package(SECRET, key, content(seq=9, kind=Kind.HISTORY))
    assert open_package(sealed, secret=SECRET, uid=UID, trusted_keys=[key.public_key]).seq == 9


def test_archives_carry_no_date_and_the_content_is_hidden(key: SigningKey) -> None:
    archive = zipfile.ZipFile(io.BytesIO(build_archive(content(), key)))
    assert {i.date_time for i in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    sealed = seal_package(SECRET, key, content(), compression=zipfile.ZIP_STORED)
    assert b"items.jsonl" not in sealed and b"Report" not in sealed


def test_rotation_lets_a_receiver_adopt_the_new_key(key: SigningKey) -> None:
    new = SigningKey(hashlib.sha256(b"new key").digest())
    rotation = make_rotation(key, new.public_key, NOW)
    sealed = seal_package(SECRET, new, content(rotation=rotation))
    opened = open_package(sealed, secret=SECRET, uid=UID, trusted_keys=[key.public_key])
    assert opened.signer == new.public_key
    assert opened.rotation is not None and opened.rotation.new_key == new.public_key
    already = open_package(sealed, secret=SECRET, uid=UID, trusted_keys=[new.public_key])
    assert already.rotation is None and already.signer == new.public_key
    assert "rotation.json" not in opened.renderings


def test_rotation_never_vouches_for_a_key_from_an_untrusted_one(key: SigningKey) -> None:
    stranger = SigningKey(hashlib.sha256(b"stranger").digest())
    new = SigningKey(hashlib.sha256(b"new key").digest())
    sealed = seal_package(SECRET, new, content(rotation=make_rotation(stranger, new.public_key, NOW)))
    assert _code(sealed, key) == "bad_signature"


def test_refused_envelopes(key: SigningKey) -> None:
    sealed = seal_package(SECRET, key, content(seq=2))
    assert _code(sealed, key, seq=3) == "seq_mismatch"
    assert _code(sealed, key, kinds={Kind.STATE}) == "kind_mismatch"
    assert _code(sealed[:69], key) == "bad_envelope"
    assert _code(sealed, key, limits=Limits(max_package=len(sealed) - 1)) == "too_large"
    other = seal_package(SECRET, key, content(uid=OTHER_UID))
    assert _code(other, key) == "uid_mismatch"
    altered = bytearray(sealed)
    altered[-1] ^= 0x80
    assert _code(bytes(altered), key) == "decryption_failed"
    with pytest.raises(ProtocolError) as error:
        open_package(sealed, secret=bytes(32), uid=UID, trusted_keys=[key.public_key])
    assert error.value.code == "decryption_failed"
    renumbered = sealed[:21] + struct.pack(">Q", 5) + sealed[29:]
    assert _code(renumbered, key) == "decryption_failed"


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        (("../items.jsonl", b""), "unexpected_file"),
        (("/etc/passwd", b""), "unexpected_file"),
        (("reports/report.md", b""), "unexpected_file"),
        (("report.MD", b""), "unexpected_file"),
        (("report.", b""), "unexpected_file"),
        (("notes.txt", b""), "unexpected_file"),
        (("items.jsonl", ITEMS), "bad_archive"),
    ],
)
def test_refused_file_names(key: SigningKey, extra: tuple[str, bytes], code: str) -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sealed = _sealed([*_signed(key, {"items.jsonl": ITEMS}), extra])
    assert _code(sealed, key) == code


def test_refused_archives(key: SigningKey) -> None:
    assert _code(seal(SECRET, Header(UID, 1, Kind.DELTA), b"PK\x05\x06" + bytes(18)), key) == "missing_file"
    assert _code(seal(SECRET, Header(UID, 1, Kind.DELTA), b"garbage"), key) == "bad_archive"
    many = {f"report.r{i}": b"" for i in range(30)}
    assert _code(_sealed(_signed(key, {"items.jsonl": ITEMS, **many})), key) == "too_many_files"
    assert _code(_sealed(_signed(key, {})), key) == "missing_file"
    assert _code(_sealed([("manifest.json", b"{}"), ("items.jsonl", ITEMS)]), key) == "missing_file"


def test_zip_bombs_are_refused_from_declared_sizes(key: SigningKey) -> None:
    bomb = {"items.jsonl": ITEMS, "report.txt": bytes(8 * 1024 * 1024)}
    sealed = _sealed(_signed(key, bomb), compression=zipfile.ZIP_DEFLATED)
    assert len(sealed) < 64 * 1024
    assert _code(sealed, key, limits=Limits(max_file=1024 * 1024)) == "file_too_large"
    assert _code(sealed, key, limits=Limits(max_total=4 * 1024 * 1024)) == "too_large"


def test_a_file_larger_than_declared_is_refused(key: SigningKey) -> None:
    """Shrinking the declared size must not let more data through, nor let a truncated file pass."""
    report = b"x" * 5000
    archive = bytearray(_zip(_signed(key, {"items.jsonl": ITEMS, "report.txt": report}), zipfile.ZIP_DEFLATED))
    for signature, offset in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        start = 0
        while (start := archive.find(signature, start)) != -1:
            name_length = struct.unpack_from("<H", archive, start + (26 if signature == b"PK\x03\x04" else 28))[0]
            name_at = start + (30 if signature == b"PK\x03\x04" else 46)
            if archive[name_at : name_at + name_length] == b"report.txt":
                struct.pack_into("<I", archive, start + offset, 100)
            start += 4
    sealed = seal(SECRET, Header(UID, 1, Kind.DELTA), bytes(archive))
    assert _code(sealed, key) == "bad_archive"


def test_refused_signatures_and_manifests(key: SigningKey) -> None:
    stranger = SigningKey(hashlib.sha256(b"stranger").digest())
    files = {"items.jsonl": ITEMS}
    assert _code(_sealed(_signed(stranger, files)), key) == "bad_signature"
    entries = _signed(key, files)
    entries[0] = ("manifest.json", entries[0][1] + b" ")
    assert _code(_sealed(entries), key) == "bad_signature"
    assert _code(_sealed(_signed(key, files, seq=2)), key) == "bad_manifest"
    assert _code(_sealed(_signed(key, files, kind="state")), key) == "bad_manifest"
    assert _code(_sealed(_signed(key, files, seq=True)), key) == "bad_manifest"
    assert _code(_sealed(_signed(key, files, protocol="2.0")), key) == "unsupported_version"
    assert _code(_sealed(_signed(key, files, protocol=1)), key) == "unsupported_version"
    assert _code(_sealed(_signed(key, files, created_at="yesterday")), key) == "bad_manifest"
    assert _code(_sealed(_signed(key, files, period=None)), key) == "bad_manifest"
    assert _code(_sealed(_signed(key, files, sources={})), key) == "bad_manifest"
    assert _code(_sealed(_signed(key, files, files={"items.jsonl": "x"})), key) == "bad_manifest"
    listed = {"items.jsonl": hashlib.sha256(ITEMS).hexdigest(), "report.md": "0" * 64}
    assert _code(_sealed(_signed(key, files, files=listed)), key) == "missing_file"
    unlisted = [*_signed(key, files), ("report.md", b"#")]
    assert _code(_sealed(unlisted), key) == "unexpected_file"
    tampered = [(n, ITEMS.replace(b'"a"', b'"c"') if n == "items.jsonl" else d) for n, d in _signed(key, files)]
    assert _code(_sealed(tampered), key) == "hash_mismatch"


def test_minor_protocol_versions_and_unknown_manifest_fields_are_accepted(key: SigningKey) -> None:
    sealed = _sealed(_signed(key, {"items.jsonl": ITEMS}, protocol="1.3", future_field={"x": 1}))
    assert open_package(sealed, secret=SECRET, uid=UID, trusted_keys=[key.public_key]).manifest["protocol"] == "1.3"


@pytest.mark.parametrize(
    "data",
    [
        b'{"key":"a"}',
        b"not json\n",
        b"[]\n",
        b'{"change":"new","fetched_at":"2026-11-17T06:00:00Z","fields":{},"hash":"' + b"0" * 64 + b'","key":"a"}\n',
        ITEMS.replace(b'"new"', b'"renamed"'),
        ITEMS.replace(b'"a"', b'"b"'),
        ITEMS.replace(b"2026-11-17T06:00:00Z", b"2026-11-17"),
    ],
)
def test_refused_items(data: bytes) -> None:
    with pytest.raises(ProtocolError) as error:
        parse_items(data)
    assert error.value.code == "bad_items"


def test_items_round_trip_and_order() -> None:
    items = [item("é"), item("z", Change.CHANGED, n=1), item("A")]
    parsed = parse_items(encode_items(items))
    assert [i.key for i in parsed] == ["A", "z", "é"]
    assert parsed[1].fields == {"n": 1}
    assert parse_items(b"") == []
    with pytest.raises(ValueError):
        encode_items([item("a"), item("a")])


def test_the_reader_only_ever_raises_protocol_errors(key: SigningKey) -> None:
    """Random damage to the plain archive (ES-13): every outcome is a clean refusal or a valid package."""
    archive = build_archive(content(), key)
    generator = random.Random(20261117)
    accepted = 0
    for _ in range(1500):
        damaged = bytearray(archive)
        for _ in range(generator.randint(1, 8)):
            choice = generator.random()
            position = generator.randrange(len(damaged))
            if choice < 0.6:
                damaged[position] = generator.randrange(256)
            elif choice < 0.8:
                del damaged[position : position + generator.randint(1, 64)]
            else:
                damaged[position:position] = generator.randbytes(generator.randint(1, 64))
        sealed = seal(SECRET, Header(UID, 1, Kind.DELTA), bytes(damaged))
        try:
            open_package(sealed, secret=SECRET, uid=UID, trusted_keys=[key.public_key])
            accepted += 1
        except ProtocolError:
            pass
    assert accepted < 1500


_JSON_NOISE = [
    b"null",
    b"true",
    b"[]",
    b"{}",
    b'""',
    b"-0",
    b"1e400",
    b"NaN",
    b'"\\ud800"',
    b"[[[[",
    b"9" * 5000,
    b'"x"',
]


def _mutate_json(text: bytes, generator: random.Random) -> bytes:
    """Replace a value, a character or a member name of a JSON text, keeping it mostly JSON."""
    choice = generator.random()
    if choice < 0.5:
        positions = [i for i, c in enumerate(text) if c in b":,["]
        at = generator.choice(positions) + 1
        end = at
        while end < len(text) and text[end] not in b",}]":
            end += 1
        return text[:at] + generator.choice(_JSON_NOISE) + text[end:]
    if choice < 0.8:
        at = generator.randrange(len(text))
        return text[:at] + bytes([generator.randrange(32, 127)]) + text[at + 1 :]
    return text.replace(b'"', b'"_', 1)


def test_signed_content_only_ever_raises_protocol_errors(key: SigningKey) -> None:
    """Random damage to a manifest and items that are correctly signed, so that steps 8 to 10 are reached (ES-13)."""
    generator = random.Random(20261118)
    refused: set[str] = set()
    for _ in range(800):
        items = ITEMS
        if generator.random() < 0.6:
            lines = items.splitlines(keepends=True)
            index = generator.randrange(len(lines))
            lines[index] = _mutate_json(lines[index][:-1], generator) + b"\n"
            items = b"".join(lines)
        manifest = manifest_bytes(content(), {"items.jsonl": items})
        if generator.random() < 0.6:
            manifest = _mutate_json(manifest, generator)
        entries = [("manifest.json", manifest), ("manifest.sig", key.sign(manifest)), ("items.jsonl", items)]
        try:
            open_package(_sealed(entries), secret=SECRET, uid=UID, trusted_keys=[key.public_key])
        except ProtocolError as error:
            refused.add(error.code)
    assert {"bad_manifest", "bad_items"} <= refused


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_writers_refuse_what_readers_refuse(key: SigningKey, value: float) -> None:
    with pytest.raises(ValueError):
        encode_items([item("a", price=value)])
    with pytest.raises(ValueError):
        seal_package(SECRET, key, content(sources=[{"id": "s", "latency": value}]))
    with pytest.raises(ValueError):
        seal_subscription(SECRET, UID, 0, {"threshold": value})


def test_writers_stay_within_the_default_limits(key: SigningKey) -> None:
    with pytest.raises(ValueError):
        seal_package(SECRET, key, content(renderings={f"report.r{i}": b"" for i in range(30)}))
    with pytest.raises(ValueError):
        seal_subscription(SECRET, UID, 0, {"x": "a" * 1_000_000})
    largest = {"x": "a" * (999_930 - len(b'{"x":""}'))}
    assert open_subscription(SECRET, UID, seal_subscription(SECRET, UID, 0, largest))[1] == largest


def _end_record(archive: bytes) -> int:
    return archive.rfind(b"PK\x05\x06")


def test_the_number_of_files_is_read_before_the_directory(key: SigningKey) -> None:
    archive = bytearray(_zip(_signed(key, {"items.jsonl": ITEMS})))
    end = _end_record(bytes(archive))
    struct.pack_into("<HH", archive, end + 8, 40, 40)
    assert _code(seal(SECRET, Header(UID, 1, Kind.DELTA), bytes(archive)), key) == "too_many_files"
    struct.pack_into("<HH", archive, end + 8, 2, 2)
    assert _code(seal(SECRET, Header(UID, 1, Kind.DELTA), bytes(archive)), key) == "bad_archive"


@pytest.mark.parametrize(
    ("offset", "fmt", "value"),
    [
        (8, "<H", 0x0008),  # general purpose flags: data descriptor
        (8, "<H", 0x0001),  # encrypted
        (10, "<H", 12),  # bzip2
        (16, "<I", 0),  # CRC differs from the local header
    ],
)
def test_entries_the_reader_does_not_support(key: SigningKey, offset: int, fmt: str, value: int) -> None:
    archive = bytearray(_zip(_signed(key, {"items.jsonl": ITEMS})))
    central = archive.find(b"PK\x01\x02")
    struct.pack_into(fmt, archive, central + offset, value)
    assert _code(seal(SECRET, Header(UID, 1, Kind.DELTA), bytes(archive)), key) == "bad_archive"


def test_zip64_markers_are_refused(key: SigningKey) -> None:
    archive = bytearray(_zip(_signed(key, {"items.jsonl": ITEMS})))
    central = archive.find(b"PK\x01\x02")
    struct.pack_into("<I", archive, central + 42, 0xFFFFFFFF)  # local header offset
    assert _code(seal(SECRET, Header(UID, 1, Kind.DELTA), bytes(archive)), key) == "bad_archive"


def test_an_archive_without_end_record_or_with_a_comment(key: SigningKey) -> None:
    archive = _zip(_signed(key, {"items.jsonl": ITEMS}))
    assert _code(seal(SECRET, Header(UID, 1, Kind.DELTA), archive[:-22]), key) == "bad_archive"
    commented = bytearray(archive)
    struct.pack_into("<H", commented, _end_record(archive) + 20, 4)
    sealed = seal(SECRET, Header(UID, 1, Kind.DELTA), bytes(commented) + b"PK\x05\x06")
    opened = open_package(sealed, secret=SECRET, uid=UID, trusted_keys=[key.public_key])
    assert [i.key for i in opened.items] == ["a", "b"]
