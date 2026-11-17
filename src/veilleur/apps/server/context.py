# SPDX-License-Identifier: EUPL-1.2
"""Wiring: the adapters behind the core's ports, for one process."""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from veilleur.adapters import keys
from veilleur.adapters.clock import SystemClock
from veilleur.adapters.http import NetworkHttpClient, OfflineHttpClient
from veilleur.adapters.http.cache import SqliteCache
from veilleur.adapters.notifiers import NtfyNotifier, WebhookNotifier
from veilleur.adapters.plugins import installed, installed_notifiers, validated
from veilleur.adapters.sealer import ProtocolSealer
from veilleur.adapters.sqlite.store import SqliteStore
from veilleur.core.domain import errors
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import Pairing
from veilleur.core.ports.clock import Clock
from veilleur.core.ports.http import HttpClient
from veilleur.core.ports.plugins import Notifier, Plugins
from veilleur.core.services.context import Core
from veilleur.core.services.pairing import find_pairing
from veilleur.core.services.subscriptions import TeamSubscription, check_team_name, parse_spec, sync_team
from veilleur_protocol import Ntfy

from .config import Config

log = logging.getLogger(__name__)


WEBHOOK_KEY_FILE = "webhook.key"


@dataclass
class App:
    config: Config
    core: Core
    store: SqliteStore
    cache: SqliteCache | None = None

    def close(self) -> None:
        self.store.close()
        if self.cache is not None:
            self.cache.close()


def read_secret(path: Path, member: str) -> str:
    """A secret given by the host as a file (ES-10, ENF-03b): its first line."""
    try:
        value = path.read_text("utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise VeilleurError(errors.INVALID_CONFIG, member=member) from exc
    if not value or "\n" in value:
        raise VeilleurError(errors.INVALID_CONFIG, member=member)
    return value


def webhook_key(config: Config) -> bytes:
    """The webhook's HMAC key: the host's file, otherwise `webhook.key` in the state directory, generated once."""
    assert config.webhook is not None
    if config.webhook.key_file is not None:
        return read_secret(config.webhook.key_file, "webhook.key_file").encode("utf-8")
    path = config.state_dir / WEBHOOK_KEY_FILE
    if not path.exists():
        keys.write_private(path, secrets.token_hex(32).encode("ascii"))
    return read_secret(path, "webhook.key_file").encode("utf-8")


def configured_notifiers(config: Config) -> list[Notifier]:
    """The provided notifiers set in the configuration, then the installed notifier plugins (EF-52): installing a
    plugin is the administrator's choice, so an installed one is used."""
    found: list[Notifier] = []
    if config.ntfy is not None:
        token = read_secret(config.ntfy.token_file, "ntfy.token_file") if config.ntfy.token_file else None
        found.append(NtfyNotifier(config.ntfy.url, token, config.language))
    if config.webhook is not None:
        found.append(WebhookNotifier(config.webhook.url, webhook_key(config)))
    found.extend(installed_notifiers().values())
    return found


def ntfy_for_pairing(config: Config, pairing: Pairing) -> Ntfy | None:
    """What the pairing code says about notifications (EF-60)."""
    if config.ntfy is None:
        return None
    file = config.ntfy.client_token_file
    token = read_secret(file, "ntfy.client_token_file") if file else None
    return Ntfy(config.ntfy.public_url, pairing.topic, token)


def open_app(
    config: Config,
    *,
    plugins: Plugins | None = None,
    clock: Clock | None = None,
    http: HttpClient | None = None,
    notifiers: Sequence[Notifier] | None = None,
) -> App:
    """Open the state directory (created with mode 700, ES-10) and the database (migrated after a backup, EF-72)."""
    clock = clock or SystemClock()
    state_dir = config.state_dir
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    store = SqliteStore(config.database, backup_dir=state_dir / "backups", now=clock.now())
    cache: SqliteCache | None = None
    if http is None and not config.offline:
        cache = SqliteCache(state_dir / "cache" / "http.db", clock.now())
        http = NetworkHttpClient(public_url=config.public_url, cache=cache, now=clock.now)
    signing_key = keys.load_signing_key(state_dir)
    sealer = ProtocolSealer(signing_key, keys.current_rotation(state_dir, signing_key, clock.now()))
    core = Core(
        store=store,
        plugins=installed() if plugins is None else validated(plugins),
        sealer=sealer,
        clock=clock,
        http=http or OfflineHttpClient(),
        notifiers=tuple(configured_notifiers(config) if notifiers is None else notifiers),
    )
    return App(config, core, store, cache)


def team_subscriptions(app: App) -> list[TeamSubscription]:
    """The declared team subscriptions, validated like a receiving tool's (EF-10, EF-12). A pairing that does not
    exist (yet) is skipped and logged, so that one typo does not stop the rounds."""
    declared = []
    for team in app.config.subscriptions:
        check_team_name(team.name)
        spec = parse_spec(team.document, app.core.plugins)
        key_ids = []
        for reference in team.pairings:
            try:
                key_ids.append(find_pairing(app.core, reference).key_id)
            except VeilleurError as exc:
                app.store.add_event(app.core.clock.now(), "team_pairing_skipped", {"name": team.name, **exc.params})
        declared.append(TeamSubscription(team.name, spec, tuple(dict.fromkeys(key_ids))))
    return declared


def synchronise_team(app: App) -> dict[str, int]:
    return sync_team(app.core, team_subscriptions(app))
