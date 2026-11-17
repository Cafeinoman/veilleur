# SPDX-License-Identifier: EUPL-1.2
"""What the services work with: the adapters behind the ports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from veilleur.core.ports.clock import Clock
from veilleur.core.ports.http import HttpClient
from veilleur.core.ports.plugins import Notifier, Plugins
from veilleur.core.ports.sealer import Sealer
from veilleur.core.ports.store import Store


@dataclass(frozen=True)
class Core:
    store: Store
    plugins: Plugins
    sealer: Sealer
    clock: Clock
    http: HttpClient
    notifiers: Sequence[Notifier] = field(default_factory=tuple)
