# SPDX-License-Identifier: EUPL-1.2
"""Independent check: docs/{en,fr}/design.md have the same structure and carry ENF-03, ENF-03b and section 9."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EN = (ROOT / "docs/en/design.md").read_text(encoding="utf-8")
FR = (ROOT / "docs/fr/design.md").read_text(encoding="utf-8")
SPEC = (ROOT / "docs/SPEC.md").read_text(encoding="utf-8")


def _shape(text: str) -> tuple[list[str], int, int]:
    heads = [re.sub(r"^(#+)\s*([\d.]*).*", r"\1 \2", line) for line in text.splitlines() if line.startswith("#")]
    rows = sum(line.startswith("|") for line in text.splitlines())
    bullets = sum(bool(re.match(r"\s*(-|\d+\.) ", line)) for line in text.splitlines())
    return heads, rows, bullets


def _section(start: str, end: str) -> str:
    i = SPEC.index(start)
    return SPEC[i:SPEC.index(end, i)]


def test_same_structure_in_both_languages() -> None:
    assert _shape(EN) == _shape(FR)


def test_enf03_enf03b_and_section9_tokens_in_both_languages() -> None:
    spec = _section("**ENF-03 ", "- **ENF-04") + _section("## 9.", "## 10.")
    tokens = {t for t in re.findall(r"`([^`\n]+)`", spec) if not t.startswith("#")}
    missing_fr = sorted(t for t in tokens if t not in FR)
    missing_en = sorted(t for t in tokens
                        if t.replace("<étiquette>", "<tag>").replace("<sujet>", "<topic>") not in EN)
    assert not missing_fr and not missing_en, (missing_en, missing_fr)


def test_manifest_carries_status_of_collections() -> None:
    assert "status of the collections" in EN
    assert "état des collectes" in FR
