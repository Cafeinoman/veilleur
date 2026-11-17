# SPDX-License-Identifier: EUPL-1.2
"""Subscriptions (cahier EF-10 to EF-14): documents sent by receiving tools, team subscriptions, versions."""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from veilleur.core.domain import errors
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import (
    LANGUAGES,
    FilterSpec,
    Frequency,
    JobKind,
    Origin,
    Subscription,
    SubscriptionSpec,
)
from veilleur.core.domain.schema import validate
from veilleur.core.ports.plugins import Collector, Plugins

from .context import Core

_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
MAX_FILTERS = 16
MAX_RENDERINGS = 8


def _member(document: Mapping[str, Any], name: str, kind: type | tuple[type, ...], default: Any) -> Any:
    value = document.get(name, default)
    if not isinstance(value, kind):
        raise VeilleurError(errors.INVALID_SUBSCRIPTION, member=name)
    return value


def _params(schema: Mapping[str, Any], params: Any, where: str) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise VeilleurError(errors.INVALID_SUBSCRIPTION, member=where)
    violation = validate(params, schema)
    if violation is not None:
        raise VeilleurError(errors.INVALID_PARAMS, path=f"{where}{violation.path}", keyword=violation.keyword)
    return params


def parse_spec(document: Mapping[str, Any], plugins: Plugins) -> SubscriptionSpec:
    """Validate a subscription document (protocol specification §9.1) against the installed plugins (EF-12).

    Unknown members are ignored, so that minor versions may add some.
    """
    collector_name = _member(document, "collector", str, None)
    collector = plugins.collectors.get(collector_name)
    if collector is None:
        raise VeilleurError(errors.UNKNOWN_COLLECTOR, name=collector_name[:64])
    params = _params(collector.schema, document.get("params", {}), "params")
    filters: list[FilterSpec] = []
    raw_filters = _member(document, "filters", list, [])
    if len(raw_filters) > MAX_FILTERS:
        raise VeilleurError(errors.INVALID_SUBSCRIPTION, member="filters")
    for index, raw in enumerate(raw_filters):
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            raise VeilleurError(errors.INVALID_SUBSCRIPTION, member=f"filters/{index}")
        plugin = plugins.filters.get(raw["name"])
        if plugin is None:
            raise VeilleurError(errors.UNKNOWN_FILTER, name=raw["name"][:64])
        filters.append(
            FilterSpec(raw["name"], _params(plugin.schema, raw.get("params", {}), f"filters/{index}/params"))
        )
    frequency_name = _member(document, "frequency", str, Frequency.DAILY.value)
    if frequency_name not in {f.value for f in Frequency}:
        raise VeilleurError(errors.INVALID_SUBSCRIPTION, member="frequency")
    language = _member(document, "language", str, "en")
    if language not in LANGUAGES:
        raise VeilleurError(errors.INVALID_SUBSCRIPTION, member="language")
    renderings = _member(document, "renderings", list, [])
    if len(renderings) > MAX_RENDERINGS or not all(isinstance(r, str) for r in renderings):
        raise VeilleurError(errors.INVALID_SUBSCRIPTION, member="renderings")
    if len(set(renderings)) != len(renderings):
        raise VeilleurError(errors.INVALID_SUBSCRIPTION, member="renderings")
    for name in renderings:
        if name not in plugins.renderers:
            raise VeilleurError(errors.UNKNOWN_RENDERER, name=name[:64])
    return SubscriptionSpec(
        collector=collector_name,
        params=params,
        filters=tuple(filters),
        frequency=Frequency(frequency_name),
        language=language,
        renderings=tuple(renderings),
    )


def is_allowed(collector: Collector, grants: Mapping[str, bool]) -> bool:
    """A receiving tool may use a collector the administrator allowed for its pairing; by default, every collector
    that does not follow an address given by the client (EF-11)."""
    return grants.get(collector.name, not collector.follows_client_urls)


def allowed_collectors(core: Core, key_id: str) -> list[Collector]:
    grants = core.store.grants(key_id)
    return [c for name, c in sorted(core.plugins.collectors.items()) if is_allowed(c, grants)]


def put_subscription(core: Core, key_id: str, uid: str, base_version: int, document: Mapping[str, Any]) -> int:
    """Create (base version 0) or replace a subscription of a receiving tool; return its new version (EF-11, EF-14).

    A subscription neither created by this pairing nor deleted is invisible to it: pairings have separate uid spaces.
    """
    spec = parse_spec(document, core.plugins)
    collector = core.plugins.collectors[spec.collector]
    with core.store.transaction():
        if not is_allowed(collector, core.store.grants(key_id)):
            raise VeilleurError(errors.COLLECTOR_NOT_ALLOWED, name=spec.collector)
        now = core.clock.now()
        current = core.store.get_subscription(key_id, uid)
        if current is None:
            if base_version != 0:
                raise VeilleurError(errors.VERSION_CONFLICT, version=0)
            subscription = Subscription(key_id, uid, spec, 1, Origin.CLIENT, now, now)
            core.store.save_subscription(subscription)
            core.store.add_job(JobKind.FIRST_STATE, key_id, uid, "", now)
            core.store.add_event(now, "subscription_created", {"key_id": key_id, "uid": uid})
            return 1
        if current.origin is Origin.TEAM:
            raise VeilleurError(errors.TEAM_SUBSCRIPTION)
        if current.deleted:
            raise VeilleurError(errors.SUBSCRIPTION_DELETED)
        if base_version != current.version:
            raise VeilleurError(errors.VERSION_CONFLICT, version=current.version)
        updated = replace(current, spec=spec, version=current.version + 1, updated_at=now)
        core.store.save_subscription(updated)
        core.store.add_event(now, "subscription_updated", {"key_id": key_id, "uid": uid, "version": updated.version})
        return updated.version


def delete_subscription(core: Core, key_id: str, uid: str) -> None:
    """Delete a subscription of a receiving tool. Deleting it again changes nothing."""
    with core.store.transaction():
        current = core.store.get_subscription(key_id, uid)
        if current is None:
            raise VeilleurError(errors.NOT_FOUND)
        if current.origin is Origin.TEAM:
            raise VeilleurError(errors.TEAM_SUBSCRIPTION)
        if current.deleted:
            return
        now = core.clock.now()
        core.store.save_subscription(replace(current, deleted=True, version=current.version + 1, updated_at=now))
        core.store.add_event(now, "subscription_deleted", {"key_id": key_id, "uid": uid})


def get_live_subscription(core: Core, key_id: str, uid: str) -> Subscription:
    """A subscription that exists and is not deleted, or `not_found`."""
    subscription = core.store.get_subscription(key_id, uid)
    if subscription is None or subscription.deleted:
        raise VeilleurError(errors.NOT_FOUND)
    return subscription


@dataclass(frozen=True)
class TeamSubscription:
    """A team subscription declared by the administrator (EF-10), for the pairings given by `key_id`."""

    name: str
    spec: SubscriptionSpec
    key_ids: tuple[str, ...]


def check_team_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise VeilleurError(errors.INVALID_CONFIG, member="subscriptions.name")
    return name


def sync_team(core: Core, declared: Sequence[TeamSubscription]) -> dict[str, int]:
    """Make the stored team subscriptions match the declaration: create, update (new version) or delete them.

    A team subscription exists once per pairing it is attached to; its uid is drawn at creation and kept.
    """
    wanted = {(key_id, team.name): team.spec for team in declared for key_id in team.key_ids}
    counts = {"created": 0, "updated": 0, "deleted": 0}
    with core.store.transaction():
        now = core.clock.now()
        existing = {
            (s.key_id, s.team_name): s
            for s in core.store.list_subscriptions(include_deleted=True)
            if s.origin is Origin.TEAM and s.team_name is not None
        }
        for (key_id, name), spec in sorted(wanted.items()):
            current = existing.get((key_id, name))
            if current is None or current.deleted:
                if core.store.get_pairing(key_id) is None:
                    raise VeilleurError(errors.UNKNOWN_PAIRING, reference=key_id)
                uid = secrets.token_hex(16)
                core.store.save_subscription(Subscription(key_id, uid, spec, 1, Origin.TEAM, now, now, team_name=name))
                core.store.add_job(JobKind.FIRST_STATE, key_id, uid, "", now)
                counts["created"] += 1
            elif current.spec != spec:
                core.store.save_subscription(replace(current, spec=spec, version=current.version + 1, updated_at=now))
                counts["updated"] += 1
        for (key_id, name), current in existing.items():
            if (key_id, name) not in wanted and not current.deleted:
                core.store.save_subscription(
                    replace(current, deleted=True, version=current.version + 1, updated_at=now)
                )
                counts["deleted"] += 1
        if any(counts.values()):
            core.store.add_event(now, "team_synchronised", counts)
    return counts
