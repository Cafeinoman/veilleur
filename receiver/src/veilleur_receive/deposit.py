# SPDX-License-Identifier: EUPL-1.2
"""Filing a checked report: `<folder>/<uid>/<number>-<kind>/`, readable by the current user only.

A report appears whole or not at all: it is written aside, then renamed into place. Every name comes from checked
data (`uid` and number from the authenticated envelope, renderings restricted by the package reader), never from text
a source could choose.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from veilleur_protocol import OpenedPackage, encode_items

from . import errors
from .errors import ReceiveError


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ReceiveError(errors.UNSAFE_FOLDER)


def _write(directory: Path, name: str, data: bytes) -> None:
    descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(data)


def deposit(folder: Path, opened: OpenedPackage) -> Path:
    """File a report and return where it is. A report filed before a crash is replaced by the same one."""
    _private_directory(folder)
    base = folder / opened.uid
    _private_directory(base)
    base.chmod(0o700)
    final = base / f"{opened.seq:08d}-{opened.kind.value}"
    temporary = Path(tempfile.mkdtemp(prefix=".incoming-", dir=base))  # created 700
    try:
        _write(temporary, "items.jsonl", encode_items(opened.items))
        _write(temporary, "manifest.json", json.dumps(opened.manifest, indent=2, sort_keys=True).encode("ascii"))
        for name, data in opened.renderings.items():
            _write(temporary, name, data)
        if final.is_symlink():
            final.unlink()
        elif final.exists():
            shutil.rmtree(final)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final
