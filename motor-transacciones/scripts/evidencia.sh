#!/usr/bin/env bash
# =============================================================================
#  evidencia.sh — Captura evidencia EXTERNA al programa de que los hilos son
#  hilos reales del sistema operativo (requisito del Proyecto 2).
#
#  Uso:   ./scripts/evidencia.sh            (busca el PID de app.py)
#         ./scripts/evidencia.sh 580        (PID explícito)
#
#  Consejo: ejecútalo MIENTRAS hay un escenario corriendo (por ejemplo con un
#  interbloqueo en pantalla) para ver los hilos bloqueados en futex.
# =============================================================================
set -u
buscar_pid() {
  local p
  for p in $(pgrep -f 'app\.py'); do
    [[ "$(cat /proc/$p/comm 2>/dev/null)" == python* ]] && { echo "$p"; return; }
  done
}
PID="${1:-$(buscar_pid)}"
if [[ -z "${PID}" || ! -d "/proc/${PID}" ]]; then
  echo "No encontré el proceso de app.py. Inícialo con: python3 app.py" >&2
  exit 1
fi

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${RAIZ}/evidencias/$(date +%Y%m%d_%H%M%S)_pid${PID}"
mkdir -p "${OUT}"
echo "Guardando evidencias del PID ${PID} en ${OUT}"

{
  echo "# uname -a"; uname -a
  echo; echo "# /proc/version"; cat /proc/version
  echo; echo "# getconf GNU_LIBPTHREAD_VERSION"; getconf GNU_LIBPTHREAD_VERSION 2>/dev/null
  echo; echo "# fecha"; date
} > "${OUT}/00_sistema.txt"

# 1) ps -eLf: una fila por hilo (LWP = TID, NLWP = hilos del proceso)
{ ps -eLf | head -n1; ps -eLf | awk -v p="${PID}" '$2 == p'; } > "${OUT}/01_ps_eLf.txt"

# 2) Vista de hilos con estado, función del kernel donde duermen y nombre asignado con prctl
ps -L -o pid,lwp,nlwp,stat,pcpu,wchan:24,comm -p "${PID}" > "${OUT}/02_ps_hilos_wchan.txt"

# 3) Directorio /proc/<PID>/task: una entrada por hilo
ls -l "/proc/${PID}/task/" > "${OUT}/03_proc_task.txt"

# 4) Detalle por hilo leído directamente de /proc
{
  printf "%-8s %-16s %-6s %-24s %s\n" "TID" "COMM" "STATE" "WCHAN" "SYSCALL(nr)"
  for t in /proc/"${PID}"/task/*; do
    tid="$(basename "$t")"
    comm="$(cat "$t/comm" 2>/dev/null)"
    state="$(awk '{print $3}' "$t/stat" 2>/dev/null)"
    wchan="$(cat "$t/wchan" 2>/dev/null)"
    sc="$(cut -d' ' -f1 "$t/syscall" 2>/dev/null)"
    printf "%-8s %-16s %-6s %-24s %s\n" "$tid" "$comm" "$state" "${wchan:-0}" "${sc:-n/d}"
  done
  echo
  echo "Nota: syscall 202 = futex en x86_64 (hilo dormido en sem.acquire()/Lock/Condition)."
} > "${OUT}/04_proc_task_detalle.txt"

# 5) /proc/<PID>/status (Threads:) y status de cada hilo
{
  grep -E '^(Name|State|Tgid|Pid|PPid|Threads)' "/proc/${PID}/status"
  echo
  for t in /proc/"${PID}"/task/*; do
    echo "== $(basename "$t") =="; grep -E '^(Name|State|Pid|voluntary_ctxt_switches|nonvoluntary_ctxt_switches)' "$t/status"
  done
} > "${OUT}/05_status.txt"

# 6) top en modo hilos (-H), una sola iteración
top -H -b -n 1 -p "${PID}" > "${OUT}/06_top_H.txt" 2>/dev/null

# 7) Estado interno del motor (el mismo JSON que dibuja el frontend: RAG, hilos, recursos)
if command -v curl >/dev/null 2>&1; then
  curl -s "http://localhost:${PUERTO:-5000}/api/estado" > "${OUT}/07_api_estado.json" || true
fi

# 8) strace de las llamadas futex durante 4 s (requiere strace; en WSL normalmente con sudo)
if command -v strace >/dev/null 2>&1; then
  timeout 4 strace -f -tt -e trace=futex -p "${PID}" -o "${OUT}/08_strace_futex.txt" 2>/dev/null \
    || timeout 4 sudo -n strace -f -tt -e trace=futex -p "${PID}" -o "${OUT}/08_strace_futex.txt" 2>/dev/null \
    || echo "strace necesita permisos: sudo strace -f -e trace=futex -p ${PID}" > "${OUT}/08_strace_futex.txt"
fi

# 9) Últimas líneas de la bitácora (WAL) con TID por evento
tail -n 60 "${RAIZ}/bitacora/prestamos.wal" > "${OUT}/09_bitacora_tail.txt" 2>/dev/null

echo "Listo. Archivos:"
ls -1 "${OUT}"
echo
echo "---- 02_ps_hilos_wchan.txt ----"
cat "${OUT}/02_ps_hilos_wchan.txt"
