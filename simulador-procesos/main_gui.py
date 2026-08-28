from src.gestor_memoria import GestorMemoria
from src.simulador import Simulador
from src.interfaz_grafica import SimuladorGUI
from src.proceso import Proceso


def cargar_procesos_ejemplo(simulador):
    """Carga procesos de prueba para tener algo con qué probar de inmediato."""
    ejemplos = [
        Proceso(memoria_requerida=300, duracion=50, nombre="navegador"),
        Proceso(memoria_requerida=400, duracion=80, nombre="editor_video"),
        Proceso(memoria_requerida=350, duracion=40),
        Proceso(memoria_requerida=200, duracion=60),
        Proceso(memoria_requerida=500, duracion=30),
    ]
    for p in ejemplos:
        simulador.agregar_proceso(p)


def main():
    gestor = GestorMemoria(memoria_total_mb=1024)  # 1 GB
    simulador = Simulador(gestor)
    cargar_procesos_ejemplo(simulador)

    app = SimuladorGUI(simulador)
    app.mainloop()


if __name__ == "__main__":
    main()