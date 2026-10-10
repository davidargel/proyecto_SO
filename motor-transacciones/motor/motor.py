"""
motor.py — Orquestador del Motor de Transacciones Concurrentes.

Reúne: recursos (semáforos), hilo guardián, generador de solicitudes, modo explicación,
bitácora y la construcción del estado que el frontend dibuja (snapshot). El frontend
NO tiene datos propios: todo lo que muestra sale de snapshot().
"""
import queue
import threading
import time
from collections import Counter, deque
from datetime import datetime

from . import explicaciones as ex
from . import rag
from .bitacora import Bitacora
from .catalogo import CATALOGO, ID_ESTACIONES, ISBN_CARRERA, NUM_ESTACIONES, POR_ISBN, nombre_recurso
from .generador import HiloGenerador
from .kernel import info_sistema, leer_info_hilo, listar_tareas
from .pasos import ControlPasos
from .recursos import EstadoRecursos, SemaforoRastreado
from .watchdog import HiloGuardian

ESCENARIOS = {
    "normal": "ESCENARIO 1: Ejecución concurrente normal (protegida, orden por ISBN)",
    "deadlock": "ESCENARIO 2: Modo caótico — inyección de interbloqueo",
    "carrera": "ESCENARIO 3: Prueba de condición de carrera",
}


class Motor:
    def __init__(self, ruta_bitacora="bitacora/prestamos.wal", durable=True, eco_consola=True):
        self.sistema = info_sistema()
        self.config = {"pausas": False, "proteccion": True, "auto_recuperacion": False}
        self.bitacora = Bitacora(ruta_bitacora, durable)
        self.eco_consola = eco_consola

        self._reg_lock = threading.Lock()
        self._ctrl_lock = threading.RLock()
        self.hilos = {}                          # transacciones vivas: nombre -> hilo
        self.hilos_sistema = {}                  # nombre -> threading.Thread (watchdog, generador, broadcast)

        self._log_lock = threading.Lock()
        self.logs = deque(maxlen=800)
        self._log_seq = 0

        self.metricas = Counter()
        self.escenario = {"nombre": None, "titulo": "", "corriendo": False, "oleada": 0, "inicio": None, "fin": None}
        self.deadlocks_escenario = 0
        self.ultima_victima = None
        self.carrera = self._carrera_vacia()
        self._deadlock = None
        self._recuperando = None
        self._reiniciando = False

        self.cola_peticiones = queue.Queue()
        self.generador = None
        self.barrera_actual = None

        self._crear_recursos()
        self.pasos = ControlPasos(self)
        self.watchdog = HiloGuardian(self)
        self.hilos_sistema["T_Watchdog"] = self.watchdog
        self.paso = None

    # ------------------------------------------------------------------ arranque
    def iniciar(self):
        self.bitacora.marcar(f"Motor iniciado PID={self.sistema['pid']}")
        self.watchdog.start()
        time.sleep(0.05)
        self.paso = ex.panel_inicial(self.contexto())

    def registrar_hilo_sistema(self, hilo: threading.Thread):
        self.hilos_sistema[hilo.name] = hilo

    def _crear_recursos(self):
        self.estado = EstadoRecursos()
        self.estaciones = SemaforoRastreado(ID_ESTACIONES, NUM_ESTACIONES, self.estado, tipo="estacion")
        self.recursos = {t.isbn: SemaforoRastreado(t.isbn, t.copias, self.estado) for t in CATALOGO}

    def recurso(self, rid):
        return self.estaciones if rid == ID_ESTACIONES else self.recursos[rid]

    def retenedores_de(self, rid):
        with self.estado.lock:
            return sorted(self.estado.recursos[rid].retenedores)

    @staticmethod
    def _carrera_vacia():
        t = POR_ISBN[ISBN_CARRERA]
        return {"protegido": True, "hilos": 0, "titulo": t.corto, "copias": t.copias,
                "exitos": 0, "rechazos": 0, "valores_leidos": set()}

    # ------------------------------------------------------------------ logs
    def log(self, hilo, mensaje, nivel="info"):
        ahora = datetime.now()
        with self._log_lock:
            self._log_seq += 1
            self.logs.append({"id": self._log_seq, "t": ahora.strftime("%H:%M:%S.%f")[:-3],
                              "hilo": hilo, "msg": mensaje, "nivel": nivel})
        if self.eco_consola:
            print(f"[{ahora.strftime('%H:%M:%S')}] [{hilo}] {mensaje}", flush=True)

    def logs_desde(self, ultimo_id):
        with self._log_lock:
            return [l for l in self.logs if l["id"] > ultimo_id]

    def ultimo_log_id(self):
        with self._log_lock:
            return self._log_seq

    # ------------------------------------------------------------------ registro de hilos
    def lanzar(self, hilo):
        """Registra el hilo ANTES de start() (así nunca 'desaparece' entre la creación y su ejecución)."""
        with self._reg_lock:
            self.hilos[hilo.name] = hilo
        hilo.start()

    def hilo_iniciado(self, hilo):
        with self._reg_lock:
            self.hilos.setdefault(hilo.name, hilo)
        self.metricas["hilos_creados"] += 1

    def hilo_terminado(self, hilo):
        with self._reg_lock:
            if self.hilos.get(hilo.name) is hilo:
                del self.hilos[hilo.name]
        if self._recuperando == hilo.name:
            self._recuperando = None

    def transacciones_vivas(self):
        with self._reg_lock:
            return len(self.hilos)

    def transaccion_completada(self, hilo):
        self.metricas["completados"] += 1

    def transaccion_abortada(self, hilo, motivo):
        if self._reiniciando or motivo == "reinicio":
            return
        self.metricas["abortados"] += 1
        sol = getattr(hilo, "solicitud", None)
        if sol and sol["intento"] == 1 and hilo.motivo_aborto.startswith("víctima"):
            nueva = dict(sol, hilo=sol["hilo"] + "r", intento=2)
            self.cola_peticiones.put(nueva)
            self.log("T_Generador", f"Solicitud de {sol['hilo']} devuelta a la cola de peticiones: se reintentará "
                                    f"como {nueva['hilo']} cuando terminen las demás transacciones", "info")

    def resultado_reserva(self, hilo, ok):
        if ok:
            self.carrera["exitos"] += 1
        else:
            self.carrera["rechazos"] += 1
        if hilo.valor_leido is not None:
            self.carrera["valores_leidos"].add(hilo.valor_leido)

    def abortar_hilo(self, nombre, motivo="víctima del watchdog", libros=None):
        with self._reg_lock:
            h = self.hilos.get(nombre)
        if not h:
            return False
        self._recuperando = nombre
        self.ultima_victima = {"hilo": nombre, "libros": libros or [], "tid": h.tid}
        h.motivo_aborto = motivo
        h.abortar.set()
        return True

    # ------------------------------------------------------------------ interbloqueo
    def deadlock_activo(self):
        return self._deadlock is not None

    def recuperacion_en_curso(self):
        return self._recuperando is not None

    def firma_deadlock(self):
        return self._deadlock["firma"] if self._deadlock else None

    def declarar_deadlock(self, ciclo, hilos, texto, snap, firma=None):
        if self._deadlock is not None:
            self.log("T_Watchdog", "El ciclo anterior desapareció, pero se formó uno NUEVO con otros hilos.", "alerta")
        self._deadlock = {"ciclo": ciclo, "hilos": hilos, "texto": texto, "t": time.time(),
                          "firma": firma or frozenset(hilos)}
        self.metricas["deadlocks"] += 1
        self.deadlocks_escenario += 1
        self.bitacora.registrar("T_Watchdog", "DEADLOCK", texto)
        self.log("T_Watchdog", f"¡ALERTA! INTERBLOQUEO DETECTADO por DFS (confirmado con Work/Finish). Ciclo: {texto}", "critico")
        self.log("T_Watchdog", "Condiciones de Coffman: exclusión mutua ✔ · retención y espera ✔ · no apropiación ✔ · "
                               "espera circular ✔", "critico")
        if not self.config["pausas"]:
            self.paso = ex.aviso_deadlock(self.contexto())

    def deadlock_resuelto(self):
        self._deadlock = None
        self.metricas["recuperaciones"] += 1
        self.log("T_Watchdog", "Ciclo eliminado: el RAG vuelve a estar libre de ciclos (Estado RAG: Normal).", "ok")
        if not self.config["pausas"] and self.escenario["corriendo"]:
            p = ex.paso_deadlock(self.contexto(), 3)
            p.update(pausa=False, numero=0, etiqueta="RECUPERADO", tipo="exito",
                     titulo="Recuperación ejecutada: rollback de la víctima y reanudación")
            self.paso = p

    # ------------------------------------------------------------------ escenarios
    def iniciar_escenario(self, nombre):
        with self._ctrl_lock:
            if nombre not in ESCENARIOS:
                return False, "Escenario desconocido"
            if self.escenario["corriendo"]:
                return False, "Ya hay un escenario en ejecución: espera a que termine o reinicia."
            self._limpiar()
            self.metricas = Counter()
            self.escenario = {"nombre": nombre, "titulo": ESCENARIOS[nombre], "corriendo": True, "oleada": 0,
                              "inicio": time.time(), "fin": None}
            self.deadlocks_escenario = 0
            self.ultima_victima = None
            self.carrera = self._carrera_vacia()
            self.pasos.reiniciar()
            self.bitacora.marcar(f"=== {ESCENARIOS[nombre]} ===")
            self.log("MOTOR", f"--- {ESCENARIOS[nombre]} ---", "sistema")
            self.paso = ex.panel_ejecucion(self.contexto(), nombre)
            self.generador = HiloGenerador(self, nombre)
            self.hilos_sistema["T_Generador"] = self.generador
            self.generador.start()
            return True, "ok"

    def oleada_sin_ciclo(self):
        if self.config["pausas"]:
            self.pasos.nueva_oleada()
            p = ex.paso_sin_ciclo(self.contexto())
            p.update(pausa=False, numero=0, etiqueta="SIGUIENTE OLEADA")
            self.paso = p

    def escenario_finalizado(self, nombre, cancelado=False, gen=None):
        if gen is not None and gen is not self.generador:
            return
        self.escenario["corriendo"] = False
        self.escenario["fin"] = time.time()
        if cancelado:
            return
        ctx = self.contexto()
        dur = self.escenario["fin"] - (self.escenario["inicio"] or self.escenario["fin"])
        if nombre == "carrera":
            c = ctx["carrera"]
            self.log("MOTOR", f"Resultado: {c['registrados']} préstamos registrados de {c['copias']} copias · "
                              f"disponibles = {c['disponibles']} · integridad {'OK' if c['integro'] else 'VIOLADA'}",
                     "ok" if c["integro"] else "critico")
        else:
            m = self.metricas
            self.log("MOTOR", f"Escenario terminado en {dur:.1f} s · completados {m['completados']} · "
                              f"deadlocks {m['deadlocks']} · rollbacks {m['abortados']} · integridad "
                              f"{'OK' if ctx['integridad_ok'] else 'VIOLADA'}", "ok")
        if self.config["pausas"]:
            if nombre == "normal":
                p = ex.paso_normal(ctx, 3)
            elif nombre == "deadlock":
                p = ex.paso_deadlock(ctx, 3) if self.ultima_victima else ex.paso_sin_ciclo(ctx)
                if not self.ultima_victima:
                    p["numero"], p["total"] = 3, 3
            else:
                p = ex.paso_carrera(ctx, 2)
            self.pasos.paso_mostrado = p["numero"]
            self.pasos.esperando_usuario = True
            self.paso = p
        else:
            self.paso = ex.aviso_final(ctx, nombre)

    def _limpiar(self):
        """Cancela todo lo que esté corriendo y deja un inventario nuevo."""
        self._reiniciando = True
        try:
            if self.generador and self.generador.is_alive():
                self.generador.cancelar.set()
            if self.barrera_actual is not None:
                self.barrera_actual.abort()
            with self._reg_lock:
                vivos = list(self.hilos.values())
            for h in vivos:
                h.motivo_aborto = "reinicio"
                h.abortar.set()
            self.pasos.liberar_todo()
            for h in vivos:
                h.join(timeout=3)
            if self.generador:
                self.generador.join(timeout=3)
            while not self.cola_peticiones.empty():
                try:
                    self.cola_peticiones.get_nowait()
                except queue.Empty:
                    break
            with self._reg_lock:
                self.hilos.clear()
            self._crear_recursos()
            self._deadlock = None
            self._recuperando = None
        finally:
            self._reiniciando = False

    def reiniciar(self):
        with self._ctrl_lock:
            self._limpiar()
            self.escenario = {"nombre": None, "titulo": "", "corriendo": False, "oleada": 0, "inicio": None, "fin": None}
            self.metricas = Counter()
            self.deadlocks_escenario = 0
            self.ultima_victima = None
            self.carrera = self._carrera_vacia()
            self.pasos.reiniciar()
            self.bitacora.marcar("=== REINICIO DE ESTADO ===")
            self.log("MOTOR", "Estado reiniciado: inventario completo, sin hilos de transacción.", "sistema")
            self.paso = ex.panel_inicial(self.contexto())

    # ------------------------------------------------------------------ comandos del panel
    def set_config(self, clave, valor):
        if clave not in self.config:
            return
        valor = bool(valor)
        self.config[clave] = valor
        nombres = {"pausas": "Modo explicación (pausas)", "proteccion": "Protección con semáforos",
                   "auto_recuperacion": "Recuperación automática"}
        self.log("MOTOR", f"{nombres[clave]}: {'ACTIVADO' if valor else 'DESACTIVADO'}", "sistema")
        if clave == "pausas" and not valor:
            self._salir_de_pausas()
        if clave == "auto_recuperacion" and valor and self.deadlock_activo():
            self.watchdog.forzar()

    def _salir_de_pausas(self):
        if self.deadlock_activo():
            self.pasos.autorizar_recuperacion()
            self.watchdog.forzar()
        self.pasos.liberar_todo()
        if self.paso and self.paso.get("pausa"):
            self.paso = dict(self.paso, pausa=False, etiqueta="SIN PAUSAS")

    def continuar(self):
        with self._ctrl_lock:
            p = self.pasos
            if not p.esperando_usuario:
                return
            if self.escenario["nombre"] == "deadlock" and self.deadlock_activo():
                p.autorizar_recuperacion()
                self.watchdog.forzar()
            p.continuar()
            etiqueta = "EN EJECUCIÓN" if self.escenario["corriendo"] else "COMPLETADO"
            self.paso = dict(self.paso, pausa=False, etiqueta=etiqueta)

    def sin_pausas(self):
        self.set_config("pausas", False)

    def resolver(self):
        if self.config["pausas"] and self.pasos.esperando_usuario and self.deadlock_activo():
            self.continuar()
            return
        self.log("MOTOR", "Solicitud manual al watchdog: escaneo DFS inmediato + recuperación.", "sistema")
        self.watchdog.forzar()

    # ------------------------------------------------------------------ tick (lo llama T_Broadcast)
    def tick(self):
        try:
            self._revisar_kernel()
            self._evaluar_pasos()
        except Exception as e:  # pragma: no cover
            self.log("MOTOR", f"tick: {e!r}", "error")

    def _revisar_kernel(self):
        """Cuando un hilo lleva >0.3 s bloqueado, se lee /proc y se registra lo que dice el kernel."""
        snap_esperas = self.estado.copiar()["esperas"]
        ahora = time.monotonic()
        with self._reg_lock:
            vivos = dict(self.hilos)
        for nombre, (rid, t0) in snap_esperas.items():
            h = vivos.get(nombre)
            if not h or not h.tid or ahora - t0 < 0.3:
                continue
            marca = (rid, round(t0, 3))
            if getattr(h, "_kernel_marca", None) == marca:
                continue
            h._kernel_marca = marca
            k = leer_info_hilo(h.tid)
            if not k["vivo"]:
                continue
            sc = f"syscall {k['syscall']} ({k['syscall_nombre']})" if k["syscall"] is not None else "syscall n/d"
            self.log(nombre, f"kernel: estado {k['estado']} · wchan={k['wchan'] or 'n/d'} · {sc} → bloqueado en "
                             f"sem.acquire() esperando «{nombre_recurso(rid)}» ({k['etiqueta']})", "kernel")

    def _evaluar_pasos(self):
        """Detecta cuándo el sistema quedó 'quieto' en un checkpoint para mostrar la siguiente pausa."""
        p = self.pasos
        if not self.config["pausas"] or not self.escenario["corriendo"] or p.esperando_usuario:
            return
        snap = self.estado.copiar()
        with self._reg_lock:
            vivos = list(self.hilos.values())
        if not vivos:
            return
        detenidos = dict(p.detenidos)
        alguno_detenido = False
        for h in vivos:
            if h.name in detenidos:
                alguno_detenido = True
                continue
            if h.name in snap["esperas"]:
                rid = snap["esperas"][h.name][0]
                if snap["disponibles"].get(rid, 0) <= 0:
                    continue                                  # bloqueado de verdad
            if h.rol == "reserva" and h.estado_logico in ("PRÉSTAMO ACTIVO", "RECHAZADA"):
                continue
            p._ticks_quieto = 0
            return                                            # alguien sigue trabajando
        p._ticks_quieto += 1
        if p._ticks_quieto < 2:
            return
        esc = self.escenario["nombre"]
        siguiente = p.fase_permitida + 1
        ctx = None
        if esc == "deadlock":
            if self.deadlock_activo():
                if p.paso_mostrado < 2:
                    ctx = self.contexto()
                    self._mostrar(2, ex.paso_deadlock(ctx, 2))
                return
            if not alguno_detenido:
                return                                        # todos bloqueados: esperar confirmación del watchdog
            if siguiente == 1:
                self._mostrar(1, ex.paso_deadlock(self.contexto(), 1))
        elif esc == "normal":
            if alguno_detenido and siguiente <= 2:
                self._mostrar(siguiente, ex.paso_normal(self.contexto(), siguiente))
        elif esc == "carrera":
            if alguno_detenido and siguiente == 1:
                self._mostrar(1, ex.paso_carrera(self.contexto(), 1))

    def _mostrar(self, numero, panel):
        self.pasos.paso_mostrado = numero
        self.pasos.esperando_usuario = True
        self.paso = panel
        self.log("MOTOR", f"PAUSA PARA EXPLICACIÓN — Paso {numero} de {panel['total']}: {panel['titulo']}", "pausa")

    # ------------------------------------------------------------------ contexto para los textos
    def contexto(self):
        snap = self.estado.copiar()
        with self._reg_lock:
            vivos = dict(self.hilos)
        retienen = []
        por_hilo = {}
        for rid, ret in snap["asignacion"].items():
            if snap["tipos"][rid] != "libro":
                continue
            for h, n in ret.items():
                por_hilo.setdefault(h, []).extend([nombre_recurso(rid)] * n)
        for h in sorted(por_hilo):
            hobj = vivos.get(h)
            siguiente = None
            if hobj is not None and getattr(hobj, "orden", None):
                tomados = [r for r in hobj.retenidos if r != ID_ESTACIONES]
                pendientes = [r for r in hobj.orden if r not in tomados]
                siguiente = nombre_recurso(pendientes[0]) if pendientes else None
            retienen.append({"hilo": h, "libros": por_hilo[h], "siguiente": siguiente})
        esperan = []
        for h, (rid, _t) in sorted(snap["esperas"].items()):
            hobj = vivos.get(h)
            tid = hobj.tid if hobj else None
            esperan.append({"hilo": h, "tid": tid, "recurso": nombre_recurso(rid),
                            "duenos": sorted(snap["asignacion"].get(rid, {})),
                            "kernel": leer_info_hilo(tid) if tid else {}})
        integ = self._integridad(snap)
        c = dict(self.carrera)
        r = POR_ISBN[ISBN_CARRERA].isbn
        c["registrados"] = snap["registrados"][r]
        c["disponibles"] = snap["disponibles"][r]
        c["integro"] = integ["por_recurso"].get(r, True)
        c["valores_leidos"] = ", ".join(str(v) for v in sorted(c["valores_leidos"], reverse=True)) or "—"
        return {
            "pid": self.sistema["pid"],
            "hilos_so": len(listar_tareas()),
            "num_estaciones": NUM_ESTACIONES,
            "tid_watchdog": self.watchdog.tid,
            "retienen": retienen,
            "esperan": esperan,
            "hilos_transaccion": sorted(vivos),
            "metricas": dict(self.metricas),
            "integridad_ok": integ["ok"],
            "deadlock": ({k: v for k, v in self._deadlock.items() if k != "firma"} if self._deadlock else None),
            "ultima_victima": self.ultima_victima,
            "carrera": c,
            "auto_recuperacion": self.config["auto_recuperacion"],
        }

    @staticmethod
    def _integridad(snap):
        por = {}
        for rid, total in snap["totales"].items():
            if snap["tipos"][rid] != "libro":
                continue
            d, reg = snap["disponibles"][rid], snap["registrados"][rid]
            por[rid] = d >= 0 and 0 <= reg <= total and d + reg == total
        return {"ok": all(por.values()), "por_recurso": por}

    # ------------------------------------------------------------------ snapshot para el frontend
    def snapshot(self):
        snap = self.estado.copiar()
        tareas = listar_tareas()
        with self._reg_lock:
            vivos = dict(self.hilos)
        deadlock = self._deadlock
        hilos_dead = set(deadlock["hilos"]) if deadlock else set()
        detenidos = dict(self.pasos.detenidos)

        # ---- hilos (sistema + transacciones) con su estado REAL en el kernel
        filas = []
        principal = threading.main_thread()
        sistema = [("T_Principal", principal.native_id, "principal")]
        for nombre in ("T_Watchdog", "T_Generador", "T_Broadcast"):
            h = self.hilos_sistema.get(nombre)
            if h is not None and h.is_alive():
                sistema.append((nombre, h.native_id, "sistema"))
        for nombre, tid, rol in sistema:
            k = leer_info_hilo(tid) if tid else {}
            filas.append({"nombre": nombre, "tid": tid, "rol": rol, "kernel": k, "logico": rol.upper(),
                          "detalle": "", "retiene": [], "espera": None})
        for nombre in sorted(vivos):
            h = vivos[nombre]
            k = leer_info_hilo(h.tid) if h.tid else {"etiqueta": "CREANDO", "estado": "-", "vivo": False}
            espera = snap["esperas"].get(nombre)
            retiene = []
            for rid, ret in snap["asignacion"].items():
                retiene += [nombre_recurso(rid)] * ret.get(nombre, 0)
            logico = h.estado_logico
            if nombre in detenidos:
                logico = f"PAUSA (checkpoint {detenidos[nombre]})"
            if nombre in hilos_dead:
                logico = "INTERBLOQUEADO"
            filas.append({"nombre": nombre, "tid": h.tid, "rol": h.rol, "kernel": k, "logico": logico,
                          "detalle": h.detalle, "retiene": retiene,
                          "espera": nombre_recurso(espera[0]) if espera else None,
                          "victima": nombre == self._recuperando})
        conocidos = {f["tid"] for f in filas}
        otros = [t for t in tareas if t not in conocidos]

        # ---- recursos
        integ = self._integridad(snap)
        recursos = []
        orden = [ID_ESTACIONES] + [t.isbn for t in CATALOGO]
        esperando_por = {}
        for h, (rid, _t) in snap["esperas"].items():
            esperando_por.setdefault(rid, []).append(h)
        for rid in orden:
            t = POR_ISBN.get(rid)
            recursos.append({
                "id": rid, "tipo": snap["tipos"][rid], "corto": nombre_recurso(rid),
                "titulo": t.titulo if t else "Estaciones de préstamo", "autor": t.autor if t else "",
                "total": snap["totales"][rid], "disponibles": snap["disponibles"][rid],
                "registrados": snap["registrados"][rid] if t else snap["totales"][rid] - snap["disponibles"][rid],
                "retenedores": snap["asignacion"][rid], "esperando": sorted(esperando_por.get(rid, [])),
                "integro": integ["por_recurso"].get(rid, True),
            })

        # ---- RAG leído del estado interno
        ciclo_aristas = rag.aristas_del_ciclo(deadlock["ciclo"]) if deadlock else set()
        nodos_ciclo = set(deadlock["ciclo"]) if deadlock else set()
        nodos, aristas = [], []
        for rid in orden:
            nodos.append({"id": f"R:{rid}", "tipo": "recurso", "label": nombre_recurso(rid),
                          "total": snap["totales"][rid], "disponibles": snap["disponibles"][rid],
                          "estacion": rid == ID_ESTACIONES, "en_ciclo": f"R:{rid}" in nodos_ciclo})
        en_grafo = set(vivos)
        for rid, ret in snap["asignacion"].items():
            en_grafo |= {h for h, n in ret.items() if n > 0}
        for h in sorted(en_grafo):
            estado_nodo = "activo"
            if h in snap["esperas"]:
                estado_nodo = "esperando"
            if h in detenidos:
                estado_nodo = "pausa"
            if h in hilos_dead:
                estado_nodo = "interbloqueado"
            if h == self._recuperando:
                estado_nodo = "victima"
            nodos.append({"id": f"T:{h}", "tipo": "hilo", "label": h, "estado": estado_nodo,
                          "tid": vivos[h].tid if h in vivos else None, "en_ciclo": f"T:{h}" in nodos_ciclo})
        for rid, ret in snap["asignacion"].items():
            for h, n in ret.items():
                if n > 0:
                    aristas.append({"id": f"a|{rid}|{h}", "de": f"R:{rid}", "a": f"T:{h}", "tipo": "asignacion",
                                    "n": n, "ciclo": (f"R:{rid}", f"T:{h}") in ciclo_aristas})
        for h, (rid, _t) in snap["esperas"].items():
            aristas.append({"id": f"s|{h}|{rid}", "de": f"T:{h}", "a": f"R:{rid}", "tipo": "solicitud",
                            "n": 1, "ciclo": (f"T:{h}", f"R:{rid}") in ciclo_aristas})

        m = dict(self.metricas)
        m["en_espera"] = len(snap["esperas"])
        m["transacciones_vivas"] = len(vivos)
        m["cola"] = self.cola_peticiones.qsize()
        m["escaneos_watchdog"] = self.watchdog.escaneos
        c = self.contexto_carrera(snap, integ)
        m["sobreprestamo"] = max(0, c["registrados"] - c["copias"]) if self.escenario["nombre"] == "carrera" else 0

        return {
            "sistema": dict(self.sistema, hilos_so=len(tareas)),
            "escenario": dict(self.escenario),
            "config": dict(self.config),
            "paso": self.paso,
            "pasos": {"esperando": self.pasos.esperando_usuario, "fase": self.pasos.fase_permitida,
                      "detenidos": len(detenidos)},
            "hilos": filas,
            "otros_hilos": {"cantidad": len(otros), "tids": otros[:12]},
            "recursos": recursos,
            "rag": {"nodos": nodos, "aristas": aristas,
                    "estado": "deadlock" if deadlock else "normal",
                    "texto_ciclo": deadlock["texto"] if deadlock else "",
                    "recuperando": self._recuperando},
            "metricas": m,
            "integridad": integ["ok"],
            "carrera": c,
            "ts": time.time(),
        }

    def contexto_carrera(self, snap, integ):
        r = ISBN_CARRERA
        c = self.carrera
        return {"protegido": c["protegido"], "hilos": c["hilos"], "titulo": c["titulo"], "copias": c["copias"],
                "exitos": c["exitos"], "rechazos": c["rechazos"],
                "registrados": snap["registrados"][r], "disponibles": snap["disponibles"][r],
                "integro": integ["por_recurso"].get(r, True)}
