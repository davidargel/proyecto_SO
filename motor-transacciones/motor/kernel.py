"""
kernel.py — Puente con el kernel de Linux.

Todo lo que el panel muestra como "Estado SO" se LEE de /proc en tiempo real:

  /proc/self/task/<TID>/stat     -> estado del planificador (R, S, D, Z, T...)
  /proc/self/task/<TID>/wchan    -> función del kernel donde duerme el hilo (p. ej. futex_do_wait)
  /proc/self/task/<TID>/syscall  -> número de la llamada al sistema en curso (202 = futex en x86_64)
  /proc/self/task/<TID>/comm     -> nombre del hilo (lo asignamos con prctl(PR_SET_NAME))

Nada de esto es simulado: si el hilo no existe en /proc, no aparece.
"""
import ctypes
import ctypes.util
import os
import platform
import threading

PR_SET_NAME = 15  # <linux/prctl.h>

_libc = None


def _obtener_libc():
    global _libc
    if _libc is None:
        try:
            _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        except OSError:
            _libc = False
    return _libc


def nombrar_hilo_so(nombre: str) -> None:
    """Asigna el nombre del hilo a nivel de kernel (máx. 15 bytes).

    Así el hilo se identifica en `top -H`, `htop`, `ps -L -o comm` y /proc/<pid>/task/<tid>/comm.
    Debe llamarse DESDE el propio hilo (prctl actúa sobre el hilo que la invoca).
    """
    libc = _obtener_libc()
    if libc:
        libc.prctl(PR_SET_NAME, ctypes.c_char_p(nombre.encode()[:15]), 0, 0, 0)


# Números de syscall de Linux x86_64 más comunes en este programa.
SYSCALLS_X86_64 = {
    0: "read", 1: "write", 3: "close", 7: "poll", 23: "select", 24: "sched_yield",
    35: "nanosleep", 43: "accept", 44: "sendto", 45: "recvfrom", 61: "wait4",
    74: "fsync", 75: "fdatasync", 202: "futex", 230: "clock_nanosleep",
    232: "epoll_wait", 270: "pselect6", 271: "ppoll", 281: "epoll_pwait", 288: "accept4",
}
ES_X86_64 = platform.machine() in ("x86_64", "AMD64")


def _leer(ruta: str) -> str:
    try:
        with open(ruta, "r") as f:
            return f.read().strip()
    except OSError:
        return ""


def leer_info_hilo(tid: int) -> dict:
    """Lee el estado real de un hilo (LWP) desde /proc/self/task/<tid>."""
    base = f"/proc/self/task/{tid}"
    stat = _leer(base + "/stat")
    if not stat:
        return {"tid": tid, "vivo": False, "estado": "-", "wchan": "", "syscall": None,
                "syscall_nombre": "", "etiqueta": "TERMINADO", "comm": ""}
    # El campo 2 (comm) va entre paréntesis y puede tener espacios: el estado va tras el último ')'.
    estado = stat[stat.rfind(")") + 2]
    wchan = _leer(base + "/wchan")
    if wchan == "0":
        wchan = ""
    sc_txt = _leer(base + "/syscall")
    syscall = None
    if sc_txt and sc_txt.split()[0].lstrip("-").isdigit():
        syscall = int(sc_txt.split()[0])
    sc_nombre = ""
    if syscall is not None and syscall >= 0:
        sc_nombre = SYSCALLS_X86_64.get(syscall, f"#{syscall}") if ES_X86_64 else f"#{syscall}"
    return {
        "tid": tid,
        "vivo": True,
        "estado": estado,
        "wchan": wchan,
        "syscall": syscall,
        "syscall_nombre": sc_nombre,
        "etiqueta": etiqueta_estado(estado, wchan, syscall),
        "comm": _leer(base + "/comm"),
    }


def etiqueta_estado(estado: str, wchan: str, syscall) -> str:
    """Traduce el estado del planificador a una etiqueta legible para el panel."""
    if estado == "R":
        return "RUNNING"
    if estado == "D":
        return "DISK_WAIT"
    if estado == "S":
        if "futex" in (wchan or "") or (ES_X86_64 and syscall == 202):
            return "FUTEX_WAIT"
        if ES_X86_64 and syscall in (35, 230):
            return "SLEEP"
        if ES_X86_64 and syscall in (7, 23, 232, 270, 271, 281, 45, 43, 288):
            return "IO_WAIT"
        return "SLEEP"
    return {"Z": "ZOMBIE", "T": "STOPPED", "t": "TRACED", "X": "DEAD", "I": "IDLE"}.get(estado, estado)


def listar_tareas() -> list:
    """TIDs de todos los hilos del proceso (entradas de /proc/self/task)."""
    try:
        return sorted(int(x) for x in os.listdir("/proc/self/task"))
    except OSError:
        return []


def info_sistema() -> dict:
    """Datos del sistema para la cabecera del panel."""
    un = platform.uname()
    release = un.release
    wsl = "microsoft" in release.lower() or "wsl" in release.lower() or os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop")
    try:
        libpthread = os.confstr("CS_GNU_LIBPTHREAD_VERSION")  # p. ej. "NPTL 2.35"
    except (ValueError, OSError):
        libpthread = ""
    hipervisor = "hypervisor" in _leer("/proc/cpuinfo")
    entorno = "WSL2" if wsl else ("VM" if hipervisor else "nativo")
    modelo = "NPTL" if "NPTL" in (libpthread or "") else (libpthread or "pthreads")
    return {
        "sistema": un.system,
        "kernel": release,
        "arquitectura": un.machine,
        "wsl": wsl,
        "libpthread": libpthread,
        "etiqueta": f"{un.system} {un.machine} ({entorno}/{modelo})",
        "pid": os.getpid(),
        "python": platform.python_version(),
        "es_linux": un.system == "Linux",
    }


def tid_actual() -> int:
    """TID del hilo que llama (equivale a gettid(2); es el LWP que muestra `ps -eLf`)."""
    return threading.get_native_id()
