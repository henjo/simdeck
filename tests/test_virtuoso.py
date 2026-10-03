import io
import sys
from pathlib import Path

import pytest

from simdeck.virtuoso import (
    Handle,
    Remote,
    SkillError,
    SkillFile,
    Symbol,
    VirtuosoSession,
    nil,
    parse,
    parse_all,
    t,
    to_skill,
)


def test_to_skill():
    assert to_skill([1, 2.5, "a\"b\n", True, False, None, Symbol("x"), []]) == '(list 1 2.5 "a\\"b\\n" t nil nil \'x nil)'
    with pytest.raises(TypeError):
        to_skill(object())
    with pytest.raises(TypeError):
        to_skill(Handle("db:0x1"))


def test_parse():
    assert parse('(1 -2 3.5 1e-09 "a\\"b" nil t ?key db:0x1f2e (nested (list)))') == [
        1, -2, 3.5, 1e-9, 'a"b', nil, t, Symbol("?key"), Handle("db:0x1f2e"), [Symbol("nested"), [Symbol("list")]]
    ]
    assert parse("'cellName") == Symbol("cellName") and parse("-") == Symbol("-") and parse("x1") == Symbol("x1")
    assert not nil and t and parse_all("1 2") == [1, 2]
    for bad in ("(1 2", ")", "1 2", ""):
        with pytest.raises(ValueError):
            parse(bad)


def test_round_trip():
    v = [1, 2.5, "s p\"q", [Symbol("a"), []]]
    assert parse(to_skill(v).replace("(list ", "(").replace("'", "")) == [1, 2.5, "s p\"q", [Symbol("a"), nil]]


def test_skill_file():
    f = io.StringIO()
    s = SkillFile(f)
    assert s.testfunc(1, 2, 3, apa=3, b="test", c=False) is None
    s.call("load", "x.il")
    assert f.getvalue() == '(testfunc 1 2 3 ?apa 3 ?b "test" ?c nil)\n(load "x.il")\n'


@pytest.fixture
def session():
    pytest.importorskip("pexpect")
    fake = Path(__file__).with_name("fake_virtuoso.py")
    with VirtuosoSession(f"{sys.executable} -u {fake}", timeout=10) as s:
        yield s


def test_session_values_errors_and_remotes(session):
    assert "virtuoso" in session.startup
    assert session.list(1, "a", [2.5]) == [1, "a", [2.5]]
    assert session.plus(1, 2) == 3
    with pytest.raises(SkillError, match="nosuch"):
        session.nosuch(1)
    cv = session.dbOpenCellViewByType("mylib", "amp", "schematic")
    assert isinstance(cv, Remote) and cv.value == Handle("db:0x1f2e3d")
    assert session.getq(cv, Symbol("cellName")) == "amp"  # the Remote is passed as its variable
