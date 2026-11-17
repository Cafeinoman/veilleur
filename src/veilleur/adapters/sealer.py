# SPDX-License-Identifier: EUPL-1.2
"""Sealing with `veilleur-protocol` (cahier ES-02 to ES-05, §7.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from veilleur.core.domain.model import ItemChange, SourceStatus
from veilleur.core.ports.sealer import PackageSpec, PackageTooLarge, SealError
from veilleur_protocol import (
    Change,
    Item,
    Kind,
    PackageContent,
    ProtocolError,
    Rotation,
    SigningKey,
    encode_items,
    format_time,
    open_subscription,
    seal_package,
)


def _item(change: ItemChange) -> Item:
    return Item(change.key, Change(change.change.value), change.hash, change.fields, change.fetched_at, change.url)


def _time(moment: datetime | None) -> str | None:
    return None if moment is None else format_time(moment)


def source_document(status: SourceStatus) -> dict[str, Any]:
    """An element of the manifest's `sources` (protocol §7.5): a stable code, never internal detail."""
    return {
        "id": status.collection_id,
        "collector": status.collector,
        "ok": status.ok,
        "last_success": _time(status.last_success),
        "error": status.error,
    }


class ProtocolSealer:
    """Implements `veilleur.core.ports.sealer.Sealer` with the server's signing key, and the rotation statement
    to join to packages while it is recent (ES-05)."""

    def __init__(self, signing_key: SigningKey, rotation: Rotation | None = None) -> None:
        self._key = signing_key
        self._rotation = rotation

    @property
    def public_key(self) -> bytes:
        return self._key.public_key

    def seal_package(self, secret: bytes, spec: PackageSpec) -> bytes:
        try:
            items = encode_items(_item(change) for change in spec.items)
            content = PackageContent(
                uid=spec.uid,
                seq=spec.seq,
                kind=Kind(spec.kind.value),
                created_at=spec.created_at,
                period_to=spec.period_to,
                period_from=spec.period_from,
                items=items,
                renderings=dict(spec.renderings),
                sources=[source_document(s) for s in spec.sources],
                rotation=self._rotation,
            )
            return seal_package(secret, self._key, content)
        except ValueError as exc:
            raise PackageTooLarge(str(exc)) from exc

    def open_subscription(self, secret: bytes, uid: str, body: bytes) -> tuple[int, dict[str, Any]]:
        try:
            return open_subscription(secret, uid, body)
        except ProtocolError as exc:
            raise SealError(exc.code) from exc
