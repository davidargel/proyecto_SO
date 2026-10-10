#!/usr/bin/env python3
"""
prueba_carga.py — Evidencia del Entregable 1: integridad de los datos BAJO CARGA.

Lanza N hilos reales (threading.Thread) que hacen M préstamos/devoluciones cada uno sobre
el catálogo, primero SIN protección y luego CON semáforos, y verifica los invariantes:

    1) nunca hay más préstamos simultáneos de un título que copias físicas
    2) al terminar, disponibles == copias  (ninguna actualización perdida)
    3) el contador nunca es negativo

Uso (desde la carpeta del proyecto):
    python3 scripts/prueba_carga.py                     # 100 hilos x 200 operaciones
    python3 scripts/prueba_carga.py --hilos 200 --operaciones 500
    python3 scripts/prueba_carga.py --modo seguro       # solo con semáforos
"""
import argparse
import os
import random
import sys
import threading
import time
from datetime import datetime
from types import SimpleNamespace

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from motor.bitacora import Bitacora                                    # noqa: E402
from motor.catalogo import CATALOGO                                    # noqa: E402
from motor.kernel import listar_tareas, nombrar_hilo_so               # noqa: E402
from motor.recursos import (EstadoRecursos, SemaforoRastreado,         # noqa: E402
                            devolver_sin_proteccion, prestar_sin_proteccion)


def ejecutar(modo: str, n_hilos: int, n_ops: int, semilla: int) -> dict:
    estado = EstadoRecursos()
    sems = {t.isbn: SemaforoRastreado(t.isbn, t.copias, estado) for t in CATALOGO}
    bit = Bitacora(os.path.join(RAIZ, "bitacora", f"carga_{modo}.wal"), durable=False)
    isbns = [t.isbn for t in CATALOGO]
    stats = {"prestamos": 0, "rechazos": 0, "violaciones": 0, "negativos": 0}
    maximo = {i: 0 for i in isbns}
    lock_stats = threading.Lock()
    barrera = threading.Barrier(n_hilos + 1)
    pico_hilos = [0]

    def trabajador(k):
        nombrar_hilo_so(f"T_Carga{k:03d}")
        hilo = SimpleNamespace(name=f"T_Carga{k:03d}", abortar=threading.Event(), valor_leido=None)
        rng = random.Random(semilla * 1000 + k)
        barrera.wait()
        p = r = v = neg = 0
        for _ in range(n_ops):
            isbn = rng.choice(isbns)
            if modo == "seguro":
                ok = sems[isbn].intentar(hilo)             # acquire(blocking=False) atómico
            else:
                ok = prestar_sin_proteccion(estado, isbn, hilo, bit)
            if not ok:
                r += 1
                continue
            p += 1
            with estado.lock:                              # auditoría: lectura consistente
                info = estado.recursos[isbn]
                prest = info.prestamos_registrados
                if prest > info.total:
                    v += 1
                if info.disponibles < 0:
                    neg += 1
            with lock_stats:
                maximo[isbn] = max(maximo[isbn], prest)
            bit.registrar(hilo.name, "PRESTAMO", isbn)      # E/S real (libera el GIL)
            if modo == "seguro":
                sems[isbn].liberar(hilo)
            else:
                devolver_sin_proteccion(estado, isbn, hilo)
        with lock_stats:
            stats["prestamos"] += p
            stats["rechazos"] += r
            stats["violaciones"] += v
            stats["negativos"] += neg

    hilos = [threading.Thread(target=trabajador, args=(k,), name=f"T_Carga{k:03d}") for k in range(n_hilos)]
    for h in hilos:
        h.start()
    pico_hilos[0] = len(listar_tareas())                   # hilos vivos en /proc/self/task
    t0 = time.perf_counter()
    barrera.wait()
    for h in hilos:
        h.join()
    dur = time.perf_counter() - t0
    bit.cerrar()

    final = {}
    perdidas = 0
    for t in CATALOGO:
        info = estado.recursos[t.isbn]
        final[t.corto] = (info.disponibles, t.copias, maximo[t.isbn])
        if info.disponibles != t.copias:
            perdidas += 1
    return {"modo": modo, "duracion": dur, "tareas_so": pico_hilos[0], "final": final,
            "titulos_inconsistentes": perdidas, **stats}


def imprimir(res: dict, out) -> None:
    ok = res["violaciones"] == 0 and res["titulos_inconsistentes"] == 0 and res["negativos"] == 0
    linea = "-" * 74
    print(linea, file=out)
    print(f" MODO: {'CON SEMÁFOROS' if res['modo'] == 'seguro' else 'SIN PROTECCIÓN'}   ·   "
          f"{res['duracion']:.2f} s   ·   hilos vivos en /proc/self/task: {res['tareas_so']}", file=out)
    print(linea, file=out)
    print(f" Préstamos realizados .............. {res['prestamos']}", file=out)
    print(f" Rechazos (sin copia disponible) ... {res['rechazos']}", file=out)
    print(f" Violaciones prestadas > copias .... {res['violaciones']}", file=out)
    print(f" Lecturas con contador negativo .... {res['negativos']}", file=out)
    print(f" Títulos con contador final ≠ copias {res['titulos_inconsistentes']}", file=out)
    print(f" {'Título':<16}{'disp. final':>12}{'copias':>9}{'máx. simult.':>14}", file=out)
    for nombre, (disp, copias, mx) in res["final"].items():
        marca = "" if (disp == copias and mx <= copias) else "  <-- inconsistente"
        print(f" {nombre:<16}{disp:>12}{copias:>9}{mx:>14}{marca}", file=out)
    print(f" RESULTADO: {'INTEGRIDAD OK' if ok else 'INTEGRIDAD VIOLADA'}", file=out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hilos", type=int, default=100)
    ap.add_argument("--operaciones", type=int, default=200)
    ap.add_argument("--modo", choices=["ambos", "seguro", "inseguro"], default="ambos")
    ap.add_argument("--semilla", type=int, default=7)
    a = ap.parse_args()

    modos = ["inseguro", "seguro"] if a.modo == "ambos" else [a.modo]
    os.makedirs(os.path.join(RAIZ, "evidencias"), exist_ok=True)
    ruta = os.path.join(RAIZ, "evidencias", f"prueba_carga_{datetime.now():%Y%m%d_%H%M%S}.txt")
    print(f"PID {os.getpid()} · {a.hilos} hilos reales x {a.operaciones} operaciones · "
          f"switchinterval={sys.getswitchinterval()} s")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(f"Prueba de carga — PID {os.getpid()} — {datetime.now()}\n"
                f"{a.hilos} hilos x {a.operaciones} operaciones\n")
        for m in modos:
            r = ejecutar(m, a.hilos, a.operaciones, a.semilla)
            imprimir(r, sys.stdout)
            imprimir(r, f)
    print(f"\nResultado guardado en {ruta}")


if __name__ == "__main__":
    main()
