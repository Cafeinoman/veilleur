# SPDX-License-Identifier: EUPL-1.2
"""Long jobs (spec §7.5): first `state` of a subscription and `history` packages, run by the worker thread."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from veilleur.core.domain import errors
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import Job, JobKind, JobStatus

from . import reports
from .collect import collect
from .context import Core

log = logging.getLogger(__name__)


def parse_since(text: str) -> datetime:
    """`YYYY-MM-DD`, as midnight UTC."""
    try:
        if len(text) != 10 or not text.isascii():
            raise ValueError(text)
        day = date.fromisoformat(text)
    except ValueError as exc:
        raise VeilleurError(errors.BAD_REQUEST) from exc
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def request_history(core: Core, key_id: str, uid: str, since: str) -> Job:
    """The `history` job of a subscription since a date, created if needed (one per date)."""
    parse_since(since)
    with core.store.transaction():
        job = core.store.find_job(JobKind.HISTORY, key_id, uid, since)
        if job is None or job.status is JobStatus.FAILED:
            job = core.store.add_job(JobKind.HISTORY, key_id, uid, since, core.clock.now())
    return job


def run_job(core: Core, job: Job) -> None:
    """Run one pending job and record its outcome; never raises."""
    ok, seq, result = True, None, None
    try:
        subscription = core.store.get_subscription(job.key_id, job.uid)
        pairing = core.store.get_pairing(job.key_id)
        if subscription is None or subscription.deleted or pairing is None or not pairing.active:
            ok = False
        elif job.kind is JobKind.FIRST_STATE:
            if core.store.package_bounds(job.key_id, job.uid).last == 0:
                status = core.store.get_source(subscription.spec.collection_id)
                if status is None or status.last_success is None:
                    collect(core, subscription.spec)
                info = reports.produce_first_state(core, subscription)
                seq = None if info is None else info.seq
        else:
            built = reports.build_history(core, subscription, parse_since(job.argument))
            if built is None:
                ok = False
            else:
                seq, result = built
    except reports.ReportSkipped as skipped:
        log.info("job %s skipped: %s", job.id, skipped.reason)
        ok = job.kind is JobKind.FIRST_STATE  # the round makes the first state once the collection succeeds
    except Exception as exc:  # recorded, never raised: the worker goes on
        log.warning("job %s failed: %s", job.id, type(exc).__name__)
        ok = False
    core.store.finish_job(job.id, ok=ok, at=core.clock.now(), seq=seq, result=result)


def run_pending(core: Core) -> int:
    """Run every pending job (including those left by a previous process); return how many ran."""
    jobs = core.store.pending_jobs()
    for job in jobs:
        run_job(core, job)
    return len(jobs)
