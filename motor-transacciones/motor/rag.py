"""
rag.py — Grafo de Asignación de Recursos (RAG) y detección de interbloqueos.

El grafo NO se dibuja a mano: se construye a partir de la copia del estado interno
(EstadoRecursos.copiar()), es decir, de qué hilo retiene qué copia y qué hilo espera qué recurso.

  Nodos:   "T:<hilo>"  (círculos)      "R:<recurso>"  (rectángulos con N instancias)
  Aristas: Hilo -> Recurso   = SOLICITUD  (el hilo está bloqueado en sem.acquire())
           Recurso -> Hilo   = ASIGNACIÓN (el hilo retiene una o más copias)

Detección (hilo guardián):
  1) DFS con colores (BLANCO/GRIS/NEGRO): una arista hacia un nodo GRIS es una arista de
     retroceso => hay ciclo. Se reconstruye el ciclo con la pila de padres.   O(V + E)
  2) Como un título puede tener VARIAS copias, un ciclo es condición necesaria pero no
     suficiente. Se confirma con el algoritmo de detección para recursos con múltiples
     instancias (Work/Finish, Coffman–Shoshani / Silberschatz cap. 8).
"""

BLANCO, GRIS, NEGRO = 0, 1, 2


def construir_grafo(snap: dict) -> dict:
    """Lista de adyacencia dirigida a partir del estado interno."""
    ady = {}

    def nodo(n):
        ady.setdefault(n, [])

    for rid in snap["totales"]:
        nodo(f"R:{rid}")
    for rid, retenedores in snap["asignacion"].items():
        for hilo, n in retenedores.items():
            if n > 0:
                nodo(f"T:{hilo}")
                ady[f"R:{rid}"].append(f"T:{hilo}")           # asignación
    for hilo, (rid, _t) in snap["esperas"].items():
        nodo(f"T:{hilo}")
        ady[f"T:{hilo}"].append(f"R:{rid}")                   # solicitud
    return ady


def dfs_buscar_ciclo(ady: dict):
    """Devuelve el primer ciclo encontrado como lista de nodos [n0, n1, ..., n0] o None."""
    color = {n: BLANCO for n in ady}
    padre = {}

    for inicio in sorted(ady):
        if color[inicio] != BLANCO or not inicio.startswith("T:"):
            continue
        # DFS iterativo (evita límite de recursión) con iteradores por nodo
        pila = [(inicio, iter(ady[inicio]))]
        color[inicio] = GRIS
        while pila:
            u, it = pila[-1]
            avanzo = False
            for v in it:
                if color.get(v, BLANCO) == BLANCO:
                    color[v] = GRIS
                    padre[v] = u
                    pila.append((v, iter(ady.get(v, []))))
                    avanzo = True
                    break
                if color.get(v) == GRIS:                      # arista de retroceso => CICLO
                    ciclo = [v]
                    x = u
                    while x != v:
                        ciclo.append(x)
                        x = padre[x]
                    ciclo.append(v)
                    ciclo.reverse()
                    return _empezar_en_hilo(ciclo)
            if not avanzo:
                color[u] = NEGRO
                pila.pop()
    return None


def _empezar_en_hilo(ciclo):
    """Rota el ciclo para que empiece (y termine) en un hilo: T → R → T → R → T."""
    base = ciclo[:-1]
    k = next((i for i, n in enumerate(base) if n.startswith("T:")), 0)
    base = base[k:] + base[:k]
    return base + [base[0]]


def detectar_interbloqueados(snap: dict) -> set:
    """Algoritmo de detección con múltiples instancias (Work / Finish).

    Work = Disponibles;  Finish[i] = (Asignación_i == 0)
    Repetir: buscar i con Finish[i] == False y Solicitud_i <= Work
             => Work += Asignación_i ; Finish[i] = True
    Los hilos que quedan con Finish == False están INTERBLOQUEADOS.
    """
    work = {rid: max(0, d) for rid, d in snap["disponibles"].items()}
    asignacion_por_hilo = {}
    for rid, ret in snap["asignacion"].items():
        for hilo, n in ret.items():
            if n > 0:
                asignacion_por_hilo.setdefault(hilo, {})[rid] = n
    solicitud = {h: rid for h, (rid, _t) in snap["esperas"].items()}
    hilos = set(asignacion_por_hilo) | set(solicitud)
    finish = {h: (h not in asignacion_por_hilo) for h in hilos}

    progreso = True
    while progreso:
        progreso = False
        for h in hilos:
            if finish[h]:
                continue
            rid = solicitud.get(h)
            if rid is None or work.get(rid, 0) >= 1:          # Solicitud_i <= Work
                for r, n in asignacion_por_hilo.get(h, {}).items():
                    work[r] = work.get(r, 0) + n
                finish[h] = True
                progreso = True
    return {h for h in hilos if not finish[h]}


def aristas_del_ciclo(ciclo) -> set:
    if not ciclo:
        return set()
    return {(ciclo[i], ciclo[i + 1]) for i in range(len(ciclo) - 1)}


def texto_ciclo(ciclo, nombre_recurso) -> str:
    """'T_Usuario03 → «Redes» → T_Usuario05 → «SO Modernos» → T_Usuario03'"""
    partes = []
    for n in ciclo:
        tipo, ident = n.split(":", 1)
        partes.append(ident if tipo == "T" else f"«{nombre_recurso(ident)}»")
    return " → ".join(partes)
