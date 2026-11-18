# SPDX-License-Identifier: EUPL-1.2
"""The example collector plugin (`examples/veilleur-example-collector`) honours the collector contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from veilleur.adapters.plugins import validated
from veilleur.core.domain.errors import CollectorError
from veilleur.core.domain.schema import validate
from veilleur.core.ports.plugins import Plugins

from .http_fakes import FakeWeb, client

sys.path.insert(0, str(Path(__file__).parents[2] / "examples" / "veilleur-example-collector" / "src"))
from veilleur_example_collector import TextLinesCollector


def test_example_collector() -> None:
    collector = TextLinesCollector()
    validated(Plugins({"text_lines": collector}, {}, {}))
    params = {"url": "https://files.example.org/list.txt", "prefix": "- "}
    assert validate(params, collector.schema) is None
    web = FakeWeb()
    web.page("files.example.org", "/list.txt", "title\n- first\n\n- second\n", "text/plain; charset=utf-8")
    result = collector.collect(params, None, client(web))
    assert [i.fields for i in result.items] == [{"line": "- first"}, {"line": "- second"}]
    assert result.complete
    web.page("files.example.org", "/list.txt", b"\xff\xfe", "text/plain")
    with pytest.raises(CollectorError) as caught:
        collector.collect(params, None, client(web))
    assert caught.value.code == "not_utf8"
