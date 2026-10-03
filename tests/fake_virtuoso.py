"""A stand-in for ``virtuoso -nograph``: a SKILL-like prompt that understands the calls the
tests make. It echoes input and logs noise, as the real one may."""

import re
import sys

from simdeck.virtuoso import Handle, Symbol, parse

CALL = re.compile(r'^progn\((\w+)=(.*) printf\("\\n<<simdeck\\n"\) print\(\1\) printf\("\\nsimdeck>>\\n"\) t\)$')
env = {}
cells = {"db:0x1f2e3d": "amp"}


def ev(x):
    if isinstance(x, Symbol):
        return env.get(x.name, x)
    if not isinstance(x, list):
        return x
    fn, *args = x
    args = [ev(a) for a in args]
    if fn.name == "list":
        return args
    if fn.name == "plus":
        return sum(args)
    if fn.name == "dbOpenCellViewByType":
        return Handle("db:0x1f2e3d")
    if fn.name == "getq":
        return cells[args[0]]
    raise NameError(fn.name)


def show(v):
    if isinstance(v, list):
        return "(" + " ".join(map(show, v)) + ")" if v else "nil"
    if isinstance(v, (Handle, Symbol)):
        return str(v)
    if isinstance(v, str):
        return '"' + v + '"'
    return repr(v)


def main():
    print("Loading something.cxt\n@(#)$CDS: virtuoso version 6.1")
    while True:
        sys.stdout.write("1> ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line or line.strip() == "exit()":
            break
        print(line.rstrip())  # echo
        m = CALL.match(line.strip())
        try:
            var, expr = m.groups()
            print("INFO (foo): log output (with parentheses")
            env[var] = ev(parse(expr))
            print("\n<<simdeck\n" + show(env[var]) + "\nsimdeck>>\nt")
        except Exception as e:  # noqa: BLE001 - a REPL reports every error
            print(f"*Error* {e}")


if __name__ == "__main__":
    main()
