#!/usr/bin/env python3
"""Genera los resultados esperados (modelo de referencia) de programas .txt.

Cadena independiente del proyecto: LLVM (llvm-mc) ensambla y Unicorn (motor
de QEMU) ejecuta. No usa el txt_loader.py ni los cores del curso.

Para cada programa escribe tests/expected/<nombre>.json con x1..x31, el pc
final (el del ebreak) y la cantidad de steps (instrucciones completadas,
contando el ebreak, igual que Simics).

Uso (con el venv que tiene unicorn):
  tools/.venv/bin/python tools/golden.py tests/programs/*.txt [otros.txt]
  tools/.venv/bin/python tools/golden.py --print programa.txt
"""

import json
import os
import re
import subprocess
import sys
import tempfile

from unicorn import UC_ARCH_RISCV, UC_HOOK_CODE, UC_MODE_RISCV32, Uc
from unicorn import riscv_const as rc

LLVM = os.environ.get("LLVM_BIN", "/opt/homebrew/opt/llvm/bin")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "tests", "expected")
RAM = 0x100000
EBREAK = 0x00100073
MAX_STEPS = 100_000


def assemble(path):
    """.txt del curso -> bytes de código máquina, vía llvm-mc."""
    with open(path) as f:
        src = "\n".join(re.sub(r"#.*", "", line).strip() for line in f)
    with tempfile.TemporaryDirectory() as d:
        s, o, b = (os.path.join(d, n) for n in ("p.s", "p.o", "p.bin"))
        with open(s, "w") as f:
            f.write(src + "\n")
        subprocess.run([f"{LLVM}/llvm-mc", "-triple=riscv32", "-mattr=-c,-relax",
                        "-filetype=obj", s, "-o", o], check=True)
        subprocess.run([f"{LLVM}/llvm-objcopy", "-O", "binary",
                        "--only-section=.text", o, b], check=True)
        with open(b, "rb") as f:
            return f.read()


def run(code):
    mu = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
    mu.mem_map(0, RAM)
    mu.mem_write(0, code)
    st = {"steps": 0, "halt": None}

    def hook(uc, addr, size, _):
        word = int.from_bytes(uc.mem_read(addr, 4), "little")
        if word == EBREAK:
            st["halt"] = addr
            st["steps"] += 1        # Simics cuenta el ebreak como step
            uc.emu_stop()
            return
        st["steps"] += 1
        if st["steps"] > MAX_STEPS:
            uc.emu_stop()

    mu.hook_add(UC_HOOK_CODE, hook)
    mu.emu_start(0, RAM)
    if st["halt"] is None:
        raise RuntimeError(f"no llegó a ebreak en {MAX_STEPS} steps")
    regs = {f"x{i}": mu.reg_read(getattr(rc, f"UC_RISCV_REG_X{i}")) & 0xFFFFFFFF
            for i in range(1, 32)}
    return {"regs": {k: f"0x{v:08x}" for k, v in regs.items()},
            "pc": f"0x{st['halt']:08x}", "steps": st["steps"],
            "instructions": len(code) // 4}


def main():
    args = sys.argv[1:]
    show = "--print" in args
    args = [a for a in args if a != "--print"]
    if not args:
        print(__doc__)
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)
    for path in args:
        name = os.path.splitext(os.path.basename(path))[0]
        res = run(assemble(path))
        res["program"] = os.path.basename(path)
        out = os.path.join(OUT_DIR, name + ".json")
        with open(out, "w") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
        nz = {k: v for k, v in res["regs"].items() if v != "0x00000000"}
        print(f"{name}: pc={res['pc']} steps={res['steps']} -> {os.path.relpath(out)}")
        if show:
            for k, v in nz.items():
                print(f"    {k:>3} = {v}")


if __name__ == "__main__":
    main()
