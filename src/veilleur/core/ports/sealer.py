# SPDX-License-Identifier: EUPL-1.2
"""Sealing (spec ES-02 to ES-05): the core describes packages, the sealer encrypts and signs them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from veilleur.core.domain.model import ItemChange, Kind, SourceStatus


@dataclass(frozen=True)
class PackageSpec:
    uid: str
    seq: int
    kind: Kind
    created_at: datetime
    period_from: datetime | None
    period_to: datetime
    items: Sequence[ItemChange]
    sources: Sequence[SourceStatus]
    renderings: Mapping[str, bytes] = field(default_factory=dict)


class SealError(Exception):
    """A sealed document was refused; `code` is the protocol's stable code (protocol specification §11)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PackageTooLarge(Exception):
    """A package a reader with the default limits would refuse."""


class Sealer(Protocol):
    @property
    def public_key(self) -> bytes:
        """The server's current Ed25519 public key."""
        ...

    def seal_package(self, secret: bytes, spec: PackageSpec) -> bytes:
        """Build, sign and seal a package; raise `PackageTooLarge` if it cannot be delivered."""
        ...

    def open_subscription(self, secret: bytes, uid: str, body: bytes) -> tuple[int, dict[str, Any]]:
        """Base version and document of a sealed subscription document; raise `SealError` when refused."""
        ...
