# SPDX-License-Identifier: EUPL-1.2
"""Translation of user-facing text (gettext, domain `veilleur`).

Source strings are written in English in the code; the catalogues in `veilleur/locale/<lang>/LC_MESSAGES/` translate
them. The core never translates anything: it reports stable codes, and applications turn them into messages.

Language, by order of precedence: the `lang` argument (`--lang`, a subscription's language...), then the
`VEILLEUR_LANG` environment variable, then the usual locale variables (`LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`).
An unsupported language falls back to English.
"""

from __future__ import annotations

import gettext
import os
from pathlib import Path

DOMAIN = "veilleur"
LOCALE_DIR = Path(__file__).parent / "locale"
SOURCE_LANGUAGE = "en"
LANGUAGES = ("en", "fr")
_LOCALE_VARIABLES = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")

_current: gettext.NullTranslations = gettext.NullTranslations()


def resolve(lang: str | None = None, environ: dict[str, str] | None = None) -> str:
    """Return the supported language to use (`en` or `fr`)."""
    env = os.environ if environ is None else environ
    candidates: list[str] = []
    if lang:
        candidates.append(lang)
    if env.get("VEILLEUR_LANG"):
        candidates.append(env["VEILLEUR_LANG"])
    for var in _LOCALE_VARIABLES:
        value = env.get(var)
        if value:
            candidates.extend(value.split(":"))
            break
    for candidate in candidates:
        code = candidate.split(".")[0].split("@")[0].split("_")[0].split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return SOURCE_LANGUAGE


def translations(language: str) -> gettext.NullTranslations:
    """Catalogue of a supported language; English needs none."""
    if language == SOURCE_LANGUAGE:
        return gettext.NullTranslations()
    return gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[language])


def setup(lang: str | None = None) -> str:
    """Choose the language of the process's messages; return it."""
    global _current
    language = resolve(lang)
    _current = translations(language)
    return language


def _(message: str) -> str:
    """Translate `message` into the current language."""
    return _current.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate a message whose form depends on the count `n`."""
    return _current.ngettext(singular, plural, n)
