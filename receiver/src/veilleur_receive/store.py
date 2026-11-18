# SPDX-License-Identifier: EUPL-1.2
"""The receiver's state: the pairing, the server keys it trusts, the last number received per subscription.

It holds the pairing secret: the folder is private to the user (700), the file too (600), and a file others can read
is refused rather than used. Each save replaces the file atomically, so a crash never leaves half a state.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veilleur_protocol import PairingCode, ProtocolError, b64u_decode, b64u_encode

from . import errors
from .errors import ReceiveError

STATE_FILE = "receiver.json"
LOCK_FILE = "lock"
_VERSION = 1


@dataclass
class State:
    server: str
    key_id: str
    secret: bytes = field(repr=False)
    trusted_keys: list[bytes]
    rotated: bool = False
    """A key was adopted: packages signed by the outgoing key are no longer accepted (protocol §6.3)."""
    last: dict[str, int] = field(default_factory=dict)


def default_directory() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local" / "state") / "veilleur-receive"


def prepare_directory(directory: Path) -> None:
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise ReceiveError(errors.STATE_UNSAFE)
    directory.chmod(0o700)


@contextmanager
def locked(directory: Path) -> Iterator[None]:
    """One command at a time on a state: two pulls would file the same reports and overwrite each other's numbers."""
    descriptor = os.open(directory / LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ReceiveError(errors.BUSY) from exc
        yield
    finally:
        os.close(descriptor)


def from_code(code: PairingCode) -> State:
    return State(code.server, code.key_id, code.secret, [code.sign_key])


def exists(directory: Path) -> bool:
    return os.path.lexists(directory / STATE_FILE)


def _parse(document: Any) -> State:
    if not isinstance(document, dict) or document.get("version") != _VERSION:
        raise ValueError("version")
    last = document["last"]
    if not isinstance(last, dict) or not all(type(seq) is int and seq >= 0 for seq in last.values()):
        raise ValueError("last")
    keys = document["trusted_keys"]
    if not isinstance(keys, list) or not keys or type(document["rotated"]) is not bool:
        raise ValueError("trusted_keys")
    # The pairing code's own checks apply to what was stored.
    code = PairingCode(document["server"], document["key_id"], b64u_decode(document["secret"]), b64u_decode(keys[0]))
    return State(code.server, code.key_id, code.secret, [b64u_decode(k) for k in keys], document["rotated"], dict(last))


def load(directory: Path) -> State:
    path = directory / STATE_FILE
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        raise ReceiveError(errors.NOT_PAIRED) from exc
    except OSError as exc:
        raise ReceiveError(errors.STATE_UNREADABLE) from exc
    with os.fdopen(descriptor, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ReceiveError(errors.STATE_UNSAFE)
        try:
            return _parse(json.loads(file.read()))
        except (ValueError, KeyError, TypeError, ProtocolError) as exc:
            raise ReceiveError(errors.STATE_UNREADABLE) from exc


def save(directory: Path, state: State) -> None:
    document = {
        "version": _VERSION,
        "server": state.server,
        "key_id": state.key_id,
        "secret": b64u_encode(state.secret),
        "trusted_keys": [b64u_encode(key) for key in state.trusted_keys],
        "rotated": state.rotated,
        "last": state.last,
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".receiver-", dir=directory)  # created 600
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(document, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, directory / STATE_FILE)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
