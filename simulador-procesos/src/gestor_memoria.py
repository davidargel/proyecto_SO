import threading

class GestorMemoria:
    """Administra la memoria RAM disponible del sistema simulado."""

    def __init__(self, memoria_total_mb=1024):  # 1 GB = 1024 MB
        self.memoria_total = memoria_total_mb
        self.memoria_usada = 0
        self.lock = threading.Lock()  # Evita que dos procesos modifiquen la memoria al mismo tiempo

    @property
    def memoria_disponible(self):
        return self.memoria_total - self.memoria_usada

    def puede_asignar(self, memoria_requerida):
        return memoria_requerida <= self.memoria_disponible

    def asignar(self, memoria_requerida):
        """Reserva memoria para un proceso. Devuelve True si lo logró."""
        with self.lock:  # Bloquea para que ningún otro hilo interfiera mientras se hace el cálculo
            if self.puede_asignar(memoria_requerida):
                self.memoria_usada += memoria_requerida
                return True
            return False

    def liberar(self, memoria_liberada):
        """Libera memoria cuando un proceso termina."""
        with self.lock:
            self.memoria_usada -= memoria_liberada