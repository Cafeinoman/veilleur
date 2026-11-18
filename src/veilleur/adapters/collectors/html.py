# SPDX-License-Identifier: EUPL-1.2
"""A small HTML tree and a CSS selector subset for the `page` collector, without dependency.

Selectors: type (`div`, `*`), `#id`, `.class`, attributes (`[name]`, `[name=value]`, `~=`, `^=`, `$=`, `*=`, with
or without quotes), the descendant (space) and child (`>`) combinators, and groups (`,`). Anything else, pseudo-
classes included, is refused with `ValueError`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
HIDDEN = frozenset({"script", "style", "template", "noscript", "head", "title"})
BLOCK = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "fieldset", "figcaption",
        "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol",
        "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }
)  # fmt: skip
MAX_DEPTH = 256


@dataclass(eq=False)
class Element:
    tag: str
    attributes: dict[str, str]
    parent: Element | None = None
    children: list[Element | str] = field(default_factory=list)

    def elements(self) -> Iterator[Element]:
        """Descendants in document order (iterative: no recursion limit)."""
        stack: list[Element] = [c for c in reversed(self.children) if isinstance(c, Element)]
        while stack:
            element = stack.pop()
            yield element
            stack.extend(c for c in reversed(element.children) if isinstance(c, Element))

    @property
    def classes(self) -> list[str]:
        return self.attributes.get("class", "").split()


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, {k: v or "" for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(element)
        if tag not in VOID and len(self.stack) < MAX_DEPTH:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(Element(tag, {k: v or "" for k, v in attrs}, self.stack[-1]))

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse(text: str) -> Element:
    builder = _Builder()
    builder.feed(text)
    builder.close()
    return builder.root


def text_of(element: Element) -> str:
    """Visible text of an element: hidden elements left out, blocks separated, white space collapsed."""
    parts: list[str] = []
    stack: list[Element | str] = [element]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            parts.append(node)
            continue
        if node.tag in HIDDEN and node is not element:
            continue
        if node.tag in BLOCK:
            parts.append("\n")
        stack.extend(reversed([*node.children, "\n"] if node.tag in BLOCK else node.children))
    lines = (" ".join(line.split()) for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def title_of(root: Element) -> str:
    for element in root.elements():
        if element.tag == "title":
            return " ".join("".join(c for c in element.children if isinstance(c, str)).split())
    return ""


# --- Selectors ------------------------------------------------------------------------------------------------

_IDENT = r"-?[A-Za-z_][A-Za-z0-9_-]*"
_TOKEN = re.compile(
    rf"""
    (?P<space>\s*>\s*|\s+)
    |(?P<type>{_IDENT}|\*)
    |\#(?P<id>{_IDENT})
    |\.(?P<cls>{_IDENT})
    |\[\s*(?P<attr>{_IDENT})\s*(?:(?P<op>[~^$*]?=)\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>{_IDENT}))\s*)?\]
    """,
    re.VERBOSE,
)


@dataclass
class _Compound:
    tag: str | None = None
    tests: list[tuple[str, str, str | None]] = field(default_factory=list)  # (attribute, operator, value)

    def matches(self, element: Element) -> bool:
        if self.tag is not None and element.tag != self.tag:
            return False
        for name, op, value in self.tests:
            if name == "class" and op == "~=":
                if value not in element.classes:
                    return False
                continue
            actual = element.attributes.get(name)
            if actual is None:
                return False
            if value is None:
                continue
            if not {
                "=": actual == value,
                "~=": value in actual.split(),
                "^=": bool(value) and actual.startswith(value),
                "$=": bool(value) and actual.endswith(value),
                "*=": bool(value) and value in actual,
            }[op]:
                return False
        return True


Complex = list[tuple[str, _Compound]]
"""Compounds from left to right, each with the combinator before it (`""` for the first)."""


def _compile_one(text: str) -> Complex:
    text = text.strip()
    if not text:
        raise ValueError("empty selector")
    steps: Complex = []
    current: _Compound | None = None
    combinator = ""
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise ValueError("unsupported selector")
        position = match.end()
        if match.group("space") is not None:
            if current is None:
                raise ValueError("combinator without a left side")
            steps.append((combinator, current))
            current = None
            combinator = ">" if ">" in match.group("space") else " "
            continue
        if current is None:
            current = _Compound()
        if match.group("type") is not None:
            if current.tag is not None or current.tests:
                raise ValueError("type selector out of place")
            current.tag = None if match.group("type") == "*" else match.group("type").lower()
        elif match.group("id") is not None:
            current.tests.append(("id", "=", match.group("id")))
        elif match.group("cls") is not None:
            current.tests.append(("class", "~=", match.group("cls")))
        else:
            value = next((match.group(g) for g in ("dq", "sq", "bare") if match.group(g) is not None), None)
            current.tests.append((match.group("attr").lower(), match.group("op") or "", value))
    if current is None:
        raise ValueError("selector ends with a combinator")
    steps.append((combinator, current))
    return steps


def compile_selector(text: str) -> list[Complex]:
    if len(text) > 500:
        raise ValueError("selector too long")
    return [_compile_one(part) for part in text.split(",")]


def _matches(element: Element, steps: Complex, memo: dict[tuple[int, int], bool]) -> bool:
    """Whether `element` matches the first `len(steps)` compounds; memoised, so that a long selector on a deep page
    stays linear in their product."""
    key = (id(element), len(steps))
    known = memo.get(key)
    if known is not None:
        return known
    combinator, compound = steps[-1]
    result = compound.matches(element)
    if result and len(steps) > 1:
        rest = steps[:-1]
        parent = element.parent
        if combinator == ">":
            result = parent is not None and parent.tag != "#document" and _matches(parent, rest, memo)
        else:
            result = False
            while parent is not None and parent.tag != "#document":
                if _matches(parent, rest, memo):
                    result = True
                    break
                parent = parent.parent
    memo[key] = result
    return result


def select(root: Element, selector: str) -> list[Element]:
    """Elements matching `selector`, in document order. Raise `ValueError` for an unsupported selector."""
    compiled = compile_selector(selector)
    found = []
    for steps in compiled:
        memo: dict[tuple[int, int], bool] = {}
        found.append({id(e) for e in root.elements() if _matches(e, steps, memo)})
    return [e for e in root.elements() if any(id(e) in ids for ids in found)]
