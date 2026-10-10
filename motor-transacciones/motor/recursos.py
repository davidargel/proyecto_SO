"""
recursos.py — Recursos compartidos y su sincronización.

  * Cada título del catálogo se protege con un threading.Semaphore(copias):
      acquire()  == P(S) / wait  -> toma una copia; si el contador es 0 el hilo se BLOQUEA
                                    (en Linux: syscall futex(FUTEX_WAIT), estado S).
      release()  == V(S) / signal -> devuelve la copia y despierta a un hilo en espera (FUTEX_WAKE).
  * Las estaciones de préstamo son otro semáforo contador (NUM_ESTACIONES).
  * Un threading.Lock (EstadoRecursos.lock) protege SOLO el diccionario de estado interno:
      quién retiene qué copia y quién espera qué recurso. De ahí sale el RAG.

SemaforoRastreado envuelve al threading.Semaphore real y actualiza ese estado en cada
acquire()/release(). La espera se hace con acquire(timeout=...) en un bucle para que el hilo
pueda atender la señal de ABORTO del watchdog (recuperación) sin alterar la semántica del
semáforo: mientras no haya copia libre, el hilo sigue bloqueado en el kernel.
"""
import threading
import time
from collections import Counter

from .catalogo import nombre_recurso

INTERVALO_ABORTO = 0.25  # cada cuánto un hilo bloqueado revisa si el watchdog lo eligió como víctima


class TransaccionAbortada(Exception):
    """Se lanza dentro del hilo víctima para ejecutar su rollback."""


class InfoRecurso:
    __slots__ = ("rid", "total", "disponibles", "retenedores", "prestamos_registrados", "tipo")

    def __init__(self, rid, total, tipo):
        self.rid = rid
        self.total = total
        self.disponibles = total            # contador visible (en modo seguro == valor del semáforo)
        self.retenedores = Counter()        # nombre_hilo -> copias que retiene
        self.prestamos_registrados = 0      # auditoría: préstamos que se registraron (para la integridad)
        self.tipo = tipo                    # "libro" | "estacion"


class EstadoRecursos:
    """Estructuras internas compartidas: la ÚNICA fuente de verdad del RAG."""

    def __init__(self):
        self.lock = threading.Lock()
        self.recursos = {}                  # rid -> InfoRecurso
        self.esperas = {}                   # nombre_hilo -> (rid, instante_solicitud)
        self.version = 0                    # cambia con cada modificación (para el broadcast)

    def agregar(self, rid, total, tipo):
        self.recursos[rid] = InfoRecurso(rid, total, tipo)

    def _cambio(self):
        self.version += 1

    def copiar(self) -> dict:
        """Copia consistente del estado (se llama con el lock tomado o lo toma aquí)."""
        with self.lock:
            return self._copiar_sin_lock()

    def _copiar_sin_lock(self) -> dict:
        return {
            "disponibles": {rid: r.disponibles for rid, r in self.recursos.items()},
            "totales": {rid: r.total for rid, r in self.recursos.items()},
            "tipos": {rid: r.tipo for rid, r in self.recursos.items()},
            "registrados": {rid: r.prestamos_registrados for rid, r in self.recursos.items()},
            "asignacion": {rid: dict(r.retenedores) for rid, r in self.recursos.items()},
            "esperas": {h: (rid, t) for h, (rid, t) in self.esperas.items()},
            "version": self.version,
        }


class SemaforoRastreado:
    """threading.Semaphore real + registro de aristas del RAG."""

    def __init__(self, rid: str, total: int, estado: EstadoRecursos, tipo: str = "libro"):
        self.rid = rid
        self.total = total
        self.estado = estado
        self._sem = threading.Semaphore(total)
        estado.agregar(rid, total, tipo)

    # ---------- P(S) bloqueante (transacciones) ----------
    def adquirir(self, hilo) -> None:
        """Toma una copia. Bloquea mientras no haya. Puede lanzar TransaccionAbortada."""
        est = self.estado
        with est.lock:                                  # arista de SOLICITUD  Hilo -> Recurso
            est.esperas[hilo.name] = (self.rid, time.monotonic())
            est._cambio()
        try:
            while not self._sem.acquire(timeout=INTERVALO_ABORTO):   # futex(FUTEX_WAIT) en el kernel
                if hilo.abortar.is_set():
                    raise TransaccionAbortada(f"{hilo.motivo_aborto or 'abortado'}; esperaba «{nombre_recurso(self.rid)}»")
        except TransaccionAbortada:
            with est.lock:
                est.esperas.pop(hilo.name, None)
                est._cambio()
            raise
        with est.lock:                                  # la solicitud se convierte en ASIGNACIÓN  Recurso -> Hilo
            est.esperas.pop(hilo.name, None)
            r = est.recursos[self.rid]
            r.disponibles -= 1
            r.retenedores[hilo.name] += 1
            if r.tipo == "libro":
                r.prestamos_registrados += 1
            est._cambio()

    # ---------- P(S) no bloqueante (reservas en línea) ----------
    def intentar(self, hilo) -> bool:
        """Verificar-y-decrementar ATÓMICO: acquire(blocking=False)."""
        if not self._sem.acquire(blocking=False):
            return False
        est = self.estado
        with est.lock:
            r = est.recursos[self.rid]
            r.disponibles -= 1
            r.retenedores[hilo.name] += 1
            r.prestamos_registrados += 1
            est._cambio()
        return True

    # ---------- V(S) ----------
    def liberar(self, hilo) -> None:
        est = self.estado
        with est.lock:
            r = est.recursos[self.rid]
            if r.retenedores.get(hilo.name, 0) <= 0:
                return                                   # nada que liberar (defensivo)
            r.retenedores[hilo.name] -= 1
            if r.retenedores[hilo.name] == 0:
                del r.retenedores[hilo.name]
            r.disponibles += 1
            if r.tipo == "libro":
                r.prestamos_registrados -= 1
            est._cambio()
        self._sem.release()                              # futex(FUTEX_WAKE) si hay hilos esperando

    def valor_interno(self) -> int:
        """Valor actual del contador del semáforo (solo lectura, para verificación)."""
        return self._sem._value


# ---------------------------------------------------------------------------
#  Versión SIN protección (solo para demostrar la condición de carrera)
# ---------------------------------------------------------------------------
def prestar_sin_proteccion(estado: EstadoRecursos, rid: str, hilo, bitacora, punto_pausa=None) -> bool:
    """Préstamo con el patrón verificar-y-actuar SIN semáforo ni lock (INCORRECTO a propósito).

        leido = disponibles          # 1) LEER
        if leido > 0:                # 2) VERIFICAR
            <registrar en bitácora>  #    E/S real: el hilo cede la CPU y otros leen el mismo valor
            disponibles = leido - 1  # 3) ESCRIBIR con un valor posiblemente obsoleto (lost update)
    """
    r = estado.recursos[rid]
    leido = r.disponibles                                # lectura sin exclusión mutua
    hilo.valor_leido = leido
    if punto_pausa:
        punto_pausa()                                    # (solo en modo explicación)
    if leido > 0:
        bitacora.registrar(hilo.name, "RESERVA_SIN_PROTECCION", f"{rid} leido={leido}")
        r.disponibles = leido - 1                        # escritura sin exclusión mutua
        with estado.lock:                                # (el registro de auditoría sí se protege
            r.retenedores[hilo.name] += 1                #  para poder CONTAR cuántos préstamos hubo)
            r.prestamos_registrados += 1
            estado._cambio()
        return True
    return False


def devolver_sin_proteccion(estado: EstadoRecursos, rid: str, hilo) -> None:
    r = estado.recursos[rid]
    leido = r.disponibles
    r.disponibles = leido + 1
    with estado.lock:
        if r.retenedores.get(hilo.name, 0) > 0:
            r.retenedores[hilo.name] -= 1
            if r.retenedores[hilo.name] == 0:
                del r.retenedores[hilo.name]
            r.prestamos_registrados -= 1
        estado._cambio()
