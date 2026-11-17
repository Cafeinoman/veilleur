# SPDX-License-Identifier: EUPL-1.2
"""Minimal zip reader for packages (specification §7.1, §10.2 steps 5, 6 and 9).

Written here rather than taken from `zipfile`, which parses the whole central directory before anything can be
counted, stops reading an entry at its declared size without noticing that the data goes on, and does not compare
local headers with the central directory. This reader:

- counts entries from the end of central directory record, before parsing any of them;
- refuses Zip64, multi-disk archives, data descriptors, encryption, and compression other than stored or deflate;
- requires every local header to agree with the central directory (flags, method, CRC, sizes, name);
- inflates the whole compressed data of an entry, never yielding more than its declared size, and requires exactly
  the declared size and CRC.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass

from .errors import BAD_ARCHIVE, FILE_TOO_LARGE, TOO_MANY_FILES, UNEXPECTED_FILE, ProtocolError

STORED = 0
DEFLATED = 8
_ENCRYPTED = 0x0001
_DATA_DESCRIPTOR = 0x0008
_UTF8 = 0x0800
_ALLOWED_FLAGS = 0x0006 | _UTF8  # deflate options and the UTF-8 name flag

_END = struct.Struct("<4sHHHHIIH")
_CENTRAL = struct.Struct("<4sHHHHHHIIIHHHHHII")
_LOCAL = struct.Struct("<4sHHHHHIIIHH")
_END_SIGNATURE = b"PK\x05\x06"
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_LOCAL_SIGNATURE = b"PK\x03\x04"
_MAX_COMMENT = 0xFFFF


@dataclass(frozen=True)
class Entry:
    name: str
    flags: int
    method: int
    crc: int
    compressed_size: int
    size: int
    offset: int


def _bad(detail: str) -> ProtocolError:
    return ProtocolError(BAD_ARCHIVE, detail)


def _end_record(data: bytes) -> tuple[int, int, int]:
    """Number of entries, size and offset of the central directory."""
    lowest = max(0, len(data) - _END.size - _MAX_COMMENT)
    position = len(data) - _END.size
    while position >= lowest:
        position = data.rfind(_END_SIGNATURE, lowest, position + 4)
        if position < 0:
            break
        fields = _END.unpack_from(data, position)
        if position + _END.size + fields[7] == len(data):
            _, disk, cd_disk, on_disk, total, cd_size, cd_offset, _ = fields
            if disk or cd_disk or on_disk != total:
                raise _bad("multi-disk archive")
            if cd_offset + cd_size > position:
                raise _bad("central directory out of the archive")
            return total, cd_size, cd_offset
        position -= 1
    raise _bad("no end of central directory record")


def read_directory(
    data: bytes, *, max_files: int, allowed: Callable[[str], bool], size_limit: Callable[[str], int]
) -> list[Entry]:
    """Entries of the central directory, checked one by one, in order (§10.2 step 5, before the total size)."""
    total, cd_size, position = _end_record(data)
    if total > max_files:
        raise ProtocolError(TOO_MANY_FILES, f"more than {max_files} files")
    end = position + cd_size
    entries: list[Entry] = []
    seen: set[str] = set()
    for _ in range(total):
        if position + _CENTRAL.size > end:
            raise _bad("truncated central directory")
        fields = _CENTRAL.unpack_from(data, position)
        signature, _, _, flags, method, _, _, crc, compressed, size, name_length, extra_length = fields[:12]
        comment_length, disk, _, _, offset = fields[12:]
        if signature != _CENTRAL_SIGNATURE:
            raise _bad("bad central directory entry")
        name_start = position + _CENTRAL.size
        position = name_start + name_length + extra_length + comment_length
        if position > end:
            raise _bad("truncated central directory")
        raw_name = data[name_start : name_start + name_length]
        name = raw_name.decode("ascii", errors="replace")
        if not raw_name.isascii() or not allowed(name):
            raise ProtocolError(UNEXPECTED_FILE, f"unexpected file {name!r}")
        if name in seen:
            raise _bad(f"duplicate file {name!r}")
        if flags & ~_ALLOWED_FLAGS or method not in (STORED, DEFLATED) or disk:
            raise _bad(f"{name}: encrypted, data descriptor, unsupported compression or Zip64")
        if 0xFFFFFFFF in (compressed, size, offset):
            raise _bad(f"{name}: Zip64 is not used by packages")
        if size > size_limit(name):
            raise ProtocolError(FILE_TOO_LARGE, f"{name} too large")
        seen.add(name)
        entries.append(Entry(name, flags, method, crc, compressed, size, offset))
    if position != end:
        raise _bad("central directory size differs from its entries")
    return entries


def read_entry(data: bytes, entry: Entry) -> bytes:
    """Content of one entry (§10.2 step 6)."""
    name = entry.name
    if entry.offset + _LOCAL.size > len(data):
        raise _bad(f"{name}: local header out of the archive")
    signature, _, flags, method, _, _, crc, compressed, size, name_length, extra_length = _LOCAL.unpack_from(
        data, entry.offset
    )
    begin = entry.offset + _LOCAL.size
    declared = (entry.flags, entry.method, entry.crc, entry.compressed_size, entry.size)
    if (
        signature != _LOCAL_SIGNATURE
        or (flags, method, crc, compressed, size) != declared
        or data[begin : begin + name_length] != name.encode("ascii")
    ):
        raise _bad(f"{name}: local header differs from the central directory")
    begin += name_length + extra_length
    end = begin + entry.compressed_size
    if end > len(data):
        raise _bad(f"{name}: data out of the archive")
    raw = data[begin:end]
    if entry.method == STORED:
        content = raw
    else:
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            content = inflater.decompress(raw, entry.size + 1)
        except zlib.error as exc:
            raise _bad(f"{name}: corrupt data") from exc
        if not inflater.eof or inflater.unconsumed_tail or inflater.unused_data:
            raise _bad(f"{name}: data goes on beyond the declared size")
    if len(content) != entry.size or zlib.crc32(content) != entry.crc:
        raise _bad(f"{name}: size or CRC differs from the declared one")
    return content
