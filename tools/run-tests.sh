#!/usr/bin/env bash
# Corre la batería de pruebas en Simics y compara contra tests/expected/.
#
# Uso:
#   tools/run-tests.sh [-c atomic|pipeline] [-t seg] [patrón]
#
#   patrón: filtra los programas por nombre (ej. "t0" o "p0"). Default: todos.
# Guarda la salida completa de cada prueba en tests/results/<core>/<prueba>.log
# y un resumen en tests/results/<core>/summary.txt (útil para el reporte).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
core=atomic tmo=120
while getopts "c:t:h" opt; do
  case $opt in
    c) core=$OPTARG ;;
    t) tmo=$OPTARG ;;
    *) sed -n '2,9p' "$0"; exit 1 ;;
  esac
done
shift $((OPTIND - 1))
pat="${1:-}"

progs=("$ROOT"/targets/rv32i/programs/all-instructions.txt)
progs+=("$ROOT"/tests/programs/*${pat}*.txt)
outdir="$ROOT/tests/results/$core"
mkdir -p "$outdir"
summary="$outdir/summary.txt"
: > "$summary"
flag=$([[ $core == atomic ]] && echo --atomic)

pass=0 fail=0 first=1
for p in "${progs[@]}"; do
  [[ -f $p ]] || continue
  name="$(basename "$p" .txt)"
  [[ -n $pat && $name != *$pat* ]] && continue
  exp="$ROOT/tests/expected/$name.json"
  [[ -f $exp ]] || { echo "SKIP  $name (sin $exp)" | tee -a "$summary"; continue; }
  # La primera prueba sincroniza y compila; las demás reusan el módulo.
  opts=(-c "$core" -t "$tmo"); (( first )) || opts+=(-s)
  "$HERE/sync-and-run.sh" "${opts[@]}" "$p" > "$outdir/$name.log" 2>&1
  rc=$?
  if (( first && rc == 2 )); then
    echo "!! la compilación falló; ver $outdir/$name.log" >&2; tail -20 "$outdir/$name.log" >&2; exit 2
  fi
  first=0
  if python3 "$HERE/compare.py" "$exp" "$outdir/$name.log" $flag | tee -a "$summary"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
  fi
done
echo "--- $core: $pass pasan, $fail fallan" | tee -a "$summary"
(( fail == 0 ))
