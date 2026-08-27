import time
from src.proceso import Proceso
from src.gestor_memoria import GestorMemoria
from src.simulador import Simulador


def crear_procesos_ejemplo():
    """Procesos predefinidos para probar el sistema rápidamente."""
    return [
        Proceso(memoria_requerida=300, duracion=5, nombre="navegador"),
        Proceso(memoria_requerida=400, duracion=8, nombre="editor_video"),
        Proceso(memoria_requerida=350, duracion=4),
        Proceso(memoria_requerida=200, duracion=6),
        Proceso(memoria_requerida=500, duracion=3),
    ]


def pedir_proceso_manual():
    """Le pregunta al usuario los datos de un proceso nuevo por teclado."""
    print("\n--- Nuevo proceso ---")
    nombre = input("Nombre del proceso (Enter para autogenerar): ").strip()
    nombre = nombre if nombre else None  # Si dejó vacío, Proceso le pone uno random

    while True:
        try:
            memoria = int(input("Memoria requerida en MB: "))
            break
        except ValueError:
            print("Por favor ingresa un número válido.")

    while True:
        try:
            duracion = int(input("Duración en segundos: "))
            break
        except ValueError:
            print("Por favor ingresa un número válido.")

    return Proceso(memoria_requerida=memoria, duracion=duracion, nombre=nombre)


def menu_inicial(procesos):
    """Menú antes de arrancar la simulación: agregar más procesos o iniciar."""
    while True:
        print("\n===== MENÚ =====")
        print("1. Agregar un proceso")
        print("2. Ver procesos cargados")
        print("3. Iniciar simulación")
        opcion = input("Elige una opción: ").strip()

        if opcion == "1":
            procesos.append(pedir_proceso_manual())
            print("Proceso agregado correctamente.")
        elif opcion == "2":
            print(f"\nProcesos cargados ({len(procesos)}):")
            for p in procesos:
                print(f"  {p}")
        elif opcion == "3":
            break
        else:
            print("Opción inválida, intenta de nuevo.")


def main():
    gestor = GestorMemoria(memoria_total_mb=1024)  # 1 GB
    simulador = Simulador(gestor)

    # Cargamos procesos de ejemplo para tener algo con qué probar de inmediato
    procesos = crear_procesos_ejemplo()

    # El usuario puede revisar, agregar más, y decidir cuándo iniciar
    menu_inicial(procesos)

    for p in procesos:
        simulador.agregar_proceso(p)

    print("\nIniciando simulación...\n")

    # Bucle principal: intenta asignar memoria y muestra el estado periódicamente
    for _ in range(15):  # subí un poco el rango por si agregaron procesos largos
        simulador.procesar_cola()
        simulador.mostrar_estado()
        time.sleep(1)


if __name__ == "__main__":
    main()