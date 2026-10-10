"""
explicaciones.py — Textos del panel "Pausa para explicación".

Los textos se ARMAN con el estado real del motor en el momento de la pausa
(nombres de hilos, TIDs, libros retenidos, estado leído de /proc, ciclo detectado),
por eso cada ejecución muestra datos distintos.
"""
from html import escape


def _b(x):
    return f"<b>{escape(str(x))}</b>"


def _c(x):
    return f"<code>{escape(str(x))}</code>"


def _libro(x):
    return f"<b>«{escape(str(x))}»</b>"


def _enum(items, vacio="—"):
    items = list(items)
    if not items:
        return vacio
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]


def _panel(tipo, titulo, resumen, que, concepto, evidencia, numero=0, total=0, pausa=False, etiqueta=""):
    return {
        "visible": True, "tipo": tipo, "titulo": titulo, "resumen": resumen,
        "que": que, "concepto": concepto, "evidencia": evidencia,
        "numero": numero, "total": total, "pausa": pausa, "etiqueta": etiqueta,
    }


def _kernel_de_esperas(ctx, maximo=3):
    partes = []
    for e in ctx["esperan"][:maximo]:
        k = e["kernel"]
        sc = f"syscall {k['syscall']} ({k['syscall_nombre']})" if k.get("syscall") is not None else "syscall n/d"
        partes.append(f"{_b(e['hilo'])} (TID {_c(e['tid'])}): estado {_c(k.get('estado', '?'))}, "
                      f"wchan={_c(k.get('wchan') or 'n/d')}, {sc}")
    return "<br>".join(partes)


# ---------------------------------------------------------------- inicio
def panel_inicial(ctx):
    pid = ctx["pid"]
    return _panel(
        "info", "Motor listo — elige un escenario",
        f"Proceso Python {_c('PID ' + str(ctx['pid']))}: hilo principal, {_c('T_Watchdog')} (detector), "
        f"{_c('T_Broadcast')} (WebSocket) y los hilos del servidor web ya corren como hilos reales del SO.",
        "Aún no hay transacciones. Cada botón lanza una oleada de solicitudes; cada solicitud será un "
        "hilo NPTL real con su propio TID.",
        f"{_b('Semáforo contador por título')} (valor inicial = copias físicas) + {_b('estaciones de préstamo')} "
        f"(semáforo de {ctx['num_estaciones']}) + un {_c('threading.Lock')} que protege solo el estado interno del RAG.",
        f"Verifícalo en otra terminal: {_c('ps -eLf | grep app.py')} · {_c('ls /proc/%s/task' % pid)} · "
        f"{_c('htop -p %s' % pid)} (tecla H muestra los hilos).",
    )


# ---------------------------------------------------------------- en ejecución (sin pausas)
def panel_ejecucion(ctx, escenario):
    if escenario == "normal":
        return _panel(
            "info", "Ejecutando: transacciones normales (orden global por ISBN)",
            "Los hilos piden sus libros en orden ascendente de ISBN: la espera circular es imposible.",
            "Observa en el RAG cómo aparecen aristas verdes (asignación) y punteadas (solicitud) y cómo "
            "desaparecen cuando cada préstamo termina.",
            f"{_b('Prevención de interbloqueos')}: imponer un orden total a los recursos niega la condición "
            "de espera circular de Coffman.",
            "En el monitor, los hilos en espera muestran estado S y wchan futex: están dormidos en el kernel, "
            "no gastan CPU (no es espera activa).",
        )
    if escenario == "deadlock":
        return _panel(
            "alerta", "Ejecutando: modo caótico (orden de la cola de peticiones)",
            "El generador respeta el orden en que cada usuario pidió sus libros; si dos solicitudes se "
            "cruzan, la espera circular surge sola.",
            "El hilo guardián recorre el RAG cada 0.5 s con DFS. Si aparece un ciclo lo resaltará en rojo.",
            "Retención y espera + no apropiación + exclusión mutua + espera circular = interbloqueo.",
            f"Cuando ocurra, compara con {_c('cat /proc/<PID>/task/<TID>/wchan')}: los hilos del ciclo duermen en futex.",
        )
    return _panel(
        "info", "Ejecutando: reservas en línea simultáneas",
        "Varias sucursales reservan al mismo tiempo el mismo título.",
        "Mira el contador del título en la estantería y la tabla de integridad.",
        "Condición de carrera: verificar-y-actuar sin exclusión mutua.",
        "Los hilos que se registran sin protección no pasan por futex: nadie los detiene.",
    )


# ---------------------------------------------------------------- escenario NORMAL
def paso_normal(ctx, n):
    total = 3
    if n == 1:
        ret = [f"{_b(r['hilo'])} adquirió {_enum([_libro(x) for x in r['libros']])}" for r in ctx["retienen"]]
        esp = [f"{_b(e['hilo'])} quedó bloqueado esperando {_libro(e['recurso'])}"
               + (f" (retenido por {_enum([_b(d) for d in e['duenos']])})" if e["duenos"] else "")
               for e in ctx["esperan"]]
        return _panel(
            "pausa", "Fase 1: Adquisición concurrente de primeras copias",
            f"Los hilos {_enum([_b(h) for h in ctx['hilos_transaccion']])} compiten en el catálogo y toman su "
            "primera copia siguiendo el orden ascendente de ISBN.",
            ("; ".join(ret) + ". " if ret else "") + ("; ".join(esp) + ". " if esp else "")
            + "En el RAG aparecen aristas de asignación (verdes) Recurso → Hilo y de solicitud (punteadas) Hilo → Recurso.",
            f"{_b('Semáforo contador (Dijkstra)')}: {_c('acquire()')} = P(S) decrementa; si el contador es 0 el hilo "
            f"se bloquea. {_c('release()')} = V(S) incrementa y despierta a uno. Pedir SIEMPRE en el mismo orden "
            "(ISBN) evita que se forme un ciclo.",
            (_kernel_de_esperas(ctx) or f"Todos los hilos tienen TID propio dentro del PID {_c(ctx['pid'])}.")
            + f"<br>Ver: {_c('ls /proc/%s/task' % ctx['pid'])}",
            numero=1, total=total, pausa=True)
    if n == 2:
        ret = [f"{_b(r['hilo'])}: {_enum([_libro(x) for x in r['libros']])}" for r in ctx["retienen"]]
        return _panel(
            "pausa", "Fase 2: Retención múltiple y registro del préstamo (Growing Phase)",
            "Las transacciones ya tienen TODAS sus copias y escribieron COMMIT en la bitácora (WAL) con fsync.",
            ("Retienen → " + "; ".join(ret) + ". " if ret else "")
            + (f"Siguen esperando: {_enum([_b(e['hilo']) for e in ctx['esperan']])}." if ctx["esperan"] else
               "Nadie está bloqueado."),
            f"{_b('Bloqueo en dos fases (2PL)')}: en la fase de crecimiento solo se adquiere, nada se libera hasta "
            f"tener todo. La actualización del inventario es una {_b('sección crítica')} protegida por el Lock del estado.",
            f"Bitácora: {_c('tail -f bitacora/prestamos.wal')} muestra BEGIN → ADQUIRIDO → COMMIT con el TID "
            "de cada hilo.<br>" + (_kernel_de_esperas(ctx) or ""),
            numero=2, total=total, pausa=True)
    m = ctx["metricas"]
    return _panel(
        "exito", "Fase 3: Devolución y consistencia del inventario (Shrinking Phase)",
        f"{_b(m.get('completados', 0))} préstamos completados, {_b(m.get('deadlocks', 0))} interbloqueos, "
        f"inventario {'CONSISTENTE' if ctx['integridad_ok'] else 'INCONSISTENTE'}.",
        "Las copias regresaron a la estantería con release() (V). Los hilos que esperaban fueron despertados "
        "(FUTEX_WAKE) y completaron su préstamo. Invariante verificado en cada título: "
        f"{_c('disponibles + prestadas = copias')}.",
        f"{_b('Fase de decrecimiento del 2PL')}: se libera en orden inverso. El semáforo nunca permitió más "
        "préstamos simultáneos que copias.",
        f"Los TIDs de los hilos terminados ya no existen en {_c('/proc/%s/task' % ctx['pid'])}: "
        f"solo quedan {ctx['hilos_so']} hilos (principal, watchdog, broadcast y servidor).",
        numero=3, total=total, pausa=True)


# ---------------------------------------------------------------- escenario DEADLOCK
def paso_deadlock(ctx, n):
    total = 3
    if n == 1:
        planes = []
        for r in ctx["retienen"]:
            sig = r.get("siguiente")
            planes.append(f"{_b(r['hilo'])} retiene {_enum([_libro(x) for x in r['libros']])}"
                          + (f" y después pedirá {_libro(sig)}" if sig else ""))
        return _panel(
            "pausa", "Fase 1: Hora pico — cada hilo toma su primer libro (modo caótico)",
            "El generador leyó la cola de peticiones y respetó el orden en que cada usuario pidió sus libros "
            "(no se ordenan por ISBN).",
            ("; ".join(planes) + ". ") if planes else "Los hilos tomaron su primera copia. ",
            f"{_b('Retención y espera')}: cada transacción conserva lo que ya obtuvo mientras pide lo siguiente. "
            "Sin un orden global, dos solicitudes pueden cruzarse (A→B y B→A).",
            f"Aristas de asignación leídas de las estructuras internas del motor (no dibujadas a mano). "
            f"El watchdog (TID {_c(ctx['tid_watchdog'])}) aún no ve ciclos.",
            numero=1, total=total, pausa=True)
    if n == 2:
        d = ctx["deadlock"] or {}
        return _panel(
            "alerta", "Fase 2: ¡INTERBLOQUEO! Espera circular detectada por el Watchdog (DFS)",
            f"Ciclo: {_b(d.get('texto', '—'))}",
            f"Ningún hilo del ciclo puede avanzar: cada uno espera una copia que retiene el siguiente. "
            f"El hilo guardián (TID {_c(ctx['tid_watchdog'])}) recorrió el RAG con DFS, encontró una arista de "
            f"retroceso y confirmó con el algoritmo Work/Finish que {_enum([_b(h) for h in d.get('hilos', [])])} "
            "están interbloqueados.",
            f"Se cumplen las 4 condiciones de Coffman: {_b('1) exclusión mutua')} (1 copia por título), "
            f"{_b('2) retención y espera')}, {_b('3) no apropiación')} (nadie quita un semáforo a la fuerza) y "
            f"{_b('4) espera circular')} (el ciclo rojo).",
            _kernel_de_esperas(ctx, 4) + "<br>Presiona <b>Continuar</b> (o <b>Resolver</b>) para que el watchdog "
            "ejecute la recuperación.",
            numero=2, total=total, pausa=True)
    m = ctx["metricas"]
    v = ctx.get("ultima_victima") or {}
    return _panel(
        "exito", "Fase 3: Recuperación por rollback y finalización",
        f"El watchdog abortó a {_b(v.get('hilo', '—'))} (el último en entrar al ciclo); su transacción hizo "
        f"ROLLBACK y liberó {_enum([_libro(x) for x in v.get('libros', [])], 'sus copias')}.",
        "Al liberarse las copias, los demás hilos despertaron (FUTEX_WAKE) y completaron sus préstamos. "
        "La solicitud de la víctima volvió a la cola y se reintentó al final, con el sistema libre y en "
        "orden de ISBN, por lo que ya no pudo formar otro ciclo.",
        f"{_b('Recuperación por terminación de una víctima')} con reversión usando la bitácora (WAL). "
        "Se elige al más reciente para perder el menor trabajo y no reiniciar todo el sistema; "
        "el reintento diferido y ordenado evita la inanición (la víctima siempre termina).",
        f"Bitácora: líneas {_c('ABORT')} y {_c('ROLLBACK')} con el TID de la víctima. "
        f"Deadlocks detectados: {_b(m.get('deadlocks', 0))} · rollbacks: {_b(m.get('abortados', 0))} · "
        f"completados: {_b(m.get('completados', 0))} · integridad: {_b('OK' if ctx['integridad_ok'] else 'VIOLADA')}.",
        numero=3, total=total, pausa=True)


def paso_sin_ciclo(ctx):
    return _panel(
        "info", "Oleada sin espera circular",
        "En esta oleada los órdenes de la cola no llegaron a cruzarse al mismo tiempo: no se formó un ciclo.",
        "Todos los hilos pudieron completar sus préstamos. El generador tomará la siguiente oleada de la cola.",
        "Un ciclo requiere que las solicitudes cruzadas coincidan en el tiempo: por eso el interbloqueo "
        "real es no determinista.",
        "El watchdog siguió escaneando sin encontrar aristas de retroceso.",
        numero=2, total=3, pausa=True)


# ---------------------------------------------------------------- escenario CARRERA
def paso_carrera(ctx, n):
    c = ctx["carrera"]
    total = 2
    if c["protegido"]:
        if n == 1:
            return _panel(
                "pausa", "Fase 1: Reserva atómica con semáforo",
                f"{_b(c['hilos'])} reservas en línea intentaron tomar {_libro(c['titulo'])} ({c['copias']} copias) "
                "al mismo tiempo.",
                f"Cada hilo ejecutó {_c('sem.acquire(blocking=False)')}: {_b(c['exitos'])} obtuvieron copia y "
                f"{_b(c['rechazos'])} recibieron False (sin copias).",
                f"{_b('Exclusión mutua')}: verificar y decrementar ocurren en UNA operación atómica del semáforo; "
                "no existe una ventana entre leer y escribir.",
                "El contador del título nunca bajó de 0.",
                numero=1, total=total, pausa=True)
        return _panel(
            "exito", "Fase 2: Resultado consistente",
            f"Préstamos registrados: {_b(c['registrados'])} de {_b(c['copias'])} copias. Disponibles: "
            f"{_b(c['disponibles'])}. Integridad: {_b('OK' if c['integro'] else 'VIOLADA')}.",
            "Ninguna copia fantasma: el semáforo limitó los préstamos al número real de copias.",
            f"Solución de la sección crítica: {_c('threading.Semaphore(copias)')} cumple exclusión mutua, "
            "progreso y espera acotada para este recurso.",
            "Desactiva 'Protección con Semáforos' y repite la prueba para ver la diferencia.",
            numero=2, total=total, pausa=True)
    if n == 1:
        return _panel(
            "pausa", "Fase 1: Lectura concurrente del contador SIN protección",
            f"{_b(c['hilos'])} reservas desde varias sucursales leyeron el contador de {_libro(c['titulo'])} "
            "al mismo tiempo.",
            f"Todos leyeron {_c('disponibles = %s' % c['valores_leidos'])} y creen que hay copia. Todavía nadie escribió.",
            f"{_b('Condición de carrera verificar-y-actuar')}: leer y escribir no son atómicos; entre ambas "
            "instrucciones el planificador ejecuta a otro hilo.",
            "Sin semáforo no hay futex: los hilos no se bloquean entre sí. El GIL cambia de hilo cada "
            f"{_c('sys.getswitchinterval()')} y en cada E/S (fsync de la bitácora).",
            numero=1, total=total, pausa=True)
    fantasma = max(0, c["registrados"] - c["copias"])
    return _panel(
        "alerta", "Fase 2: Escritura con valor obsoleto → SOBRE-PRÉSTAMO",
        f"Se registraron {_b(c['registrados'])} préstamos de un título con {_b(c['copias'])} copias: "
        f"{_b(fantasma)} copias fantasma.",
        f"Cada hilo escribió {_c('disponibles = leído − 1')} (actualización perdida / lost update). Contador final: "
        f"{_b(c['disponibles'])}. Invariante violado: prestadas ({c['registrados']}) > copias ({c['copias']}).",
        f"{_b('Sección crítica sin exclusión mutua')}. Solución: {_c('sem.acquire(blocking=False)')} verifica y "
        "decrementa en un solo paso atómico.",
        "Activa 'Protección con Semáforos' y repite: exactamente tantos préstamos como copias; el resto rechazados.",
        numero=2, total=total, pausa=True)


# ---------------------------------------------------------------- avisos sin pausa
def _sin_fase(titulo):
    return titulo.split(": ", 1)[1] if titulo.startswith("Fase ") and ": " in titulo else titulo


def aviso_deadlock(ctx):
    p = paso_deadlock(ctx, 2)
    p["pausa"] = False
    p["numero"] = 0
    p["titulo"] = _sin_fase(p["titulo"])
    p["evidencia"] = _kernel_de_esperas(ctx, 4) + (
        "<br>Recuperación automática activada: el watchdog actuará en el siguiente escaneo."
        if ctx["auto_recuperacion"] else
        "<br>Presiona <b>Resolver Interbloqueo (Watchdog DFS)</b> para ejecutar la recuperación.")
    return p


def aviso_final(ctx, escenario):
    if escenario == "normal":
        p = paso_normal(ctx, 3)
    elif escenario == "deadlock":
        p = paso_deadlock(ctx, 3) if ctx.get("ultima_victima") else paso_normal(ctx, 3)
    else:
        p = paso_carrera(ctx, 2)
    p["pausa"] = False
    p["numero"] = 0
    p["titulo"] = _sin_fase(p["titulo"])
    return p
