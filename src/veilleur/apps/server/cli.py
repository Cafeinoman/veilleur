# SPDX-License-Identifier: EUPL-1.2
"""`veilleur` command: administration of the watch server.

The language is chosen before the parser is built, so that help texts are translated too.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from veilleur import __version__, i18n
from veilleur.apps.server import argparse_i18n
from veilleur.i18n import _


def _language_option(argv: Sequence[str]) -> str | None:
    """Read `--lang` before anything else (the parser's own texts depend on it)."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang")
    known, _rest = pre.parse_known_args(argv)
    value: str | None = known.lang
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veilleur",
        description=_("Administration of the Veilleur watch server."),
    )
    parser.add_argument("--lang", choices=i18n.LANGUAGES, help=_("language of messages (default: from the system)"))
    commands = parser.add_subparsers(dest="command", metavar=_("command"))
    commands.add_parser("version", help=_("show the version"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    i18n.setup(_language_option(args_list))
    argparse_i18n.install()
    parser = build_parser()
    args = parser.parse_args(args_list)
    if args.command == "version":
        print(_("Veilleur {version}, watch server under the EUPL-1.2 licence").format(version=__version__))
        return 0
    parser.print_help()
    return 0
