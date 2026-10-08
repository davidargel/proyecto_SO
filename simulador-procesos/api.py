"""API REST (FastAPI) que expone el simulador para que la wiki web lo use.

Ejecutar:  uvicorn api:app --reload      (desde la carpeta simulador-procesos)
Docs auto-generadas: http://127.0.0.1:8000/docs
"""
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.gestor_memoria import GestorMemoria
from src.proceso import Proceso
from src.simulador import Simulador

MEMORIA_TOTAL_MB = 1024
gestor = GestorMemoria(MEMORIA_TOTAL_MB)
simulador = Simulador(gestor)
historial = []  # Registro de eventos acumulado (la cola `eventos` se vacía al leerla)


def _bucle_simulacion():
    """Hilo de fondo: hace lo mismo que el ciclo de 500ms de la GUI de tkinter."""
    while True:
        simulador.procesar_cola()
        while not simulador.eventos.empty():
            historial.append(simulador.eventos.get())
        del historial[:-50]  # Solo guardamos los últimos 50 eventos
        time.sleep(0.5)


@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=_bucle_simulacion, daemon=True).start()
    yield


app = FastAPI(title="Simulador de Procesos", lifespan=lifespan)

# CORS: permite que la wiki (otro origen, ej. GitHub Pages) llame a esta API desde el navegador
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ProcesoNuevo(BaseModel):
    nombre: str | None = None
    memoria: int = Field(gt=0, description="MB requeridos")
    duracion: int = Field(gt=0, description="segundos de ejecución")


def _a_dict(p):
    return {"pid": p.pid, "nombre": p.nombre, "memoria": p.memoria_requerida,
            "duracion": p.duracion, "estado": p.estado}


@app.post("/procesos", status_code=201)
def crear_proceso(datos: ProcesoNuevo):
    """Crea un proceso y lo envía a la cola de espera."""
    if datos.memoria > MEMORIA_TOTAL_MB:  # Nunca cabría: quedaría en cola para siempre
        raise HTTPException(400, f"El proceso excede la RAM total ({MEMORIA_TOTAL_MB}MB)")
    proceso = Proceso(datos.memoria, datos.duracion, (datos.nombre or "").strip() or None)
    simulador.agregar_proceso(proceso)
    return _a_dict(proceso)


@app.get("/estado")
def estado():
    """Foto actual del sistema: memoria, procesos en ejecución, cola y eventos."""
    with simulador.lock_lista:
        ejecutando = [_a_dict(p) for p in simulador.procesos_ejecutando]
    return {
        "memoria": {"total": gestor.memoria_total, "usada": gestor.memoria_usada,
                    "disponible": gestor.memoria_disponible},
        "ejecutando": ejecutando,
        "cola": [_a_dict(p) for p in list(simulador.cola_espera.queue)],
        "eventos": historial[-15:],
    }
