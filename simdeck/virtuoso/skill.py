"""SKILL values in Python: :class:`Symbol`, :func:`to_skill` (Python -> SKILL code) and
:func:`parse` (SKILL text -> Python), without a running Virtuoso.

    >>> to_skill([1, "a", True, None, Symbol("x")])
    '(list 1 "a" t nil \\'x)'
    >>> parse('(1 2.5 "a" nil (x))')
    [1, 2.5, 'a', nil, [x]]

Ported from pycircuit (``pycircuit.post.cds.skill``) to Python 3, with a hand-written parser
instead of the yapps grammar.
"""

from __future__ import annotations

import re

__all__ = ["Handle", "Symbol", "nil", "parse", "parse_all", "t", "to_skill"]


class Symbol:
    """A SKILL symbol (``nil``, ``t``, ``?name``, ...). ``nil`` is false and ``t`` true."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __bool__(self) -> bool:
        if self.name == "nil":
            return False
        if self.name == "t":
            return True
        raise ValueError(f"cannot convert symbol {self.name} to bool")

    def __eq__(self, other) -> bool:
        return isinstance(other, Symbol) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return self.name

    __str__ = __repr__


class Handle(str):
    """An object Virtuoso prints but cannot read back (``db:0x1234abcd``)."""

    def __repr__(self) -> str:
        return f"Handle({str.__repr__(self)})"


nil = Symbol("nil")
t = Symbol("t")


def _string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def to_skill(x) -> str:
    """SKILL code for a Python value: lists and tuples become ``(list ...)``, ``True``/``False``/
    ``None`` ``t``/``nil``, :class:`Symbol` a quoted symbol. Objects with a ``skill`` attribute
    (e.g. a session's :class:`~simdeck.virtuoso.Remote`) insert that code.

        >>> to_skill((1, 2.5, "a\\"b"))
        '(list 1 2.5 "a\\\\"b")'
    """
    if x is True:
        return "t"
    if x is False or x is None:
        return "nil"
    if isinstance(x, Handle):
        raise TypeError(f"{x} cannot be passed back to SKILL; keep it in Virtuoso (Remote)")
    if isinstance(x, str):
        return _string(x)
    if isinstance(x, Symbol):
        return f"'{x.name}"
    if isinstance(x, (list, tuple)):
        return "(list " + " ".join(to_skill(e) for e in x) + ")" if x else "nil"
    if isinstance(x, (int, float)):
        return repr(x)
    code = getattr(x, "skill", None)
    if isinstance(code, str):
        return code
    raise TypeError(f"cannot convert {type(x).__name__} to SKILL")


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<open>\()|(?P<close>\))
      | (?P<str>"(?:[^"\\]|\\.)*")
      | (?P<handle>[A-Za-z]+:0x[0-9a-fA-F]+)
      | (?P<num>[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?(?![-+*/!@$%^&=.?\w:<>]))
      | (?P<id>'?[-+*/!@$%^&=.?\w:<>|~]+)
    )""",
    re.VERBOSE,
)
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


def _tokens(text: str):
    pos, end = 0, len(text)
    while True:
        while pos < end and text[pos].isspace():
            pos += 1
        if pos >= end:
            return
        m = _TOKEN.match(text, pos)
        if m is None or m.end() == pos:
            raise ValueError(f"cannot parse SKILL at {text[pos:pos + 30]!r}")
        pos = m.end()
        yield m.lastgroup, m.group(m.lastgroup)


def _value(kind: str, tok: str):
    if kind == "str":
        return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), tok[1:-1])
    if kind == "num":
        return float(tok) if any(c in tok for c in ".eE") else int(tok)
    if kind == "handle":
        return Handle(tok)
    return Symbol(tok.lstrip("'"))  # 'x: the quoted symbol x


def parse_all(text: str) -> list:
    """All SKILL values in ``text``, in order."""
    out: list = []
    stack: list[list] = []
    for kind, tok in _tokens(text):
        if kind == "open":
            stack.append([])
            continue
        if kind == "close":
            if not stack:
                raise ValueError("unbalanced ')' in SKILL text")
            value = stack.pop()
        else:
            value = _value(kind, tok)
        (stack[-1] if stack else out).append(value)
    if stack:
        raise ValueError("unbalanced '(' in SKILL text")
    return out


def parse(text: str):
    """The one SKILL value in ``text``: numbers, strings, lists, :class:`Symbol` (``nil``, ``t``,
    names) and :class:`Handle` (database objects)."""
    values = parse_all(text)
    if len(values) != 1:
        raise ValueError(f"expected one SKILL value, got {len(values)}")
    return values[0]
