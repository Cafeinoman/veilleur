# SPDX-License-Identifier: EUPL-1.2
"""Strict JSON reading (specification §2): RFC 8259 only, unique member names, no NaN or Infinity.

Python's `json` module accepts duplicate members (the last wins) and the non-standard constants, and raises
`ValueError` or `RecursionError` on numbers or nesting it cannot handle. Every such case becomes `InvalidJson`, which
callers turn into the protocol error of what they were reading.
"""

from __future__ import annotations

import json
from typing import Any


class InvalidJson(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document = dict(pairs)
    if len(document) != len(pairs):
        raise InvalidJson("duplicate member name")
    return document


def _constant(name: str) -> Any:
    raise InvalidJson(f"{name} is not JSON")


def loads(data: bytes) -> Any:
    """Parse UTF-8 JSON bytes, or raise `InvalidJson`."""
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    except InvalidJson:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        # JSONDecodeError and the integer string conversion limit are both ValueError.
        raise InvalidJson(str(exc)) from exc
