#!/usr/bin/env python3
"""Prueba txt_loader.load_program() en el Mac, sin Simics.

Simula el módulo `simics` (SIM_write_phys_memory guarda bytes en un dict),
ensambla cada vector conocido y lo compara con su codificación esperada.
Herramienta de verificación: no contiene lógica del ensamblador.

Uso:
  python3 tools/test_loader.py                      # vectores + all-instructions.txt
  python3 tools/test_loader.py programa.txt         # además vuelca ese programa
  LOADER=ruta/txt_loader.py python3 tools/test_loader.py
"""

import importlib.util
import os
import sys
import tempfile
import types

sys.dont_write_bytecode = True  # no dejar __pycache__ dentro del módulo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
LOADER = os.environ.get(
    "LOADER", os.path.join(REPO, "modules", "rv32-atomic", "txt_loader.py"))

# (instrucción, palabra esperada). Calculadas a mano y cruzadas con la
# presentación del curso (bytes de all-instructions.txt en 0x0).
VECTORS = [
    ("lui x1, 0x12345", 0x123450B7),
    ("auipc x2, 0", 0x00000117),
    ("addi x3, x0, 100", 0x06400193),
    ("addi x4, x0, -7", 0xFF900213),
    ("addi x1, x1, -1", 0xFFF08093),
    ("srai x12, x4, 1", 0x40125613),
    ("bne x1, x0, -4", 0xFE009EE3),
    ("jal x5, 12", 0x00C002EF),
    ("jalr x0, 0(x5)", 0x00028067),
    ("ebreak", 0x00100073),
]

# Primeros 16 bytes de all-instructions.txt (diapositiva 19 de la presentación)
ALL_INSTR_HEAD = bytes.fromhex("b7503412 17010000 93014006 130290ff".replace(" ", ""))


class FakeMemory:
    def __init__(self):
        self.bytes = {}

    def write(self, core, addr, value, size):
        if size != 1:
            raise AssertionError(f"se esperaba size=1, llegó {size}")
        if not 0 <= value <= 0xFF:
            raise AssertionError(f"byte fuera de rango en 0x{addr:x}: {value}")
        self.bytes[addr] = value

    def word(self, addr):
        b = [self.bytes.get(addr + i) for i in range(4)]
        if None in b:
            return None
        return b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24


def load_module(mem):
    fake = types.ModuleType("simics")
    fake.SIM_write_phys_memory = mem.write
    sys.modules["simics"] = fake
    spec = importlib.util.spec_from_file_location("txt_loader", LOADER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def assemble_file(path, address=0):
    mem = FakeMemory()
    load_module(mem).load_program(object(), path, address)
    return mem


def assemble_one(line):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(line + "\n")
        path = f.name
    try:
        return assemble_file(path).word(0)
    finally:
        os.unlink(path)


def main():
    print(f"loader: {os.path.relpath(LOADER)}\n")
    fails = 0
    for text, want in VECTORS:
        try:
            got = assemble_one(text)
        except Exception as e:  # noqa: BLE001 - reportar cualquier fallo del loader
            got, err = None, f"{type(e).__name__}: {e}"
        else:
            err = None
        ok = got == want
        fails += not ok
        got_s = "--------" if got is None else f"{got:08x}"
        print(f"{'OK ' if ok else 'BAD'} {text:<22} esperado {want:08x}  obtenido {got_s}"
              + (f"  ({err})" if err else ""))

    allp = os.path.join(REPO, "targets", "rv32i", "programs", "all-instructions.txt")
    try:
        mem = assemble_file(allp)
        head = bytes(mem.bytes.get(i, 0) for i in range(16))
        ok = head == ALL_INSTR_HEAD
        n = len(mem.bytes)
    except Exception as e:  # noqa: BLE001
        ok, head, n = False, b"", 0
        print(f"BAD all-instructions.txt: {type(e).__name__}: {e}")
    fails += not ok
    print(f"\n{'OK ' if ok else 'BAD'} all-instructions.txt primeros 16 bytes: {head.hex(' ')}"
          f"\n    esperado:                            {ALL_INSTR_HEAD.hex(' ')}"
          f"\n    bytes escritos: {n} (esperado 216 = 54 instrucciones)")
    fails += n != 216

    for extra in sys.argv[1:]:
        mem = assemble_file(extra)
        print(f"\n{extra}:")
        for a in range(0, max(mem.bytes, default=-4) + 4, 4):
            w = mem.word(a)
            print(f"  0x{a:04x}: {'(hueco)' if w is None else f'{w:08x}'}")

    print(f"\n{'TODO OK' if fails == 0 else f'{fails} fallo(s)'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
