# SPDX-License-Identifier: EUPL-1.2
"""Shared values for the protocol tests (no network, no randomness unless a test asks for it)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from veilleur_protocol import Change, Item, Kind, PackageContent, SigningKey, encode_items

SECRET = bytes(range(32))
UID = "00112233445566778899aabbccddeeff"
OTHER_UID = "ffeeddccbbaa99887766554433221100"
KEY_ID = "0123456789abcdef"
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)


def item(key: str, change: Change = Change.NEW, **fields: object) -> Item:
    return Item(key, change, hashlib.sha256(key.encode()).hexdigest(), dict(fields), NOW, f"https://example.org/{key}")


def content(seq: int = 1, kind: Kind = Kind.DELTA, **extra: object) -> PackageContent:
    values: dict[str, object] = {
        "uid": UID,
        "seq": seq,
        "kind": kind,
        "created_at": NOW,
        "period_to": NOW,
        "period_from": None,
        "items": encode_items([item("a", title="A"), item("b", Change.GONE)]),
        "renderings": {"report.md": b"# Report\n", "report.html": b"<p>Report</p>"},
        "sources": [{"id": "rss:example.org", "ok": True}],
    }
    values.update(extra)
    return PackageContent(**values)  # type: ignore[arg-type]


@pytest.fixture
def key() -> SigningKey:
    return SigningKey(hashlib.sha256(b"test key").digest())
