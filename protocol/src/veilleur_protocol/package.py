# SPDX-License-Identifier: EUPL-1.2
"""Report packages (specification §6, §7): a zip archive with a signed manifest, sealed in an envelope.

The reader (`open_package`) checks, in this order, before interpreting any data: envelope size and header,
decryption, archive structure (number, names, declared and actual sizes of files), manifest signature (through a key
rotation statement if needed), manifest, hash of every other file, and finally `items.jsonl`.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import zipfile
import zlib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import strict_json
from .encoding import b64u_decode, b64u_encode, format_time, parse_time
from .envelope import PACKAGE_KINDS, Header, Kind, open_envelope, seal
from .errors import (
    BAD_ARCHIVE,
    BAD_MANIFEST,
    BAD_ROTATION,
    BAD_SIGNATURE,
    FILE_TOO_LARGE,
    HASH_MISMATCH,
    MISSING_FILE,
    TOO_LARGE,
    TOO_MANY_FILES,
    UNEXPECTED_FILE,
    UNSUPPORTED_VERSION,
    ProtocolError,
)
from .items import Item, parse_items
from .signing import PUBLIC_KEY_BYTES, SIGNATURE_BYTES, SigningKey, verify

PROTOCOL_VERSION = "1.0"
MANIFEST = "manifest.json"
MANIFEST_SIG = "manifest.sig"
ITEMS = "items.jsonl"
ROTATION = "rotation.json"
ROTATION_SIG = "rotation.sig"
REQUIRED = (MANIFEST, MANIFEST_SIG, ITEMS)
_RENDERING = re.compile(r"report\.[a-z0-9]{1,16}")
_PROTOCOL = re.compile(r"1\.(0|[1-9][0-9]{0,5})")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_LOCAL_HEADER = struct.Struct("<4s22xHH")  # signature, then file name and extra field lengths at offsets 26 and 28
MAX_MANIFEST = 1024 * 1024
MAX_ROTATION = 4096
MiB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    """What a reader accepts. Lower values are allowed; higher values weaken the reader."""

    max_package: int = 64 * MiB
    max_files: int = 32
    max_file: int = 64 * MiB
    max_total: int = 128 * MiB


DEFAULT_LIMITS = Limits()


def is_allowed_name(name: str) -> bool:
    """File names a package may contain: no directory, nothing the package kinds do not provide for."""
    return name in (MANIFEST, MANIFEST_SIG, ITEMS, ROTATION, ROTATION_SIG) or _RENDERING.fullmatch(name) is not None


def _size_limit(name: str, limits: Limits) -> int:
    if name in (MANIFEST_SIG, ROTATION_SIG):
        return SIGNATURE_BYTES
    if name == MANIFEST:
        return min(MAX_MANIFEST, limits.max_file)
    if name == ROTATION:
        return MAX_ROTATION
    return limits.max_file


# --- Key rotation -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rotation:
    """Statement by which the outgoing server key vouches for the incoming one (specification §6.3)."""

    old_key: bytes
    new_key: bytes
    issued_at: datetime
    statement: bytes
    """Exact bytes of `rotation.json`, signed by `old_key`."""
    signature: bytes


def make_rotation(old: SigningKey, new_key: bytes, issued_at: datetime) -> Rotation:
    if len(new_key) != PUBLIC_KEY_BYTES:
        raise ValueError("an Ed25519 public key is 32 bytes")
    document = {
        "protocol": PROTOCOL_VERSION,
        "old_key": b64u_encode(old.public_key),
        "new_key": b64u_encode(new_key),
        "issued_at": format_time(issued_at),
    }
    statement = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    return Rotation(old.public_key, new_key, issued_at, statement, old.sign(statement))


def verify_rotation(statement: bytes, signature: bytes) -> Rotation:
    """Parse a rotation statement and check its signature by the key it names as outgoing."""
    try:
        document = strict_json.loads(statement)
        protocol = document.get("protocol") if isinstance(document, dict) else None
        if not isinstance(protocol, str) or not _PROTOCOL.fullmatch(protocol):
            raise ValueError("protocol is a string 1.<minor>")
        old_key = b64u_decode(document["old_key"])
        new_key = b64u_decode(document["new_key"])
        issued_at = parse_time(document["issued_at"])
    except (ValueError, KeyError, ProtocolError) as exc:  # strict_json.InvalidJson is a ValueError
        raise ProtocolError(BAD_ROTATION, "malformed rotation statement") from exc
    if len(old_key) != PUBLIC_KEY_BYTES or len(new_key) != PUBLIC_KEY_BYTES:
        raise ProtocolError(BAD_ROTATION, "keys are 32 bytes")
    if not verify(old_key, statement, signature):
        raise ProtocolError(BAD_ROTATION, "rotation statement not signed by the outgoing key")
    return Rotation(old_key, new_key, issued_at, statement, signature)


# --- Writing ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageContent:
    """What the server puts in a package."""

    uid: str
    seq: int
    kind: Kind
    created_at: datetime
    period_to: datetime
    period_from: datetime | None
    items: bytes
    """Content of `items.jsonl`, from `encode_items`."""
    renderings: Mapping[str, bytes] = field(default_factory=dict)
    sources: Sequence[Mapping[str, Any]] = ()
    rotation: Rotation | None = None


def manifest_bytes(content: PackageContent, files: Mapping[str, bytes]) -> bytes:
    document = {
        "protocol": PROTOCOL_VERSION,
        "uid": content.uid,
        "seq": content.seq,
        "kind": content.kind.value,
        "created_at": format_time(content.created_at),
        "period": {
            "from": None if content.period_from is None else format_time(content.period_from),
            "to": format_time(content.period_to),
        },
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "sources": [dict(source) for source in content.sources],
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def build_archive(
    content: PackageContent, signing_key: SigningKey, *, compression: int = zipfile.ZIP_DEFLATED
) -> bytes:
    """The plain archive (before sealing). `ZIP_STORED` makes it reproducible, for test vectors."""
    if content.kind not in PACKAGE_KINDS:
        raise ValueError("a package is a delta, a state or a history")
    files: dict[str, bytes] = {ITEMS: content.items}
    if content.rotation is not None:
        files[ROTATION] = content.rotation.statement
        files[ROTATION_SIG] = content.rotation.signature
    for name, data in sorted(content.renderings.items()):
        if not _RENDERING.fullmatch(name):
            raise ValueError(f"a rendering is named report.<extension>, not {name!r}")
        files[name] = data
    manifest = manifest_bytes(content, files)
    ordered = [(MANIFEST, manifest), (MANIFEST_SIG, signing_key.sign(manifest)), *files.items()]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in ordered:
            info = zipfile.ZipInfo(name, _ZIP_TIME)
            info.compress_type = compression
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def seal_package(
    secret: bytes,
    signing_key: SigningKey,
    content: PackageContent,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    nonce: bytes | None = None,
) -> bytes:
    """Build, sign and seal a package. `nonce` is for test vectors only."""
    archive = build_archive(content, signing_key, compression=compression)
    return seal(secret, Header(content.uid, content.seq, content.kind), archive, nonce=nonce)


# --- Reading ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenedPackage:
    """A package whose every check passed."""

    uid: str
    seq: int
    kind: Kind
    manifest: dict[str, Any]
    items: list[Item]
    renderings: dict[str, bytes]
    signer: bytes
    """Public key that signed the manifest."""
    rotation: Rotation | None
    """Set when the manifest was signed by a key the reader did not trust yet, vouched for by a trusted one: the
    receiving tool should then add `rotation.new_key` to its trusted keys."""


def _archive(plain: bytes, limits: Limits) -> dict[str, zipfile.ZipInfo]:
    """Entries of the archive's central directory, checked against §7.1 and the limits."""
    try:
        with zipfile.ZipFile(io.BytesIO(plain)) as archive:
            infos = archive.infolist()
    except Exception as exc:  # zipfile raises many kinds of errors on hostile input.
        raise ProtocolError(BAD_ARCHIVE, "not a readable zip archive") from exc
    if len(infos) > limits.max_files:
        raise ProtocolError(TOO_MANY_FILES, f"more than {limits.max_files} files")
    entries: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        name = info.filename
        if not is_allowed_name(name) or info.orig_filename != name:
            raise ProtocolError(UNEXPECTED_FILE, f"unexpected file {name!r}")
        if name in entries:
            raise ProtocolError(BAD_ARCHIVE, f"duplicate file {name!r}")
        if info.flag_bits & 0x1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ProtocolError(BAD_ARCHIVE, f"{name}: encrypted or unsupported compression")
        if info.file_size > _size_limit(name, limits):
            raise ProtocolError(FILE_TOO_LARGE, f"{name} too large")
        total += info.file_size
        entries[name] = info
    if total > limits.max_total:
        raise ProtocolError(TOO_LARGE, "archive content too large")
    for name in REQUIRED:
        if name not in entries:
            raise ProtocolError(MISSING_FILE, f"{name} missing")
    if (ROTATION in entries) != (ROTATION_SIG in entries):
        raise ProtocolError(MISSING_FILE, "rotation.json and rotation.sig go together")
    return entries


def _read(plain: bytes, info: zipfile.ZipInfo) -> bytes:
    """Decompress one file, never more than its declared size (already checked against the limits).

    Done here rather than by `zipfile`, which stops at the declared size without noticing that the data goes on: the
    whole compressed data must decompress to exactly the declared size and CRC.
    """
    name = info.filename
    start = info.header_offset
    if start < 0 or start + _LOCAL_HEADER.size > len(plain):
        raise ProtocolError(BAD_ARCHIVE, f"{name}: local header out of the archive")
    signature, name_length, extra_length = _LOCAL_HEADER.unpack_from(plain, start)
    begin = start + _LOCAL_HEADER.size
    if signature != b"PK\x03\x04" or plain[begin : begin + name_length] != name.encode("ascii"):
        raise ProtocolError(BAD_ARCHIVE, f"{name}: local header differs from the central directory")
    begin += name_length + extra_length
    end = begin + info.compress_size
    if end > len(plain):
        raise ProtocolError(BAD_ARCHIVE, f"{name}: data out of the archive")
    raw = plain[begin:end]
    if info.compress_type == zipfile.ZIP_STORED:
        data = raw
    else:
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            data = inflater.decompress(raw, info.file_size + 1)
        except zlib.error as exc:
            raise ProtocolError(BAD_ARCHIVE, f"{name}: corrupt data") from exc
        if not inflater.eof or inflater.unconsumed_tail or inflater.unused_data:
            raise ProtocolError(BAD_ARCHIVE, f"{name}: size differs from the declared one")
    if len(data) != info.file_size or zlib.crc32(data) != info.CRC:
        raise ProtocolError(BAD_ARCHIVE, f"{name}: size or CRC differs from the declared one")
    return data


def _signer(
    manifest: bytes, signature: bytes, trusted_keys: Collection[bytes], rotation: tuple[bytes, bytes] | None
) -> tuple[bytes, Rotation | None]:
    statement = None if rotation is None else verify_rotation(*rotation)
    for key in trusted_keys:
        if verify(key, manifest, signature):
            return key, None
    if statement is None:
        raise ProtocolError(BAD_SIGNATURE, "manifest not signed by a trusted key")
    if statement.old_key not in trusted_keys:
        raise ProtocolError(BAD_SIGNATURE, "rotation from a key the reader does not trust")
    if not verify(statement.new_key, manifest, signature):
        raise ProtocolError(BAD_SIGNATURE, "manifest not signed by the incoming key")
    return statement.new_key, statement


def _manifest(data: bytes, header: Header, names: Collection[str]) -> dict[str, Any]:
    try:
        manifest = strict_json.loads(data)
    except strict_json.InvalidJson as exc:
        raise ProtocolError(BAD_MANIFEST, "not UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ProtocolError(BAD_MANIFEST, "not an object")
    protocol = manifest.get("protocol")
    if not isinstance(protocol, str) or not _PROTOCOL.fullmatch(protocol):
        raise ProtocolError(UNSUPPORTED_VERSION, f"protocol {protocol!r}")
    seq = manifest.get("seq")
    if (
        manifest.get("uid") != header.uid
        or type(seq) is not int
        or seq != header.seq
        or manifest.get("kind") != header.kind.value
    ):
        raise ProtocolError(BAD_MANIFEST, "uid, seq or kind differ from the envelope")
    period = manifest.get("period")
    try:
        parse_time(manifest.get("created_at"))
        if not isinstance(period, dict):
            raise ValueError("period")
        parse_time(period.get("to"))
        if period.get("from") is not None:
            parse_time(period.get("from"))
    except (ProtocolError, ValueError) as exc:
        raise ProtocolError(BAD_MANIFEST, "created_at or period") from exc
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not all(isinstance(source, dict) for source in sources):
        raise ProtocolError(BAD_MANIFEST, "sources is a list of objects")
    files = manifest.get("files")
    if not isinstance(files, dict) or not all(isinstance(h, str) and _SHA256.fullmatch(h) for h in files.values()):
        raise ProtocolError(BAD_MANIFEST, "files maps names to SHA-256 digests")
    present = set(names) - {MANIFEST, MANIFEST_SIG}
    if missing := set(files) - present:
        raise ProtocolError(MISSING_FILE, f"listed but absent: {sorted(missing)}")
    if unlisted := present - set(files):
        raise ProtocolError(UNEXPECTED_FILE, f"present but not listed: {sorted(unlisted)}")
    return manifest


def open_package(
    data: bytes,
    *,
    secret: bytes,
    uid: str,
    trusted_keys: Collection[bytes],
    seq: int | None = None,
    kinds: Collection[Kind] = PACKAGE_KINDS,
    limits: Limits = DEFAULT_LIMITS,
) -> OpenedPackage:
    """Check and open a package of subscription `uid`.

    `seq` is the expected number (None when reading a folder: the number is then read from the envelope, and the
    caller must check it follows the previous one). `trusted_keys` are the server's public keys the receiving tool
    trusts: the one from the pairing code, then those adopted through rotation statements.
    """
    allowed = frozenset(kinds) & PACKAGE_KINDS
    header, plain = open_envelope(secret, data, uid=uid, kinds=allowed, seq=seq, max_size=limits.max_package)
    entries = _archive(plain, limits)
    manifest_data = _read(plain, entries[MANIFEST])
    signature = _read(plain, entries[MANIFEST_SIG])
    rotation = None
    if ROTATION in entries:
        rotation = (_read(plain, entries[ROTATION]), _read(plain, entries[ROTATION_SIG]))
    signer, adopted = _signer(manifest_data, signature, trusted_keys, rotation)
    manifest = _manifest(manifest_data, header, entries.keys())
    contents: dict[str, bytes] = {}
    for name, digest in manifest["files"].items():
        content = _read(plain, entries[name])
        if hashlib.sha256(content).hexdigest() != digest:
            raise ProtocolError(HASH_MISMATCH, f"{name} does not match the manifest")
        contents[name] = content
    items = parse_items(contents.pop(ITEMS))
    contents.pop(ROTATION, None)
    contents.pop(ROTATION_SIG, None)
    return OpenedPackage(header.uid, header.seq, header.kind, manifest, items, contents, signer, adopted)
