// Dirección de la API FastAPI. En local: uvicorn api:app. En producción: la URL https del backend desplegado.
const API_URL = "http://127.0.0.1:8000";

// Escapa texto antes de meterlo al HTML (los nombres de proceso los escribe el usuario)
const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const filas = (lista, clase = "") => lista.length
    ? lista.map((p) => `<tr class="${clase}"><td><span class="pid">${p.pid}</span></td><td>${esc(p.nombre)}</td><td>${p.memoria}</td><td>${p.duracion}</td></tr>`).join("")
    : '<tr><td colspan="4" class="vacio">Sin procesos</td></tr>';

// Clase de color para cada línea del registro según su tipo
const claseEvento = (t) => (t.startsWith("▶") ? "ini" : t.startsWith("✔") ? "fin" : "add");
const set = (id, v) => (document.getElementById(id).textContent = v);

async function actualizar() {
    const estadoApi = document.getElementById("estadoApi");
    try {
        const e = await (await fetch(`${API_URL}/estado`)).json();
        const m = e.memoria, pct = (m.usada / m.total) * 100;

        estadoApi.textContent = "API conectada";
        estadoApi.className = "ok";
        set("sTotal", m.total); set("sUsada", m.usada); set("sLibre", m.disponible);
        set("sProc", `${e.ejecutando.length} / ${e.cola.length}`);
        set("nEjec", e.ejecutando.length); set("nCola", e.cola.length);
        const barra = document.getElementById("barraUso");
        barra.style.width = pct + "%";
        barra.style.background = pct < 70 ? "linear-gradient(90deg,#66bb6a,#4CAF50)"
            : pct < 90 ? "linear-gradient(90deg,#ffd54f,#FFC107)" : "linear-gradient(90deg,#ef5350,#F44336)";
        document.getElementById("barraTexto").textContent = `${m.usada}MB / ${m.total}MB (${pct.toFixed(1)}%)`;

        document.getElementById("tEjec").innerHTML = filas(e.ejecutando, "run");
        document.getElementById("tCola").innerHTML = filas(e.cola);
        const log = document.getElementById("log");
        log.innerHTML = e.eventos.map((t) => `<div class="${claseEvento(t)}">${esc(t)}</div>`).join("");
        log.scrollTop = log.scrollHeight;
    } catch (err) {
        estadoApi.textContent = "API desconectada: inicia el backend con 'uvicorn api:app' o revisa API_URL en simulador.js";
        estadoApi.className = "mal";
    }
}

async function agregar() {
    const memoria = parseInt(document.getElementById("memoria").value);
    const duracion = parseInt(document.getElementById("duracion").value);
    if (!(memoria > 0 && duracion > 0)) { alert("Memoria y duración deben ser números mayores a 0."); return; }

    const r = await fetch(`${API_URL}/procesos`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre: document.getElementById("nombre").value, memoria, duracion }),
    });
    if (!r.ok) { alert("No se pudo crear: " + ((await r.json()).detail || r.status)); return; }
    ["nombre", "memoria", "duracion"].forEach((id) => (document.getElementById(id).value = ""));
    actualizar();
}

// Carga los mismos 5 procesos de ejemplo de la versión de consola y de tkinter
async function cargarEjemplos() {
    const ejemplos = [["navegador", 300, 20], ["editor_video", 400, 30], [null, 350, 15], [null, 200, 25], [null, 500, 12]];
    for (const [nombre, memoria, duracion] of ejemplos) {
        await fetch(`${API_URL}/procesos`, { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nombre, memoria, duracion }) });
    }
    actualizar();
}

actualizar();
setInterval(actualizar, 1000); // Refresca cada segundo, como el ciclo de la GUI
