"""
pasos.py — "Modo Explicación (Pausas)".

Son puntos de control didácticos, equivalentes a los breakpoints de un depurador:
el hilo que llega a un checkpoint espera en una threading.Condition (futex real) hasta que
el expositor presiona "Continuar Siguiente Paso". No cambian el ORDEN en que cada hilo pide
sus recursos ni deciden quién gana un semáforo; solo congelan la ejecución para poder
explicar el estado. Con "Continuar sin pausas" el motor corre libremente y los mismos
fenómenos (carrera, espera circular) aparecen por sí solos.

Checkpoint 1: después de tomar la PRIMERA copia (o, en la prueba de carrera, después de leer el contador).
Checkpoint 2: después del COMMIT (la transacción ya retiene todo: fin de la fase de crecimiento).
              Solo en el escenario normal; en el modo caótico, después del checkpoint 1 los hilos
              corren libres y el siguiente alto lo marca el propio interbloqueo (o el fin de la oleada).
"""
import threading

from .recursos import TransaccionAbortada


class ControlPasos:
    def __init__(self, motor):
        self.motor = motor
        self.cond = threading.Condition()
        self.fase_permitida = 0
        self.detenidos = {}             # nombre_hilo -> número de checkpoint
        self.esperando_usuario = False  # hay una pausa mostrada en pantalla
        self.paso_mostrado = 0
        self._autoriza_recuperacion = False
        self._ticks_quieto = 0

    def reiniciar(self):
        with self.cond:
            self.fase_permitida = 0
            self.detenidos.clear()
            self.esperando_usuario = False
            self.paso_mostrado = 0
            self._autoriza_recuperacion = False
            self._ticks_quieto = 0
            self.cond.notify_all()

    def nueva_oleada(self):
        with self.cond:
            self.fase_permitida = 0
            self.esperando_usuario = False
            self.paso_mostrado = 0
            self._ticks_quieto = 0

    def activo(self) -> bool:
        return bool(self.motor.config["pausas"])

    def checkpoint(self, hilo, n: int) -> None:
        with self.cond:
            if not self.activo() or self.fase_permitida >= n:
                return
            self.detenidos[hilo.name] = n
            while self.activo() and self.fase_permitida < n and not hilo.abortar.is_set():
                self.cond.wait(0.5)
            self.detenidos.pop(hilo.name, None)
        if hilo.abortar.is_set():
            raise TransaccionAbortada(hilo.motivo_aborto or "reinicio")

    def continuar(self) -> None:
        with self.cond:
            self.esperando_usuario = False
            self.fase_permitida = max(self.fase_permitida, self.paso_mostrado)
            self._ticks_quieto = 0
            self.cond.notify_all()

    def liberar_todo(self) -> None:
        """'Continuar sin pausas' o reinicio: suelta a todos los hilos detenidos."""
        with self.cond:
            self.esperando_usuario = False
            self._ticks_quieto = 0
            self.cond.notify_all()

    def autorizar_recuperacion(self) -> None:
        self._autoriza_recuperacion = True

    def recuperacion_autorizada(self) -> bool:
        return self._autoriza_recuperacion
