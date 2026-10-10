/* ==========================================================================
   BiblioSync — cliente del panel.
   No contiene datos de ejemplo: TODO lo que se dibuja llega del backend por
   WebSocket (evento "estado"), construido a partir de los hilos reales, los
   semáforos y /proc/<PID>/task.
   ========================================================================== */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const socket = io({ transports: ["websocket", "polling"] });
  let ultimo = null;
  let totalLogs = 0;

  // ------------------------------------------------------------ conexión
  socket.on("connect", () => setConexion("ok", "conectado · WebSocket"));
  socket.on("disconnect", () => setConexion("caida", "desconectado"));
  socket.on("connect_error", () => setConexion("caida", "sin conexión con el backend"));
  socket.on("aviso", (d) => aviso(d.msg));
  socket.on("estado", (s) => {
    if (s.historial) { $("terminal").innerHTML = ""; totalLogs = 0; }
    ultimo = s;
    render(s);
  });

  function setConexion(clase, texto) {
    const el = $("conexion");
    el.className = "conexion " + clase;
    el.querySelector("span").textContent = texto;
  }
  let avisoTimer = null;
  function aviso(msg) {
    const el = $("aviso");
    el.textContent = msg; el.hidden = false;
    clearTimeout(avisoTimer);
    avisoTimer = setTimeout(() => (el.hidden = true), 3500);
  }

  // ------------------------------------------------------------ acciones
  document.querySelectorAll("[data-escenario]").forEach((b) =>
    b.addEventListener("click", () => socket.emit("iniciar", { escenario: b.dataset.escenario })));
  $("btn-resolver").addEventListener("click", () => socket.emit("resolver"));
  $("btn-reiniciar").addEventListener("click", () => socket.emit("reiniciar"));
  $("btn-continuar").addEventListener("click", () => socket.emit("continuar"));
  $("btn-sin-pausas").addEventListener("click", () => socket.emit("sin_pausas"));
  $("btn-limpiar").addEventListener("click", () => { $("terminal").innerHTML = ""; totalLogs = 0; $("n-logs").textContent = "0"; });
  const toggles = { "t-pausas": "pausas", "t-proteccion": "proteccion", "t-auto": "auto_recuperacion" };
  Object.entries(toggles).forEach(([id, clave]) =>
    $(id).addEventListener("change", (e) => socket.emit("config", { clave, valor: e.target.checked })));
  document.addEventListener("keydown", (e) => {
    // Espacio = "Continuar siguiente paso" mientras haya una pausa en pantalla
    if (e.code === "Space" && ultimo && ultimo.paso && ultimo.paso.pausa &&
        !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      socket.emit("continuar");
    }
  });

  // ------------------------------------------------------------ render general
  function render(s) {
    renderCabecera(s);
    renderPaso(s);
    renderMetricas(s);
    renderRecursos(s);
    renderRAG(s);
    renderHilos(s);
    renderLogs(s.logs || []);
  }

  function renderCabecera(s) {
    $("chip-kernel").textContent = s.sistema.etiqueta;
    $("chip-kernel").title = `Kernel ${s.sistema.kernel} · ${s.sistema.libpthread} · Python ${s.sistema.python}`;
    $("chip-pid").textContent = s.sistema.pid;
    $("chip-hilos").textContent = `${s.sistema.hilos_so} hilos`;

    const corriendo = s.escenario.corriendo;
    document.querySelectorAll("[data-escenario]").forEach((b) => {
      b.disabled = corriendo;
      b.classList.toggle("activo", corriendo && b.dataset.escenario === s.escenario.nombre);
    });
    const dl = s.rag.estado === "deadlock";
    $("btn-resolver").classList.toggle("urgente", dl && !s.rag.recuperando);

    const c = s.config;
    $("t-pausas").checked = c.pausas;
    $("t-proteccion").checked = c.proteccion;
    $("t-auto").checked = c.auto_recuperacion;
    setInsignia("b-pausas", c.pausas ? "PAUSAS ACTIVAS" : "SIN PAUSAS", c.pausas ? "on" : "");
    setInsignia("b-proteccion", c.proteccion ? "ACTIVADO · semáforo seguro" : "DESACTIVADO · riesgo de carrera",
      c.proteccion ? "on" : "off-peligro");
    setInsignia("b-auto", c.auto_recuperacion ? "AUTOMÁTICA (watchdog)" : "MANUAL (botón Resolver)", c.auto_recuperacion ? "on" : "");
    const bc = $("btn-carrera");
    bc.querySelector(".esc-desc").textContent = c.proteccion
      ? "12 reservas simultáneas · con semáforo" : "12 reservas simultáneas · SIN semáforo";
    bc.classList.toggle("peligro", !c.proteccion);
  }
  function setInsignia(id, texto, clase) { const el = $(id); el.textContent = texto; el.className = "insignia " + clase; }

  function renderPaso(s) {
    const p = s.paso || {};
    const panel = $("panel-paso");
    panel.className = "card explicacion tipo-" + (p.tipo || "info");
    const etiquetas = { pausa: "PAUSA PARA EXPLICACIÓN", alerta: "ALERTA DEL WATCHDOG", exito: "RESULTADO", info: "ESTADO DEL MOTOR" };
    let etiqueta = p.pausa ? "PAUSA PARA EXPLICACIÓN" : (p.etiqueta || etiquetas[p.tipo] || "ESTADO DEL MOTOR");
    $("p-etiqueta").querySelector("span").textContent = etiqueta;
    const num = $("p-numero");
    const pasos = $("p-pasos");
    if (p.numero && p.total) {
      num.hidden = false; num.textContent = `Paso ${p.numero} de ${p.total}`;
      pasos.hidden = false;
      let html = "";
      for (let i = 1; i <= p.total; i++) {
        if (i > 1) html += `<b class="${i <= p.numero ? "hecho" : ""}"></b>`;
        html += `<i class="${i < p.numero ? "hecho" : i === p.numero ? "actual" : ""}">${i}</i>`;
      }
      pasos.innerHTML = html;
    } else { num.hidden = true; pasos.hidden = true; }
    $("p-titulo").textContent = p.titulo || "";
    $("p-resumen").innerHTML = p.resumen || "";
    $("p-que").innerHTML = p.que || "—";
    $("p-concepto").innerHTML = p.concepto || "—";
    $("p-evidencia").innerHTML = p.evidencia || "—";
    $("btn-continuar").disabled = !p.pausa;
    $("btn-sin-pausas").disabled = !s.config.pausas;
  }

  function renderMetricas(s) {
    const m = s.metricas;
    const e = s.escenario;
    const nombres = { normal: "Transacciones normales", deadlock: "Modo caótico (deadlock)", carrera: "Condición de carrera" };
    $("m-escenario").textContent = e.nombre ? nombres[e.nombre] : "Ninguno";
    let sub = "elige un escenario en el panel izquierdo";
    if (e.nombre) sub = (e.corriendo ? "en ejecución" : "finalizado") + (e.oleada ? ` · oleada ${e.oleada}` : "") +
      (m.transacciones_vivas ? ` · ${m.transacciones_vivas} hilos` : "") + (m.cola ? ` · cola ${m.cola}` : "");
    $("m-escenario-sub").textContent = sub;
    $("m-completados").textContent = m.completados || 0;
    $("m-espera").textContent = m.en_espera || 0;
    $("m-deadlocks").textContent = m.deadlocks || 0;
    $("m-deadlocks").parentElement.classList.toggle("caliente", s.rag.estado === "deadlock");
    $("m-escaneos").textContent = `${m.escaneos_watchdog || 0} escaneos DFS`;
    $("m-rollbacks").textContent = m.abortados || 0;
    const box = $("m-integridad-box");
    box.classList.toggle("ok", s.integridad);
    box.classList.toggle("mal", !s.integridad);
    $("m-integridad").textContent = s.integridad ? "OK" : "VIOLADA";
    $("m-integridad-sub").textContent = s.integridad ? "disponibles + prestadas = copias"
      : `sobre-préstamo: ${m.sobreprestamo || 0} copias fantasma`;
  }

  // ------------------------------------------------------------ recursos
  function renderRecursos(s) {
    const libros = s.recursos.filter((r) => r.tipo === "libro");
    const est = s.recursos.find((r) => r.tipo === "estacion");
    const ciclo = new Set((s.rag.nodos || []).filter((n) => n.en_ciclo && n.tipo === "recurso").map((n) => n.id.slice(2)));
    const libres = libros.reduce((a, r) => a + Math.max(0, r.disponibles), 0);
    const total = libros.reduce((a, r) => a + r.total, 0);
    $("copias-libres").textContent = `${libres}/${total} copias libres`;

    $("libros").innerHTML = libros.map((r) => {
      const ret = Object.entries(r.retenedores);
      const prestadas = r.registrados;
      const cls = ["libro"];
      if (prestadas > 0) cls.push("tomado");
      if (r.disponibles <= 0) cls.push("agotado");
      if (r.esperando.length) cls.push("con-espera");
      if (ciclo.has(r.id)) cls.push("en-ciclo");
      if (!r.integro) cls.push("violado");
      let cuadros = "";
      for (let i = 0; i < Math.max(r.total, prestadas); i++) {
        const c = i >= r.total ? "copia fantasma" : i < Math.min(prestadas, r.total) ? "copia tomada" : "copia";
        cuadros += `<i class="${c}" title="${i >= r.total ? "copia fantasma (no existe)" : "copia " + (i + 1)}"></i>`;
      }
      const quien = ret.length
        ? "Held: " + ret.map(([h, n]) => n > 1 ? `${h}×${n}` : h).join(", ")
        : "Disponible";
      const contador = `disp=${r.disponibles} · prest=${prestadas}/${r.total}`;
      return `<div class="${cls.join(" ")}" title="${esc(r.titulo)} — ${esc(r.autor)} · ISBN ${esc(r.id)}">
        <div class="l-cab"><svg><use href="#i-libro"/></svg><span class="l-nombre">${esc(r.corto)}</span></div>
        <div class="l-autor">${esc(r.autor)}</div>
        <div class="copias">${cuadros}</div>
        <div class="l-estado">${esc(quien)}</div>
        <div class="l-estado cifras">${contador}</div>
        ${r.esperando.length ? `<div class="l-espera">En espera: ${esc(r.esperando.join(", "))}</div>` : ""}
      </div>`;
    }).join("");

    if (est) {
      let slots = "";
      for (let i = 0; i < est.total; i++) slots += `<i class="slot ${i < est.total - est.disponibles ? "tomada" : ""}"></i>`;
      const usando = Object.keys(est.retenedores);
      $("estaciones").innerHTML = `<span class="e-titulo"><svg><use href="#i-mostrador"/></svg>Estaciones de préstamo</span>
        <span class="e-slots">${slots}</span>
        <span class="e-info">${usando.length ? "En uso: " + esc(usando.join(", ")) : "Todas libres"}${est.esperando.length ? ` · esperan: ${esc(est.esperando.join(", "))}` : ""}</span>`;
    }
  }

  // ------------------------------------------------------------ RAG (vis-network)
  const nodosDS = new vis.DataSet();
  const aristasDS = new vis.DataSet();
  const red = new vis.Network($("rag"), { nodes: nodosDS, edges: aristasDS }, {
    physics: false,
    interaction: { hover: true, dragNodes: true, zoomView: true, dragView: true, tooltipDelay: 120 },
    nodes: { font: { face: "IBM Plex Sans", color: "#0f172a", size: 13 }, borderWidth: 2, shadow: { enabled: false } },
    edges: { smooth: { enabled: true, type: "curvedCW", roundness: 0.08 }, arrows: { to: { enabled: true, scaleFactor: 0.7 } },
      font: { face: "JetBrains Mono", size: 11, color: "#0f172a", strokeWidth: 0, background: "#ffffff" }, selectionWidth: 0 },
  });
  const ranuras = new Map();       // hilo -> {lado, fila} para posiciones estables
  let firmaNodos = "";

  function posicionHilo(nombre) {
    if (!ranuras.has(nombre)) {
      const usadas = new Set([...ranuras.values()].map((r) => r.lado + ":" + r.fila));
      for (let fila = 0; fila < 40; fila++) {
        for (const lado of [-1, 1]) {
          if (!usadas.has(lado + ":" + fila)) { ranuras.set(nombre, { lado, fila }); return calcular(ranuras.get(nombre)); }
        }
      }
    }
    return calcular(ranuras.get(nombre));
  }
  function calcular(r) {
    const col = Math.floor(r.fila / 8);
    return { x: r.lado * (290 + col * 120), y: -245 + (r.fila % 8) * 70 };
  }

  // Paleta institucional (tema claro): azul rey, ámbar, verde, rojo carmesí
  const coloresHilo = {
    activo:         { border: "#2457d6", background: "#e9effd", texto: "#0f2557" },
    esperando:      { border: "#d97706", background: "#fff6e6", texto: "#7a4205" },
    pausa:          { border: "#0e7490", background: "#e6f6f9", texto: "#0b4f63" },
    interbloqueado: { border: "#c62828", background: "#fdecec", texto: "#7f1414" },
    victima:        { border: "#a87a1c", background: "#fbf3e1", texto: "#5c4210" },
  };

  function renderRAG(s) {
    const r = s.rag;
    const est = $("estado-rag");
    if (r.estado === "deadlock") {
      est.className = "estado-rag deadlock";
      est.querySelector("span").textContent = "¡DEADLOCK DETECTADO! Ciclo: " + r.texto_ciclo;
    } else {
      est.className = "estado-rag normal";
      est.querySelector("span").textContent = "Estado RAG: Normal (sin ciclos)";
    }

    const recursos = r.nodos.filter((n) => n.tipo === "recurso");
    const hilos = r.nodos.filter((n) => n.tipo === "hilo");
    const vivos = new Set(hilos.map((h) => h.label));
    for (const k of [...ranuras.keys()]) if (!vivos.has(k)) ranuras.delete(k);

    const nodos = [];
    recursos.forEach((n, i) => {
      const agotado = n.disponibles <= 0;
      const neg = n.disponibles < 0;
      const colorBorde = n.en_ciclo ? "#c62828" : n.estacion ? "#2457d6" : neg ? "#c62828" : agotado ? "#b45309" : "#0f8a5f";
      nodos.push({
        id: n.id, shape: "box", x: 0, y: -245 + i * 80, fixed: false,
        label: `${n.label}\n${n.disponibles}/${n.total} libres`,
        margin: { top: 7, bottom: 7, left: 11, right: 11 },
        color: { border: colorBorde,
          background: n.en_ciclo ? "#fdecec" : n.estacion ? "#eef3ff" : agotado ? "#fff6e6" : "#e9f6ef",
          highlight: { border: "#0f2557", background: "#ffffff" }, hover: { border: "#0f2557", background: "#ffffff" } },
        font: { color: n.en_ciclo ? "#7f1414" : n.estacion ? "#1a43ad" : agotado ? "#7a4205" : "#0b5f42", size: 12.5, multi: false, face: "IBM Plex Sans" },
        borderWidth: n.en_ciclo ? 3 : 2,
        shapeProperties: { borderRadius: 6 },
        shadow: { enabled: true, color: n.en_ciclo ? "rgba(198,40,40,.35)" : "rgba(15,37,87,.12)", size: n.en_ciclo ? 14 : 6, x: 0, y: 2 },
        title: `${n.label}: ${n.disponibles} de ${n.total} instancias libres`,
      });
    });
    hilos.forEach((n) => {
      const p = posicionHilo(n.label);
      const c = coloresHilo[n.estado] || coloresHilo.activo;
      nodos.push({
        id: n.id, shape: "circle", x: p.x, y: p.y,
        label: n.label, widthConstraint: { minimum: 62, maximum: 86 },
        color: { border: c.border, background: c.background, highlight: { border: "#0f2557", background: c.background }, hover: { border: "#0f2557", background: c.background } },
        font: { color: c.texto, size: 11, face: "JetBrains Mono", bold: { color: c.texto } },
        borderWidth: n.en_ciclo ? 3.5 : 2.4,
        shadow: n.en_ciclo || n.estado === "interbloqueado" ? { enabled: true, color: "rgba(198,40,40,.35)", size: 14, x: 0, y: 2 }
          : { enabled: true, color: "rgba(15,37,87,.14)", size: 6, x: 0, y: 2 },
        title: `${n.label} · TID ${n.tid ?? "—"} · ${n.estado}`,
      });
    });

    const aristas = r.aristas.map((a) => {
      const esCiclo = a.ciclo;
      const esSol = a.tipo === "solicitud";
      return {
        id: a.id, from: a.de, to: a.a,
        label: a.n > 1 ? `×${a.n}` : undefined,
        dashes: esSol ? [7, 6] : false,
        width: esCiclo ? 3.5 : esSol ? 2 : 2.2,
        color: { color: esCiclo ? "#c62828" : esSol ? "#d97706" : "#0f8a5f", highlight: "#0f2557", hover: "#0f2557", opacity: 1 },
        smooth: esSol ? { enabled: true, type: "curvedCCW", roundness: 0.12 } : { enabled: true, type: "curvedCW", roundness: 0.06 },
        title: esSol ? "Solicitud: el hilo está bloqueado en sem.acquire()" : "Asignación: el hilo retiene la copia",
      };
    });

    // actualización incremental (sin parpadeo)
    const idsN = new Set(nodos.map((n) => n.id));
    nodosDS.remove(nodosDS.getIds().filter((id) => !idsN.has(id)));
    nodosDS.update(nodos);
    const idsA = new Set(aristas.map((a) => a.id));
    aristasDS.remove(aristasDS.getIds().filter((id) => !idsA.has(id)));
    aristasDS.update(aristas);

    const firma = [...idsN].sort().join("|");
    if (firma !== firmaNodos) {
      firmaNodos = firma;
      red.fit({ animation: { duration: 300, easingFunction: "easeInOutQuad" }, maxZoomLevel: 1.15 });
    }
  }
  window.addEventListener("resize", () => red.fit({ maxZoomLevel: 1.15 }));

  // ------------------------------------------------------------ monitor /proc
  function renderHilos(s) {
    const filas = s.hilos.map((h) => {
      const k = h.kernel || {};
      const etiqueta = k.etiqueta || "—";
      const wch = k.wchan ? (k.wchan.length > 22 ? k.wchan.slice(0, 21) + "…" : k.wchan) : "";
      const wchan = [k.estado ? `stat ${k.estado}` : "", wch, k.syscall != null && k.syscall >= 0 ? `sc ${k.syscall}${k.syscall_nombre ? " " + k.syscall_nombre : ""}` : ""]
        .filter(Boolean).join(" · ");
      let rec = '<span class="rec-no">None</span>';
      if (h.espera) rec = `<span class="rec-esp">Waiting ${esc(h.espera)}</span>`;
      if (h.retiene && h.retiene.length) rec = `<span class="rec-ret">Held ${esc(h.retiene.join(", "))}</span>` + (h.espera ? `<br>${rec}` : "");
      const cls = [h.rol === "principal" || h.rol === "sistema" ? "sistema" : "",
        h.logico === "INTERBLOQUEADO" ? "dead" : "", h.victima ? "victima" : ""].join(" ");
      return `<tr class="${cls}">
        <td class="tid">${h.tid ?? "—"}</td>
        <td class="nombre">${esc(h.nombre)}<small>${esc(h.logico)}${h.detalle ? " · " + esc(h.detalle) : ""}</small></td>
        <td><span class="est ${esc(etiqueta)}">${esc(etiqueta)}</span><span class="wchan" title="${esc(k.wchan || "")}">${esc(wchan)}</span></td>
        <td class="rec">${rec}</td></tr>`;
    }).join("");
    $("tabla-hilos").innerHTML = filas;
    const o = s.otros_hilos;
    $("otros-hilos").innerHTML = o.cantidad
      ? `+ ${o.cantidad} hilo(s) del servidor web (Werkzeug / Socket.IO) en el mismo PID: <code>${o.tids.join(", ")}${o.cantidad > o.tids.length ? ", …" : ""}</code>`
      : "";
  }

  // ------------------------------------------------------------ terminal
  function renderLogs(logs) {
    if (!logs.length) return;
    const term = $("terminal");
    const alFinal = term.scrollHeight - term.scrollTop - term.clientHeight < 40;
    const frag = document.createDocumentFragment();
    for (const l of logs) {
      const div = document.createElement("div");
      div.className = "l " + (l.nivel || "info");
      div.innerHTML = `<span class="t">[${esc(l.t)}]</span> <span class="h">[${esc(l.hilo)}]</span> ${esc(l.msg)}`;
      frag.appendChild(div);
    }
    term.appendChild(frag);
    totalLogs += logs.length;
    while (term.childElementCount > 500) term.removeChild(term.firstChild);
    $("n-logs").textContent = totalLogs;
    if (alFinal) term.scrollTop = term.scrollHeight;
  }
})();
