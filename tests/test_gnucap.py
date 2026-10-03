import math
import shutil

import numpy as np
import polars_waveform as pw
import pytest

from simdeck.gnucap import VS, C, Gnucap, Netlist, R, Result, spice_float

if not shutil.which("gnucap"):
    pytest.skip("gnucap not installed", allow_module_level=True)

DIVIDER = """divider
V1 1 0 1.0
R1 1 2 1k
R2 2 0 3k
"""


def rc():
    n = Netlist("rc lowpass")
    n["V1"] = VS(1, 0, "dc 1 ac 1")
    n["R1"] = R(1, 2, "10k")
    n["C1"] = C(2, 0, "1n")
    return n


def test_netlist_builder():
    n = Netlist("divider")
    n["V1"] = VS(1, 0, 1.0)
    n["R1"] = R(1, 2, "1k")
    n["R2"] = R(2, 0, "3k")
    assert n == Netlist.from_text(DIVIDER)
    with pytest.raises(ValueError):
        n["X1"] = R(1, 2, 3)


def test_op_and_dc():
    sim = Gnucap(DIVIDER)
    op = sim.op()
    assert isinstance(op, Result) and isinstance(op, pw.ResultSource) and op.names == ["1", "2"]
    assert op.value("2") == pytest.approx(0.75) and op.value("1", "2") == pytest.approx(0.25)
    dc = sim.dc("V1", 0, 2, 0.5)
    assert dc.frame.columns == ["V1", "v(1)", "v(2)"]
    np.testing.assert_allclose(dc.v("2").y.to_numpy(), 0.75 * np.arange(0, 2.01, 0.5))


def test_ac_is_complex():
    ac = Gnucap(rc()).ac(1e3, 1e6, decade=50)
    w = ac.v("2")
    assert w.is_complex and w.xname == "frequency" and w.xunit == "Hz" and w.yunit == "V"
    assert w.bandwidth() == pytest.approx(1 / (2 * math.pi * 1e-5), rel=1e-2)
    assert w.value(1e4) == pytest.approx(1 / (1 + 2j * math.pi * 1e4 * 1e-5), rel=1e-3)
    lin = Gnucap(rc()).ac(1e3, 2e3, points=3)
    assert lin.frame["frequency"].to_list() == pytest.approx([1e3, 1.5e3, 2e3])
    with pytest.raises(ValueError):
        Gnucap(rc()).ac(1e3, 2e3)


def test_transient():
    tr = Gnucap(DIVIDER).transient(1.0, 0.2)
    assert tr.frame["time"].to_list() == pytest.approx([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    assert tr.v("2").y.to_list() == pytest.approx([0.75] * 6)


def test_spice_float():
    assert spice_float("16.K") == 16e3 and spice_float("1.5u") == 1.5e-6 and spice_float("-3.") == -3.0
    with pytest.raises(ValueError):
        spice_float("1.5x")
