# SPDX-License-Identifier: EUPL-1.2
"""Time source, so that the core and its tests never read the system clock directly."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, in UTC, to the second."""
        ...
