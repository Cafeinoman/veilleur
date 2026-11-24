# SPDX-License-Identifier: EUPL-1.2
"""Reports of a subscription (spec EF-21, EF-32, EF-40 to EF-44).

Each subscription keeps what it last reported about every item. A report compares the filtered current items of its
collection with that: new, changed or gone. Frequencies and filters thus stay consistent: changes accumulate until
the report is due, and an item a filter no longer keeps leaves the receiver's view as `gone`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from veilleur.core.domain.model import (
    Change,
    Frequency,
    ItemChange,
    Kind,
    PackageInfo,
    ReportedItem,
    SourceStatus,
    Subscription,
    item_hash,
    sha256_hex,
)
from veilleur.core.ports.plugins import FilterItem, ReportView, SetFilter
from veilleur.core.ports.sealer import PackageSpec, PackageTooLarge

from .context import Core

log = logging.getLogger(__name__)
_RENDERING = re.compile(r"report\.[a-z0-9]{1,16}")
_SLACK = timedelta(hours=1)
"""A daily or weekly report is due a little early, so that a timer firing a few minutes late does not skip a day."""
PERIODS = {Frequency.EVERY_ROUND: timedelta(0), Frequency.DAILY: timedelta(days=1), Frequency.WEEKLY: timedelta(days=7)}


class ReportSkipped(Exception):
    """A report cannot be made this time (a missing or failing filter, a collection that never succeeded...);
    `reason` is a stable code for the administration log."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _Current:
    hash: str
    fields: dict[str, object]
    url: str | None
    fetched_at: datetime


def _current_view(core: Core, subscription: Subscription) -> dict[str, _Current]:
    """The items of the subscription's collection, through its filters (they never modify stored items, EF-21)."""
    status = core.store.get_source(subscription.spec.collection_id)
    if status is None or status.last_success is None:
        raise ReportSkipped("never_collected")
    filters = []
    for spec in subscription.spec.filters:
        plugin = core.plugins.filters.get(spec.name)
        if plugin is None:
            raise ReportSkipped("filter_missing")
        filters.append((plugin, spec.params))
    stored = core.store.current_items(subscription.spec.collection_id)
    seen = [FilterItem(key, item.fields, item.url) for key, item in sorted(stored.items())]
    try:
        for plugin, params in filters:
            if isinstance(plugin, SetFilter):
                kept = list(plugin.select(seen, params))
            else:
                kept = [result for item in seen if (result := plugin.apply(item, params)) is not None]
            if not all(
                isinstance(item, FilterItem) and item.key in stored and (item.url is None or isinstance(item.url, str))
                for item in kept
            ):
                raise TypeError("a filter returned something else than an item it was given")
            seen = kept
        view: dict[str, _Current] = {}
        for item in seen:
            # Hashed again: a filter may have changed the fields, even in place (protocol §7.4: `hash` matches
            # `fields`).
            view[item.key] = _Current(item_hash(item.fields), item.fields, item.url, stored[item.key].fetched_at)
    except Exception as exc:  # a plugin may raise anything; the subscription waits for the next round
        log.warning("filter failed for a subscription: %s", type(exc).__name__)
        raise ReportSkipped("filter_failed") from exc
    return view


def _diff(
    view: dict[str, _Current], reported: dict[str, ReportedItem], now: datetime
) -> tuple[list[ItemChange], list[ReportedItem]]:
    changes: list[ItemChange] = []
    updates: list[ReportedItem] = []
    for key, current in view.items():
        old = reported.get(key)
        if old is None or old.gone_at is not None:
            changes.append(ItemChange(key, Change.NEW, current.hash, current.fields, current.fetched_at, current.url))
            updates.append(ReportedItem(key, current.hash, current.fields, current.url, current.fetched_at, now, now))
        elif old.hash != current.hash:
            changes.append(
                ItemChange(key, Change.CHANGED, current.hash, current.fields, current.fetched_at, current.url)
            )
            updates.append(
                replace(
                    old,
                    hash=current.hash,
                    fields=current.fields,
                    url=current.url,
                    fetched_at=current.fetched_at,
                    last_changed=now,
                )
            )
    for key, old in reported.items():
        if old.gone_at is None and key not in view:
            changes.append(ItemChange(key, Change.GONE, old.hash, old.fields, old.fetched_at, old.url))
            updates.append(replace(old, gone_at=now))
    changes.sort(key=lambda change: change.key)
    return changes, updates


def sources(core: Core, subscription: Subscription) -> list[SourceStatus]:
    status = core.store.get_source(subscription.spec.collection_id)
    if status is None:
        status = SourceStatus(subscription.spec.collection_id, subscription.spec.collector, None, None, None)
    return [status]


def _renderings(core: Core, subscription: Subscription, view: ReportView) -> dict[str, bytes]:
    """Readable renderings; optional and derived (EF-43): a missing or failing renderer is left out."""
    files: dict[str, bytes] = {}
    for name in subscription.spec.renderings:
        renderer = core.plugins.renderers.get(name)
        if renderer is None:
            continue
        try:
            for file_name, data in renderer.render(view, subscription.spec.language).items():
                if _RENDERING.fullmatch(file_name) and isinstance(data, bytes) and file_name not in files:
                    files[file_name] = data
        except Exception as exc:  # a plugin may raise anything
            log.warning("renderer %s failed: %s", name, type(exc).__name__)
    return files


def _seal(
    core: Core,
    subscription: Subscription,
    seq: int,
    kind: Kind,
    items: list[ItemChange],
    period_from: datetime | None,
    now: datetime,
) -> bytes:
    pairing = core.store.get_pairing(subscription.key_id)
    if pairing is None or not pairing.active:
        raise ReportSkipped("pairing_revoked")
    status = sources(core, subscription)
    view = ReportView(subscription.uid, seq, kind, now, period_from, now, items, status)
    renderings = _renderings(core, subscription, view)
    spec = PackageSpec(subscription.uid, seq, kind, now, period_from, now, items, status, renderings)
    try:
        try:
            return core.sealer.seal_package(pairing.secret, spec)
        except PackageTooLarge:
            if not renderings:
                raise
            # Renderings are optional (EF-43): they never cost a report its authoritative data.
            log.warning("package too large with its renderings: sealed without them")
            return core.sealer.seal_package(pairing.secret, replace(spec, renderings={}))
    except PackageTooLarge as exc:
        raise ReportSkipped("package_too_large") from exc


def _store_package(
    core: Core,
    subscription: Subscription,
    kind: Kind,
    changes: list[ItemChange],
    updates: list[ReportedItem],
    period_from: datetime | None,
    now: datetime,
) -> PackageInfo:
    seq = core.store.package_bounds(subscription.key_id, subscription.uid).last + 1
    data = _seal(core, subscription, seq, kind, changes, period_from, now)
    info = PackageInfo(seq, kind, len(data), sha256_hex(data), now, now)
    core.store.add_package(subscription.key_id, subscription.uid, info, data)
    core.store.save_reported(subscription.key_id, subscription.uid, updates)
    return info


def produce_first_state(core: Core, subscription: Subscription) -> PackageInfo | None:
    """Package 1 of a new subscription: a `state` of what is in force (EF-32), even with no item, as soon as its
    collection has succeeded once. None if it already has packages."""
    with core.store.transaction():
        if core.store.package_bounds(subscription.key_id, subscription.uid).last != 0:
            return None
        now = core.clock.now()
        view = _current_view(core, subscription)
        changes, updates = _diff(view, {}, now)
        return _store_package(core, subscription, Kind.STATE, changes, updates, None, now)


def is_due(subscription: Subscription, last: PackageInfo | None, now: datetime) -> bool:
    if last is None:
        return False
    period = PERIODS[subscription.spec.frequency]
    return period == timedelta(0) or now - last.created_at >= period - _SLACK


def produce_delta(core: Core, subscription: Subscription) -> PackageInfo | None:
    """The next `delta` if the subscription's report is due and something changed (EF-44), otherwise None."""
    with core.store.transaction():
        now = core.clock.now()
        last = core.store.last_package(subscription.key_id, subscription.uid)
        if last is None or not is_due(subscription, last, now):
            return None
        view = _current_view(core, subscription)
        changes, updates = _diff(view, core.store.reported_items(subscription.key_id, subscription.uid), now)
        if not changes:
            return None
        return _store_package(core, subscription, Kind.DELTA, changes, updates, last.period_to, now)


def _reported_change(item: ReportedItem, change: Change) -> ItemChange:
    return ItemChange(item.key, change, item.hash, item.fields, item.fetched_at, item.url)


def build_state(core: Core, subscription: Subscription) -> tuple[int, bytes] | None:
    """A `state` on request: what the receiving tool holds after the last package, numbered as it (protocol §7.3).
    None while the subscription has no package yet."""
    with core.store.transaction():
        last = core.store.package_bounds(subscription.key_id, subscription.uid).last
        if last == 0:
            return None
        reported = core.store.reported_items(subscription.key_id, subscription.uid)
        items = sorted(
            (_reported_change(i, Change.NEW) for i in reported.values() if i.gone_at is None), key=lambda c: c.key
        )
        return last, _seal(core, subscription, last, Kind.STATE, items, None, core.clock.now())


def build_history(core: Core, subscription: Subscription, since: datetime) -> tuple[int, bytes] | None:
    """A `history` since `since`: items first reported, changed or gone since then, among those still kept (90
    days). None while the subscription has no package yet."""
    with core.store.transaction():
        last = core.store.package_bounds(subscription.key_id, subscription.uid).last
        if last == 0:
            return None
        items: list[ItemChange] = []
        for item in core.store.reported_items(subscription.key_id, subscription.uid).values():
            if item.gone_at is not None:
                if item.gone_at >= since:
                    items.append(_reported_change(item, Change.GONE))
            elif item.first_reported >= since:
                items.append(_reported_change(item, Change.NEW))
            elif item.last_changed >= since:
                items.append(_reported_change(item, Change.CHANGED))
        items.sort(key=lambda c: c.key)
        return last, _seal(core, subscription, last, Kind.HISTORY, items, since, core.clock.now())
