#!/usr/bin/env python3
"""Compara la salida de Simics (pregs + ptime) con un archivo esperado.

Uso:
  tools/sync-and-run.sh prog.txt | python3 tools/compare.py tests/expected/prog.json
  python3 tools/compare.py tests/expected/prog.json salida.txt [--atomic]

--atomic: además exige ciclos == steps (CPI = 1 en el core de un ciclo).
Imprime una línea de resumen (PASS/FAIL) y, si falla, cada diferencia.
Sale con 0 si pasa y con 1 si falla.
"""

import json
import re
import sys


def parse(text):
    regs = {f"x{n}": int(v, 16)
            for n, v in re.findall(r"\bx(\d+)\s*=\s*(0x[0-9a-fA-F]+)", text)}
    m = re.search(r"\bpc\s*=\s*(0x[0-9a-fA-F]+)", text)
    pc = int(m.group(1), 16) if m else None
    m = re.search(r"cosim0\s*│\s*(\d+)│\s*(\d+)│", text)
    steps, cycles = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    return regs, pc, steps, cycles


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    atomic = "--atomic" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(2)
    exp = json.load(open(args[0]))
    text = open(args[1]).read() if len(args) > 1 else sys.stdin.read()
    regs, pc, steps, cycles = parse(text)

    errs = []
    if not regs:
        errs.append("no se encontró la salida de pregs (¿Simics se colgó o falló?)")
    else:
        if regs.get("x0", 0) != 0:
            errs.append(f"x0 = 0x{regs['x0']:08x} (debe ser 0)")
        for r, v in exp["regs"].items():
            want = int(v, 16)
            got = regs.get(r)
            if got != want:
                got_s = "?" if got is None else f"0x{got:08x}"
                errs.append(f"{r}: esperado 0x{want:08x}, obtenido {got_s}")
        want_pc = int(exp["pc"], 16)
        if pc != want_pc:
            errs.append(f"pc: esperado 0x{want_pc:08x}, obtenido "
                        f"{'?' if pc is None else f'0x{pc:08x}'}")
    if steps != exp["steps"]:
        errs.append(f"steps: esperado {exp['steps']}, obtenido {steps}")
    if atomic and steps is not None and cycles != steps:
        errs.append(f"core de un ciclo: ciclos ({cycles}) != steps ({steps})")

    cpi = f"{cycles / steps:.2f}" if steps and cycles is not None else "-"
    name = exp.get("program", args[0])
    status = "PASS" if not errs else "FAIL"
    print(f"{status}  {name:<26} steps={steps} ciclos={cycles} CPI={cpi}")
    for e in errs:
        print(f"      - {e}")
    sys.exit(0 if not errs else 1)


if __name__ == "__main__":
    main()
