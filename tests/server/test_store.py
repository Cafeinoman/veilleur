# SPDX-License-Identifier: EUPL-1.2
"""SQLite store: WAL, numbered migrations, backup before migrating (EF-72), transactions."""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from pathlib import Path

import pytest

from veilleur.adapters.sqlite.store import SqliteStore, migrations
from veilleur.core.domain.model import Pairing

from .fakes import START


def test_new_database_is_migrated_without_backup(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "v.db", backup_dir=tmp_path / "backups")
    try:
        assert store.backup is None and not (tmp_path / "backups").exists()
        assert store._one("PRAGMA journal_mode")[0] == "wal"  # type: ignore[index]
        assert store._one("PRAGMA user_version")[0] == len(migrations())  # type: ignore[index]
    finally:
        store.close()


def test_backup_before_migrating_an_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "v.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE keepsake (x TEXT)")
    old.execute("INSERT INTO keepsake VALUES ('before')")
    old.commit()
    old.close()
    store = SqliteStore(path, backup_dir=tmp_path / "backups", now=START)
    try:
        assert store.backup == tmp_path / "backups" / "veilleur-schema0-20261117T060000Z.db"
        assert store.backup.stat().st_mode & 0o777 == 0o600
        copy = sqlite3.connect(store.backup)
        assert copy.execute("SELECT x FROM keepsake").fetchall() == [("before",)]
        assert copy.execute("PRAGMA user_version").fetchone() == (0,)
        copy.close()
    finally:
        store.close()
    again = SqliteStore(path, backup_dir=tmp_path / "backups")
    assert again.backup is None
    again.close()


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "v.db"
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version = {len(migrations()) + 1}")
    db.close()
    with pytest.raises(RuntimeError, match="newer"):
        SqliteStore(path)


def test_transactions_roll_back_and_nest(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "v.db")
    pairing = Pairing("0" * 16, "desk", bytes(32), START)
    with pytest.raises(ZeroDivisionError), store.transaction():
        with store.transaction():
            store.add_pairing(pairing)
        1 / 0  # noqa: B018
    assert store.list_pairings() == []
    with store.transaction():
        store.add_pairing(pairing)
    assert store.list_pairings() == [pairing]
    store.close()


def test_two_connections_see_each_other(tmp_path: Path) -> None:
    """The service and the round are two processes on the same database (EF-71)."""
    first, second = SqliteStore(tmp_path / "v.db"), SqliteStore(tmp_path / "v.db")
    first.add_pairing(Pairing("1" * 16, "desk", bytes(32), START))
    assert [p.key_id for p in second.list_pairings()] == ["1" * 16]
    first.close()
    second.close()


def test_threads_share_one_connection(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "v.db")

    def add(n: int) -> None:
        with store.transaction():
            store.add_pairing(Pairing(f"{n:016x}", "desk", bytes(32), START))

    threads = [threading.Thread(target=add, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.list_pairings()) == 8
    store.close()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_database_and_wal_files_are_private_whatever_the_umask(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        store = SqliteStore(tmp_path / "v.db")
        with store.transaction():
            pass
        files = [tmp_path / "v.db", tmp_path / "v.db-wal", tmp_path / "v.db-shm"]
        assert all(f.exists() for f in files)
        assert [_mode(f) for f in files] == [0o600] * 3
        store.close()
    finally:
        os.umask(previous)


def test_an_older_readable_database_is_made_private(tmp_path: Path) -> None:
    path = tmp_path / "v.db"
    SqliteStore(path).close()
    path.chmod(0o644)
    SqliteStore(path).close()
    assert _mode(path) == 0o600
