# SPDX-License-Identifier: EUPL-1.2
"""Translation of the receiver's messages (gettext, domain `veilleur_receive`).

Language, by order of precedence: `--lang`, then `VEILLEUR_LANG`, then the usual locale variables; otherwise English.
"""

from __future__ import annotations

import gettext
import os
from pathlib import Path

DOMAIN = "veilleur_receive"
LOCALE_DIR = Path(__file__).parent / "locale"
SOURCE_LANGUAGE = "en"
LANGUAGES = ("en", "fr")
_LOCALE_VARIABLES = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")

_current: gettext.NullTranslations = gettext.NullTranslations()


def resolve(lang: str | None = None) -> str:
    candidates = [lang] if lang else []
    if os.environ.get("VEILLEUR_LANG"):
        candidates.append(os.environ["VEILLEUR_LANG"])
    for variable in _LOCALE_VARIABLES:
        if value := os.environ.get(variable):
            candidates.extend(value.split(":"))
            break
    for candidate in candidates:
        code = candidate.split(".")[0].split("@")[0].split("_")[0].split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return SOURCE_LANGUAGE


def setup(lang: str | None = None) -> str:
    global _current
    language = resolve(lang)
    _current = (
        gettext.NullTranslations()
        if language == SOURCE_LANGUAGE
        else gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[language])
    )
    return language


def _(message: str) -> str:
    return _current.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _current.ngettext(singular, plural, n)
