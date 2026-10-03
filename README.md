# simdeck

Run external circuit simulators from Python and get the results as Polars tables.

Results are Polars tables and [polars-waveform](https://github.com/henjo/polars-waveform)
waveforms. Available: gnucap (`simdeck.gnucap`) and Virtuoso without a GUI (`simdeck.virtuoso`).
Planned: Spectre runs from Virtuoso designs or plain netlists, read through
[polars-psf](https://github.com/henjo/polars-psf).

## gnucap

```python
from simdeck.gnucap import Gnucap, Netlist, VS, R, C

n = Netlist("rc lowpass")
n["V1"] = VS(1, 0, "dc 1 ac 1")
n["R1"] = R(1, 2, "10k")
n["C1"] = C(2, 0, "1n")

sim = Gnucap(n)                                    # or Gnucap(spice_text)
sim.op().value("2")                                # 1.0
ac = sim.ac(1e3, 1e6, decade=20)
ac.v("2").bandwidth()                              # 15.9 kHz
ac.frame                                           # frequency, v(1), v(2): one column per node
sim.transient(1e-6, 1e-8).v("2").plot()
sim.dc("V1", 0, 2, 0.1)
```

AC voltages are complex. Every analysis runs `gnucap` (from `PATH` or `$GNUCAP`) once, so
results don't depend on earlier calls. Results implement polars-waveform's `ResultSource`, like
pycircuit and polars-psf results.

## Virtuoso without a GUI

For a Virtuoso you are working in, use [skillbridge](https://github.com/unihd-cag/skillbridge).
`simdeck.virtuoso` covers what skillbridge does not: starting a headless Virtuoso for scripts and
CI, writing SKILL scripts, and reading SKILL values from text.

```python
from simdeck.virtuoso import VirtuosoSession, SkillFile, Symbol, parse, to_skill

with VirtuosoSession() as s:                       # starts `virtuoso -nograph`
    cv = s.dbOpenCellViewByType("mylib", "amp", "schematic")
    s.getq(cv, Symbol("cellName"))                 # 'amp'

with open("setup.il", "w") as f:                   # the same calls as a SKILL script
    SkillFile(f).load("netlist.il")

parse('(1 "a" nil (2.5))')                         # [1, 'a', nil, [2.5]]
to_skill(["a", True, None])                        # '(list "a" t nil)'
```

Results come back as Python values (numbers, strings, lists, `Symbol`s); values holding
database objects stay in Virtuoso as a `Remote`, which later calls accept as an argument.

```
pip install "simdeck[virtuoso]"     # the session needs pexpect (Linux/macOS)
```

## License

BSD-3-Clause. `simdeck.virtuoso` and `simdeck.gnucap` are ported from [pycircuit](https://github.com/henjo/pycircuit).
