# SPDX-License-Identifier: EUPL-1.2
"""Report packages (specification §6, §7): a zip archive with a signed manifest, sealed in an envelope.

The reader (`open_package`) checks, in this order, before interpreting any data: envelope size and header,
decryption, archive structure (number, names, declared and actual sizes of files), manifest signature (through a key
rotation statement if needed), manifest, hash of every other file, and finally `items.jsonl`.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import strict_json
from .archive import Entry, read_directory, read_entry
from .encoding import b64u_decode, b64u_encode, format_time, parse_time
from .envelope import PACKAGE_KINDS, Header, Kind, open_envelope, seal
from .errors import (
    BAD_MANIFEST,
    BAD_ROTATION,
    BAD_SIGNATURE,
    HASH_MISMATCH,
    MISSING_FILE,
    TOO_LARGE,
    UNEXPECTED_FILE,
    UNSUPPORTED_VERSION,
    ProtocolError,
)
from .items import Item, parse_items
from .signing import SIGNATURE_BYTES, SigningKey, is_public_key, verify

PROTOCOL_VERSION = "1.0"
MANIFEST = "manifest.json"
MANIFEST_SIG = "manifest.sig"
ITEMS = "items.jsonl"
ROTATION = "rotation.json"
ROTATION_SIG = "rotation.sig"
REQUIRED = (MANIFEST, MANIFEST_SIG, ITEMS)
_RENDERING = re.compile(r"report\.[a-z0-9]{1,16}")
_PROTOCOL = re.compile(r"1\.(0|[1-9][0-9]*)")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
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
    """The fixed limit of a file (§10.1), lowered to `limits.max_file` if the reader chose a lower one."""
    fixed = {
        MANIFEST_SIG: SIGNATURE_BYTES,
        ROTATION_SIG: SIGNATURE_BYTES,
        MANIFEST: MAX_MANIFEST,
        ROTATION: MAX_ROTATION,
    }
    return min(fixed.get(name, limits.max_file), limits.max_file)


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
    if not is_public_key(new_key):
        raise ValueError("new_key is not a valid Ed25519 public key (§6.1)")
    document = {
        "protocol": PROTOCOL_VERSION,
        "old_key": b64u_encode(old.public_key),
        "new_key": b64u_encode(new_key),
        "issued_at": format_time(issued_at),
    }
    statement = strict_json.dumps(document)
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
    if not is_public_key(old_key) or not is_public_key(new_key):
        raise ProtocolError(BAD_ROTATION, "keys are valid Ed25519 public keys (§6.1)")
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
    return strict_json.dumps(document)


def _within_limits(files: Sequence[tuple[str, bytes]]) -> None:
    limits = DEFAULT_LIMITS
    if len(files) > limits.max_files:
        raise ValueError(f"a package holds at most {limits.max_files} files")
    for name, data in files:
        if len(data) > _size_limit(name, limits):
            raise ValueError(f"{name} is over its size limit")
    if sum(len(data) for _, data in files) > limits.max_total:
        raise ValueError(f"the files of a package add up to at most {limits.max_total} bytes")


def build_archive(
    content: PackageContent, signing_key: SigningKey, *, compression: int = zipfile.ZIP_DEFLATED
) -> bytes:
    """The plain archive (before sealing). `ZIP_STORED` makes it reproducible, for test vectors."""
    if content.kind not in PACKAGE_KINDS:
        raise ValueError("a package is a delta, a state or a history")
    if type(content.seq) is not int:
        raise ValueError("seq is an integer, not a boolean")
    try:
        parse_items(content.items)
    except ProtocolError as exc:
        raise ValueError(f"items.jsonl would be refused: {exc.detail}") from exc
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
    _within_limits(ordered)
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
    """Build, sign and seal a package. `nonce` is for test vectors only.

    Raises `ValueError` for a package a reader with the default limits would refuse (too many files, too large, NaN or
    infinity in the items or the sources): the server must split or fix it rather than deliver it.
    """
    archive = build_archive(content, signing_key, compression=compression)
    sealed = seal(secret, Header(content.uid, content.seq, content.kind), archive, nonce=nonce)
    if len(sealed) > DEFAULT_LIMITS.max_package:
        raise ValueError(f"a package is at most {DEFAULT_LIMITS.max_package} bytes")
    return sealed


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
    receiving tool must then trust `rotation.new_key` and stop trusting `rotation.old_key` (specification §6.3)."""


def _archive(plain: bytes, limits: Limits) -> dict[str, Entry]:
    """Entries of the archive's central directory, checked against §7.1 and the limits (§10.2 step 5)."""
    directory = read_directory(
        plain, max_files=limits.max_files, allowed=is_allowed_name, size_limit=lambda name: _size_limit(name, limits)
    )
    entries = {entry.name: entry for entry in directory}
    if sum(entry.size for entry in directory) > limits.max_total:
        raise ProtocolError(TOO_LARGE, "archive content too large")
    for name in REQUIRED:
        if name not in entries:
            raise ProtocolError(MISSING_FILE, f"{name} missing")
    if (ROTATION in entries) != (ROTATION_SIG in entries):
        raise ProtocolError(MISSING_FILE, "rotation.json and rotation.sig go together")
    return entries


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
        if "from" not in period:
            raise ValueError("period.from")
        if period["from"] is not None:
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
    manifest_data = read_entry(plain, entries[MANIFEST])
    signature = read_entry(plain, entries[MANIFEST_SIG])
    rotation = None
    if ROTATION in entries:
        rotation = (read_entry(plain, entries[ROTATION]), read_entry(plain, entries[ROTATION_SIG]))
    signer, adopted = _signer(manifest_data, signature, trusted_keys, rotation)
    manifest = _manifest(manifest_data, header, entries.keys())
    contents: dict[str, bytes] = {}
    for name, digest in manifest["files"].items():
        content = read_entry(plain, entries[name])
        if hashlib.sha256(content).hexdigest() != digest:
            raise ProtocolError(HASH_MISMATCH, f"{name} does not match the manifest")
        contents[name] = content
    items = parse_items(contents.pop(ITEMS))
    contents.pop(ROTATION, None)
    contents.pop(ROTATION_SIG, None)
    return OpenedPackage(header.uid, header.seq, header.kind, manifest, items, contents, signer, adopted)
