# Plan de verificación — cores RV32I (Etapa 2)

## 1. Objetivo y alcance

Demostrar que los dos cores (`rv32-atomic`, de un ciclo, y `rv32-pipeline`)
ejecutan correctamente el subconjunto RV32I del curso (30 instrucciones:
`lui`, `auipc`, `jal`, `jalr`, 6 branches, 9 aritmético-lógicas con
inmediato, 10 registro-registro y `ebreak`) y que **ambos producen el mismo
estado final** para el mismo programa.

Fuera de alcance: loads/stores (no forman parte del ISA definido en
`CONVENTIONS.md`), excepciones distintas de `ebreak` e instrucción ilegal, y
extensiones (M, C, etc.). *Pendiente de confirmar con el profesor: cómo
evidenciar "acceso a memoria" si no hay `lw`/`sw`. Por ahora, el acceso a
memoria se cubre con la búsqueda de instrucciones (fetch) y con el volcado de
memoria del ensamblador.*

## 2. Metodología

### 2.1 Modelo de referencia (golden model)

Los valores esperados **no salen de los cores bajo prueba**. Se obtienen con una
cadena independiente:

1. **LLVM `llvm-mc`** ensambla el `.txt` (sin el `txt_loader.py` del proyecto).
2. **Unicorn** (el motor de emulación de QEMU) ejecuta el código hasta el `ebreak`.
3. `tools/golden.py` guarda en `tests/expected/<prueba>.json` los registros
   x1..x31, el `pc` final y el número de *steps*.

El modelo se validó a mano con `all-instructions.txt`: los 25 registros
distintos de cero y los 46 steps coinciden con el cálculo manual.

### 2.2 Criterio de aprobación (por programa)

| Verificación | Condición |
|---|---|
| Registros | x1..x31 iguales al modelo de referencia; x0 = 0 |
| PC final | apunta al `ebreak` que terminó el programa |
| Steps | igual al número de instrucciones completadas (incluye el `ebreak`) |
| Ciclos (solo un ciclo) | ciclos = steps (CPI = 1) |
| Ciclos (pipeline) | se reportan y se explican (sección 4.3); no hay valor fijo |

### 2.3 Automatización

| Herramienta | Función |
|---|---|
| `tools/test_loader.py` | Prueba el ensamblador en el Mac, sin Simics (10 vectores y el inicio de `all-instructions.txt`) |
| `tools/golden.py` | Genera los resultados esperados (LLVM + Unicorn) |
| `tools/sync-and-run.sh` | Copia el core a la VM, compila, corre en Simics y muestra memoria, registros y `ptime` |
| `tools/compare.py` | Compara la salida de Simics con el `.json` esperado |
| `tools/run-tests.sh` | Corre toda la batería; deja los logs y `summary.txt` en `tests/results/<core>/` |

Para regenerar los valores esperados después de agregar o cambiar un programa:

```
tools/.venv/bin/python tools/golden.py tests/programs/*.txt targets/rv32i/programs/all-instructions.txt
```

El comparador se validó con una prueba negativa: un valor esperado alterado a
propósito produce `FAIL` con la diferencia exacta, y una salida vacía produce
`FAIL` por falta de `pregs`.

## 3. Core de un ciclo — verificación por módulo

| Módulo del datapath | Qué se verifica | Programa(s) |
|---|---|---|
| Ensamblador (`txt_loader.py`) | Codificación de los 6 formatos, little-endian, comentarios y líneas vacías | `test_loader.py`; volcado `x`/`disassemble` de `all-instructions.txt` comparado con LLVM (54/54 palabras) |
| Fetch / PC | PC + 4 secuencial, lectura de 4 bytes en little-endian | todos (cada programa empieza en 0x0 y avanza) |
| Decodificador | opcode/funct3/funct7 de las 30 instrucciones; distinguir `add`/`sub`, `srl`/`sra`, `srli`/`srai` | `all-instructions`, t03, t05 |
| Generador de inmediatos | I (±2047/−2048), U (0, 0x80000, 0xfffff), extensión de signo en `addi`/`ori`/`andi`/`sltiu`, shamt 0 y 31 | t02, t04, t06 |
| Banco de registros | Escribir y leer x1..x31; x0 inmutable desde los formatos I, U, R y J; rd = rs1 = rs2 | t01 |
| ALU suma/resta | Desbordamiento (INT_MAX+1, INT_MIN−1), −INT_MIN, acarreo descartado | t03 |
| ALU lógica | and/or/xor, NOT con `xori -1`, máscaras con inmediato negativo | t04 |
| ALU desplazamientos | 0 y 31; aritmético vs lógico; solo los 5 bits bajos de rs2 (rs2 = 33 → 1) | t05 |
| Comparaciones | slt vs sltu con −1/1 e INT_MIN; `sltiu` con inmediato extendido (−1 → 0xffffffff); patrón `seqz` | t06 |
| Comparador de branches | Los 6 branches tomados y no tomados; iguales; signo vs sin signo; lazo hacia atrás | t07, `all-instructions` |
| Siguiente PC / saltos | `jal` adelante y atrás, `jal x0`, link = PC+4, `jalr` con bit 0 limpiado, `jalr` con rd = rs1 (usa el rs1 viejo), llamada y retorno | t08 |
| Control de fin (`ebreak`) | Cuenta el step, no mueve el PC, detiene la simulación | todos; p06 |
| Sistema | Programas completos: suma 1..10, Fibonacci(20), multiplicación por suma y desplazamiento | t09 |

**Pruebas manuales adicionales** (no caben en el formato automático porque no terminan en `ebreak`):

- **Instrucción ilegal:** un programa sin `ebreak` (por ejemplo, solo `addi x1, x0, 1`)
  debe terminar con el error `illegal or unsupported instruction 0x00000000 at 0x00000004`,
  con el PC en 0x04 y sin contar step para la instrucción ilegal.
- **Errores del ensamblador:** inmediato fuera de rango (`addi … 2048`), `slli … 32`,
  offset impar, `x32`, falta de operando, mnemónico desconocido (`mul`). Cada uno
  debe dar un error con número de línea.

## 4. Core pipelined

Requisito del enunciado: los mismos programas deben dar **exactamente** el
mismo estado final que en el core de un ciclo. Por eso toda la batería t01–t09
y `all-instructions` se vuelve a correr con `-c pipeline`.

### 4.1 Verificación por etapa

*(Las etapas se confirman con el profesor: el enunciado dice cuatro y la presentación cinco.
Con el ISA sin loads/stores, la propuesta es IF → ID → EX → WB.)*

Método: registrar con `SIM_LOG_INFO` el contenido de cada latch al final de
cada ciclo (`log-level core0 2`), avanzar ciclo por ciclo con `run 1 cycles`,
y comparar contra un diagrama de pipeline hecho a mano para un programa corto
(p01 y p04).

| Etapa | Qué se verifica | Evidencia |
|---|---|---|
| IF | PC correcto cada ciclo; PC+4 secuencial; redirección al destino del branch o salto; el PC se mantiene durante un stall | Log del PC por ciclo vs diagrama; p04, p05 |
| ID | Campos e inmediato decodificados; lectura del banco; detección de hazards (comparar rs1/rs2 con el rd de las etapas siguientes, ignorando x0) | Log del latch IF/ID → ID/EX; p01, p03 |
| EX | Resultado de la ALU; decisión del branch y destino; adelantamiento (*forwarding*) desde EX/WB y WB | Log del latch ID/EX → EX/WB; p01, p02 |
| WB | Escritura en el banco solo para instrucciones válidas; x0 nunca se escribe; `increment_step()` una vez por instrucción que sale del pipeline | `pregs` y `ptime`; p03, p06 |

Plantilla del diagrama (llenar con el diseño final):

```
ciclo:            1    2    3    4    5    6    7
addi x1,x0,1      IF   ID   EX   WB
add  x1,x1,x1          IF   ID   EX*  WB          * adelantamiento desde EX/WB
add  x1,x1,x1               IF   ID   EX*  WB
```

### 4.2 Verificación del sistema completo: hazards y casos especiales

| Caso | Riesgo si está mal | Programa |
|---|---|---|
| RAW a distancia 1 (en ambos operandos) | Lee el valor viejo | p01 |
| RAW a distancia 2 y 3 (escritura y lectura del banco en el mismo ciclo) | Lee el valor viejo o un valor intermedio | p02 |
| Dos productores seguidos del mismo registro | Adelanta el valor más antiguo en vez del más reciente | p02 (x7/x8), p01 |
| Escribir x0 y leerlo enseguida | Adelanta un valor distinto de 0 desde x0 | p03 |
| Branch que depende de la instrucción anterior | Decide con un operando viejo | p04, p05 |
| `jalr` que depende de la instrucción anterior (`auipc`) | Salta a una dirección incorrecta | p04 |
| Instrucciones en el camino incorrecto tras un branch, `jal` o `jalr` | Escriben registros (veneno x31 ≠ 0) | p04, p05, t07, t08 |
| `ebreak` en el camino incorrecto | Detiene el programa antes de tiempo | p04 (0x38 y 0x44) |
| Branches tomados consecutivos | Un flush pierde el segundo salto | p05 |
| Instrucciones antes del `ebreak` | No terminan (falta vaciar el pipeline) | p06 |
| Instrucciones después del `ebreak` | Se ejecutan (veneno x31) | p06 |
| Conteo de steps | Más de un `increment_step()` por llamada (ASSERT) o cuenta instrucciones anuladas | todos (steps vs modelo de referencia) |

### 4.3 Rendimiento (ciclos)

En el pipeline, ciclos = steps + llenado inicial (etapas − 1) + ciclos de stall
+ penalización × (branches tomados + saltos). La penalización depende de en qué
etapa se resuelvan los saltos. Para cada programa se reportan los ciclos y el CPI
de ambos cores, y la diferencia se explica con esta fórmula. `run-tests.sh` ya
imprime los steps, los ciclos y el CPI.

## 5. Resultados

### 5.1 Core de un ciclo — 2026-11-09

`tools/run-tests.sh -c atomic` → **16/16 PASS**, CPI = 1.00 en todos los programas.

| Programa | Steps | Ciclos | Resultado |
|---|---|---|---|
| all-instructions | 46 | 46 | PASS |
| t01_regfile | 40 | 40 | PASS |
| t02_immediates | 17 | 17 | PASS |
| t03_alu_arith | 13 | 13 | PASS |
| t04_alu_logic | 14 | 14 | PASS |
| t05_alu_shift | 17 | 17 | PASS |
| t06_alu_compare | 18 | 18 | PASS |
| t07_branches | 57 | 57 | PASS |
| t08_jumps | 15 | 15 | PASS |
| t09_programs | 174 | 174 | PASS |
| p01_raw_chain | 10 | 10 | PASS |
| p02_raw_distances | 16 | 16 | PASS |
| p03_x0_hazard | 8 | 8 | PASS |
| p04_control_flush | 13 | 13 | PASS |
| p05_loop_hazards | 39 | 39 | PASS |
| p06_ebreak_drain | 4 | 4 | PASS |

Pendiente: las pruebas manuales de la sección 3 (instrucción ilegal y errores del ensamblador).

### 5.2 Core pipelined

Pendiente de implementación.

## 6. Uso de IA en la verificación (para la sección de transparencia del reporte)

Herramienta: Claude Code (modelo Claude Opus 5.5), noviembre 2026. Generado con
IA y revisado por el estudiante: los programas de prueba `tests/programs/*.txt`,
los scripts de `tools/` (infraestructura de pruebas y modelo de referencia), y
este plan. **No** se generaron con IA: `txt_loader.py`, `rv32-atomic.c` ni
`rv32-pipeline.c`. Los valores esperados vienen de LLVM y Unicorn, no de la IA,
y se validaron a mano con `all-instructions.txt`.
