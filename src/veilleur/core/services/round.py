# SPDX-License-Identifier: EUPL-1.2
"""A round (cahier §4): due collections, change detection, reports, purge, notification."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from veilleur.core.domain.model import RETENTION_DAYS, Subscription
from veilleur.core.ports.plugins import RoundCounts

from . import reports
from .collect import CollectionResult, collect
from .context import Core

log = logging.getLogger(__name__)
FAILURE_NOTICE = timedelta(days=2)
"""A source failing for longer is counted in notifications (EF-05)."""
JOB_RETENTION = timedelta(days=1)


@dataclass
class RoundSummary:
    collections: int = 0
    failed_collections: int = 0
    reports: int = 0
    states: int = 0
    new_items: int = 0
    failing_sources: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    purged: dict[str, int] = field(default_factory=dict)

    def counts(self) -> RoundCounts:
        return RoundCounts(self.reports + self.states, self.new_items, self.failing_sources)


def active_subscriptions(core: Core) -> list[Subscription]:
    """Subscriptions that are served: not deleted, of a pairing that is not revoked (EF-62)."""
    active = {p.key_id for p in core.store.list_pairings() if p.active}
    return [s for s in core.store.list_subscriptions() if s.key_id in active]


def run_round(core: Core) -> RoundSummary:
    summary = RoundSummary()
    subscriptions = active_subscriptions(core)
    results: dict[str, CollectionResult] = {}
    for subscription in subscriptions:
        collection_id = subscription.spec.collection_id
        if collection_id not in results:  # shared collections (EF-04)
            results[collection_id] = collect(core, subscription.spec)
    summary.collections = len(results)
    summary.failed_collections = sum(1 for r in results.values() if r.status.error is not None)
    for subscription in subscriptions:
        try:
            if core.store.package_bounds(subscription.key_id, subscription.uid).last == 0:
                info = reports.produce_first_state(core, subscription)
                summary.states += info is not None
            else:
                info = reports.produce_delta(core, subscription)
                summary.reports += info is not None
        except reports.ReportSkipped as skipped:
            summary.skipped[skipped.reason] = summary.skipped.get(skipped.reason, 0) + 1
            continue
        if info is not None:
            summary.new_items += _count_new(core, subscription)
    now = core.clock.now()
    summary.failing_sources = sum(
        1
        for status in core.store.list_sources()
        if status.collection_id in results
        and status.failing_since is not None
        and now - status.failing_since >= FAILURE_NOTICE
    )
    summary.purged = dict(core.store.purge(now - timedelta(days=RETENTION_DAYS), now - JOB_RETENTION))
    core.store.add_event(
        now,
        "round_finished",
        {
            "collections": summary.collections,
            "failed": summary.failed_collections,
            "reports": summary.reports + summary.states,
            "new_items": summary.new_items,
        },
    )
    if summary.reports + summary.states:
        notify(core, summary.counts())
    return summary


def _count_new(core: Core, subscription: Subscription) -> int:
    """Items first reported by the package just made."""
    last = core.store.last_package(subscription.key_id, subscription.uid)
    if last is None:
        return 0
    return sum(
        1
        for item in core.store.reported_items(subscription.key_id, subscription.uid).values()
        if item.gone_at is None and item.first_reported == last.created_at
    )


def notify(core: Core, counts: RoundCounts) -> int:
    """Send the counts to every notifier (EF-52); return how many failed. A failing notifier never stops a round."""
    failed = 0
    for notifier in core.notifiers:
        try:
            notifier.notify(counts)
        except Exception as exc:  # a plugin may raise anything
            log.warning("notifier %s failed: %s", notifier.name, type(exc).__name__)
            failed += 1
    return failed
