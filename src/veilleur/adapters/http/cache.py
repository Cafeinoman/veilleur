# SPDX-License-Identifier: EUPL-1.2
"""Cache of conditional requests (cahier EF-06): the last response of an address with an `ETag` or a
`Last-Modified`, so that an unchanged source answers `304 Not Modified` and costs it almost nothing.

The cache lives in its own SQLite file of the state directory; it holds collected content (never a secret) and can
be deleted at any time.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

KEEP = timedelta(days=30)
"""An entry not refreshed for this long is dropped."""


@dataclass(frozen=True)
class CachedResponse:
    url: str
    headers: Mapping[str, str]
    body: bytes = field(repr=False)
    etag: str | None
    last_modified: str | None
    stored_at: datetime


class HttpCache(Protocol):
    def get(self, url: str) -> CachedResponse | None: ...

    def put(self, url: str, response: CachedResponse) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._entries: dict[str, CachedResponse] = {}

    def get(self, url: str) -> CachedResponse | None:
        return self._entries.get(url)

    def put(self, url: str, response: CachedResponse) -> None:
        self._entries[url] = response


class SqliteCache:
    def __init__(self, path: Path, now: datetime) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS response (url TEXT PRIMARY KEY, final_url TEXT NOT NULL, headers TEXT NOT"
            " NULL, body BLOB NOT NULL, etag TEXT, last_modified TEXT, stored_at TEXT NOT NULL) STRICT"
        )
        self._db.execute("DELETE FROM response WHERE stored_at < ?", ((now - KEEP).isoformat(),))
        path.chmod(0o600)

    def get(self, url: str) -> CachedResponse | None:
        with self._lock:
            row = self._db.execute(
                "SELECT final_url, headers, body, etag, last_modified, stored_at FROM response WHERE url = ?", (url,)
            ).fetchone()
        if row is None:
            return None
        return CachedResponse(row[0], json.loads(row[1]), row[2], row[3], row[4], datetime.fromisoformat(row[5]))

    def put(self, url: str, response: CachedResponse) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO response VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    url,
                    response.url,
                    json.dumps(dict(response.headers)),
                    response.body,
                    response.etag,
                    response.last_modified,
                    response.stored_at.isoformat(),
                ),
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()
