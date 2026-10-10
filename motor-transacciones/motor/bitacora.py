"""
bitacora.py — Bitácora de préstamos (Write-Ahead Log).

Cada paso de una transacción (BEGIN, ADQUIRIDO, COMMIT, ABORT, ROLLBACK, DEVUELTO)
se escribe en disco ANTES de continuar, como en un gestor de bases de datos.
Gracias a eso el hilo guardián puede revertir (rollback) una transacción víctima
sabiendo exactamente qué copias había tomado.

Detalle importante para el proyecto: os.write() y os.fsync() son llamadas al sistema
reales; mientras el hilo espera al disco, el intérprete de Python libera el GIL y el
planificador de Linux ejecuta otros hilos. Esa E/S genuina es la que abre la ventana
donde aparecen las condiciones de carrera y los cruces de solicitudes: no se usa
time.sleep() para provocar nada.
"""
import os
import threading
from datetime import datetime


class Bitacora:
    def __init__(self, ruta: str, durable: bool = True):
        os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
        self.ruta = ruta
        self.durable = durable
        # O_APPEND: cada write() se agrega al final de forma atómica (no hace falta un lock).
        self.fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        self._cerrada = False

    def registrar(self, hilo: str, evento: str, detalle: str = "") -> None:
        if self._cerrada:
            return
        linea = (f"{datetime.now().isoformat(timespec='milliseconds')}|pid={os.getpid()}"
                 f"|tid={threading.get_native_id()}|{hilo}|{evento}|{detalle}\n")
        try:
            os.write(self.fd, linea.encode("utf-8"))   # syscall write(2)
            if self.durable:
                os.fsync(self.fd)                      # syscall fsync(2): fuerza a disco
        except OSError:
            pass

    def marcar(self, texto: str) -> None:
        self.registrar("MOTOR", "INFO", texto)

    def cerrar(self) -> None:
        if not self._cerrada:
            self._cerrada = True
            try:
                os.close(self.fd)
            except OSError:
                pass
