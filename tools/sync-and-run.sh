#!/usr/bin/env bash
# Copia los archivos editables de un core a la VM de Windows, compila el
# módulo en Simics y corre un programa .txt, mostrando memoria, registros y
# contadores. Herramienta de pruebas: no contiene lógica del core.
#
# Uso:
#   tools/sync-and-run.sh [-c atomic|pipeline] [-n] [-m ciclos] [-t seg] programa.txt
#
#   -c  core a usar (default: atomic)
#   -n  no ejecutar `run`: solo carga el programa y muestra memoria/disassemble
#       (útil para probar el ensamblador antes de tener execute())
#   -s  no copiar ni compilar el módulo (ya está al día en la VM)
#   -m  tope de ciclos antes de detenerse (default: 100000), por si no llega a ebreak
#   -t  timeout en segundos de toda la corrida (default: 120), por si Simics se cuelga
#
# Variables de entorno: VM (default chris@192.168.64.11), SRC (repo local),
# PROJ (proyecto Simics en la VM).

set -euo pipefail

VM="${VM:-chris@192.168.64.11}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${SRC:-$HERE/..}"
PROJ="${PROJ:-C:/Users/chris/simics-projects/rv32i}"

core=atomic norun=0 max_cycles=100000 tmo=120 skip_build=0
while getopts "c:nsm:t:h" opt; do
  case $opt in
    c) core=$OPTARG ;;
    n) norun=1 ;;
    s) skip_build=1 ;;
    m) max_cycles=$OPTARG ;;
    t) tmo=$OPTARG ;;
    *) sed -n '2,18p' "$0"; exit 1 ;;
  esac
done
shift $((OPTIND - 1))
[[ $# -eq 1 ]] || { sed -n '2,18p' "$0"; exit 1; }
[[ $core == atomic || $core == pipeline ]] || { echo "core inválido: $core" >&2; exit 1; }

prog="$1"
[[ -f $prog ]] || { echo "no existe: $prog" >&2; exit 1; }
mod="rv32-$core"
moddir="$SRC/modules/$mod"
[[ -d $moddir ]] || { echo "no existe: $moddir" >&2; exit 1; }

# Instrucciones del programa (líneas sin comentario ni vacías) -> bytes a mostrar
ninstr=$(sed 's/#.*//' "$prog" | grep -cv '^[[:space:]]*$' || true)
nbytes=$(( ninstr * 4 ))
(( nbytes > 0 )) || nbytes=16
pname="$(basename "$prog")"

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=5 -o LogLevel=ERROR)
filter() { grep -v 'quantum\|upgraded\|pq.html' || true; }

echo "== sync $( ((skip_build)) || echo "$mod + ")$pname -> $VM"
if (( ! skip_build )); then
  scp -q "${SSH_OPTS[@]}" "$moddir"/rv32-*.c "$moddir"/rv32-*.h "$moddir"/txt_loader.py \
      "$VM:$PROJ/modules/$mod/" 2>&1 | filter
fi
scp -q "${SSH_OPTS[@]}" "$prog" "$VM:$PROJ/targets/rv32i/programs/$pname" 2>&1 | filter

if (( ! skip_build )); then
echo "== build $mod"
set +e
build_out=$(ssh "${SSH_OPTS[@]}" "$VM" "cd $PROJ; cmd /c 'bin\\make.bat $mod 2>&1'; exit \$LASTEXITCODE" 2>&1)
build_rc=$?
set -e
# Solo mostrar advertencias/errores, no el ruido de make
printf '%s\n' "$build_out" | filter | grep -vE '^(DEP|PYC|GEN|CC|CCLD) |^=== |up-to date|^[0-9]+\.[0-9]+\.[0-9]+$' || true
if (( build_rc != 0 )); then
  echo "!! la compilación falló (exit $build_rc)" >&2
  exit 2
fi
fi

# Comandos de Simics. Se pasan a cmd con comillas dobles duplicadas.
cmds=(-e '""output-radix 16""')
cmds+=(-e "\"\"x 0x0 $nbytes\"\"")
cmds+=(-e "\"\"disassemble 0x0 $ninstr\"\"")
if (( ! norun )); then
  cmds+=(-e "\"\"bp.cycle.break cosim0 $max_cycles\"\"" -e run)
fi
cmds+=(-e pregs -e ptime -e quit)

echo "== run $pname en $mod $( ((norun)) && echo '(sin run)')"
remote="cd $PROJ; cmd /c \"simics.bat --batch-mode targets\\rv32i\\$mod.simics program=targets/rv32i/programs/$pname ${cmds[*]} 2>&1\""

# Simics corre en la VM como python.exe; se identifica por su línea de comandos.
kill_remote='Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -like "*Programs\Simics\simics-*" -or $_.CommandLine -like "*simics.bat --batch-mode*") } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'

ssh "${SSH_OPTS[@]}" "$VM" "$remote" > >(filter) 2>&1 &
pid=$!
waited=0
while kill -0 $pid 2>/dev/null && (( waited < tmo )); do
  sleep 1; waited=$((waited + 1))
done
if kill -0 $pid 2>/dev/null; then
  echo "!! timeout de ${tmo}s: Simics no terminó (¿falta increment_cycle() o el programa no llega a ebreak?). Deteniéndolo." >&2
  ssh "${SSH_OPTS[@]}" "$VM" "$kill_remote" 2>&1 | filter
  kill $pid 2>/dev/null || true
  wait $pid 2>/dev/null || true
  exit 3
fi
wait $pid 2>/dev/null || true
sleep 0.2  # deja que el filtro termine de imprimir
