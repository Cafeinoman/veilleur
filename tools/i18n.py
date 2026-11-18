# SPDX-License-Identifier: EUPL-1.2
"""Translation workflow: `uv run python tools/i18n.py extract|update|compile|all`.

- extract: collect the source strings of each package into its `locale/<domain>.pot`;
- update: merge the template into each language's `<domain>.po` (new strings appear untranslated);
- compile: build each `<domain>.mo` from its `<domain>.po` (the `.mo` files are committed);
- all: the three, in that order.

The server (`src/veilleur`) and the reference receiver (`receiver/src/veilleur_receive`) each have their own
catalogue: the receiver does not depend on the server.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOGUES = (
    (ROOT / "src" / "veilleur", "veilleur"),
    (ROOT / "receiver" / "src" / "veilleur_receive", "veilleur_receive"),
)
LANGUAGES = ("fr",)


def _pybabel(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "babel.messages.frontend", *args], check=True, cwd=ROOT)


def extract() -> None:
    for package, domain in CATALOGUES:
        (package / "locale").mkdir(exist_ok=True)
        _pybabel(
            "extract",
            "--project=Veilleur",
            "--copyright-holder=Veilleur contributors",
            "--no-location",
            "--sort-output",
            "-o",
            str(package / "locale" / f"{domain}.pot"),
            str(package),
        )


def update() -> None:
    for package, domain in CATALOGUES:
        locale, template = package / "locale", package / "locale" / f"{domain}.pot"
        for language in LANGUAGES:
            if not (locale / language / "LC_MESSAGES" / f"{domain}.po").exists():
                _pybabel("init", "-D", domain, "-i", str(template), "-d", str(locale), "-l", language)
        _pybabel(
            "update",
            "--no-fuzzy-matching",
            "--ignore-pot-creation-date",
            "-D",
            domain,
            "-i",
            str(template),
            "-d",
            str(locale),
        )


def compile_() -> None:
    for package, domain in CATALOGUES:
        _pybabel("compile", "--statistics", "-D", domain, "-d", str(package / "locale"))


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
