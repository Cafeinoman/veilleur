# SPDX-License-Identifier: EUPL-1.2
"""`veilleur` command: administration of the watch server (cahier EF-70).

The language is chosen before the parser is built, so that help texts are translated too.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from veilleur import __version__, i18n
from veilleur.adapters import keys
from veilleur.apps.server import argparse_i18n
from veilleur.core.domain import errors
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import Origin, Pairing, Subscription
from veilleur.core.ports.plugins import RoundCounts
from veilleur.core.services import pairing as pairings
from veilleur.core.services import reports, round
from veilleur.core.services.subscriptions import is_allowed
from veilleur.i18n import _, ngettext
from veilleur_protocol import PairingCode, ProtocolError, b64u_encode

from . import config as config_module
from .context import App, ntfy_for_pairing, open_app, synchronise_team
from .messages import error_message, event_message, source_error

Opener = Callable[[config_module.Config], App]


def _is_lang_option(token: str) -> bool:
    """`--lang` or an abbreviation argparse would accept (`--la`, `--lan`)."""
    return len(token) >= 3 and "--lang".startswith(token)


def _language_option(argv: Sequence[str]) -> str | None:
    """Read `--lang` before anything else (the parser's own texts depend on it).

    This scan never fails: a malformed command line is left to the real parser, which then reports the error in the
    language found here. The last supported value wins, so `--lang fr --lang` or `--lang fr --lang xx` still
    produce a French error message.
    """
    found: str | None = None
    tokens = iter(argv)
    for token in tokens:
        if token == "--":
            break
        if "=" in token:
            option, value = token.split("=", 1)
            if not _is_lang_option(option):
                continue
        elif _is_lang_option(token):
            value = next(tokens, "")
        else:
            continue
        if value in i18n.LANGUAGES:
            found = value
    return found


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veilleur",
        description=_("Administration of the Veilleur watch server."),
    )
    parser.add_argument("--lang", choices=i18n.LANGUAGES, help=_("language of messages (default: from the system)"))
    parser.add_argument("--config", type=Path, metavar=_("file"), help=_("configuration file (TOML)"))
    parser.add_argument("--state-dir", type=Path, metavar=_("folder"), help=_("state directory (database, keys)"))
    commands = parser.add_subparsers(dest="command", metavar=_("command"))
    commands.add_parser("version", help=_("show the version"))
    commands.add_parser("info", help=_("show the state of the server"))
    commands.add_parser("config", help=_("show the configuration in force"))

    pairing = commands.add_parser("pairing", help=_("create, list and revoke pairings"))
    pairing_commands = pairing.add_subparsers(dest="pairing_command", metavar=_("action"), required=True)
    new = pairing_commands.add_parser("new", help=_("create a pairing and show its code, once"))
    new.add_argument("--label", required=True, help=_("a marker such as “desk 3”, never a person's name"))
    pairing_commands.add_parser("list", help=_("list the pairings"))
    revoke = pairing_commands.add_parser("revoke", help=_("revoke a pairing"))
    revoke.add_argument("pairing", metavar=_("pairing"), help=_("key_id or label"))

    subscription = commands.add_parser("subscription", help=_("list and show subscriptions"))
    subscription_commands = subscription.add_subparsers(dest="subscription_command", metavar=_("action"), required=True)
    listing = subscription_commands.add_parser("list", help=_("list the subscriptions"))
    listing.add_argument("--deleted", action="store_true", help=_("include deleted subscriptions"))
    show = subscription_commands.add_parser("show", help=_("show a subscription"))
    show.add_argument("uid", help=_("uid of the subscription"))

    collectors = commands.add_parser("collectors", help=_("installed collectors and those allowed per pairing"))
    collectors.add_argument("--pairing", metavar=_("pairing"), help=_("show what this pairing may use"))
    grant_commands = collectors.add_subparsers(dest="grant_command", metavar=_("action"))
    for name, text in (
        ("allow", _("allow a collector to a pairing")),
        ("deny", _("deny a collector to a pairing")),
        ("default", _("go back to the default for a collector and a pairing")),
    ):
        grant = grant_commands.add_parser(name, help=text)
        grant.add_argument("grant_pairing", metavar=_("pairing"), help=_("key_id or label"))
        grant.add_argument("collector", metavar=_("collector"))

    commands.add_parser("round", help=_("run a round now and show its outcome"))
    commands.add_parser("sources", help=_("show the state of the collections"))
    log = commands.add_parser("log", help=_("show the administration log"))
    log.add_argument("--limit", type=int, default=50, help=_("number of entries"))
    export = commands.add_parser("export", help=_("write the packages of a subscription into a folder"))
    export.add_argument("uid", help=_("uid of the subscription"))
    export.add_argument("--folder", type=Path, required=True, metavar=_("folder"), help=_("destination folder"))
    export.add_argument("--after", type=int, default=0, help=_("only the packages after this number"))
    notify = commands.add_parser("notify", help=_("send notifications"))
    notify.add_argument("--test", action="store_true", required=True, help=_("send a test notification"))
    notify.add_argument(
        "--pairing", dest="notify_pairing", metavar=_("pairing"), help=_("only to this pairing (key_id or label)")
    )
    key = commands.add_parser("key", help=_("manage the server's signing key"))
    key_commands = key.add_subparsers(dest="key_command", metavar=_("action"), required=True)
    key_commands.add_parser("rotate", help=_("replace the server's key; paired tools follow without re-pairing"))
    serve = commands.add_parser("serve", help=_("run the HTTP service"))
    serve.add_argument("--listen", help=_("local address to listen on"))
    serve.add_argument("--port", type=int, help=_("port to listen on"))
    return parser


def _time(moment: datetime | None) -> str:
    return "-" if moment is None else moment.strftime("%Y-%m-%d %H:%M:%SZ")


def _table(rows: Sequence[Sequence[str]]) -> None:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip())


def _find_subscription(app: App, uid: str) -> Subscription:
    matches = [s for s in app.store.list_subscriptions(include_deleted=True) if s.uid == uid]
    if len(matches) != 1:
        raise VeilleurError(errors.UNKNOWN_SUBSCRIPTION, reference=uid)
    return matches[0]


def _cmd_info(app: App) -> None:
    active = [p for p in app.store.list_pairings() if p.active]
    revoked = len(app.store.list_pairings()) - len(active)
    print(_("Veilleur {version}").format(version=__version__))
    print(_("State directory: {path}").format(path=app.config.state_dir))
    print(_("Public address: {url}").format(url=app.config.public_url))
    print(_("Server key: {key}").format(key=b64u_encode(app.core.sealer.public_key)))
    print(_("Pairings: {active} active, {revoked} revoked").format(active=len(active), revoked=revoked))
    print(_("Subscriptions: {count}").format(count=len(round.active_subscriptions(app.core))))
    rounds = [e for e in app.store.events(1000) if e.code == "round_finished"]
    print(_("Last round: {time}").format(time=_time(rounds[-1].at if rounds else None)))


def _cmd_config(app: App) -> None:
    c = app.config
    print(_("Configuration file: {path}").format(path=c.source or "-"))
    print(_("State directory: {path}").format(path=c.state_dir))
    print(_("Public address: {url}").format(url=c.public_url))
    print(_("Language: {language}").format(language=c.language))
    print(_("Listening on: {host}:{port}").format(host=c.listen, port=c.port))
    for team in c.subscriptions:
        print(
            _("Team subscription {name}: collector {collector}, pairings {pairings}").format(
                name=team.name, collector=team.document.get("collector"), pairings=", ".join(team.pairings)
            )
        )


def _cmd_pairing(app: App, args: argparse.Namespace) -> None:
    if args.pairing_command == "new":
        pairings.check_label(args.label)
        try:  # check the public address and the ntfy settings before creating anything
            PairingCode(
                app.config.public_url,
                "0" * 16,
                bytes(32),
                app.core.sealer.public_key,
                ntfy_for_pairing(app.config, Pairing("0" * 16, "-", bytes(32), datetime.now(UTC), topic="0" * 32)),
            )
        except ProtocolError as exc:
            raise VeilleurError(errors.INVALID_CONFIG, member="public_url") from exc
        created = pairings.create_pairing(app.core, args.label)
        code = PairingCode(
            app.config.public_url,
            created.key_id,
            created.secret,
            app.core.sealer.public_key,
            ntfy_for_pairing(app.config, created),
        )
        print(_("Pairing {key_id} created ({label}).").format(key_id=created.key_id, label=created.label))
        print(_("Give this code to the receiving tool. It is shown only once and holds a secret:"))
        print(code.encode())
    elif args.pairing_command == "list":
        rows = [[_("key_id"), _("label"), _("created"), _("revoked")]]
        rows += [[p.key_id, p.label, _time(p.created_at), _time(p.revoked_at)] for p in app.store.list_pairings()]
        _table(rows)
    else:
        revoked = pairings.revoke_pairing(app.core, args.pairing)
        print(_("Pairing {key_id} revoked.").format(key_id=revoked.key_id))


def _cmd_subscription(app: App, args: argparse.Namespace) -> None:
    if args.subscription_command == "list":
        rows = [[_("uid"), _("pairing"), _("origin"), _("collector"), _("frequency"), _("version"), _("state")]]
        for s in app.store.list_subscriptions(include_deleted=args.deleted):
            origin = s.team_name if s.origin is Origin.TEAM else _("receiving tool")
            state = _("deleted") if s.deleted else str(app.store.package_bounds(s.key_id, s.uid).last)
            rows.append(
                [s.uid, s.key_id, origin or "", s.spec.collector, s.spec.frequency.value, str(s.version), state]
            )
        _table(rows)
        return
    s = _find_subscription(app, args.uid)
    bounds = app.store.package_bounds(s.key_id, s.uid)
    print(_("Subscription {uid}").format(uid=s.uid))
    print(_("Pairing: {key_id}").format(key_id=s.key_id))
    print(_("Origin: {origin}").format(origin=s.team_name if s.origin is Origin.TEAM else _("receiving tool")))
    print(_("Collector: {collector}").format(collector=s.spec.collector))
    print(_("Parameters: {params}").format(params=s.spec.params))
    print(_("Filters: {filters}").format(filters=", ".join(f.name for f in s.spec.filters) or "-"))
    print(_("Frequency: {frequency}").format(frequency=s.spec.frequency.value))
    print(_("Language: {language}").format(language=s.spec.language))
    print(_("Renderings: {renderings}").format(renderings=", ".join(s.spec.renderings) or "-"))
    print(_("Version: {version}").format(version=s.version))
    print(_("Packages: last {last}, oldest kept {oldest}").format(last=bounds.last, oldest=bounds.oldest or "-"))
    if s.deleted:
        print(_("Deleted."))


def _cmd_collectors(app: App, args: argparse.Namespace) -> None:
    if args.grant_command:
        target = pairings.find_pairing(app.core, args.grant_pairing)
        if args.collector not in app.core.plugins.collectors:
            raise VeilleurError(errors.UNKNOWN_COLLECTOR, name=args.collector)
        allowed = {"allow": True, "deny": False, "default": None}[args.grant_command]
        app.store.set_grant(target.key_id, args.collector, allowed)
        print(_("Done."))
        return
    grants = {}
    if args.pairing:
        grants = app.store.grants(pairings.find_pairing(app.core, args.pairing).key_id)
    rows = [[_("collector"), _("follows client addresses"), _("allowed") if args.pairing else _("allowed by default")]]
    for name, collector in sorted(app.core.plugins.collectors.items()):
        rows.append(
            [
                name,
                _("yes") if collector.follows_client_urls else _("no"),
                _("yes") if is_allowed(collector, grants) else _("no"),
            ]
        )
    _table(rows)


def _cmd_round(app: App) -> None:
    synchronise_team(app)
    summary = round.run_round(app.core)
    print(
        _("Round finished: {collections} collections, {failed} failed.").format(
            collections=summary.collections, failed=summary.failed_collections
        )
    )
    reports_made = summary.reports + summary.states
    print(ngettext("{count} report produced", "{count} reports produced", reports_made).format(count=reports_made))
    print(ngettext("{count} new item", "{count} new items", summary.new_items).format(count=summary.new_items))
    if summary.failing_sources:
        print(
            ngettext(
                "{count} source failing for more than two days",
                "{count} sources failing for more than two days",
                summary.failing_sources,
            ).format(count=summary.failing_sources)
        )


def _cmd_sources(app: App) -> None:
    rows = [[_("collection"), _("collector"), _("last attempt"), _("last success"), _("state")]]
    for status in app.store.list_sources():
        state = _("ok") if status.error is None else source_error(status.error)
        rows.append(
            [status.collection_id, status.collector, _time(status.last_attempt), _time(status.last_success), state]
        )
    _table(rows)


def _cmd_log(app: App, limit: int) -> None:
    for event in app.store.events(max(limit, 1)):
        print(f"{_time(event.at)}  {event_message(event.code, event.params)}")


def _cmd_export(app: App, args: argparse.Namespace) -> None:
    """Delivery by folder (EF-51): sealed packages need no care in transport."""
    s = _find_subscription(app, args.uid)
    if s.deleted:
        raise VeilleurError(errors.UNKNOWN_SUBSCRIPTION, reference=args.uid)
    args.folder.mkdir(parents=True, exist_ok=True)
    written = 0
    bounds = app.store.package_bounds(s.key_id, s.uid)
    if args.after < bounds.purged_through:
        built = reports.build_state(app.core, s)
        if built is not None:
            (args.folder / f"{s.uid}-{built[0]:08d}-state.veil").write_bytes(built[1])
            written += 1
            print(_("Packages up to {seq} are purged: a state was written instead.").format(seq=bounds.purged_through))
    for info in app.store.list_packages(s.key_id, s.uid, max(args.after, bounds.purged_through)):
        data = app.store.get_package(s.key_id, s.uid, info.seq)
        if data is not None:
            (args.folder / f"{s.uid}-{info.seq:08d}-{info.kind.value}.veil").write_bytes(data)
            written += 1
    print(ngettext("{count} package written", "{count} packages written", written).format(count=written))


def _cmd_notify(app: App, reference: str | None) -> None:
    if not app.core.notifiers:
        print(_("No notifier is configured."))
        return
    if reference is not None:
        targets = [pairings.find_pairing(app.core, reference)]
    else:
        targets = [p for p in app.store.list_pairings() if p.active]
    failed = round.notify(app.core, {p.key_id: RoundCounts(0, 0, 0) for p in targets if p.active})
    sent = len([p for p in targets if p.active]) * len(app.core.notifiers)
    print(_("Test notification: {ok} of {total} sendings succeeded.").format(ok=sent - failed, total=sent))


def _cmd_key(app: App) -> None:
    keys.rotate(app.config.state_dir, app.core.clock.now())
    app.store.add_event(app.core.clock.now(), "key_rotated", {})
    print(_("The server key was replaced; packages carry the rotation statement for 90 days."))


def _run(args: argparse.Namespace, opener: Opener | None) -> int:
    config = config_module.load(args.config, state_dir=args.state_dir)
    app = (opener or open_app)(config)
    try:
        match args.command:
            case "info":
                _cmd_info(app)
            case "config":
                _cmd_config(app)
            case "pairing":
                _cmd_pairing(app, args)
            case "subscription":
                _cmd_subscription(app, args)
            case "collectors":
                _cmd_collectors(app, args)
            case "round":
                _cmd_round(app)
            case "sources":
                _cmd_sources(app)
            case "log":
                _cmd_log(app, args.limit)
            case "export":
                _cmd_export(app, args)
            case "notify":
                _cmd_notify(app, args.notify_pairing)
            case "key":
                _cmd_key(app)
            case "serve":
                from .service import serve

                synchronise_team(app)
                serve(app.core, args.listen or config.listen, args.port or config.port, language=config.language)
    finally:
        app.close()
    return 0


def main(argv: Sequence[str] | None = None, *, opener: Opener | None = None) -> int:
    """Entry point. `opener` replaces the wiring of adapters (tests: fake plugins, clock)."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    i18n.setup(_language_option(args_list))
    argparse_i18n.install()
    parser = build_parser()
    args = parser.parse_args(args_list)
    if args.command == "version":
        print(_("Veilleur {version}, watch server under the EUPL-1.2 licence").format(version=__version__))
        return 0
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return _run(args, opener)
    except VeilleurError as exc:
        print(_("error: {message}").format(message=error_message(exc.code, exc.params)), file=sys.stderr)
        return 1
