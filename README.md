# simdeck

Run external circuit simulators from Python and get the results as Polars tables.

Planned: Spectre runs from Virtuoso designs or plain netlists and gnucap, with results read
through [polars-psf](https://github.com/henjo/polars-psf) and
[polars-waveform](https://github.com/henjo/polars-waveform). Available now: `simdeck.virtuoso`.

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

BSD-3-Clause. `simdeck.virtuoso` is ported from [pycircuit](https://github.com/henjo/pycircuit).
