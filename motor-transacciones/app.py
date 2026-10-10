#!/usr/bin/env python3
"""
app.py — Servidor web del Motor de Transacciones Concurrentes (Flask + Flask-SocketIO).

Uso (en WSL2 / VM Linux):
    python3 app.py                # http://localhost:5000
    python3 app.py --puerto 8080 --host 0.0.0.0

IMPORTANTE: Flask-SocketIO se ejecuta en async_mode="threading". Así los hilos del motor son
threading.Thread reales (NPTL), no "green threads" de eventlet/gevent, que NO serían hilos del SO.

El hilo T_Broadcast lee el estado real del motor y de /proc cada 250 ms y lo envía al
navegador por WebSocket. El navegador no simula nada: solo dibuja lo que recibe.
"""
import argparse
import logging
import os
import sys
import threading
import time

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO, emit

from motor import Motor
from motor.kernel import nombrar_hilo_so, tid_actual

BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder=os.path.join(BASE, "templates"), static_folder=os.path.join(BASE, "static"))
app.config["SECRET_KEY"] = "so1-proyecto2"
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")
logging.getLogger("werkzeug").setLevel(logging.ERROR)   # sin ruido de peticiones HTTP en la consola

motor = Motor(ruta_bitacora=os.path.join(BASE, "bitacora", "prestamos.wal"))


# ---------------------------------------------------------------------------
#  Difusión del estado (T_Broadcast)
# ---------------------------------------------------------------------------
class HiloBroadcast(threading.Thread):
    INTERVALO = 0.25

    def __init__(self):
        super().__init__(name="T_Broadcast", daemon=True)
        self.ultimo_log = 0

    def run(self):
        nombrar_hilo_so(self.name)
        motor.log(self.name, f"Difusión WebSocket activa (TID SO: {tid_actual()}) cada {int(self.INTERVALO * 1000)} ms", "sistema")
        while True:
            try:
                motor.tick()
                estado = motor.snapshot()
                nuevos = motor.logs_desde(self.ultimo_log)
                if nuevos:
                    self.ultimo_log = nuevos[-1]["id"]
                estado["logs"] = nuevos
                socketio.emit("estado", estado)
            except Exception as e:  # pragma: no cover
                print(f"[T_Broadcast] error: {e!r}", flush=True)
            time.sleep(self.INTERVALO)


# ---------------------------------------------------------------------------
#  Rutas HTTP
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/estado")
def api_estado():
    """Estado completo en JSON (útil como evidencia: curl localhost:5000/api/estado)."""
    return jsonify(motor.snapshot())


@app.route("/api/rag")
def api_rag():
    s = motor.snapshot()
    return jsonify({"rag": s["rag"], "hilos": s["hilos"], "pid": s["sistema"]["pid"]})


# ---------------------------------------------------------------------------
#  Eventos WebSocket (acciones del panel)
# ---------------------------------------------------------------------------
@socketio.on("connect")
def al_conectar():
    estado = motor.snapshot()
    estado["logs"] = motor.logs_desde(max(0, motor.ultimo_log_id() - 300))
    estado["historial"] = True
    emit("estado", estado)


@socketio.on("iniciar")
def on_iniciar(data):
    ok, msg = motor.iniciar_escenario((data or {}).get("escenario"))
    if not ok:
        emit("aviso", {"msg": msg})


@socketio.on("continuar")
def on_continuar(_data=None):
    motor.continuar()


@socketio.on("sin_pausas")
def on_sin_pausas(_data=None):
    motor.sin_pausas()


@socketio.on("resolver")
def on_resolver(_data=None):
    motor.resolver()


@socketio.on("reiniciar")
def on_reiniciar(_data=None):
    threading.Thread(target=motor.reiniciar, name="T_Reinicio", daemon=True).start()


@socketio.on("config")
def on_config(data):
    data = data or {}
    motor.set_config(data.get("clave"), data.get("valor"))


# ---------------------------------------------------------------------------
def banner(host, puerto):
    pid = os.getpid()
    s = motor.sistema
    linea = "=" * 78
    print(linea)
    print("      BIBLIOSYNC — MOTOR DE TRANSACCIONES CONCURRENTES & DETECTOR DE INTERBLOQUEOS")
    print(linea)
    print(f" PID del proceso principal (Linux): {pid}")
    print(f" Kernel: {s['kernel']}  ·  {s['etiqueta']}  ·  {s['libpthread']}  ·  Python {s['python']}")
    print(" Para verificar los HILOS REALES creados en Linux, abre otra terminal y ejecuta:")
    print("    1) ps -eLf | grep app.py            (una fila por hilo: columna LWP = TID)")
    print(f"    2) ps -L -o pid,lwp,stat,wchan:20,comm -p {pid}")
    print(f"    3) ls -l /proc/{pid}/task/")
    print(f"    4) htop -p {pid}   (presiona H para ver hilos)")
    print(f"    5) ./scripts/evidencia.sh {pid}     (guarda todas las evidencias en ./evidencias)")
    print(linea)
    print(f" Panel web: http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{puerto}")
    print(linea, flush=True)


def main():
    ap = argparse.ArgumentParser(description="Motor de transacciones concurrentes — Biblioteca")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--puerto", type=int, default=5000)
    args = ap.parse_args()
    if not motor.sistema["es_linux"]:
        print("ADVERTENCIA: el proyecto debe ejecutarse en Linux real (WSL2 o VM). /proc no está disponible.",
              file=sys.stderr)
    banner(args.host, args.puerto)
    motor.iniciar()
    b = HiloBroadcast()
    motor.registrar_hilo_sistema(b)
    b.start()
    socketio.run(app, host=args.host, port=args.puerto, debug=False, use_reloader=False,
                 allow_unsafe_werkzeug=True, log_output=False)


if __name__ == "__main__":
    main()
