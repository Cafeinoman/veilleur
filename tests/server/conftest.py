# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from .fakes import World, make_world


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path / "state")
    yield w
    w.app.close()
