"""Running SKILL: in a headless Virtuoso this package starts itself, or into a file.

For a Virtuoso someone is already working in, use skillbridge
(https://github.com/unihd-cag/skillbridge). :class:`VirtuosoSession` covers the batch case
skillbridge does not: it starts ``virtuoso -nograph`` and drives its SKILL prompt, so scripts
and CI jobs can netlist and query designs without a GUI. :class:`SkillFile` writes the same calls
as SKILL code instead, as a dry run or to make a script for ``virtuoso -replay``.

    with VirtuosoSession() as s:
        cv = s.dbOpenCellViewByType("mylib", "amp", "schematic")  # a Remote (database object)
        s.call("getq", cv, Symbol("cellName"))                     # 'amp'

Both share the calling convention: ``s.name(*args, key=value)`` and ``s.call("name", ...)`` send
``(name args... ?key value)``; :func:`~simdeck.virtuoso.skill.to_skill` converts the arguments.
"""

from __future__ import annotations

import contextlib
import itertools
import re
import shutil
import sys
from typing import IO

from .skill import Handle, parse, to_skill

__all__ = ["Remote", "SkillError", "SkillFile", "VirtuosoSession", "find_virtuoso"]


class SkillError(RuntimeError):
    """SKILL reported ``*Error*``."""


def _has_handle(v) -> bool:
    return isinstance(v, Handle) or (isinstance(v, list) and any(_has_handle(e) for e in v))


class Remote:
    """A value kept in a Virtuoso variable, because it holds database objects Python cannot
    rebuild. Pass it as an argument to use it in later calls."""

    def __init__(self, session: VirtuosoSession, varname: str, value):
        self.session, self.skill, self.value = session, varname, value

    def __repr__(self) -> str:
        return f"Remote({self.skill}={self.value!r})"


class _Caller:
    def send(self, expr: str):
        raise NotImplementedError

    def call(self, name: str, *args, **optargs):
        """Call the SKILL function ``name``; keyword arguments become ``?key value``."""
        parts = [name, *map(to_skill, args), *(f"?{k} {to_skill(v)}" for k, v in optargs.items())]
        return self.send("(" + " ".join(parts) + ")")

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args, **optargs: self.call(name, *args, **optargs)


class SkillFile(_Caller):
    """Write SKILL calls to a file (or stdout) instead of running them; every call returns ``None``.

        >>> SkillFile(sys.stdout).testfunc(1, "a", c=False)
        (testfunc 1 "a" ?c nil)
    """

    def __init__(self, file: IO[str] = sys.stdout):
        self.file = file

    def send(self, expr: str) -> None:
        self.file.write(expr + "\n")


def find_virtuoso() -> str:
    """Command for a headless Virtuoso (``virtuoso -nograph``, or ``icfb`` on old installs)."""
    exe = shutil.which("virtuoso") or shutil.which("icfb")
    if exe is None:
        raise FileNotFoundError("cannot find virtuoso (or icfb) on PATH")
    return f"{exe} -nograph"


_BEGIN, _END = "<<simdeck", "simdeck>>"
_RESULT = re.compile(rf"(?ms)^{_BEGIN}$(.*?)^{_END}$")  # markers on their own lines, not an echo


class VirtuosoSession(_Caller):
    """A headless Virtuoso, started on construction and driven through its SKILL prompt.

    ``cmd`` defaults to :func:`find_virtuoso`; ``timeout`` (seconds) applies to start-up and to
    each call. Results are parsed into Python values; values holding database objects come back
    as :class:`Remote`. Use as a context manager, or call :meth:`close`.
    """

    prompt = re.compile(r"(?m)^\d*> ")

    def __init__(self, cmd: str | None = None, timeout: float = 60, verbose: bool = False):
        import pexpect

        self.verbose = verbose
        self._count = itertools.count()
        self._proc = pexpect.spawn(cmd or find_virtuoso(), timeout=timeout, encoding="utf-8")
        self._proc.setecho(False)
        self._proc.expect(self.prompt)
        self.startup = self._proc.before

    def send(self, expr: str):
        """Evaluate the SKILL expression ``expr`` and return its value."""
        var = f"simdeck_{next(self._count)}"
        # print the value between markers, so log output from the call does not mix in
        wrapped = f'progn({var}={expr} printf("\\n{_BEGIN}\\n") print({var}) printf("\\n{_END}\\n") t)'
        if self.verbose:
            print(f"> {wrapped}", file=sys.stderr)
        self._proc.sendline(wrapped)
        self._proc.expect(self.prompt)
        out = self._proc.before.replace("\r\n", "\n")
        if self.verbose:
            print(out, file=sys.stderr)
        m = _RESULT.search(out)
        if "*Error*" in out or m is None:
            raise SkillError(out.strip())
        value = parse(m.group(1))
        return Remote(self, var, value) if _has_handle(value) else value

    def close(self) -> None:
        proc, self._proc = getattr(self, "_proc", None), None
        if proc is not None and proc.isalive():
            proc.sendline("exit()")
            proc.expect(__import__("pexpect").EOF)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        with contextlib.suppress(Exception):  # interpreter shutdown
            self.close()
