# Translating Veilleur

*[Version française](../fr/translating.md)*

Veilleur speaks English and French. Code, identifiers and comments are in English; everything a person reads (command line, logs, API error messages, reports, documentation) exists in both languages.

## Messages

- In the code, wrap user-facing text in `_()` from `veilleur.i18n`, in English: `_("show the version")`. Use named placeholders with `str.format`: `_("Veilleur {version}").format(version=...)`, never string concatenation, so that the translator can move words around.
- For text that depends on a count, use `ngettext(singular, plural, n)`.
- The core (`veilleur.core`) translates nothing: it reports stable codes, and applications turn them into messages. `lint-imports` enforces this.
- API errors carry a stable English `code`, never translated, and a translated `message`.

Then, from the repository root:

```bash
uv run python tools/i18n.py all
```

This extracts the strings into `src/veilleur/locale/veilleur.pot`, merges them into `src/veilleur/locale/fr/LC_MESSAGES/veilleur.po` and compiles `veilleur.mo`. Translate the new entries in the `.po` file (empty `msgstr`), then run `uv run python tools/i18n.py compile`. Both the `.po` and the `.mo` files are committed.

The tests fail when a message has no French translation, when a translation is fuzzy or obsolete, when a placeholder is lost and when the `.mo` file is out of date.

## Language selection

By order of precedence: the `--lang` option (or, for a report, the subscription's language), the `VEILLEUR_LANG` environment variable, the system locale (`LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`). Anything else falls back to English.

The command line also translates the standard `argparse` texts (usage, headings, errors): see `src/veilleur/apps/server/argparse_i18n.py`.

## French conventions

A non-breaking-style space before `:`, `;`, `?` and `!` is written as a plain space in messages (`options :`); French quotation marks « … »; no anglicism when a common French word exists (*greffon* for plugin, *jumelage* for pairing).

## Documentation

Every page exists in `docs/en/` and `docs/fr/` under the same file name; a test checks it. Update both in the same change. Where they differ, the English version of the protocol specification is normative; other pages have no reference language.
