# SPDX-License-Identifier: EUPL-1.2
"""Strict JSON reading (specification §2): RFC 8259 only, unique member names, no NaN or Infinity.

Python's `json` module accepts duplicate members (the last wins), the non-standard constants and numbers that overflow
to infinity, and raises `ValueError` or `RecursionError` on numbers or nesting it cannot handle. Every such case
becomes `InvalidJson`, which callers turn into the protocol error of what they were reading.
"""

from __future__ import annotations

import json
import math
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


def _float(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise InvalidJson(f"{text} cannot be represented")
    return number


def dumps(document: Any, *, sort_keys: bool = True) -> bytes:
    """Compact UTF-8 JSON. Raises `ValueError` on NaN or an infinity, which no reader accepts (§2): a writer must not
    produce what readers refuse, even when a collected value carries one."""
    text = json.dumps(document, sort_keys=sort_keys, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.encode("utf-8")


def loads(data: bytes) -> Any:
    """Parse UTF-8 JSON bytes, or raise `InvalidJson`."""
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant, parse_float=_float)
    except InvalidJson:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        # JSONDecodeError and the integer string conversion limit are both ValueError.
        raise InvalidJson(str(exc)) from exc
