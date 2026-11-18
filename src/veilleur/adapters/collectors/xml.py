# SPDX-License-Identifier: EUPL-1.2
"""A guarded XML reader for feeds: no document type declaration, hence no entity, internal or external.

Built on expat directly, so that a DTD is refused before anything in it is expanded (billion laughs, external
entities). Element names are in ElementTree's form, `{namespace}local`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from xml.parsers import expat


class XmlRefused(ValueError):
    pass


def _name(raw: str) -> str:
    namespace, separator, local = raw.rpartition("\x01")
    return f"{{{namespace}}}{local}" if separator else raw


def parse(data: bytes) -> ET.Element:
    """The root element of `data`. Raise `XmlRefused` for malformed XML or any DTD."""
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate(namespace_separator="\x01")

    def refuse(*_args: Any) -> None:
        raise XmlRefused("document type declarations are refused")

    def refuse_external(*_args: Any) -> int:
        raise XmlRefused("external entities are refused")

    def start(name: str, attributes: dict[str, str]) -> None:
        builder.start(_name(name), {_name(k): v for k, v in attributes.items()})

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.UnparsedEntityDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse_external
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartElementHandler = start
    parser.EndElementHandler = lambda name: builder.end(_name(name))
    parser.CharacterDataHandler = builder.data
    parser.buffer_text = True
    try:
        parser.Parse(data, True)
        root = builder.close()
    except (expat.ExpatError, AssertionError, RecursionError) as exc:
        raise XmlRefused("malformed XML") from exc
    return root
