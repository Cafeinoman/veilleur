# SPDX-License-Identifier: EUPL-1.2
"""Translation of the standard library's `argparse` texts ("usage:", "options", error messages...).

`argparse` translates its texts with the `_` and `ngettext` functions of its own module, looked up at call time; the
standard library ships no catalogue for them. `install()` points them to Veilleur's catalogue. The source strings
below are those of `argparse` (Python 3.12): listed here so that extraction puts them in the catalogue. If a later
Python version changes one of them, the text simply stays in English.
"""

from __future__ import annotations

import argparse

from veilleur import i18n


def N_(message: str) -> str:
    """Mark a string for extraction without translating it."""
    return message


ARGPARSE_MESSAGES = (
    N_("%(heading)s:"),
    N_("usage: "),
    N_("positional arguments"),
    N_("options"),
    N_("subcommands"),
    N_("show this help message and exit"),
    N_("%(prog)s: error: %(message)s\n"),
    N_("argument %(argument_name)s: %(message)s"),
    N_("the following arguments are required: %s"),
    N_("one of the arguments %s is required"),
    N_("unrecognized arguments: %s"),
    N_("expected one argument"),
    N_("ambiguous option: %(option)s could match %(matches)s"),
    N_("invalid choice: %(value)r (choose from %(choices)s)"),
    N_("invalid %(type)s value: %(value)r"),
    N_("not allowed with argument %s"),
    N_("ignored explicit argument %r"),
    N_("expected at least one argument"),
    N_("expected at most one argument"),
    N_("unexpected option string: %s"),
    N_("unknown parser %(parser_name)r (choices: %(choices)s)"),
    N_("can't open '%(filename)s': %(error)s"),
    N_("show program's version number and exit"),
    N_(" (default: %(default)s)"),
)


def _plural_messages() -> None:  # pragma: no cover - never called, read by the extractor only
    """Plural texts of `argparse`, listed for extraction (there is no plural form of `N_`)."""
    i18n.ngettext("expected %s argument", "expected %s arguments", 1)


def install() -> None:
    """Make `argparse` use Veilleur's current language."""
    argparse._ = i18n._  # type: ignore[attr-defined]
    argparse.ngettext = i18n.ngettext  # type: ignore[attr-defined]
