import tkinter as tk
from tkinter import ttk, messagebox
from src.proceso import Proceso


class SimuladorGUI(tk.Tk):
    """Ventana principal del simulador, construida con tkinter."""

    def __init__(self, simulador):
        super().__init__()
        self.simulador = simulador
        self.gestor = simulador.gestor_memoria

        self.title("Simulador de Gestión de Procesos en Memoria")
        self.geometry("850x650")

        self._crear_widgets()
        self._actualizar_ciclo()  # Arranca el bucle que refresca la pantalla

    def _crear_widgets(self):
        # --- Barra de memoria ---
        frame_memoria = ttk.LabelFrame(self, text="Estado de la memoria RAM")
        frame_memoria.pack(fill="x", padx=10, pady=10)

        self.label_memoria = ttk.Label(frame_memoria, text="", font=("Segoe UI", 10))
        self.label_memoria.pack(anchor="w", padx=10, pady=(5, 0))

        self.canvas_barra = tk.Canvas(frame_memoria, height=25, bg="white",
                                       highlightthickness=1, highlightbackground="gray")
        self.canvas_barra.pack(fill="x", padx=10, pady=(0, 10))

        # --- Tablas de procesos ---
        frame_tablas = ttk.Frame(self)
        frame_tablas.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columnas = ("PID", "Nombre", "Memoria (MB)", "Duración (s)")

        frame_ejec = ttk.LabelFrame(frame_tablas, text="Procesos en ejecución")
        frame_ejec.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.tabla_ejecucion = ttk.Treeview(frame_ejec, columns=columnas, show="headings", height=8)
        for col in columnas:
            self.tabla_ejecucion.heading(col, text=col)
            self.tabla_ejecucion.column(col, width=100, anchor="center")
        self.tabla_ejecucion.pack(fill="both", expand=True, padx=5, pady=5)

        frame_cola = ttk.LabelFrame(frame_tablas, text="Procesos en cola de espera")
        frame_cola.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.tabla_cola = ttk.Treeview(frame_cola, columns=columnas, show="headings", height=8)
        for col in columnas:
            self.tabla_cola.heading(col, text=col)
            self.tabla_cola.column(col, width=100, anchor="center")
        self.tabla_cola.pack(fill="both", expand=True, padx=5, pady=5)

        # --- Registro de eventos ---
        frame_log = ttk.LabelFrame(self, text="Registro de eventos")
        frame_log.pack(fill="both", expand=False, padx=10, pady=(0, 10))
        self.texto_log = tk.Text(frame_log, height=7, state="disabled", wrap="word")
        self.texto_log.pack(fill="both", expand=True, padx=5, pady=5)

        # --- Formulario para agregar procesos ---
        frame_form = ttk.LabelFrame(self, text="Agregar nuevo proceso")
        frame_form.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Label(frame_form, text="Nombre (opcional):").grid(row=0, column=0, padx=5, pady=8, sticky="w")
        self.entry_nombre = ttk.Entry(frame_form, width=15)
        self.entry_nombre.grid(row=0, column=1, padx=5, pady=8)

        ttk.Label(frame_form, text="Memoria (MB):").grid(row=0, column=2, padx=5, pady=8, sticky="w")
        self.entry_memoria = ttk.Entry(frame_form, width=10)
        self.entry_memoria.grid(row=0, column=3, padx=5, pady=8)

        ttk.Label(frame_form, text="Duración (s):").grid(row=0, column=4, padx=5, pady=8, sticky="w")
        self.entry_duracion = ttk.Entry(frame_form, width=10)
        self.entry_duracion.grid(row=0, column=5, padx=5, pady=8)

        ttk.Button(frame_form, text="Agregar proceso", command=self._agregar_proceso).grid(
            row=0, column=6, padx=10, pady=8)

    def _agregar_proceso(self):
        nombre = self.entry_nombre.get().strip() or None

        try:
            memoria = int(self.entry_memoria.get())
            duracion = int(self.entry_duracion.get())
        except ValueError:
            messagebox.showerror("Datos inválidos", "Memoria y duración deben ser números enteros.")
            return

        if memoria <= 0 or duracion <= 0:
            messagebox.showerror("Datos inválidos", "Memoria y duración deben ser mayores a cero.")
            return

        proceso = Proceso(memoria_requerida=memoria, duracion=duracion, nombre=nombre)
        self.simulador.agregar_proceso(proceso)

        self.entry_nombre.delete(0, tk.END)
        self.entry_memoria.delete(0, tk.END)
        self.entry_duracion.delete(0, tk.END)

    def _dibujar_barra_memoria(self):
        self.canvas_barra.delete("all")
        ancho_total = self.canvas_barra.winfo_width() or 800
        alto = 25

        usada = self.gestor.memoria_usada
        total = self.gestor.memoria_total
        porcentaje = usada / total if total else 0
        ancho_usado = int(ancho_total * porcentaje)

        if porcentaje < 0.7:
            color = "#4CAF50"   # verde: memoria tranquila
        elif porcentaje < 0.9:
            color = "#FFC107"   # amarillo: memoria ocupada
        else:
            color = "#F44336"   # rojo: memoria casi llena

        self.canvas_barra.create_rectangle(0, 0, ancho_usado, alto, fill=color, outline="")
        self.canvas_barra.create_text(
            ancho_total // 2, alto // 2,
            text=f"{usada}MB / {total}MB ({porcentaje * 100:.1f}%)"
        )

    def _actualizar_tablas(self):
        for fila in self.tabla_ejecucion.get_children():
            self.tabla_ejecucion.delete(fila)
        for fila in self.tabla_cola.get_children():
            self.tabla_cola.delete(fila)

        with self.simulador.lock_lista:
            procesos_ejecutando = list(self.simulador.procesos_ejecutando)

        for p in procesos_ejecutando:
            self.tabla_ejecucion.insert("", "end", values=(p.pid, p.nombre, p.memoria_requerida, p.duracion))

        for p in list(self.simulador.cola_espera.queue):
            self.tabla_cola.insert("", "end", values=(p.pid, p.nombre, p.memoria_requerida, p.duracion))

    def _procesar_eventos_log(self):
        while not self.simulador.eventos.empty():
            mensaje = self.simulador.eventos.get()
            self.texto_log.config(state="normal")
            self.texto_log.insert(tk.END, mensaje + "\n")
            self.texto_log.see(tk.END)
            self.texto_log.config(state="disabled")

    def _actualizar_ciclo(self):
        """Se ejecuta cada 500ms: procesa la cola, refresca tablas, barra y log."""
        self.simulador.procesar_cola()
        self._actualizar_tablas()
        self._dibujar_barra_memoria()
        self._procesar_eventos_log()

        disponible = self.gestor.memoria_disponible
        usada = self.gestor.memoria_usada
        total = self.gestor.memoria_total
        self.label_memoria.config(
            text=f"Memoria disponible: {disponible}MB   |   Memoria usada: {usada}MB de {total}MB"
        )

        self.after(500, self._actualizar_ciclo)  # se vuelve a llamar a sí misma cada 500ms