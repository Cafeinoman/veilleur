# SPDX-License-Identifier: EUPL-1.2
"""SQLite store (cahier §7.2, EF-72): WAL mode for two processes (service and round), numbered SQL migrations run
at opening after a backup of the database, one connection per process used under a lock."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from veilleur.core.domain.model import (
    Event,
    FilterSpec,
    Frequency,
    Job,
    JobKind,
    JobStatus,
    Kind,
    Origin,
    PackageBounds,
    PackageInfo,
    Pairing,
    ReportedItem,
    SourceStatus,
    StoredItem,
    Subscription,
    SubscriptionSpec,
    canonical_json,
)

_TIME = "%Y-%m-%dT%H:%M:%SZ"
BUSY_TIMEOUT_MS = 30_000


def _t(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).strftime(_TIME)


def _d(text: str | None) -> datetime | None:
    return None if text is None else datetime.strptime(text, _TIME).replace(tzinfo=UTC)


def _dd(text: str) -> datetime:
    return datetime.strptime(text, _TIME).replace(tzinfo=UTC)


def _json(value: Any) -> str:
    return canonical_json(value).decode("utf-8")


def migrations() -> list[tuple[int, str]]:
    """Numbered migrations shipped with the package: `NNNN_name.sql`."""
    found = []
    for entry in resources.files(__package__).joinpath("migrations").iterdir():
        if entry.name.endswith(".sql"):
            found.append((int(entry.name.split("_", 1)[0]), entry.read_text(encoding="utf-8")))
    found.sort()
    if [n for n, _ in found] != list(range(1, len(found) + 1)):
        raise RuntimeError("migrations are numbered from 1 without gaps")
    return found


def _spec_to_json(spec: SubscriptionSpec) -> str:
    return _json(
        {
            "collector": spec.collector,
            "params": spec.params,
            "filters": [{"name": f.name, "params": f.params} for f in spec.filters],
            "frequency": spec.frequency.value,
            "language": spec.language,
            "renderings": list(spec.renderings),
        }
    )


def _spec_from_json(text: str) -> SubscriptionSpec:
    data = json.loads(text)
    return SubscriptionSpec(
        collector=data["collector"],
        params=data["params"],
        filters=tuple(FilterSpec(f["name"], f["params"]) for f in data["filters"]),
        frequency=Frequency(data["frequency"]),
        language=data["language"],
        renderings=tuple(data["renderings"]),
    )


class SqliteStore:
    """Implements `veilleur.core.ports.store.Store`."""

    def __init__(self, path: Path | str, *, backup_dir: Path | None = None, now: datetime | None = None) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._depth = 0
        existed = self.path != ":memory:" and Path(self.path).exists() and Path(self.path).stat().st_size > 0
        self._db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self._db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        self._db.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self.backup: Path | None = None
        self._migrate(existed, backup_dir, now or datetime.now(UTC))

    # --- Opening --------------------------------------------------------------------------------------------

    def _migrate(self, existed: bool, backup_dir: Path | None, now: datetime) -> None:
        available = migrations()
        version = self._version()
        if version > len(available):
            raise RuntimeError(f"database schema {version} is newer than this version of Veilleur")
        if version == len(available):
            return
        if existed:
            # Before the write transaction: a backup is a consistent read of its own, and cannot run inside it.
            self.backup = self._backup(backup_dir or Path(self.path).parent, version, now)
        with self.transaction():
            for number, script in available[self._version() :]:  # another process may have migrated meanwhile
                for statement in _statements(script):
                    self._db.execute(statement)
                self._db.execute(f"PRAGMA user_version = {number}")

    def _version(self) -> int:
        with self._lock:
            version: int = self._db.execute("PRAGMA user_version").fetchone()[0]
            return version

    def _backup(self, directory: Path, version: int, now: datetime) -> Path:
        """Copy the database before migrating it (EF-72), with SQLite's online backup (a consistent copy)."""
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = directory / f"veilleur-schema{version}-{now.strftime('%Y%m%dT%H%M%SZ')}.db"
        copy = sqlite3.connect(target)
        try:
            self._db.backup(copy)
        finally:
            copy.close()
        target.chmod(0o600)
        return target

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            if self._depth == 0:
                self._db.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self._db.execute("ROLLBACK")
                raise
            self._depth -= 1
            if self._depth == 0:
                self._db.execute("COMMIT")

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._db.execute(sql, params)
            cursor.row_factory = sqlite3.Row
            return cursor.fetchall()

    def _one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def _run(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            return self._db.execute(sql, params).rowcount

    def _many(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self.transaction():
            self._db.executemany(sql, rows)

    # --- Pairings and grants ----------------------------------------------------------------------------------

    @staticmethod
    def _pairing(row: sqlite3.Row) -> Pairing:
        return Pairing(
            row["key_id"], row["label"], row["secret"], _dd(row["created_at"]), _d(row["revoked_at"]), row["topic"]
        )

    def add_pairing(self, pairing: Pairing) -> None:
        self._run(
            "INSERT INTO pairing (key_id, label, secret, created_at, revoked_at, topic) VALUES (?, ?, ?, ?, ?, ?)",
            (
                pairing.key_id,
                pairing.label,
                pairing.secret,
                _t(pairing.created_at),
                _t(pairing.revoked_at),
                pairing.topic,
            ),
        )

    def get_pairing(self, key_id: str) -> Pairing | None:
        row = self._one("SELECT * FROM pairing WHERE key_id = ?", (key_id,))
        return None if row is None else self._pairing(row)

    def list_pairings(self) -> list[Pairing]:
        return [self._pairing(r) for r in self._all("SELECT * FROM pairing ORDER BY created_at, key_id")]

    def revoke_pairing(self, key_id: str, at: datetime) -> None:
        self._run("UPDATE pairing SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL", (_t(at), key_id))

    def set_grant(self, key_id: str, collector: str, allowed: bool | None) -> None:
        if allowed is None:
            self._run("DELETE FROM collector_grant WHERE key_id = ? AND collector = ?", (key_id, collector))
        else:
            self._run(
                "INSERT OR REPLACE INTO collector_grant (key_id, collector, allowed) VALUES (?, ?, ?)",
                (key_id, collector, int(allowed)),
            )

    def grants(self, key_id: str) -> dict[str, bool]:
        rows = self._all("SELECT collector, allowed FROM collector_grant WHERE key_id = ?", (key_id,))
        return {r["collector"]: bool(r["allowed"]) for r in rows}

    # --- Subscriptions ----------------------------------------------------------------------------------------

    @staticmethod
    def _subscription(row: sqlite3.Row) -> Subscription:
        return Subscription(
            key_id=row["key_id"],
            uid=row["uid"],
            spec=_spec_from_json(row["spec"]),
            version=row["version"],
            origin=Origin(row["origin"]),
            created_at=_dd(row["created_at"]),
            updated_at=_dd(row["updated_at"]),
            team_name=row["team_name"],
            deleted=bool(row["deleted"]),
        )

    def get_subscription(self, key_id: str, uid: str) -> Subscription | None:
        row = self._one("SELECT * FROM subscription WHERE key_id = ? AND uid = ?", (key_id, uid))
        return None if row is None else self._subscription(row)

    def save_subscription(self, s: Subscription) -> None:
        self._run(
            "INSERT OR REPLACE INTO subscription (key_id, uid, spec, collection, version, origin, team_name, deleted,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s.key_id,
                s.uid,
                _spec_to_json(s.spec),
                s.spec.collection_id,
                s.version,
                s.origin.value,
                s.team_name,
                int(s.deleted),
                _t(s.created_at),
                _t(s.updated_at),
            ),
        )

    def list_subscriptions(self, *, include_deleted: bool = False) -> list[Subscription]:
        where = "" if include_deleted else " WHERE deleted = 0"
        return [self._subscription(r) for r in self._all(f"SELECT * FROM subscription{where} ORDER BY created_at, uid")]

    # --- Collections ------------------------------------------------------------------------------------------

    @staticmethod
    def _item(row: sqlite3.Row) -> StoredItem:
        return StoredItem(
            row["key"],
            row["hash"],
            json.loads(row["fields"]),
            row["url"],
            _dd(row["fetched_at"]),
            _dd(row["first_seen"]),
            _dd(row["last_seen"]),
            _d(row["gone_at"]),
        )

    def current_items(self, collection_id: str) -> dict[str, StoredItem]:
        rows = self._all("SELECT * FROM item WHERE collection = ? AND gone_at IS NULL", (collection_id,))
        return {r["key"]: self._item(r) for r in rows}

    def save_items(self, collection_id: str, items: Iterable[StoredItem]) -> None:
        self._many(
            "INSERT OR REPLACE INTO item (collection, key, hash, fields, url, fetched_at, first_seen, last_seen,"
            " gone_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    collection_id,
                    i.key,
                    i.hash,
                    _json(i.fields),
                    i.url,
                    _t(i.fetched_at),
                    _t(i.first_seen),
                    _t(i.last_seen),
                    _t(i.gone_at),
                )
                for i in items
            ),
        )

    @staticmethod
    def _source(row: sqlite3.Row) -> SourceStatus:
        return SourceStatus(
            row["id"],
            row["collector"],
            _d(row["last_attempt"]),
            _d(row["last_success"]),
            row["error"],
            _d(row["failing_since"]),
        )

    def get_source(self, collection_id: str) -> SourceStatus | None:
        row = self._one("SELECT * FROM source_status WHERE id = ?", (collection_id,))
        return None if row is None else self._source(row)

    def save_source(self, status: SourceStatus) -> None:
        self._run(
            "INSERT OR REPLACE INTO source_status (id, collector, last_attempt, last_success, error, failing_since)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                status.collection_id,
                status.collector,
                _t(status.last_attempt),
                _t(status.last_success),
                status.error,
                _t(status.failing_since),
            ),
        )

    def list_sources(self) -> list[SourceStatus]:
        return [self._source(r) for r in self._all("SELECT * FROM source_status ORDER BY collector, id")]

    # --- Reported items ---------------------------------------------------------------------------------------

    def reported_items(self, key_id: str, uid: str) -> dict[str, ReportedItem]:
        rows = self._all("SELECT * FROM reported WHERE key_id = ? AND uid = ?", (key_id, uid))
        return {
            r["key"]: ReportedItem(
                r["key"],
                r["hash"],
                json.loads(r["fields"]),
                r["url"],
                _dd(r["fetched_at"]),
                _dd(r["first_reported"]),
                _dd(r["last_changed"]),
                _d(r["gone_at"]),
            )
            for r in rows
        }

    def save_reported(self, key_id: str, uid: str, items: Iterable[ReportedItem]) -> None:
        self._many(
            "INSERT OR REPLACE INTO reported (key_id, uid, key, hash, fields, url, fetched_at, first_reported,"
            " last_changed, gone_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    key_id,
                    uid,
                    i.key,
                    i.hash,
                    _json(i.fields),
                    i.url,
                    _t(i.fetched_at),
                    _t(i.first_reported),
                    _t(i.last_changed),
                    _t(i.gone_at),
                )
                for i in items
            ),
        )

    # --- Packages ---------------------------------------------------------------------------------------------

    @staticmethod
    def _package(row: sqlite3.Row) -> PackageInfo:
        return PackageInfo(
            row["seq"], Kind(row["kind"]), row["size"], row["sha256"], _dd(row["created_at"]), _dd(row["period_to"])
        )

    def package_bounds(self, key_id: str, uid: str) -> PackageBounds:
        row = self._one(
            "SELECT MAX(seq) AS last, MIN(CASE WHEN data IS NOT NULL THEN seq END) AS oldest,"
            " MAX(CASE WHEN data IS NULL THEN seq END) AS purged FROM package WHERE key_id = ? AND uid = ?",
            (key_id, uid),
        )
        assert row is not None
        return PackageBounds(row["last"] or 0, row["oldest"], row["purged"] or 0)

    def add_package(self, key_id: str, uid: str, info: PackageInfo, data: bytes) -> None:
        self._run(
            "INSERT INTO package (key_id, uid, seq, kind, size, sha256, created_at, period_to, data)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key_id,
                uid,
                info.seq,
                info.kind.value,
                info.size,
                info.sha256,
                _t(info.created_at),
                _t(info.period_to),
                data,
            ),
        )

    def list_packages(self, key_id: str, uid: str, after: int) -> list[PackageInfo]:
        rows = self._all(
            "SELECT seq, kind, size, sha256, created_at, period_to FROM package"
            " WHERE key_id = ? AND uid = ? AND seq > ? AND data IS NOT NULL ORDER BY seq",
            (key_id, uid, after),
        )
        return [self._package(r) for r in rows]

    def last_package(self, key_id: str, uid: str) -> PackageInfo | None:
        row = self._one(
            "SELECT seq, kind, size, sha256, created_at, period_to FROM package WHERE key_id = ? AND uid = ?"
            " ORDER BY seq DESC LIMIT 1",
            (key_id, uid),
        )
        return None if row is None else self._package(row)

    def get_package(self, key_id: str, uid: str, seq: int) -> bytes | None:
        row = self._one("SELECT data FROM package WHERE key_id = ? AND uid = ? AND seq = ?", (key_id, uid, seq))
        return None if row is None else row["data"]

    # --- Jobs -------------------------------------------------------------------------------------------------

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            row["id"],
            JobKind(row["kind"]),
            row["key_id"],
            row["uid"],
            row["argument"],
            JobStatus(row["status"]),
            _dd(row["created_at"]),
            _d(row["finished_at"]),
            row["seq"],
            row["result"],
        )

    def add_job(self, kind: JobKind, key_id: str, uid: str, argument: str, at: datetime) -> Job:
        with self.transaction():
            self._run(
                "INSERT INTO job (kind, key_id, uid, argument, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (kind.value, key_id, uid, argument, JobStatus.PENDING.value, _t(at)),
            )
            row = self._one("SELECT * FROM job WHERE id = last_insert_rowid()")
        assert row is not None
        return self._job(row)

    def find_job(self, kind: JobKind, key_id: str, uid: str, argument: str) -> Job | None:
        row = self._one(
            "SELECT * FROM job WHERE kind = ? AND key_id = ? AND uid = ? AND argument = ? ORDER BY id DESC LIMIT 1",
            (kind.value, key_id, uid, argument),
        )
        return None if row is None else self._job(row)

    def pending_jobs(self) -> list[Job]:
        rows = self._all("SELECT * FROM job WHERE status = ? ORDER BY id", (JobStatus.PENDING.value,))
        return [self._job(r) for r in rows]

    def finish_job(self, job_id: int, *, ok: bool, at: datetime, seq: int | None, result: bytes | None) -> None:
        status = JobStatus.DONE if ok else JobStatus.FAILED
        self._run(
            "UPDATE job SET status = ?, finished_at = ?, seq = ?, result = ? WHERE id = ?",
            (status.value, _t(at), seq, result, job_id),
        )

    # --- Retention --------------------------------------------------------------------------------------------

    def purge(self, before: datetime, jobs_before: datetime) -> Mapping[str, int]:
        limit, jobs_limit = _t(before), _t(jobs_before)
        with self.transaction():
            return {
                "packages": self._run(
                    "UPDATE package SET data = NULL WHERE created_at < ? AND data IS NOT NULL", (limit,)
                ),
                "items": self._run("DELETE FROM item WHERE gone_at < ?", (limit,)),
                "reported": self._run("DELETE FROM reported WHERE gone_at < ?", (limit,)),
                "jobs": self._run("DELETE FROM job WHERE status != 'pending' AND finished_at < ?", (jobs_limit,)),
                "events": self._run("DELETE FROM event WHERE at < ?", (limit,)),
            }

    # --- Administration log -----------------------------------------------------------------------------------

    def add_event(self, at: datetime, code: str, params: Mapping[str, Any]) -> None:
        self._run("INSERT INTO event (at, code, params) VALUES (?, ?, ?)", (_t(at), code, _json(dict(params))))

    def events(self, limit: int) -> Sequence[Event]:
        rows = self._all("SELECT * FROM event ORDER BY id DESC LIMIT ?", (limit,))
        return [Event(_dd(r["at"]), r["code"], json.loads(r["params"])) for r in reversed(rows)]


def _statements(script: str) -> Iterator[str]:
    """Split a migration into statements (`sqlite3.Connection.executescript` would commit the transaction)."""
    buffer = ""
    for line in script.splitlines(keepends=True):
        if line.lstrip().startswith("--") and not buffer.strip():
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer.strip()
            buffer = ""
    if buffer.strip():
        raise RuntimeError("incomplete statement at the end of a migration")
