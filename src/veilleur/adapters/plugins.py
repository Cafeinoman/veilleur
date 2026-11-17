# SPDX-License-Identifier: EUPL-1.2
"""Installed plugins, found through entry points (cahier EF-01, EF-20, EF-43, EF-52)."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from importlib.metadata import entry_points
from typing import Any

from veilleur.core.domain.schema import check_schema
from veilleur.core.ports.plugins import Collector, Filter, Plugins, Renderer

log = logging.getLogger(__name__)
NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
GROUPS = ("veilleur.collectors", "veilleur.filters", "veilleur.renderers")


def _load(group: str) -> dict[str, Any]:
    """Plugins of an entry point group. A plugin that cannot be loaded, has an invalid name or schema, or whose
    name is taken, is left out with a warning: one broken plugin does not stop the server."""
    found: dict[str, Any] = {}
    for entry in sorted(entry_points(group=group), key=lambda e: e.name):
        try:
            plugin = entry.load()
            plugin = plugin() if isinstance(plugin, type) else plugin
            if not NAME.fullmatch(entry.name) or getattr(plugin, "name", None) != entry.name:
                raise ValueError("name")
            if hasattr(plugin, "schema"):
                check_schema(plugin.schema)
        except Exception as exc:  # a plugin may raise anything while loading
            log.warning("plugin %s (%s) left out: %s", entry.name, group, type(exc).__name__)
            continue
        if entry.name in found:
            log.warning("plugin %s (%s) left out: name already taken", entry.name, group)
            continue
        found[entry.name] = plugin
    return found


def validated(plugins: Plugins) -> Plugins:
    """Check the schemas of plugins given directly (tests, embedding): raise `ValueError` for an invalid one."""
    for mapping in (plugins.collectors, plugins.filters):
        for name, plugin in mapping.items():
            if not NAME.fullmatch(name) or plugin.name != name:
                raise ValueError(f"plugin name {name!r}")
            check_schema(plugin.schema)
    return plugins


def installed(extra: Mapping[str, Collector] | None = None) -> Plugins:
    collectors: dict[str, Collector] = _load("veilleur.collectors")
    collectors.update(extra or {})
    filters: dict[str, Filter] = _load("veilleur.filters")
    renderers: dict[str, Renderer] = _load("veilleur.renderers")
    return Plugins(collectors, filters, renderers)
