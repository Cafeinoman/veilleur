# SPDX-License-Identifier: EUPL-1.2
"""Pairings (cahier EF-60 to EF-62): a random secret and `key_id`, a label that is a marker, never a name."""

from __future__ import annotations

import secrets
import unicodedata

from veilleur.core.domain import errors
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import Pairing

from .context import Core

SECRET_BYTES = 32
KEY_ID_BYTES = 8
MAX_LABEL = 64


def check_label(label: str) -> str:
    """A label is 1 to 64 printable characters, without surrounding white space."""
    label = label.strip()
    if not label or len(label) > MAX_LABEL or any(unicodedata.category(c)[0] == "C" for c in label):
        raise VeilleurError(errors.INVALID_LABEL, max=MAX_LABEL)
    return label


def create_pairing(core: Core, label: str) -> Pairing:
    label = check_label(label)
    with core.store.transaction():
        while True:
            key_id = secrets.token_hex(KEY_ID_BYTES)
            if core.store.get_pairing(key_id) is None:
                break
        pairing = Pairing(key_id, label, secrets.token_bytes(SECRET_BYTES), core.clock.now())
        core.store.add_pairing(pairing)
        core.store.add_event(pairing.created_at, "pairing_created", {"key_id": key_id})
    return pairing


def find_pairing(core: Core, reference: str) -> Pairing:
    """A pairing by `key_id`, or by label when no `key_id` matches."""
    pairing = core.store.get_pairing(reference)
    if pairing is not None:
        return pairing
    matches = [p for p in core.store.list_pairings() if p.label == reference.strip()]
    if not matches:
        raise VeilleurError(errors.UNKNOWN_PAIRING, reference=reference)
    if len(matches) > 1:
        raise VeilleurError(errors.AMBIGUOUS_PAIRING, reference=reference)
    return matches[0]


def revoke_pairing(core: Core, reference: str) -> Pairing:
    """Revoke a pairing: its requests get `403` and its subscriptions are no longer served (EF-62)."""
    with core.store.transaction():
        pairing = find_pairing(core, reference)
        if pairing.active:
            now = core.clock.now()
            core.store.revoke_pairing(pairing.key_id, now)
            core.store.add_event(now, "pairing_revoked", {"key_id": pairing.key_id})
        revoked = core.store.get_pairing(pairing.key_id)
    assert revoked is not None
    return revoked
