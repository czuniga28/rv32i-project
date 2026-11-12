# © 2026 Intel Corporation
#
# This software and the related documents are Intel copyrighted materials, and
# your use of them is governed by the express license under which they were
# provided to you ("License"). Unless the License provides otherwise, you may
# not use, modify, copy, publish, distribute, disclose or transmit this software
# or the related documents without Intel's prior written permission.
#
# This software and the related documents are provided as is, with no express or
# implied warranties, other than those that are expressly stated in the License.

import re

try:
    import simics
except ImportError:
    simics = None


def mem_write8(core, addr, value):
    """Write the byte value (0..255) to address addr of the core's memory."""
    simics.SIM_write_phys_memory(core, addr, value, 1)


def write_word(core, addr, word):
    """Write a 32-bit word in little-endian order to address addr."""
    mem_write8(core, addr + 0, (word >> 0) & 0xFF)
    mem_write8(core, addr + 1, (word >> 8) & 0xFF)
    mem_write8(core, addr + 2, (word >> 16) & 0xFF)
    mem_write8(core, addr + 3, (word >> 24) & 0xFF)


def parse_reg(s):
    """Parse register string 'x0'..'x31' into an integer 0..31."""
    s = s.strip().lower()
    if not s.startswith("x") or not s[1:].isdigit():
        raise ValueError(f"Invalid register name '{s}', expected 'x0'..'x31'")
    reg_num = int(s[1:])
    if not (0 <= reg_num <= 31):
        raise ValueError(f"Register number x{reg_num} out of range 0..31")
    return reg_num


def parse_imm(s):
    """Parse integer immediate supporting decimal, hex, and optional sign."""
    try:
        return int(s.strip(), 0)
    except ValueError:
        raise ValueError(f"Invalid number literal '{s}'")


def parse_offset_base(s):
    """Parse 'offset(rs1)' syntax, e.g. '13(x26)' or '0(x5)'."""
    s = s.strip()
    match = re.match(r"^([+-]?(?:0x[0-9a-fA-F]+|\d+))\s*\(\s*(x\d+)\s*\)$", s)
    if not match:
        raise ValueError(f"Invalid offset(base) syntax '{s}'")
    offset = parse_imm(match.group(1))
    rs1 = parse_reg(match.group(2))
    return offset, rs1


def check_arg_count(op, args, expected):
    """Validate that the argument list has the expected number of operands."""
    if len(args) != expected:
        raise ValueError(
            f"Instruction '{op}' requires {expected} operand(s), but got {len(args)}"
        )


def check_imm_range(imm, min_val, max_val, desc="Immediate"):
    """Validate that an immediate or offset is within [min_val, max_val]."""
    if not (min_val <= imm <= max_val):
        hex_hint = f" (0x{imm:x})" if imm >= 0 else f" (-0x{-imm:x})"
        raise ValueError(
            f"{desc} {imm}{hex_hint} out of allowed range [{min_val}, {max_val}]"
        )


# --- RISC-V 32I instruction encoders ---

def encode_r(funct7, rs2, rs1, funct3, rd, opcode=0x33):
    return (
        ((funct7 & 0x7F) << 25)
        | ((rs2 & 0x1F) << 20)
        | ((rs1 & 0x1F) << 15)
        | ((funct3 & 0x7) << 12)
        | ((rd & 0x1F) << 7)
        | (opcode & 0x7F)
    )


def encode_i(imm, rs1, funct3, rd, opcode=0x13):
    check_imm_range(imm, -2048, 2047, "12-bit signed immediate")
    return (
        ((imm & 0xFFF) << 20)
        | ((rs1 & 0x1F) << 15)
        | ((funct3 & 0x7) << 12)
        | ((rd & 0x1F) << 7)
        | (opcode & 0x7F)
    )


def encode_shift(funct7, shamt, rs1, funct3, rd, opcode=0x13):
    check_imm_range(shamt, 0, 31, "Shift amount")
    return (
        ((funct7 & 0x7F) << 25)
        | ((shamt & 0x1F) << 20)
        | ((rs1 & 0x1F) << 15)
        | ((funct3 & 0x7) << 12)
        | ((rd & 0x1F) << 7)
        | (opcode & 0x7F)
    )


def encode_u(imm, rd, opcode):
    check_imm_range(imm, -524288, 0xFFFFF, "20-bit upper immediate")
    return (
        ((imm & 0xFFFFF) << 12)
        | ((rd & 0x1F) << 7)
        | (opcode & 0x7F)
    )


def encode_b(imm, rs1, rs2, funct3, opcode=0x63):
    if imm % 2 != 0:
        raise ValueError(
            f"Branch offset must be a multiple of 2 (even), got odd offset {imm}"
        )
    check_imm_range(imm, -4096, 4094, "Branch offset")
    imm_12 = (imm >> 12) & 0x1
    imm_10_5 = (imm >> 5) & 0x3F
    imm_4_1 = (imm >> 1) & 0xF
    imm_11 = (imm >> 11) & 0x1
    return (
        (imm_12 << 31)
        | (imm_10_5 << 25)
        | ((rs2 & 0x1F) << 20)
        | ((rs1 & 0x1F) << 15)
        | ((funct3 & 0x7) << 12)
        | (imm_4_1 << 8)
        | (imm_11 << 7)
        | (opcode & 0x7F)
    )


def encode_j(imm, rd, opcode=0x6F):
    if imm % 2 != 0:
        raise ValueError(
            f"Jump offset must be a multiple of 2 (even), got odd offset {imm}"
        )
    check_imm_range(imm, -1048576, 1048574, "Jump offset")
    imm_20 = (imm >> 20) & 0x1
    imm_10_1 = (imm >> 1) & 0x3FF
    imm_11 = (imm >> 11) & 0x1
    imm_19_12 = (imm >> 12) & 0xFF
    return (
        (imm_20 << 31)
        | (imm_10_1 << 21)
        | (imm_11 << 20)
        | (imm_19_12 << 12)
        | ((rd & 0x1F) << 7)
        | (opcode & 0x7F)
    )


# Lookup tables for opcode & function fields
R_INSTRUCTIONS = {
    "add":  (0x00, 0x0),
    "sub":  (0x20, 0x0),
    "sll":  (0x00, 0x1),
    "slt":  (0x00, 0x2),
    "sltu": (0x00, 0x3),
    "xor":  (0x00, 0x4),
    "srl":  (0x00, 0x5),
    "sra":  (0x20, 0x5),
    "or":   (0x00, 0x6),
    "and":  (0x00, 0x7),
}

I_ARITH_INSTRUCTIONS = {
    "addi":  0x0,
    "slti":  0x2,
    "sltiu": 0x3,
    "xori":  0x4,
    "ori":   0x6,
    "andi":  0x7,
}

I_SHIFT_INSTRUCTIONS = {
    "slli": (0x00, 0x1),
    "srli": (0x00, 0x5),
    "srai": (0x20, 0x5),
}

B_INSTRUCTIONS = {
    "beq":  0x0,
    "bne":  0x1,
    "blt":  0x4,
    "bge":  0x5,
    "bltu": 0x6,
    "bgeu": 0x7,
}


def assemble_instruction(line):
    """Assemble a single line of assembly text into a 32-bit integer."""
    parts = line.split(None, 1)
    op = parts[0].lower()
    args_str = parts[1] if len(parts) > 1 else ""
    args = [arg.strip() for arg in args_str.split(",") if arg.strip()]

    if op == "ebreak":
        check_arg_count(op, args, 0)
        return 0x00100073

    elif op == "lui":
        check_arg_count(op, args, 2)
        rd = parse_reg(args[0])
        imm = parse_imm(args[1])
        return encode_u(imm, rd, 0x37)

    elif op == "auipc":
        check_arg_count(op, args, 2)
        rd = parse_reg(args[0])
        imm = parse_imm(args[1])
        return encode_u(imm, rd, 0x17)

    elif op == "jal":
        check_arg_count(op, args, 2)
        rd = parse_reg(args[0])
        offset = parse_imm(args[1])
        return encode_j(offset, rd, 0x6F)

    elif op == "jalr":
        if len(args) == 2:
            rd = parse_reg(args[0])
            offset, rs1 = parse_offset_base(args[1])
        elif len(args) == 3:
            rd = parse_reg(args[0])
            rs1 = parse_reg(args[1])
            offset = parse_imm(args[2])
        else:
            raise ValueError(
                f"Instruction 'jalr' requires 2 operands ('rd, offset(rs1)') "
                f"or 3 operands ('rd, rs1, offset'), but got {len(args)}"
            )
        return encode_i(offset, rs1, 0x0, rd, 0x67)

    elif op in B_INSTRUCTIONS:
        check_arg_count(op, args, 3)
        rs1 = parse_reg(args[0])
        rs2 = parse_reg(args[1])
        offset = parse_imm(args[2])
        return encode_b(offset, rs1, rs2, B_INSTRUCTIONS[op], 0x63)

    elif op in I_ARITH_INSTRUCTIONS:
        check_arg_count(op, args, 3)
        rd = parse_reg(args[0])
        rs1 = parse_reg(args[1])
        imm = parse_imm(args[2])
        return encode_i(imm, rs1, I_ARITH_INSTRUCTIONS[op], rd, 0x13)

    elif op in I_SHIFT_INSTRUCTIONS:
        check_arg_count(op, args, 3)
        rd = parse_reg(args[0])
        rs1 = parse_reg(args[1])
        shamt = parse_imm(args[2])
        funct7, funct3 = I_SHIFT_INSTRUCTIONS[op]
        return encode_shift(funct7, shamt, rs1, funct3, rd, 0x13)

    elif op in R_INSTRUCTIONS:
        check_arg_count(op, args, 3)
        rd = parse_reg(args[0])
        rs1 = parse_reg(args[1])
        rs2 = parse_reg(args[2])
        funct7, funct3 = R_INSTRUCTIONS[op]
        return encode_r(funct7, rs2, rs1, funct3, rd, 0x33)

    else:
        raise ValueError(f"Unknown or unsupported instruction '{op}'")


def load_program(core, path, address):
    """Read the assembly program in the text file path and write the machine
    code of its instructions into memory, the first one at address."""
    cur_addr = address
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.split("#")[0].strip()
            if not line:
                continue

            try:
                word = assemble_instruction(line)
            except Exception as e:
                raise ValueError(
                    f"{path}:{line_num}: error assembling '{line}': {e}"
                )

            write_word(core, cur_addr, word)
            cur_addr += 4
