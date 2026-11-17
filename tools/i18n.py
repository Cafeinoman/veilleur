# SPDX-License-Identifier: EUPL-1.2
"""Translation workflow: `uv run python tools/i18n.py extract|update|compile|all`.

- extract: collect the source strings of `src/veilleur` into `locale/veilleur.pot`;
- update: merge the template into each language's `veilleur.po` (new strings appear untranslated);
- compile: build each `veilleur.mo` from its `veilleur.po` (the `.mo` files are committed);
- all: the three, in that order.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "veilleur"
LOCALE = PACKAGE / "locale"
TEMPLATE = LOCALE / "veilleur.pot"


def _pybabel(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "babel.messages.frontend", *args], check=True, cwd=ROOT)


def extract() -> None:
    _pybabel("extract", "--project=Veilleur", "--copyright-holder=Veilleur contributors",
             "--no-location", "--sort-output", "-o", str(TEMPLATE), str(PACKAGE))


def update() -> None:
    _pybabel("update", "--no-fuzzy-matching", "--ignore-pot-creation-date", "-D", "veilleur",
             "-i", str(TEMPLATE), "-d", str(LOCALE))


def compile_() -> None:
    _pybabel("compile", "--statistics", "-D", "veilleur", "-d", str(LOCALE))


def main(argv: list[str]) -> int:
    steps = {"extract": [extract], "update": [update], "compile": [compile_], "all": [extract, update, compile_]}
    if len(argv) != 1 or argv[0] not in steps:
        print(__doc__)
        return 2
    for step in steps[argv[0]]:
        step()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
