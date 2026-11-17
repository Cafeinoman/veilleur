# SPDX-License-Identifier: EUPL-1.2
"""Repository rules: licence header in every source file, same documentation in both languages."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPDX = "# SPDX-License-Identifier: EUPL-1.2"


def test_every_python_file_has_the_licence_header() -> None:
    files = [p for d in ("src", "tests", "tools") for p in (ROOT / d).rglob("*.py")]
    assert files
    missing = [str(p.relative_to(ROOT)) for p in files if not p.read_text(encoding="utf-8").startswith(SPDX)]
    assert not missing, f"first line must be {SPDX!r}: {missing}"


def test_documentation_exists_in_both_languages() -> None:
    en = {p.relative_to(ROOT / "docs" / "en") for p in (ROOT / "docs" / "en").rglob("*.md")}
    fr = {p.relative_to(ROOT / "docs" / "fr") for p in (ROOT / "docs" / "fr").rglob("*.md")}
    assert en
    assert en == fr, f"only in English: {sorted(map(str, en - fr))}; only in French: {sorted(map(str, fr - en))}"
