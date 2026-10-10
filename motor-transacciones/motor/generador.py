"""
generador.py — Cola de peticiones entrantes y generador de solicitudes (T_Generador).

Patrón productor–consumidor:
    usuarios (simulados)  --put-->  queue.Queue (cola de peticiones)  --get-->  T_Generador  --start-->  hilo por solicitud

Cada usuario elige qué libros quiere y EN QUÉ ORDEN los pide (aleatorio, como en la vida real).
  * Modo normal : el hilo reordena los libros por ISBN antes de pedirlos.
  * Modo caótico: el hilo respeta el orden que trae la solicitud de la cola.
El generador no sabe cuándo habrá un interbloqueo: si una oleada termina sin ciclo,
simplemente toma la siguiente oleada de la cola.
"""
import queue
import random
import threading

from .catalogo import CATALOGO, SUCURSALES, ISBN_CARRERA, POR_ISBN
from .kernel import nombrar_hilo_so, tid_actual
from .transacciones import HiloPrestamo, HiloReservaEnLinea

USUARIOS_POR_OLEADA = 6
MAX_OLEADAS_CAOS = 6
RESERVAS_CARRERA = 12


def generar_oleada(escenario: str, primer_numero: int, rng: random.Random) -> list:
    """Crea las solicitudes que los usuarios dejan en la cola (hora pico)."""
    populares = [t.isbn for t in CATALOGO if t.popular]
    todos = [t.isbn for t in CATALOGO]
    solicitudes = []
    for i in range(USUARIOS_POR_OLEADA):
        num = primer_numero + i
        if escenario == "deadlock":
            # semana de parciales: todos quieren los títulos de 1 sola copia
            k = 2 if rng.random() < 0.85 else 3
            base = rng.sample(populares, 2)
            if k == 3:
                base.append(rng.choice([x for x in todos if x not in base]))
            libros = base
        else:
            k = rng.choice([2, 2, 3])
            libros = [rng.choice(populares)]
            libros += rng.sample([x for x in todos if x not in libros], k - 1)
        rng.shuffle(libros)                       # el orden lo decide el usuario
        solicitudes.append({
            "id": num,
            "hilo": f"T_Usuario{num:02d}",
            "sucursal": rng.choice(SUCURSALES),
            "libros": libros,
            "duracion": round(rng.uniform(1.5, 3.0), 2),   # periodo de préstamo simulado (segundos)
            "intento": 1,
        })
    return solicitudes


class HiloGenerador(threading.Thread):
    def __init__(self, motor, escenario: str, semilla=None):
        super().__init__(name="T_Generador", daemon=True)
        self.motor = motor
        self.escenario = escenario
        self.cancelar = threading.Event()
        self.rng = random.Random(semilla)
        self.tid = None
        self.barrera = None

    def run(self):
        self.tid = tid_actual()
        nombrar_hilo_so(self.name)
        m = self.motor
        try:
            if self.escenario == "carrera":
                self._carrera()
            else:
                self._prestamos()
        except Exception as e:  # pragma: no cover
            m.log(self.name, f"Error en el generador: {e!r}", "error")
        finally:
            m.escenario_finalizado(self.escenario, cancelado=self.cancelar.is_set(), gen=self)

    # ------------------------------------------------------------------
    def _prestamos(self):
        m = self.motor
        ordenar = self.escenario == "normal"
        max_oleadas = 1 if ordenar else MAX_OLEADAS_CAOS
        siguiente_num = 1
        for oleada in range(1, max_oleadas + 1):
            if self.cancelar.is_set():
                return
            m.escenario["oleada"] = oleada
            solicitudes = generar_oleada(self.escenario, siguiente_num, self.rng)
            siguiente_num += len(solicitudes)
            for s in solicitudes:
                m.cola_peticiones.put(s)
            detalle = "; ".join(f"{s['hilo']}: " + "→".join(POR_ISBN[i].corto for i in s["libros"]) for s in solicitudes)
            m.log(self.name, f"Oleada {oleada}: {len(solicitudes)} solicitudes en la cola de peticiones "
                             f"({'se ordenarán por ISBN' if ordenar else 'orden original de la cola — MODO CAÓTICO'}). {detalle}",
                  "sistema")
            self.barrera = threading.Barrier(len(solicitudes))
            m.barrera_actual = self.barrera
            lanzados = 0
            diferidas = []          # reintentos de víctimas: esperan a que el sistema quede libre
            while not self.cancelar.is_set():
                try:
                    s = m.cola_peticiones.get(timeout=0.1)
                except queue.Empty:
                    vivas = m.transacciones_vivas()
                    if vivas == 0 and diferidas:
                        # Política anti-inanición: la víctima se reintenta cuando ya no queda nadie
                        # compitiendo y pidiendo en orden de ISBN => no puede volver a formar un ciclo.
                        for r in diferidas:
                            m.log(self.name, f"Reintento de {r['hilo']} con el sistema libre y en orden de ISBN "
                                             "(evita inanición y un nuevo ciclo)", "sistema")
                            m.lanzar(HiloPrestamo(m, r, True, None, checkpoint_commit=False))
                        diferidas = []
                        continue
                    if vivas == 0 and m.cola_peticiones.empty():
                        break
                    continue
                if s["intento"] > 1:
                    diferidas.append(s)
                    continue
                usa_barrera = lanzados < len(solicitudes)
                m.lanzar(HiloPrestamo(m, s, ordenar, self.barrera if usa_barrera else None,
                                      checkpoint_commit=ordenar))
                lanzados += 1
            if self.cancelar.is_set() or ordenar or m.deadlocks_escenario > 0:
                return
            m.log(self.name, f"Oleada {oleada} terminó sin interbloqueo: se toma la siguiente oleada de la cola.", "info")
            m.oleada_sin_ciclo()

    def _carrera(self):
        m = self.motor
        protegido = bool(m.config["proteccion"])
        t = POR_ISBN[ISBN_CARRERA]
        m.carrera.update({"protegido": protegido, "hilos": RESERVAS_CARRERA, "titulo": t.corto,
                          "copias": t.copias, "exitos": 0, "rechazos": 0, "valores_leidos": set()})
        m.log(self.name, f"Prueba de carrera: {RESERVAS_CARRERA} reservas en línea simultáneas de «{t.corto}» "
                         f"({t.copias} copias) — {'CON semáforo' if protegido else 'SIN protección'}", "sistema")
        self.barrera = threading.Barrier(RESERVAS_CARRERA)
        m.barrera_actual = self.barrera
        for i in range(RESERVAS_CARRERA):
            m.lanzar(HiloReservaEnLinea(m, f"T_Reserva{i + 1:02d}", SUCURSALES[i % len(SUCURSALES)],
                                        self.barrera, protegido))
        while not self.cancelar.is_set() and m.carrera["exitos"] + m.carrera["rechazos"] < RESERVAS_CARRERA:
            self.cancelar.wait(0.05)
