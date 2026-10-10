# BiblioSync — Motor de Transacciones Concurrentes y Detector de Interbloqueos

**Sistemas Operativos I · Proyecto 2 · Unidades 3 (Concurrencia y Sincronización) y 4 (Interbloqueos)**
Universidad Mariano Gálvez de Guatemala — Ingeniería en Sistemas de Información

Sistema de **préstamo de libros de una biblioteca universitaria** con varias sucursales conectadas al
mismo catálogo. Cada solicitud de préstamo es un **hilo real del sistema operativo** (NPTL en Linux) que
compite por copias físicas limitadas. El motor:

1. protege cada título con un `threading.Semaphore(copias)` (semáforo contador) y demuestra que así
   **no hay condiciones de carrera** (Entregable 1);
2. tiene un **modo caótico** que respeta el orden en que cada usuario pidió sus libros, de modo que la
   **espera circular surge sola** (Entregable 2);
3. construye el **Grafo de Asignación de Recursos (RAG)** leyendo sus estructuras internas y un **hilo
   guardián** (`T_Watchdog`) lo recorre con **DFS** para detectar ciclos y **recuperar** abortando
   (rollback) a una víctima;
4. muestra todo en un **panel web en tiempo real** (Flask + Flask-SocketIO + vis-network) alimentado
   por el estado real del backend y de `/proc/<PID>/task`.

> No hay simulaciones ni datos de ejemplo: si un hilo aparece en el panel es porque existe en
> `/proc/<PID>/task`, y si hay una arista en el grafo es porque un semáforo real está tomado o esperado.

---

## 1. Requisitos

| Componente | Versión |
|---|---|
| Linux real: **WSL2** (Ubuntu 22.04/24.04) o máquina virtual | kernel 5.x o superior |
| Python | 3.10 o superior |
| Paquetes Python | `Flask`, `Flask-SocketIO`, `simple-websocket` (ver `requirements.txt`) |
| Herramientas para evidencias | `procps` (ps, top), `htop`, `strace`, `curl` |

## 2. Instalación y ejecución en WSL2

```bash
# 1) Herramientas del sistema
sudo apt update
sudo apt install -y python3 python3-venv python3-pip htop strace curl

# 2) Copiar el proyecto DENTRO del sistema de archivos de Linux (recomendado: fsync es mucho más
#    rápido en ~/ que en /mnt/c/...)
git clone https://github.com/davidargel/proyecto_SO.git ~/proyecto_SO
cd ~/proyecto_SO/motor-transacciones

# 3) Entorno virtual + dependencias + arranque (todo en uno)
./run.sh
#    o manualmente:
#    python3 -m venv .venv && source .venv/bin/activate
#    pip install -r requirements.txt
#    python3 app.py
```

Abre **http://localhost:5000** en el navegador de Windows (WSL2 reenvía `localhost`).
Opciones: `python3 app.py --puerto 8080 --host 0.0.0.0`.

Al arrancar, la consola imprime el **PID** y los comandos para verificar los hilos:

```
==============================================================================
      BIBLIOSYNC — MOTOR DE TRANSACCIONES CONCURRENTES & DETECTOR DE INTERBLOQUEOS
==============================================================================
 PID del proceso principal (Linux): 580
 Para verificar los HILOS REALES creados en Linux, abre otra terminal y ejecuta:
    1) ps -eLf | grep app.py
    2) ps -L -o pid,lwp,stat,wchan:20,comm -p 580
    3) ls -l /proc/580/task/
    4) htop -p 580   (presiona H para ver hilos)
    5) ./scripts/evidencia.sh 580
```

## 3. Uso del panel

| Control | Qué hace |
|---|---|
| **Transacciones Normales** | Oleada de 6 préstamos combinados. Cada hilo pide sus libros en **orden ascendente de ISBN** → la espera circular es imposible (prevención). |
| **Provocar Interbloqueo (Deadlock)** | **Modo caótico**: el generador lee la cola de peticiones y respeta el orden de cada usuario. Si las solicitudes se cruzan (A→B y B→A), se forma un ciclo real. Si una oleada termina sin ciclo, se toma la siguiente. |
| **Resolver Interbloqueo (Watchdog DFS)** | Pide al hilo guardián un escaneo inmediato y la recuperación: aborta a la víctima (la última en entrar al ciclo), que hace ROLLBACK. |
| **Probar Condición de Carrera** | 12 reservas en línea simultáneas de «Cálculo» (3 copias). Con el interruptor **Protección con Semáforos** apagado se ve el sobre-préstamo; encendido, exactamente 3 préstamos. |
| **Reiniciar Estado** | Aborta todos los hilos de transacción y deja el inventario completo. |
| **Modo Explicación (Pausas)** | Detiene los hilos en puntos de control (como breakpoints) y muestra *Paso N de M* con tres columnas: qué ocurrió, concepto de SO y evidencia del kernel. **Espacio** = continuar. |
| **Recuperación automática** | Si está activa, el watchdog recupera en cuanto confirma el ciclo; si no, espera el botón *Resolver*. |

Distribución del panel: a la **izquierda**, la barra azul marino con los escenarios, los botones de control,
la configuración y los datos del sistema (kernel, PID, hilos). A la **derecha**, el área de trabajo:
indicadores, explicación paso a paso y cuatro paneles:

* **Estantería**: copias por título (cuadros), quién las retiene, quién espera, estaciones de préstamo.
* **RAG dinámico**: círculos = hilos, rectángulos = recursos (libres/total). Verde sólido = asignación
  (recurso → hilo); ámbar punteado = solicitud (hilo → recurso, el hilo duerme en futex); rojo = ciclo.
* **Monitor `/proc/[PID]/task`**: TID (LWP), estado del planificador (`R`, `S`), `wchan`
  (p. ej. `futex_do_wait`), número de syscall (`202 = futex`) y recurso.
* **Bitácora del backend**: espejo de la consola (adquisiciones, esperas en futex, alertas del watchdog, rollbacks).

## 4. Guion de la demostración (Entregable 3)

1. `./run.sh` → mostrar el banner con el PID. En otra terminal: `ps -eLf | grep app.py` (3–5 hilos).
2. **Transacciones Normales** con *Modo Explicación* activado → recorrer las 3 fases (2PL).
   Mientras está en pausa: `ps -L -o pid,lwp,stat,wchan:20,comm -p <PID>` → los `T_UsuarioNN` aparecen
   con `futex_do_wait`.
3. **Provocar Interbloqueo** → Fase 1 (cada hilo toma su primer libro) → Fase 2: ciclo en rojo,
   alerta del watchdog, 4 condiciones de Coffman. Ejecutar `./scripts/evidencia.sh` **en ese momento**.
4. **Continuar / Resolver** → Fase 3: víctima, ROLLBACK, los demás terminan, integridad OK.
5. Apagar *Protección con Semáforos* → **Probar Condición de Carrera** → 12 préstamos de 3 copias
   (integridad VIOLADA). Encenderla y repetir → 3 préstamos, 9 rechazos.
6. `python3 scripts/prueba_carga.py` → 100 hilos × 200 operaciones con y sin semáforos.

## 5. Evidencias externas al programa

```bash
./scripts/evidencia.sh              # guarda en evidencias/<fecha>_pid<PID>/
python3 scripts/prueba_carga.py     # integridad bajo carga → evidencias/prueba_carga_<fecha>.txt
sudo strace -f -tt -e trace=futex -p <PID>     # ver FUTEX_WAIT / FUTEX_WAKE en vivo
tail -f bitacora/prestamos.wal                  # BEGIN / ADQUIRIDO / COMMIT / ABORT / ROLLBACK con TID
curl -s localhost:5000/api/estado | python3 -m json.tool | less   # RAG y estado interno en JSON
```

`evidencia.sh` genera: `ps -eLf`, `ps -L ... wchan`, `ls /proc/<PID>/task`, detalle por hilo
(`comm`, `stat`, `wchan`, `syscall`), `status`, `top -H`, el JSON del RAG, `strace` (si hay permisos)
y las últimas líneas de la bitácora.

## 6. Arquitectura

```
 Navegador (index.html + app.js + vis-network)
        ▲  WebSocket (Socket.IO, cada 250 ms)          acciones: iniciar / continuar / resolver / config
        │                                                         │
 ┌──────┴──────────────────────── proceso python3 app.py (PID) ───▼─────────────────────────────┐
 │  T_Principal (Flask-SocketIO, async_mode="threading")    T_Broadcast: snapshot() + /proc      │
 │                                                                                              │
 │  T_Generador ──► cola de peticiones (queue.Queue) ──► T_Usuario01 … T_UsuarioNN (hilos NPTL) │
 │                                                          │ acquire()/release()               │
 │                                   ┌──────────────────────▼───────────────────────┐           │
 │                                   │ SemaforoRastreado = threading.Semaphore(n)   │           │
 │                                   │  + EstadoRecursos (threading.Lock):          │           │
 │                                   │    quién RETIENE qué / quién ESPERA qué      │──► RAG    │
 │                                   └──────────────────────▲───────────────────────┘           │
 │  T_Watchdog: cada 0.5 s copia el estado → RAG → DFS → Work/Finish → víctima → ABORT          │
 │  Bitácora WAL (bitacora/prestamos.wal): write + fsync por evento → rollback                   │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Archivo | Responsabilidad |
|---|---|
| `app.py` | Servidor Flask-SocketIO (modo *threading*), hilo `T_Broadcast`, API `/api/estado`. |
| `motor/catalogo.py` | Títulos, copias (valor inicial de cada semáforo), estaciones, ISBN (orden global). |
| `motor/recursos.py` | `SemaforoRastreado`, `EstadoRecursos`, versión *sin protección* para la carrera. |
| `motor/transacciones.py` | `HiloPrestamo` (2PL, rollback) y `HiloReservaEnLinea` (prueba de carrera). |
| `motor/generador.py` | Cola de peticiones y `T_Generador` (productor–consumidor, oleadas). |
| `motor/rag.py` | Construcción del RAG, **DFS** con colores, algoritmo **Work/Finish** (multi-instancia). |
| `motor/watchdog.py` | `T_Watchdog`: detección periódica, confirmación y recuperación (víctima). |
| `motor/pasos.py` / `explicaciones.py` | Modo explicación (checkpoints) y textos dinámicos. |
| `motor/kernel.py` | Lectura de `/proc/self/task/<TID>/{stat,wchan,syscall,comm}` y `prctl(PR_SET_NAME)`. |
| `motor/bitacora.py` | Write-Ahead Log con `os.write` + `os.fsync`. |
| `scripts/evidencia.sh` | Captura de evidencias con herramientas del SO. |
| `scripts/prueba_carga.py` | Prueba de integridad bajo carga (con y sin semáforos). |

## 7. Cómo se cumple cada requisito de la guía

| Requisito | Dónde / cómo |
|---|---|
| Hilos reales del SO, verificables con `ps -eLf`, `/proc/[pid]/task`, `htop` | `threading.Thread` (NPTL, 1:1). Cada hilo se nombra con `prctl` (`T_Usuario03`, `T_Watchdog`…) y el panel lee su TID y estado de `/proc`. |
| Semáforos y/o locks nativos protegiendo secciones críticas | `threading.Semaphore(copias)` por título y para estaciones; `threading.Lock` para el estado interno. |
| Provocar y comprobar una condición de carrera real | Botón de carrera sin protección (verificar-y-actuar + E/S real) y `prueba_carga.py`. |
| Integridad bajo carga | `prueba_carga.py`: 0 violaciones con semáforos vs. miles sin ellos. |
| Modo que fuerza las 4 condiciones de Coffman | Modo caótico: 1 copia por título (exclusión mutua), retención y espera, no apropiación, orden de la cola (espera circular). |
| Deadlock NO actuado con `sleep()` | Ningún `sleep` entre adquisiciones: el cruce surge del orden de la cola, del planificador y de la E/S real (`fsync`). |
| RAG construido desde el estado real | `rag.construir_grafo(estado.copiar())` — mismas estructuras que modifica cada `acquire()/release()`. |
| Hilo guardián con DFS/Tarjan | `T_Watchdog` → DFS iterativo con colores + confirmación Work/Finish. |
| Estrategia de recuperación | Terminación de la víctima más reciente con ROLLBACK (bitácora) y reintento limitado. |
| README para reproducir en WSL/VM + demo en vivo | Este archivo, secciones 2 y 4. |

## 8. Solución de problemas

* **El panel dice "sin conexión"**: verifica que `app.py` siga corriendo y abre `http://localhost:5000`.
* **`strace: attach: ptrace(PTRACE_SEIZE): Operation not permitted`**: usa `sudo strace ...`.
* **Todo va lento en `/mnt/c`**: copia el proyecto a `~/` dentro de WSL (el `fsync` en NTFS es lento).
* **El modo caótico tardó en formar el ciclo**: es normal que alguna oleada no se cruce; el generador
  lanza la siguiente automáticamente (máx. 6 oleadas).
* **Puerto ocupado**: `python3 app.py --puerto 5050`.

Bibliotecas incluidas en `static/vendor` (para que funcione sin internet): vis-network 9.1 (MIT/Apache-2.0),
Socket.IO client 4.8 (MIT); fuentes IBM Plex Sans y JetBrains Mono (OFL).
