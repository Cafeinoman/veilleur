# SPDX-License-Identifier: EUPL-1.2
"""Wiring: the adapters behind the core's ports, for one process."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass

from veilleur.adapters import keys
from veilleur.adapters.clock import SystemClock
from veilleur.adapters.offline_http import OfflineHttpClient
from veilleur.adapters.plugins import installed, validated
from veilleur.adapters.sealer import ProtocolSealer
from veilleur.adapters.sqlite.store import SqliteStore
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.ports.clock import Clock
from veilleur.core.ports.http import HttpClient
from veilleur.core.ports.plugins import Notifier, Plugins
from veilleur.core.services.context import Core
from veilleur.core.services.pairing import find_pairing
from veilleur.core.services.subscriptions import TeamSubscription, check_team_name, parse_spec, sync_team

from .config import Config

log = logging.getLogger(__name__)


@dataclass
class App:
    config: Config
    core: Core
    store: SqliteStore

    def close(self) -> None:
        self.store.close()


def open_app(
    config: Config,
    *,
    plugins: Plugins | None = None,
    clock: Clock | None = None,
    http: HttpClient | None = None,
    notifiers: Sequence[Notifier] = (),
) -> App:
    """Open the state directory (created with mode 700, ES-10) and the database (migrated after a backup, EF-72)."""
    clock = clock or SystemClock()
    state_dir = config.state_dir
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    store = SqliteStore(config.database, backup_dir=state_dir / "backups", now=clock.now())
    signing_key = keys.load_signing_key(state_dir)
    sealer = ProtocolSealer(signing_key, keys.current_rotation(state_dir, signing_key, clock.now()))
    core = Core(
        store=store,
        plugins=installed() if plugins is None else validated(plugins),
        sealer=sealer,
        clock=clock,
        http=http or OfflineHttpClient(),
        notifiers=tuple(notifiers),
    )
    return App(config, core, store)


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
