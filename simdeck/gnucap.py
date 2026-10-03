"""gnucap: run analyses on a netlist and get the results as Polars tables.

    from simdeck.gnucap import Gnucap, Netlist, VS, R, C

    n = Netlist("rc lowpass")
    n["V1"] = VS(1, 0, "dc 1 ac 1")
    n["R1"] = R(1, 2, "10k")
    n["C1"] = C(2, 0, "1n")

    sim = Gnucap(n)
    sim.op().value("2")                          # 1.0
    ac = sim.ac(1e3, 1e6, decade=20)             # a Result (polars_waveform.ResultSource)
    ac.v("2").bandwidth()                        # 15.9 kHz
    ac.frame                                     # frequency, v(1), v(2) (complex: Struct{re, im})
    sim.transient(1e-6, 1e-8).v("2").plot()

Each analysis runs ``gnucap`` once (netlist from a temporary file, commands on stdin), so there is no
session state between calls. The executable is ``$GNUCAP`` or ``gnucap`` on ``PATH``.

Ported from pycircuit (``pycircuit.sim.gnucap``) to Python 3.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
import polars_waveform as pw
from polars_waveform import cx

__all__ = ["IS", "VS", "C", "Gnucap", "GnucapError", "Instance", "L", "Netlist", "R", "Result", "spice_float"]


class GnucapError(RuntimeError):
    """gnucap failed or printed no result."""


# --- netlists ---------------------------------------------------------------------------------
class Instance:
    """A netlist element: positional arguments (nodes, value) and ``key value`` pairs."""

    name_prefix: str | None = None

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs

    def __str__(self) -> str:
        return " ".join([*map(str, self.args), *(f"{k} {v}" for k, v in self.kwargs.items())])


class VS(Instance):
    name_prefix = "V"


class IS(Instance):
    name_prefix = "I"


class R(Instance):
    name_prefix = "R"


class C(Instance):
    name_prefix = "C"


class L(Instance):
    name_prefix = "L"


class Netlist:
    """A SPICE-style netlist: a title line and named elements, or given as text.

        >>> n = Netlist("divider")
        >>> n["V1"] = VS(1, 0, 1.0)
        >>> n["R1"] = R(1, 2, "1k")
        >>> print(n, end="")
        divider
        V1 1 0 1.0
        R1 1 2 1k
    """

    def __init__(self, title: str = "simdeck", text: str | None = None):
        self.title, self.text = title, text
        self.instances: dict[str, Instance] = {}

    @classmethod
    def from_text(cls, text: str) -> Netlist:
        """A netlist from SPICE text; its first line is the title."""
        title, _, body = text.partition("\n")
        return cls(title, body)

    def __setitem__(self, name: str, inst: Instance) -> None:
        if not isinstance(inst, Instance):
            raise TypeError("netlist elements must be Instance objects")
        if inst.name_prefix and not name.upper().startswith(inst.name_prefix):
            raise ValueError(f"{type(inst).__name__} names must start with {inst.name_prefix}")
        self.instances[name] = inst

    def __getitem__(self, name: str) -> Instance:
        return self.instances[name]

    def __str__(self) -> str:
        lines = [self.title]
        if self.text:
            lines.append(self.text.rstrip("\n"))
        lines += [f"{k} {v}" for k, v in self.instances.items()]
        return "\n".join(lines) + "\n"

    def __eq__(self, other) -> bool:
        return str(self) == str(other)


# --- output parsing ---------------------------------------------------------------------------
_SCALE = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "K": 1e3, "k": 1e3, "Meg": 1e6, "MEG": 1e6,
          "G": 1e9, "T": 1e12, "a": 1e-18}  # fmt: skip
_NUMBER = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([A-Za-z]*)$")


def spice_float(text: str) -> float:
    """A number as SPICE and gnucap write it.

        >>> spice_float("1.K"), spice_float("-62.5p"), spice_float("2.2Meg"), spice_float("0.")
        (1000.0, -6.25e-11, 2200000.0, 0.0)
    """
    m = _NUMBER.match(text.strip())
    if m is None:
        raise ValueError(f"not a number: {text!r}")
    value, suffix = m.groups()
    if suffix and suffix not in _SCALE:
        raise ValueError(f"unknown scale suffix in {text!r}")
    return float(value) * _SCALE.get(suffix, 1.0)


def _tables(output: str) -> list[tuple[list[str], list[list[float]]]]:
    """The ``#``-headed tables in gnucap output: (header names, rows)."""
    tables: list[tuple[list[str], list[list[float]]]] = []
    for line in output.splitlines():
        if line.startswith("#"):
            # the first column may be unnamed (op: temperature, dc: the swept source)
            head = line[1:]
            names = head.split()
            if head[:1].isspace():
                names.insert(0, "")
            tables.append((names, []))
        elif tables and line.strip():
            try:
                tables[-1][1].append([spice_float(v) for v in line.split()])
            except ValueError:  # a message after the table
                continue
    return tables


_PROBE = re.compile(r"^v([ri]?)\((.+)\)$")


@dataclass
class Result:
    """One analysis: ``frame`` holds the sweep and one column per node voltage ``v(<node>)``
    (complex for AC). Implements :class:`polars_waveform.ResultSource`."""

    frame: pl.DataFrame
    sweep: str
    sweep_unit: str | None = None
    units: dict[str, str] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        """Node names ``v()`` accepts."""
        return [m.group(2) for c in self.frame.columns if (m := _PROBE.match(c))]

    @property
    def leaves(self) -> pl.DataFrame:
        """One leaf without parameters (one gnucap run)."""
        return pl.DataFrame({"leaf": [0]})

    def scan(self) -> pl.LazyFrame:
        return self.frame.lazy()

    def v(self, plus, minus=None) -> pw.Waveform:
        """Voltage of node ``plus`` (against ``minus``, or ground) over the sweep."""
        w = self._wave(f"v({plus})")
        return w if minus is None else w - self._wave(f"v({minus})")

    def value(self, node, minus=None) -> float | complex:
        """``v(node)`` of a one-point result (``op()``) as a number."""
        if self.frame.height != 1:
            raise ValueError(f"{self.frame.height} points; use v()")
        def one(n):
            if n is None:
                return 0.0
            v = self.frame[f"v({n})"][0] if f"v({n})" in self.frame.columns else None
            if v is None:
                raise KeyError(f"no v({n}) in {self.frame.columns[1:]}")
            return complex(v["re"], v["im"]) if isinstance(v, dict) else v

        return one(node) - one(minus)

    def _wave(self, col: str) -> pw.Waveform:
        if col not in self.frame.columns:
            raise KeyError(f"no {col} in {self.frame.columns[1:]}")
        units = {self.sweep: self.sweep_unit, col: self.units.get(col, "V")}
        return pw.Waveform(self.frame.select(self.sweep, col), col, index=[self.sweep], units=units)

    def __repr__(self) -> str:
        return f"Result({self.sweep}: {self.frame.height} points, nodes {self.names})"


def _result(table, sweep: str, unit: str | None) -> Result:
    names, rows = table
    names = [sweep, *names[1:]]
    df = pl.DataFrame(rows, schema=names, orient="row") if rows else pl.DataFrame(schema=dict.fromkeys(names, pl.Float64))
    re_cols = {m.group(2): c for c in df.columns if (m := _PROBE.match(c)) and m.group(1) == "r"}
    if re_cols:  # ac: vr()/vi() pairs -> complex v()
        df = df.select(sweep, *(cx.complex(pl.col(c), pl.col(f"vi({n})")).alias(f"v({n})") for n, c in re_cols.items()))
    return Result(df, sweep, unit)


# --- running ----------------------------------------------------------------------------------
def _executable(executable: str | None) -> str:
    exe = executable or os.environ.get("GNUCAP") or shutil.which("gnucap")
    if not exe:
        raise FileNotFoundError("cannot find gnucap: put it on PATH or set $GNUCAP")
    return exe


class Gnucap:
    """Analyses of one netlist (a :class:`Netlist` or SPICE text with a title line)."""

    def __init__(self, netlist: Netlist | str, executable: str | None = None, digits: int = 12, timeout: float = 600):
        self.netlist = netlist if isinstance(netlist, Netlist) else Netlist.from_text(netlist)
        self.executable = _executable(executable)
        self.digits, self.timeout = digits, timeout

    def run(self, *commands: str) -> str:
        """Run gnucap commands after loading the netlist; returns the raw output."""
        with tempfile.TemporaryDirectory(prefix="simdeck-") as tmp:
            ckt = Path(tmp) / "netlist.ckt"
            ckt.write_text(str(self.netlist))
            script = "\n".join([f"options numdgt={self.digits}", f"get {ckt}", *commands, "end", ""])
            proc = subprocess.run([self.executable], input=script, capture_output=True, text=True, cwd=tmp,
                                  timeout=self.timeout, check=False)  # fmt: skip
        if proc.returncode != 0:
            raise GnucapError(f"gnucap exited with {proc.returncode}: {proc.stderr.strip() or proc.stdout[-500:]}")
        return proc.stdout

    def _analysis(self, kind: str, probes: str, command: str, sweep: str, unit: str | None) -> Result:
        tables = _tables(self.run(f"print {kind} {probes}", command))
        if not tables:
            raise GnucapError(f"no output from {command!r}")
        return _result(tables[-1], sweep, unit)

    def op(self, temp: float = 27.0) -> Result:
        """Operating point at ``temp`` (C); ``result.value("node")``."""
        return self._analysis("op", "v(nodes)", f"op {temp}", "temp", "C")

    def dc(self, source: str, start: float, stop: float, step: float) -> Result:
        """DC sweep of ``source`` (e.g. ``"V1"``) from ``start`` to ``stop``."""
        return self._analysis("dc", "v(nodes)", f"dc {source} {start} {stop} {step}", source, None)

    def ac(self, start: float, stop: float, *, decade: int | None = None, points: int | None = None) -> Result:
        """Small-signal AC from ``start`` to ``stop`` Hz: ``decade`` points per decade
        (logarithmic) or ``points`` points in all (linear). Node voltages are complex."""
        if (decade is None) == (points is None):
            raise ValueError("give decade= (log sweep) or points= (linear sweep)")
        sweep = f"dec {decade}" if decade is not None else f"{(stop - start) / max(points - 1, 1)}"
        return self._analysis("ac", "vr(nodes) vi(nodes)", f"ac {start} {stop} {sweep}", "frequency", "Hz")

    def transient(self, stop: float, step: float, start: float = 0.0) -> Result:
        """Transient from ``start`` to ``stop`` seconds, printed every ``step``."""
        return self._analysis("tran", "v(nodes)", f"tran {start} {stop} {step}", "time", "s")
