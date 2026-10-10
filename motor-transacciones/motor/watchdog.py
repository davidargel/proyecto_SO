"""
watchdog.py — Hilo guardián (T_Watchdog): detección periódica y recuperación.

Cada INTERVALO segundos:
  1. Toma una copia consistente del estado interno (bajo el Lock del estado).
  2. Construye el RAG y lo recorre con DFS buscando un ciclo.
  3. Confirma con el algoritmo Work/Finish que los hilos del ciclo realmente no pueden avanzar.
  4. Si el mismo conjunto aparece en 2 escaneos seguidos => declara INTERBLOQUEO
     (así se descartan estados transitorios entre acquire() y la actualización del estado).
  5. Recuperación (automática o al presionar "Resolver"): elige como VÍCTIMA al hilo del ciclo
     que entró más recientemente (su solicitud es la más nueva) y le envía la señal de aborto.
     La víctima ejecuta ROLLBACK: libera en orden inverso todo lo que tomó, lo que despierta
     a los demás hilos. El resto del sistema no se reinicia.
"""
import threading

from . import rag
from .catalogo import nombre_recurso
from .kernel import nombrar_hilo_so, tid_actual


class HiloGuardian(threading.Thread):
    INTERVALO = 0.5
    CONFIRMACIONES = 2

    def __init__(self, motor):
        super().__init__(name="T_Watchdog", daemon=True)
        self.motor = motor
        self.detener = threading.Event()
        self.despertar = threading.Event()
        self.solicitud_resolver = threading.Event()
        self.tid = None
        self._firma_previa = None
        self._conteo = 0
        self.escaneos = 0
        self.ultimo_resultado = {"ciclo": None, "interbloqueados": [], "texto": ""}

    def run(self):
        self.tid = tid_actual()
        nombrar_hilo_so(self.name)
        self.motor.log(self.name, f"WATCHDOG ACTIVO: monitor de interbloqueos en ejecución (TID SO: {self.tid})", "sistema")
        while not self.detener.is_set():
            self.despertar.wait(self.INTERVALO)
            self.despertar.clear()
            if self.detener.is_set():
                break
            try:
                self.escanear()
            except Exception as e:  # el guardián nunca debe morir
                self.motor.log(self.name, f"Error en escaneo: {e!r}", "error")

    def forzar(self):
        """Botón 'Resolver Interbloqueo (Watchdog DFS)'."""
        self.solicitud_resolver.set()
        self.despertar.set()

    # ------------------------------------------------------------------
    def escanear(self):
        m = self.motor
        self.escaneos += 1
        snap = m.estado.copiar()
        grafo = rag.construir_grafo(snap)
        ciclo = rag.dfs_buscar_ciclo(grafo)
        interbloqueados = rag.detectar_interbloqueados(snap) if ciclo else set()
        hilos_ciclo = {n[2:] for n in (ciclo or []) if n.startswith("T:")}
        confirmado = bool(ciclo) and hilos_ciclo and hilos_ciclo <= interbloqueados

        pedido_manual = self.solicitud_resolver.is_set()
        if pedido_manual:
            self.solicitud_resolver.clear()

        if not confirmado:
            self._firma_previa, self._conteo = None, 0
            self.ultimo_resultado = {"ciclo": None, "interbloqueados": [], "texto": ""}
            if m.deadlock_activo():
                m.deadlock_resuelto()
            if pedido_manual:
                m.log(self.name, f"DFS ejecutado sobre el RAG ({len(grafo)} nodos): no hay ciclos. Nada que recuperar.", "info")
            return

        firma = frozenset(interbloqueados)
        self._conteo = self._conteo + 1 if firma == self._firma_previa else 1
        self._firma_previa = firma
        texto = rag.texto_ciclo(ciclo, nombre_recurso)
        self.ultimo_resultado = {"ciclo": ciclo, "interbloqueados": sorted(interbloqueados), "texto": texto}

        if self._conteo < self.CONFIRMACIONES:
            if pedido_manual:                       # aún no confirmado: se atiende en el siguiente escaneo
                m.log(self.name, "Ciclo en confirmación: se recuperará en el siguiente escaneo.", "info")
                self.solicitud_resolver.set()
                self.despertar.set()
            return

        if not m.deadlock_activo() or m.firma_deadlock() != firma:
            m.declarar_deadlock(ciclo, sorted(interbloqueados), texto, snap, firma)

        if not m.recuperacion_en_curso():
            # En modo explicación la recuperación espera a que el expositor avance (paso 2 → 3).
            automatica = m.config["auto_recuperacion"] and not m.config["pausas"]
            if automatica or pedido_manual or m.pasos.recuperacion_autorizada():
                self.recuperar(ciclo, snap)

    def recuperar(self, ciclo, snap):
        """Estrategia: abortar (rollback) al hilo que entró más recientemente al ciclo."""
        m = self.motor
        hilos_ciclo = [n[2:] for n in ciclo[:-1] if n.startswith("T:")]
        esperas = snap["esperas"]
        victima = max(hilos_ciclo, key=lambda h: esperas.get(h, (None, 0.0))[1])
        rid_esperado = esperas.get(victima, (None, 0))[0]
        retiene = [nombre_recurso(r) for r, ret in snap["asignacion"].items() if ret.get(victima)]
        m.log(self.name, f"RECUPERACIÓN: víctima = {victima} (última en entrar al ciclo, esperaba "
                         f"«{nombre_recurso(rid_esperado)}»). Enviando señal de ABORTO → rollback de "
                         f"{', '.join('«%s»' % x for x in retiene) or 'nada'}.", "alerta")
        m.abortar_hilo(victima, motivo="víctima del watchdog", libros=retiene)
