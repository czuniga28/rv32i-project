/*
  © 2026 Intel Corporation

  This software and the related documents are Intel copyrighted materials, and
  your use of them is governed by the express license under which they were
  provided to you ("License"). Unless the License provides otherwise, you may
  not use, modify, copy, publish, distribute, disclose or transmit this software
  or the related documents without Intel's prior written permission.

  This software and the related documents are provided as is, with no express or
  implied warranties, other than those that are expressly stated in the License.
*/

#include <simics/util/strbuf.h>
#include "cosim.h"
#include "rv32-core.h"
#include "rv32-helpers.h"

/* --- Funciones auxiliares para decodificar inmediatos --- */

static inline int32
decode_i_imm(uint32 instr)
{
        /* Inmediato de 12 bits con extensión de signo */
        return ((int32)instr) >> 20;
}

static inline uint32
decode_u_imm(uint32 instr)
{
        /* Inmediato superior de 20 bits (bits 31:12) */
        return instr & 0xfffff000;
}

static inline int32
decode_b_imm(uint32 instr)
{
        /* Inmediato de branch (13 bits con signo, múltiplo de 2) */
        int32 sign = (instr & 0x80000000) ? -4096 : 0;
        return sign
               | (int32)((instr & 0x00000080) << 4)   /* bit 7  -> bit 11 */
               | (int32)((instr & 0x7e000000) >> 20)  /* bits 30:25 -> bits 10:5 */
               | (int32)((instr & 0x00000f00) >> 7);  /* bits 11:8  -> bits 4:1 */
}

static inline int32
decode_j_imm(uint32 instr)
{
        /* Inmediato de jal (21 bits con signo, múltiplo de 2) */
        int32 sign = (instr & 0x80000000) ? -1048576 : 0;
        return sign
               | (int32)(instr & 0x000ff000)           /* bits 19:12 */
               | (int32)((instr & 0x00100000) >> 9)   /* bit 20     -> bit 11 */
               | (int32)((instr & 0x7fe00000) >> 20); /* bits 30:21 -> bits 10:1 */
}

/*
 * execute(): se llama una vez por ciclo del reloj.
 * Núcleo atómico de un ciclo (RV32I): busca, decodifica, ejecuta y completa
 * cada instrucción en el mismo ciclo.
 */
void
execute(rv32_t *cpu)
{
        uint32 pc = cpu->pc;

        /* 1. Fetch con mem_read8 (cuatro bytes, en little-endian) */
        uint32 b0 = mem_read8(cpu, pc + 0);
        uint32 b1 = mem_read8(cpu, pc + 1);
        uint32 b2 = mem_read8(cpu, pc + 2);
        uint32 b3 = mem_read8(cpu, pc + 3);
        uint32 instr = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24);

        /* 2. Decodificar campos de la instrucción */
        uint32 opcode = instr & 0x7f;
        uint32 rd     = (instr >> 7) & 0x1f;
        uint32 funct3 = (instr >> 12) & 0x7;
        uint32 rs1    = (instr >> 15) & 0x1f;
        uint32 rs2    = (instr >> 20) & 0x1f;
        uint32 funct7 = (instr >> 25) & 0x7f;

        uint32 next_pc = pc + 4;
        bool is_illegal = false;

        /* 3 & 4. Ejecutar operación y escribir resultado con reg_write_x */
        switch (opcode) {
        case 0x37: /* lui rd, imm */
                reg_write_x(cpu, rd, decode_u_imm(instr));
                break;

        case 0x17: /* auipc rd, imm */
                reg_write_x(cpu, rd, pc + decode_u_imm(instr));
                break;

        case 0x6f: /* jal rd, offset */
                reg_write_x(cpu, rd, pc + 4);
                next_pc = pc + decode_j_imm(instr);
                break;

        case 0x67: /* jalr rd, offset(rs1) */
                if (funct3 == 0) {
                        uint32 base = reg_read_x(cpu, rs1);
                        int32 imm = decode_i_imm(instr);
                        reg_write_x(cpu, rd, pc + 4);
                        next_pc = (base + imm) & ~1U;
                } else {
                        is_illegal = true;
                }
                break;

        case 0x63: { /* branches */
                uint32 r1 = reg_read_x(cpu, rs1);
                uint32 r2 = reg_read_x(cpu, rs2);
                bool take_branch = false;

                switch (funct3) {
                case 0: /* beq */  take_branch = (r1 == r2); break;
                case 1: /* bne */  take_branch = (r1 != r2); break;
                case 4: /* blt */  take_branch = ((int32)r1 < (int32)r2); break;
                case 5: /* bge */  take_branch = ((int32)r1 >= (int32)r2); break;
                case 6: /* bltu */ take_branch = (r1 < r2); break;
                case 7: /* bgeu */ take_branch = (r1 >= r2); break;
                default: is_illegal = true; break;
                }

                if (!is_illegal && take_branch) {
                        next_pc = pc + decode_b_imm(instr);
                }
                break;
        }

        case 0x13: { /* registro-inmediato aritmético y desplazamientos */
                uint32 r1 = reg_read_x(cpu, rs1);
                int32 imm = decode_i_imm(instr);
                uint32 shamt = (instr >> 20) & 0x1f;

                switch (funct3) {
                case 0: /* addi */
                        reg_write_x(cpu, rd, r1 + imm);
                        break;
                case 2: /* slti */
                        reg_write_x(cpu, rd, ((int32)r1 < imm) ? 1 : 0);
                        break;
                case 3: /* sltiu */
                        reg_write_x(cpu, rd, (r1 < (uint32)imm) ? 1 : 0);
                        break;
                case 4: /* xori */
                        reg_write_x(cpu, rd, r1 ^ (uint32)imm);
                        break;
                case 6: /* ori */
                        reg_write_x(cpu, rd, r1 | (uint32)imm);
                        break;
                case 7: /* andi */
                        reg_write_x(cpu, rd, r1 & (uint32)imm);
                        break;
                case 1: /* slli */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, r1 << shamt);
                        } else {
                                is_illegal = true;
                        }
                        break;
                case 5: /* srli, srai */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, r1 >> shamt);
                        } else if (funct7 == 0x20) {
                                reg_write_x(cpu, rd, (uint32)(((int32)r1) >> shamt));
                        } else {
                                is_illegal = true;
                        }
                        break;
                default:
                        is_illegal = true;
                        break;
                }
                break;
        }

        case 0x33: { /* registro-registro */
                uint32 r1 = reg_read_x(cpu, rs1);
                uint32 r2 = reg_read_x(cpu, rs2);
                uint32 shamt = r2 & 0x1f;

                switch (funct3) {
                case 0: /* add, sub */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, r1 + r2);
                        } else if (funct7 == 0x20) {
                                reg_write_x(cpu, rd, r1 - r2);
                        } else {
                                is_illegal = true;
                        }
                        break;
                case 1: /* sll */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, r1 << shamt);
                        } else {
                                is_illegal = true;
                        }
                        break;
                case 2: /* slt */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, ((int32)r1 < (int32)r2) ? 1 : 0);
                        } else {
                                is_illegal = true;
                        }
                        break;
                case 3: /* sltu */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, (r1 < r2) ? 1 : 0);
                        } else {
                                is_illegal = true;
                        }
                        break;
                case 4: /* xor */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, r1 ^ r2);
                        } else {
                                is_illegal = true;
                        }
                        break;
                case 5: /* srl, sra */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, r1 >> shamt);
                        } else if (funct7 == 0x20) {
                                reg_write_x(cpu, rd, (uint32)(((int32)r1) >> shamt));
                        } else {
                                is_illegal = true;
                        }
                        break;
                case 6: /* or */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, r1 | r2);
                        } else {
                                is_illegal = true;
                        }
                        break;
                case 7: /* and */
                        if (funct7 == 0x00) {
                                reg_write_x(cpu, rd, r1 & r2);
                        } else {
                                is_illegal = true;
                        }
                        break;
                default:
                        is_illegal = true;
                        break;
                }
                break;
        }

        case 0x73: /* system / ebreak */
                if (instr == 0x00100073) {
                        /* ebreak: cuenta el step pero no cambia el pc */
                        increment_step(cpu);
                        increment_cycle(cpu);
                        ebreak(cpu);
                        return;
                } else {
                        is_illegal = true;
                }
                break;

        default:
                is_illegal = true;
                break;
        }

        if (is_illegal) {
                /* Instrucción ilegal: no cuenta step, el pc no cambia */
                increment_cycle(cpu);
                illegal_instruction(cpu, cpu->pc, instr);
                return;
        }

        /* 5. Actualizar el pc */
        cpu->pc = next_pc;

        /* 6. Llamar a increment_cycle() y increment_step() */
        increment_step(cpu);
        increment_cycle(cpu);
}

/*
 * Desensamblador para la CLI de Simics (ej. "disassemble 0x0 10").
 * Convierte una palabra de 32 bits a la sintaxis ensamblador RV32I.
 */
char *
rv32_disassemble(uint32 instr)
{
        strbuf_t b = SB_INIT;

        uint32 opcode = instr & 0x7f;
        uint32 rd     = (instr >> 7) & 0x1f;
        uint32 funct3 = (instr >> 12) & 0x7;
        uint32 rs1    = (instr >> 15) & 0x1f;
        uint32 rs2    = (instr >> 20) & 0x1f;
        uint32 funct7 = (instr >> 25) & 0x7f;

        if (instr == 0x00100073) {
                sb_addfmt(&b, "ebreak");
                return sb_detach(&b);
        }

        switch (opcode) {
        case 0x37:
                sb_addfmt(&b, "lui x%u, 0x%x", rd, decode_u_imm(instr) >> 12);
                return sb_detach(&b);

        case 0x17:
                sb_addfmt(&b, "auipc x%u, 0x%x", rd, decode_u_imm(instr) >> 12);
                return sb_detach(&b);

        case 0x6f:
                sb_addfmt(&b, "jal x%u, %d", rd, decode_j_imm(instr));
                return sb_detach(&b);

        case 0x67:
                if (funct3 == 0) {
                        sb_addfmt(&b, "jalr x%u, %d(x%u)", rd, decode_i_imm(instr), rs1);
                        return sb_detach(&b);
                }
                break;

        case 0x63: {
                int32 offset = decode_b_imm(instr);
                const char *name = NULL;
                switch (funct3) {
                case 0: name = "beq"; break;
                case 1: name = "bne"; break;
                case 4: name = "blt"; break;
                case 5: name = "bge"; break;
                case 6: name = "bltu"; break;
                case 7: name = "bgeu"; break;
                }
                if (name) {
                        sb_addfmt(&b, "%s x%u, x%u, %d", name, rs1, rs2, offset);
                        return sb_detach(&b);
                }
                break;
        }

        case 0x13: {
                int32 imm = decode_i_imm(instr);
                uint32 shamt = (instr >> 20) & 0x1f;
                switch (funct3) {
                case 0: sb_addfmt(&b, "addi x%u, x%u, %d", rd, rs1, imm); return sb_detach(&b);
                case 2: sb_addfmt(&b, "slti x%u, x%u, %d", rd, rs1, imm); return sb_detach(&b);
                case 3: sb_addfmt(&b, "sltiu x%u, x%u, %d", rd, rs1, imm); return sb_detach(&b);
                case 4: sb_addfmt(&b, "xori x%u, x%u, 0x%x", rd, rs1, imm & 0xfff); return sb_detach(&b);
                case 6: sb_addfmt(&b, "ori x%u, x%u, 0x%x", rd, rs1, imm & 0xfff); return sb_detach(&b);
                case 7: sb_addfmt(&b, "andi x%u, x%u, 0x%x", rd, rs1, imm & 0xfff); return sb_detach(&b);
                case 1:
                        if (funct7 == 0x00) {
                                sb_addfmt(&b, "slli x%u, x%u, %u", rd, rs1, shamt);
                                return sb_detach(&b);
                        }
                        break;
                case 5:
                        if (funct7 == 0x00) {
                                sb_addfmt(&b, "srli x%u, x%u, %u", rd, rs1, shamt);
                                return sb_detach(&b);
                        } else if (funct7 == 0x20) {
                                sb_addfmt(&b, "srai x%u, x%u, %u", rd, rs1, shamt);
                                return sb_detach(&b);
                        }
                        break;
                }
                break;
        }

        case 0x33: {
                const char *name = NULL;
                switch (funct3) {
                case 0:
                        if (funct7 == 0x00) name = "add";
                        else if (funct7 == 0x20) name = "sub";
                        break;
                case 1:
                        if (funct7 == 0x00) name = "sll";
                        break;
                case 2:
                        if (funct7 == 0x00) name = "slt";
                        break;
                case 3:
                        if (funct7 == 0x00) name = "sltu";
                        break;
                case 4:
                        if (funct7 == 0x00) name = "xor";
                        break;
                case 5:
                        if (funct7 == 0x00) name = "srl";
                        else if (funct7 == 0x20) name = "sra";
                        break;
                case 6:
                        if (funct7 == 0x00) name = "or";
                        break;
                case 7:
                        if (funct7 == 0x00) name = "and";
                        break;
                }
                if (name) {
                        sb_addfmt(&b, "%s x%u, x%u, x%u", name, rd, rs1, rs2);
                        return sb_detach(&b);
                }
                break;
        }
        }

        sb_addfmt(&b, ".word 0x%08x", instr);
        return sb_detach(&b);
}
