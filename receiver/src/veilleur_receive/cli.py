# SPDX-License-Identifier: EUPL-1.2
"""`veilleur-receive` command: pair once, then pull reports into a folder.

The pairing code holds a secret: it is read from the terminal or from standard input, never from the command line,
where it would stay in the shell's history and be visible to other processes.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from veilleur_protocol import ProtocolError, decode_pairing_code

from . import __version__, errors, i18n, store
from .errors import ReceiveError
from .i18n import _, ngettext
from .receiver import Failure, Outcome, pull, read_folder
from .transport import HttpsTransport, Transport

FOLDER_SERVER = "folder:"
MAX_CODE = 4096


def N_(message: str) -> str:
    """Mark a string for extraction without translating it."""
    return message


ARGPARSE_MESSAGES = (
    N_("%(heading)s:"),
    N_("usage: "),
    N_("positional arguments"),
    N_("options"),
    N_("show this help message and exit"),
    N_("%(prog)s: error: %(message)s\n"),
    N_("argument %(argument_name)s: %(message)s"),
    N_("the following arguments are required: %s"),
    N_("unrecognized arguments: %s"),
    N_("expected one argument"),
    N_("invalid choice: %(value)r (choose from %(choices)s)"),
)
_MESSAGES = {
    errors.NOT_PAIRED: N_("This receiver is not paired yet: run “veilleur-receive pair” first."),
    errors.ALREADY_PAIRED: N_("This receiver is already paired; use another state directory for another pairing."),
    errors.STATE_UNREADABLE: N_("The receiver's state file cannot be read."),
    errors.STATE_UNSAFE: N_("The receiver's state is not private to this user; nothing was done."),
    errors.BUSY: N_("Another veilleur-receive command is running on this state."),
    errors.FOLDER_ONLY: N_("This pairing is for delivery by folder: give the folder to read with --from."),
    errors.NO_SOURCE_FOLDER: N_("The folder to read does not exist."),
    errors.UNSAFE_FOLDER: N_("The destination folder cannot be used safely."),
    errors.BAD_PAIRING_CODE: N_("This pairing code is not valid."),
}


def _language_option(argv: Sequence[str]) -> str | None:
    """`--lang` is needed before the parser is built, for the parser's own texts."""
    found: str | None = None
    for index, token in enumerate(argv):
        value = token[7:] if token.startswith("--lang=") else None
        if token == "--lang" and index + 1 < len(argv):
            value = argv[index + 1]
        if value in i18n.LANGUAGES:
            found = value
    return found


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veilleur-receive", description=_("Reference receiver of Veilleur reports."), allow_abbrev=False
    )
    parser.add_argument("--lang", choices=i18n.LANGUAGES, help=_("language of messages (default: from the system)"))
    parser.add_argument("--state-dir", type=Path, metavar=_("folder"), help=_("where the pairing is kept"))
    commands = parser.add_subparsers(dest="command", metavar=_("command"), required=True)
    commands.add_parser("version", help=_("show the version"))
    commands.add_parser("pair", help=_("read a pairing code from the terminal or standard input"))
    fetch = commands.add_parser("pull", help=_("fetch, check and file the new reports"))
    fetch.add_argument("--folder", type=Path, required=True, metavar=_("folder"), help=_("where to file the reports"))
    fetch.add_argument(
        "--from",
        dest="source",
        type=Path,
        metavar=_("folder"),
        help=_("read the packages of this folder instead of the server"),
    )
    return parser


def _read_code() -> str:
    if sys.stdin.isatty():
        return getpass.getpass(_("Pairing code: "))
    return sys.stdin.readline(MAX_CODE + 2)


def _pair(directory: Path) -> None:
    store.prepare_directory(directory)
    with store.locked(directory):
        if store.exists(directory):
            raise ReceiveError(errors.ALREADY_PAIRED)
        try:
            code = decode_pairing_code(_read_code())
        except ProtocolError as exc:
            raise ReceiveError(errors.BAD_PAIRING_CODE) from exc
        store.save(directory, store.from_code(code))
    if code.server == FOLDER_SERVER:
        print(_("Paired for delivery by folder ({key_id}).").format(key_id=code.key_id))
    else:
        print(_("Paired with {server} ({key_id}).").format(server=code.server, key_id=code.key_id))


def _failure_text(failure: Failure) -> str:
    if failure.file is not None:
        return _("file {file}: refused ({code})").format(file=ascii(failure.file), code=failure.code)
    if failure.uid is None:
        return _("the server refused or failed ({code})").format(code=failure.code)
    if failure.seq is None:
        return _("subscription {uid}: stopped ({code})").format(uid=failure.uid, code=failure.code)
    return _("subscription {uid}, package {seq}: refused ({code})").format(
        uid=failure.uid, seq=failure.seq, code=failure.code
    )


def _report(outcome: Outcome, folder: Path) -> int:
    count = len(outcome.written)
    print(ngettext("{count} report filed in {folder}", "{count} reports filed in {folder}", count).format(
        count=count, folder=folder
    ))
    if outcome.key_adopted:
        print(_("The server's key changed: the new key is now trusted, the old one no longer is."))
    for uid in outcome.pending:
        print(_("subscription {uid}: the server is preparing a report, pull again later").format(uid=uid))
    for failure in outcome.failures:
        print(_("error: {message}").format(message=_failure_text(failure)), file=sys.stderr)
    return 1 if outcome.failures else 0


def _pull(
    directory: Path,
    folder: Path,
    source: Path | None,
    transport: Transport | None,
    clock: Callable[[], datetime],
) -> int:
    if not store.exists(directory):
        raise ReceiveError(errors.NOT_PAIRED)
    store.prepare_directory(directory)
    with store.locked(directory):
        state = store.load(directory)

        def save(current: store.State) -> None:
            store.save(directory, current)

        if source is not None:
            outcome = read_folder(state, source, folder, save)
        elif state.server == FOLDER_SERVER:
            raise ReceiveError(errors.FOLDER_ONLY)
        else:
            outcome = pull(state, transport or HttpsTransport(state.server), folder, save, clock)
    return _report(outcome, folder)


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: Transport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Entry point. `transport` and `clock` replace the network and the time in tests."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    i18n.setup(_language_option(arguments))
    argparse._ = i18n._  # type: ignore[attr-defined]
    argparse.ngettext = i18n.ngettext  # type: ignore[attr-defined]
    args = build_parser().parse_args(arguments)
    if args.command == "version":
        print(_("veilleur-receive {version}").format(version=__version__))
        return 0
    directory = args.state_dir or store.default_directory()
    try:
        if args.command == "pair":
            _pair(directory)
            return 0
        return _pull(directory, args.folder, args.source, transport, clock)
    except ReceiveError as exc:
        print(_("error: {message}").format(message=_(_MESSAGES[exc.code])), file=sys.stderr)
        return 1
    except OSError:
        print(_("error: {message}").format(message=_("A file or folder cannot be read or written.")), file=sys.stderr)
        return 1
