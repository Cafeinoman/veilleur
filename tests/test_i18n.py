# SPDX-License-Identifier: EUPL-1.2
"""Language resolution and completeness of the translation catalogues."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.mofile import read_mo
from babel.messages.pofile import read_po

from veilleur import i18n

PACKAGE = Path(i18n.__file__).parent
TRANSLATED = [lang for lang in i18n.LANGUAGES if lang != i18n.SOURCE_LANGUAGE]


@pytest.mark.parametrize(
    ("lang", "environ", "expected"),
    [
        ("fr", {"LANG": "en_US.UTF-8"}, "fr"),
        (None, {"VEILLEUR_LANG": "fr", "LANG": "en_GB.UTF-8"}, "fr"),
        (None, {"LANG": "fr_FR.UTF-8"}, "fr"),
        (None, {"LANGUAGE": "de:fr", "LANG": "en_US"}, "fr"),
        (None, {"LC_ALL": "fr_BE.UTF-8@euro"}, "fr"),
        (None, {"LANG": "de_DE.UTF-8"}, "en"),
        (None, {}, "en"),
        ("es", {}, "en"),
    ],
)
def test_resolve(lang: str | None, environ: dict[str, str], expected: str) -> None:
    assert i18n.resolve(lang, environ) == expected


def _key(msgid: object) -> str:
    """Singular form of a message identifier (plural entries have a tuple of forms)."""
    return msgid if isinstance(msgid, str) else str(msgid[0])  # type: ignore[index]


def _forms(text: object) -> tuple[str, ...]:
    """Every form of a message text, singular or plural."""
    return (text,) if isinstance(text, str) else tuple(text)  # type: ignore[arg-type]


def _source_ids() -> set[str]:
    return {_key(msgid) for _file, _line, msgid, _comments, _context in extract_from_dir(str(PACKAGE))}


def _po(lang: str) -> Catalog:
    with (PACKAGE / "locale" / lang / "LC_MESSAGES" / "veilleur.po").open("rb") as f:
        return read_po(f)


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_message_is_translated(lang: str) -> None:
    catalog = _po(lang)
    missing = sorted(i for i in _source_ids() if not (catalog.get(i) and all(_forms(catalog[i].string))))
    assert not missing, f"untranslated in {lang} (run tools/i18n.py all, then translate): {missing}"
    fuzzy = sorted(str(m.id) for m in catalog if m.id and m.fuzzy)
    assert not fuzzy, f"fuzzy entries in {lang}: {fuzzy}"


@pytest.mark.parametrize("lang", TRANSLATED)
def test_no_obsolete_message(lang: str) -> None:
    catalog = _po(lang)
    obsolete = sorted(_key(m.id) for m in catalog if m.id and _key(m.id) not in _source_ids())
    assert not obsolete and not catalog.obsolete, f"obsolete in {lang} (run tools/i18n.py update): {obsolete}"


@pytest.mark.parametrize("lang", TRANSLATED)
def test_placeholders_are_kept(lang: str) -> None:
    pattern = re.compile(r"%\(\w+\)[sdr]|%[sdr]|\{\w*\}")
    for m in _po(lang):
        if m.id and m.string:
            source = sorted(pattern.findall(_key(m.id)))
            for form in _forms(m.string):
                assert sorted(pattern.findall(form)) == source, m.id


@pytest.mark.parametrize("lang", TRANSLATED)
def test_compiled_catalogue_is_up_to_date(lang: str) -> None:
    mo_path = PACKAGE / "locale" / lang / "LC_MESSAGES" / "veilleur.mo"
    with mo_path.open("rb") as f:
        compiled = read_mo(io.BytesIO(f.read()))
    expected = {_key(m.id): _forms(m.string) for m in _po(lang) if m.id and m.string}
    actual = {_key(m.id): _forms(m.string) for m in compiled if m.id}
    assert actual == expected, "run tools/i18n.py compile"
