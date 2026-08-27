import random

# Lista de nombres para generar procesos automáticamente si no se especifica uno
NOMBRES_GENERICOS = ["navegador", "editor", "compilador", "antivirus", "juego", "musica", "video", "backup"]

class Proceso:
    """Representa un proceso que va a competir por memoria y CPU."""

    contador_pid = 1  # Variable de clase: se comparte entre todos los procesos para dar PIDs únicos

    def __init__(self, memoria_requerida, duracion, nombre=None):
        self.pid = Proceso.contador_pid
        Proceso.contador_pid += 1  # El siguiente proceso tendrá un PID distinto

        self.nombre = nombre if nombre else f"{random.choice(NOMBRES_GENERICOS)}_{self.pid}"
        self.memoria_requerida = memoria_requerida  # en MB
        self.duracion = duracion  # en segundos
        self.estado = "en_cola"  # puede ser: en_cola, ejecutando, finalizado

    def __str__(self):
        return f"[PID {self.pid}] {self.nombre} | {self.memoria_requerida}MB | {self.duracion}s | Estado: {self.estado}"