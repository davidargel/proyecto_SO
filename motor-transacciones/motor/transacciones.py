"""
transacciones.py — Hilos REALES del sistema operativo que ejecutan las transacciones.

Cada solicitud de préstamo es un threading.Thread. En Linux, CPython crea cada uno con
pthread_create() -> clone(), es decir, un hilo NPTL con su propio TID (LWP) visible en:
    ps -eLf | grep app.py        ls /proc/<PID>/task        htop -p <PID>  (tecla H)

HiloPrestamo (transacción combinada, 2PL):
    estación -> copia 1 -> copia 2 [-> copia 3] -> COMMIT -> (periodo de préstamo) -> devolución
    - Modo normal : pide los libros en ORDEN ASCENDENTE DE ISBN (prevención: rompe la espera circular).
    - Modo caótico: pide los libros en el ORDEN EN QUE VIENEN EN LA COLA (el que eligió el usuario).
      Si dos solicitudes se cruzan (A->B y B->A) la espera circular surge sola.

HiloReservaEnLinea (prueba de condición de carrera):
    reserva de 1 copia de un título muy solicitado desde varias sucursales a la vez,
    con semáforo (acquire no bloqueante, atómico) o SIN protección (verificar-y-actuar).
"""
import os
import threading
import time

from .catalogo import ID_ESTACIONES, ISBN_CARRERA, nombre_recurso
from .kernel import nombrar_hilo_so, tid_actual
from .recursos import TransaccionAbortada, prestar_sin_proteccion


class HiloTransaccion(threading.Thread):
    rol = "transaccion"

    def __init__(self, motor, nombre, barrera=None):
        super().__init__(name=nombre, daemon=True)
        self.motor = motor
        self.barrera = barrera
        self.abortar = threading.Event()        # señal del watchdog (o del reinicio)
        self.tid = None
        self.estado_logico = "CREADO"
        self.detalle = ""
        self.retenidos = []                     # pila de recursos tomados (para devolver/rollback)
        self.inicio = time.monotonic()
        self.valor_leido = None
        self.motivo_aborto = ""

    def _estado(self, estado, detalle=""):
        self.estado_logico = estado
        self.detalle = detalle

    def _esperar_apertura(self):
        """Barrera de 'hora pico': todas las solicitudes de la oleada llegan al mismo tiempo.
        Es una primitiva de sincronización real (threading.Barrier), no una pausa artificial."""
        if self.barrera is None:
            return
        self._estado("EN COLA", "apertura de ventanilla")
        try:
            self.barrera.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        if self.abortar.is_set():
            raise TransaccionAbortada("cancelado antes de iniciar")


class HiloPrestamo(HiloTransaccion):
    rol = "prestamo"

    def __init__(self, motor, solicitud, ordenar, barrera=None, checkpoint_commit=None):
        super().__init__(motor, solicitud["hilo"], barrera)
        self.solicitud = solicitud
        self.ordenar = ordenar
        self.checkpoint_commit = ordenar if checkpoint_commit is None else checkpoint_commit
        libros = list(solicitud["libros"])
        self.orden = sorted(libros) if ordenar else libros

    def run(self):
        m = self.motor
        self.tid = tid_actual()
        nombrar_hilo_so(self.name)
        m.hilo_iniciado(self)
        try:
            self._esperar_apertura()
            cortos = " → ".join(f"«{nombre_recurso(i)}»" for i in self.orden)
            criterio = "orden ascendente de ISBN" if self.ordenar else "orden original de la cola"
            m.log(self.name, f"INICIANDO transacción (PID {os.getpid()}, LWP/TID {self.tid}) · sucursal "
                             f"{self.solicitud['sucursal']} · pide {cortos} [{criterio}]")

            # --- Estación de préstamo (semáforo contador de NUM_ESTACIONES) ---
            self._estado("ESPERANDO", "Estaciones")
            m.estaciones.adquirir(self)
            self.retenidos.append(ID_ESTACIONES)
            m.bitacora.registrar(self.name, "BEGIN", ",".join(self.orden))

            # --- FASE DE CRECIMIENTO (2PL): solo se adquiere ---
            for k, isbn in enumerate(self.orden):
                corto = nombre_recurso(isbn)
                self._estado("ESPERANDO", corto)
                duenos = m.retenedores_de(isbn)
                if duenos and m.estado.recursos[isbn].disponibles <= 0:
                    m.log(self.name, f"Solicitando copia de «{corto}» (retenida por {', '.join(duenos)}) → sem.acquire()")
                else:
                    m.log(self.name, f"Solicitando copia de «{corto}» → sem.acquire()")
                m.recursos[isbn].adquirir(self)                   # P(S): puede bloquear en futex
                self.retenidos.append(isbn)
                m.bitacora.registrar(self.name, "ADQUIRIDO", isbn)  # WAL + fsync (E/S real)
                m.log(self.name, f"Copia de «{corto}» ADQUIRIDA ({k + 1}/{len(self.orden)})", "ok")
                self._estado("RETIENE", ", ".join(nombre_recurso(r) for r in self.retenidos if r != ID_ESTACIONES))
                if k == 0:
                    m.pasos.checkpoint(self, 1)                   # punto de explicación (solo modo pausas)
                if self.abortar.is_set():
                    raise TransaccionAbortada(self.motivo_aborto or "abortado")

            # --- COMMIT ---
            libros = [r for r in self.retenidos if r != ID_ESTACIONES]
            m.bitacora.registrar(self.name, "COMMIT", ",".join(libros))
            m.estaciones.liberar(self)
            self.retenidos.remove(ID_ESTACIONES)
            m.transaccion_completada(self)
            m.log(self.name, "COMMIT: préstamo registrado en la bitácora; estación liberada", "ok")
            if self.checkpoint_commit:          # checkpoint 2 solo en el escenario normal (fin del growing phase)
                m.pasos.checkpoint(self, 2)

            # --- Periodo de préstamo (tiempo simulado de lectura; fuera de toda adquisición) ---
            self._estado("PRÉSTAMO ACTIVO", ", ".join(nombre_recurso(r) for r in libros))
            self.abortar.wait(self.solicitud["duracion"])

            # --- FASE DE DECRECIMIENTO (2PL): devolución en orden inverso ---
            self._estado("DEVOLVIENDO", "")
            for isbn in reversed(libros):
                m.recursos[isbn].liberar(self)                    # V(S): despierta a quien espera
                self.retenidos.remove(isbn)
                m.bitacora.registrar(self.name, "DEVUELTO", isbn)
            m.log(self.name, "Devolución completada: las copias regresan a la estantería (release = V)")
            self._estado("TERMINADO")
        except TransaccionAbortada as e:
            self._rollback(str(e))
        except Exception as e:  # pragma: no cover
            m.log(self.name, f"Error inesperado: {e!r}", "error")
            self._rollback("error")
        finally:
            m.hilo_terminado(self)

    def _rollback(self, motivo):
        m = self.motor
        self._estado("ROLLBACK", motivo)
        m.bitacora.registrar(self.name, "ABORT", motivo)
        if self.retenidos:
            m.log(self.name, f"ABORT recibido ({motivo}). Ejecutando ROLLBACK según la bitácora…", "alerta")
        for rid in reversed(list(self.retenidos)):
            m.recurso(rid).liberar(self)
            self.retenidos.remove(rid)
            m.bitacora.registrar(self.name, "ROLLBACK", rid)
            m.log(self.name, f"ROLLBACK: libera «{nombre_recurso(rid)}» (release = V)", "alerta")
        self._estado("ABORTADO", motivo)
        m.transaccion_abortada(self, motivo)


class HiloReservaEnLinea(HiloTransaccion):
    rol = "reserva"

    def __init__(self, motor, nombre, sucursal, barrera, protegido):
        super().__init__(motor, nombre, barrera)
        self.sucursal = sucursal
        self.protegido = protegido
        self.exito = None

    def run(self):
        m = self.motor
        self.tid = tid_actual()
        nombrar_hilo_so(self.name)
        m.hilo_iniciado(self)
        rid = ISBN_CARRERA
        corto = nombre_recurso(rid)
        try:
            self._esperar_apertura()
            self._estado("RESERVANDO", corto)
            if self.protegido:
                ok = m.recursos[rid].intentar(self)               # acquire(blocking=False): atómico
                if ok:
                    self.retenidos.append(rid)
                    m.bitacora.registrar(self.name, "RESERVA", rid)
                m.pasos.checkpoint(self, 1)
                m.log(self.name, (f"[{self.sucursal}] sem.acquire(blocking=False) = True → RESERVA de «{corto}» OK"
                                  if ok else
                                  f"[{self.sucursal}] sem.acquire(blocking=False) = False → RECHAZADA: no quedan copias"),
                      "ok" if ok else "info")
            else:
                ok = prestar_sin_proteccion(m.estado, rid, self, m.bitacora,
                                            punto_pausa=lambda: m.pasos.checkpoint(self, 1))
                if ok:
                    self.retenidos.append(rid)
                m.log(self.name, (f"[{self.sucursal}] leyó disponibles = {self.valor_leido} → escribió "
                                  f"{self.valor_leido - 1} → RESERVA registrada SIN protección"
                                  if ok else
                                  f"[{self.sucursal}] leyó disponibles = {self.valor_leido} → rechazada"),
                      "alerta" if ok else "info")
            self.exito = ok
            m.resultado_reserva(self, ok)
            if ok:
                self._estado("PRÉSTAMO ACTIVO", corto)
                self.abortar.wait()                               # conserva la copia hasta reiniciar
            else:
                self._estado("RECHAZADA", corto)
        except TransaccionAbortada:
            if self.exito is None:
                m.resultado_reserva(self, False)
        finally:
            m.hilo_terminado(self)
