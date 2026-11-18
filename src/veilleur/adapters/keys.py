# SPDX-License-Identifier: EUPL-1.2
"""The server's signing key and its rotation (cahier ES-05, ES-10), kept in the state directory, never elsewhere."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from veilleur_protocol import Rotation, SigningKey, make_rotation, verify_rotation

KEY_FILE = "signing.key"
ROTATION_FILE = "rotation.json"
ROTATION_SIG_FILE = "rotation.sig"
ROTATION_WINDOW = timedelta(days=90)
"""A rotation statement travels in every package for 90 days (ES-05)."""


def write_private(path: Path, data: bytes) -> None:
    """Write a file only the service user can read, atomically."""
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def load_signing_key(state_dir: Path) -> SigningKey:
    """The server's key, drawn on first use."""
    path = state_dir / KEY_FILE
    if not path.exists():
        write_private(path, SigningKey.generate().seed)
    return SigningKey(path.read_bytes())


def current_rotation(state_dir: Path, signing_key: SigningKey, now: datetime) -> Rotation | None:
    """The statement vouching for the current key, while it is less than 90 days old."""
    statement, signature = state_dir / ROTATION_FILE, state_dir / ROTATION_SIG_FILE
    if not statement.exists() or not signature.exists():
        return None
    rotation = verify_rotation(statement.read_bytes(), signature.read_bytes())
    if rotation.new_key != signing_key.public_key or now - rotation.issued_at > ROTATION_WINDOW:
        return None
    return rotation


def rotate(state_dir: Path, now: datetime) -> Rotation:
    """Replace the server's key: the outgoing key signs the incoming one (protocol §6.3).

    The new key is written last, so that an interruption leaves the old key in force.
    """
    old = load_signing_key(state_dir)
    new = SigningKey.generate()
    rotation = make_rotation(old, new.public_key, now)
    write_private(state_dir / ROTATION_FILE, rotation.statement)
    write_private(state_dir / ROTATION_SIG_FILE, rotation.signature)
    write_private(state_dir / KEY_FILE, new.seed)
    return rotation
