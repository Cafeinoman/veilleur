# SPDX-License-Identifier: EUPL-1.2
"""The protocol test vectors pass the independent implementation (tools/check_vectors.py), which notices damage."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "check_vectors.py"
VECTORS = ROOT / "protocol" / "vectors"


def _run(vectors: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CHECKER), str(vectors)], capture_output=True, text=True)


def test_vectors_pass_the_independent_implementation() -> None:
    result = _run(VECTORS)
    assert result.returncode == 0, result.stderr
    assert "vectors: OK" in result.stdout


def test_the_independent_implementation_does_not_import_the_library() -> None:
    source = CHECKER.read_text(encoding="utf-8")
    assert "veilleur_protocol" not in source.replace("without importing `veilleur_protocol`", "")
    assert "Cryptodome" not in source


def test_every_kind_of_refusal_is_covered() -> None:
    refusals = json.loads((VECTORS / "refusals.json").read_text(encoding="utf-8"))
    codes = {case["error"] for group in refusals.values() if isinstance(group, list) for case in group}
    assert codes >= {
        "too_large",
        "bad_envelope",
        "unsupported_version",
        "uid_mismatch",
        "seq_mismatch",
        "kind_mismatch",
        "decryption_failed",
        "bad_archive",
        "too_many_files",
        "unexpected_file",
        "missing_file",
        "file_too_large",
        "bad_signature",
        "bad_rotation",
        "bad_manifest",
        "hash_mismatch",
        "bad_items",
        "bad_authorization",
        "bad_date",
        "stale_date",
        "bad_pairing_code",
    }


def test_the_independent_implementation_notices_damaged_vectors(tmp_path: Path) -> None:
    damaged = tmp_path / "vectors"
    shutil.copytree(VECTORS, damaged)
    keys = json.loads((damaged / "keys.json").read_text(encoding="utf-8"))
    keys["cases"][0]["key"] = "00" * 32
    (damaged / "keys.json").write_text(json.dumps(keys), encoding="utf-8")
    packages = json.loads((damaged / "packages.json").read_text(encoding="utf-8"))
    envelope = bytearray.fromhex(packages["cases"][0]["envelope"])
    envelope[-1] ^= 1
    packages["cases"][0]["envelope"] = envelope.hex()
    (damaged / "packages.json").write_text(json.dumps(packages), encoding="utf-8")
    refusals = json.loads((damaged / "refusals.json").read_text(encoding="utf-8"))
    refusals["packages"][0]["error"] = "bad_items"
    (damaged / "refusals.json").write_text(json.dumps(refusals), encoding="utf-8")
    result = _run(damaged)
    assert result.returncode == 1
    assert "keys:" in result.stderr
    assert "refused (decryption_failed)" in result.stderr
    assert "instead of bad_items" in result.stderr
