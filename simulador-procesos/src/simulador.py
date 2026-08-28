import threading
import time
import queue

class Simulador:
    """Coordina la ejecución de procesos, la cola de espera y la memoria."""

    def __init__(self, gestor_memoria):
        self.gestor_memoria = gestor_memoria
        self.cola_espera = queue.Queue()   # Procesos esperando memoria disponible
        self.procesos_ejecutando = []      # Lista de procesos actualmente corriendo
        self.lock_lista = threading.Lock() # Protege la lista de procesos_ejecutando

        self.eventos = queue.Queue()       # Mensajes de eventos (para la interfaz gráfica o consola)

    def agregar_proceso(self, proceso):
        """Agrega un proceso nuevo al sistema."""
        self.cola_espera.put(proceso)
        self.eventos.put(f"Proceso agregado a la cola: {proceso}")


    def agregar_proceso(self, proceso):
        """Agrega un proceso nuevo al sistema. Se intenta ejecutar de inmediato."""
        self.cola_espera.put(proceso)
        print(f"Proceso agregado a la cola: {proceso}")


    def _ejecutar_proceso(self, proceso):
        """Esta función corre en un hilo (thread) separado por cada proceso."""
        proceso.estado = "ejecutando"
        with self.lock_lista:
            self.procesos_ejecutando.append(proceso)

        self.eventos.put(f"▶ Ejecutando {proceso}")

        print(f"▶ Ejecutando {proceso}")

        time.sleep(proceso.duracion)  # Simula el tiempo que tarda el proceso en correr

        # Al terminar: liberar memoria y sacar de la lista de ejecución
        self.gestor_memoria.liberar(proceso.memoria_requerida)
        proceso.estado = "finalizado"
        with self.lock_lista:
            self.procesos_ejecutando.remove(proceso)

        self.eventos.put(f"✔ Finalizó {proceso} | Memoria disponible: {self.gestor_memoria.memoria_disponible}MB")

    def procesar_cola(self):
        """Revisa la cola e intenta asignar memoria a los procesos esperando."""

        print(f"✔ Finalizó {proceso} | Memoria disponible: {self.gestor_memoria.memoria_disponible}MB")

    def procesar_cola(self):
        """Revisa la cola constantemente e intenta asignar memoria a los procesos esperando."""

        pendientes = []

        while not self.cola_espera.empty():
            proceso = self.cola_espera.get()

            if self.gestor_memoria.asignar(proceso.memoria_requerida):

                hilo = threading.Thread(target=self._ejecutar_proceso, args=(proceso,))
                hilo.start()
            else:
                pendientes.append(proceso)


                # Si hay memoria, se lanza un hilo nuevo para ese proceso
                hilo = threading.Thread(target=self._ejecutar_proceso, args=(proceso,))
                hilo.start()
        else:
            
                # Si no hay memoria todavía, se queda esperando
                pendientes.append(proceso)
            
        # Los que no pudieron ejecutarse regresan a la cola
        for p in pendientes:
            self.cola_espera.put(p)

    def mostrar_estado(self):

        """Muestra el estado del sistema en consola (usado por main.py)."""

        print("\n===== ESTADO DEL SISTEMA =====")
        print(f"Memoria total: {self.gestor_memoria.memoria_total}MB")
        print(f"Memoria usada: {self.gestor_memoria.memoria_usada}MB")
        print(f"Memoria disponible: {self.gestor_memoria.memoria_disponible}MB")

        with self.lock_lista:
            print(f"\nProcesos en ejecución ({len(self.procesos_ejecutando)}):")
            for p in self.procesos_ejecutando:
                print(f"  {p}")

        print(f"\nProcesos en cola de espera ({self.cola_espera.qsize()}):")
        for p in list(self.cola_espera.queue):
            print(f"  {p}")
        print("===============================\n")