/* Drawings workspace — PDF.js viewer + overlay markup tool (Phase 2).

   The original PDF renders on one canvas; annotations live on a second canvas
   stacked above it. Shapes are stored NORMALIZED (0..1 of the page box) so a
   markup made at any zoom or screen lands identically everywhere. This module
   only writes the 'internal' layer; rfi:/submittal: layers come with the
   pipeline and reuse everything here. */

"use strict";

/* global pdfjsLib */

const DW = (() => {
  const COLORS = ["#C23A2E", "#2F74B8", "#1E7A46", "#1A1D20", "#C7420A"];

  const state = {
    docId: null,
    pdf: null,
    pageNum: 1,
    pageCount: 0,
    scale: 1,
    tool: "pen",
    color: COLORS[0],
    shapes: [],        // current page, current layer (with ids)
    drawing: null,     // in-progress shape
    layer: "internal",
  };

  let apiRef = null;   // injected from app.js (carries the user header)

  function boot() {
    if (typeof pdfjsLib !== "undefined") {
      pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.min.js";
    }
  }

  /* ---- open / render ------------------------------------------------------- */

  async function open(docId, api, opts = {}) {
    apiRef = api;
    state.docId = docId;
    state.layer = opts.layer || "internal";
    state.pageNum = opts.page || 1;
    const task = pdfjsLib.getDocument({ url: `/api/documents/${docId}/file` });
    state.pdf = await task.promise;
    state.pageCount = state.pdf.numPages;
    if (state.pageNum > state.pageCount) state.pageNum = 1;
    await renderPage();
  }

  // Renders are strictly serialized. PDF.js refuses two render() operations
  // on one canvas ("Cannot use the same canvas during multiple render
  // operations"), and the resize that precedes a render wipes the ink layer —
  // so an overlap from fast page-flipping left a blank overlay and a stale
  // sheet label. One chain, and any in-flight task is cancelled first.
  let renderTask = null;
  let renderChain = Promise.resolve();

  function renderPage() {
    renderChain = renderChain.then(_renderPage).catch((e) => {
      if (e?.name !== "RenderingCancelledException") console.warn("render:", e);
    });
    return renderChain;
  }

  async function _renderPage() {
    const holder = document.querySelector("#dwCanvasHolder");
    const pdfCanvas = document.querySelector("#dwPdf");
    const inkCanvas = document.querySelector("#dwInk");
    if (!holder || !state.pdf) return;

    if (renderTask) { try { renderTask.cancel(); } catch { /* already done */ } }

    const page = await state.pdf.getPage(state.pageNum);
    const base = page.getViewport({ scale: 1 });
    const fitWidth = holder.clientWidth - 2;
    state.scale = Math.max(0.2, fitWidth / base.width);
    const vp = page.getViewport({ scale: state.scale });
    const dpr = window.devicePixelRatio || 1;

    for (const c of [pdfCanvas, inkCanvas]) {
      c.width = Math.floor(vp.width * dpr);
      c.height = Math.floor(vp.height * dpr);
      c.style.width = `${Math.floor(vp.width)}px`;
      c.style.height = `${Math.floor(vp.height)}px`;
    }
    const ctx = pdfCanvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // intent "print": PDF.js paces display-intent rendering with
    // requestAnimationFrame, which browsers stop for hidden/backgrounded
    // tabs — a render started there hangs forever. Print intent uses
    // timeouts, renders identically for our purposes, and always finishes.
    renderTask = page.render({ canvasContext: ctx, viewport: vp, intent: "print" });
    try {
      await renderTask.promise;
    } finally {
      renderTask = null;
    }

    const meta = document.querySelector("#dwPageMeta");
    if (meta) meta.textContent = `Sheet ${state.pageNum} / ${state.pageCount}`;

    await loadShapes();
  }

  async function loadShapes() {
    const { annotations } = await apiRef(
      `/api/documents/${state.docId}/annotations?layer=${encodeURIComponent(state.layer)}&page=${state.pageNum}`);
    state.shapes = annotations;
    drawAll();
  }

  /* ---- drawing ------------------------------------------------------------- */

  function ink() { return document.querySelector("#dwInk"); }

  function drawAll() {
    const c = ink();
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, c.width, c.height);
    const W = c.width / dpr, H = c.height / dpr;
    for (const a of state.shapes) drawShape(ctx, a.shape, W, H);
    if (state.drawing) drawShape(ctx, state.drawing, W, H, true);
  }

  function drawShape(ctx, s, W, H, ghost = false) {
    ctx.save();
    ctx.globalAlpha = ghost ? 0.75 : 1;
    ctx.strokeStyle = s.color || COLORS[0];
    ctx.fillStyle = s.color || COLORS[0];
    ctx.lineWidth = (s.width || 0.0035) * W;
    ctx.lineCap = ctx.lineJoin = "round";
    if (s.type === "pen" && s.points?.length) {
      ctx.beginPath();
      s.points.forEach(([x, y], i) => (i ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H)));
      ctx.stroke();
    } else if (s.type === "rect") {
      ctx.strokeRect(s.x * W, s.y * H, s.w * W, s.h * H);
    } else if (s.type === "ellipse") {
      ctx.beginPath();
      ctx.ellipse((s.x + s.w / 2) * W, (s.y + s.h / 2) * H,
                  Math.max(1, (s.w / 2) * W), Math.max(1, (s.h / 2) * H), 0, 0, Math.PI * 2);
      ctx.stroke();
    } else if (s.type === "arrow") {
      const x1 = s.x1 * W, y1 = s.y1 * H, x2 = s.x2 * W, y2 = s.y2 * H;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      const ang = Math.atan2(y2 - y1, x2 - x1), h = Math.max(9, ctx.lineWidth * 3.2);
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - h * Math.cos(ang - 0.45), y2 - h * Math.sin(ang - 0.45));
      ctx.lineTo(x2 - h * Math.cos(ang + 0.45), y2 - h * Math.sin(ang + 0.45));
      ctx.closePath(); ctx.fill();
    } else if (s.type === "text" && s.text) {
      const px = Math.max(11, (s.size || 0.016) * H);
      ctx.font = `600 ${px}px Bahnschrift, 'Segoe UI', sans-serif`;
      ctx.textBaseline = "top";
      if (s.w) {
        // text box: border + text wrapped to the box width
        ctx.strokeRect(s.x * W, s.y * H, s.w * W, (s.h || 0.04) * H);
        const pad = 4, maxW = s.w * W - pad * 2;
        let line = "", ty = s.y * H + pad;
        for (const word of s.text.split(/\s+/)) {
          const probe = line ? line + " " + word : word;
          if (line && ctx.measureText(probe).width > maxW) {
            ctx.fillText(line, s.x * W + pad, ty);
            ty += px * 1.25;
            line = word;
          } else {
            line = probe;
          }
        }
        if (line) ctx.fillText(line, s.x * W + pad, ty);
      } else {
        ctx.fillText(s.text, s.x * W, s.y * H);
      }
    }
    ctx.restore();
  }

  function norm(e) {
    const r = ink().getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    ];
  }

  function onDown(e) {
    if (state.tool === "eraser") return eraseAt(e);
    const [x, y] = norm(e);
    ink().setPointerCapture(e.pointerId);
    if (state.tool === "text") {
      // click places point text; DRAG sizes a text box — decided on pointerup.
      e.preventDefault(); // keep focus off the canvas so the editor keeps it
      state.drawing = { type: "text", x, y, w: 0, h: 0, _x0: x, _y0: y, color: state.color };
      return;
    }
    state.drawing =
      state.tool === "pen" ? { type: "pen", points: [[x, y]], color: state.color }
      : state.tool === "rect" || state.tool === "ellipse"
        ? { type: state.tool, x, y, w: 0, h: 0, _x0: x, _y0: y, color: state.color }
      : { type: "arrow", x1: x, y1: y, x2: x, y2: y, color: state.color };
  }

  function onMove(e) {
    if (!state.drawing) return;
    const [x, y] = norm(e);
    const s = state.drawing;
    if (s.type === "pen") s.points.push([x, y]);
    else if (s.type === "rect" || s.type === "ellipse" || s.type === "text") {
      s.x = Math.min(s._x0, x); s.y = Math.min(s._y0, y);
      s.w = Math.abs(x - s._x0); s.h = Math.abs(y - s._y0);
    } else { s.x2 = x; s.y2 = y; }
    if (s.type !== "text") drawAll();
  }

  async function onUp(e) {
    const s = state.drawing;
    state.drawing = null;
    if (!s) return;
    if (s.type === "text") return openTextEditor(e, s);
    if (s.type === "pen" && s.points.length < 2) return drawAll();
    if ((s.type === "rect" || s.type === "ellipse") && (s.w < 0.004 || s.h < 0.004)) return drawAll();
    if (s.type === "arrow" && Math.hypot(s.x2 - s.x1, s.y2 - s.y1) < 0.006) return drawAll();
    delete s._x0; delete s._y0;
    await save(s);
  }

  /* Text editor overlay. Opens on pointerUP (opening on pointerdown lost a
     focus race with the canvas: the click's default focus handling blurred
     the input instantly, which auto-committed empty text and removed it —
     "text does not work"). Commit: Enter or click elsewhere. Esc cancels. */
  function openTextEditor(e, s) {
    const holder = document.querySelector("#dwCanvasHolder");
    const inkC = ink();
    const r = inkC.getBoundingClientRect(), hr = holder.getBoundingClientRect();
    const boxMode = s.w > 0.02 && s.h > 0.015;

    const input = document.createElement(boxMode ? "textarea" : "input");
    input.className = "dw-textinput";
    input.style.left = `${s.x * r.width + (r.left - hr.left) + holder.scrollLeft}px`;
    input.style.top = `${s.y * r.height + (r.top - hr.top) + holder.scrollTop}px`;
    if (boxMode) {
      input.style.width = `${s.w * r.width}px`;
      input.style.height = `${Math.max(34, s.h * r.height)}px`;
    }
    input.style.color = s.color;
    holder.appendChild(input);
    // focus after the click cycle fully settles
    setTimeout(() => input.focus(), 30);

    let done = false;
    const commit = async () => {
      if (done) return; done = true;
      const text = input.value.trim();
      input.remove();
      if (!text) return;
      const shape = { type: "text", x: s.x, y: s.y, text, color: s.color };
      if (boxMode) { shape.w = s.w; shape.h = s.h; }
      await save(shape);
    };
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (!boxMode || !ev.shiftKey)) { ev.preventDefault(); commit(); }
      if (ev.key === "Escape") { done = true; input.remove(); }
    });
    input.addEventListener("blur", commit);
    input.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  }

  async function eraseAt(e) {
    const [x, y] = norm(e);
    const hit = [...state.shapes].reverse().find((a) => hitTest(a.shape, x, y));
    if (!hit) return;
    await apiRef(`/api/annotations/${hit.id}`, { method: "DELETE" });
    await loadShapes();
  }

  function hitTest(s, x, y) {
    const T = 0.012;
    if (s.type === "pen") return s.points?.some(([px, py]) => Math.hypot(px - x, py - y) < T);
    if (s.type === "ellipse") {
      const rx = Math.max(s.w / 2, 1e-4), ry = Math.max(s.h / 2, 1e-4);
      const q = Math.hypot((x - (s.x + rx)) / rx, (y - (s.y + ry)) / ry);
      return Math.abs(q - 1) < 0.18 || (rx < T * 2 && ry < T * 2);
    }
    if (s.type === "rect")
      return x > s.x - T && x < s.x + s.w + T && y > s.y - T && y < s.y + s.h + T &&
        (Math.abs(x - s.x) < T || Math.abs(x - (s.x + s.w)) < T ||
         Math.abs(y - s.y) < T || Math.abs(y - (s.y + s.h)) < T || (s.w < T * 3 || s.h < T * 3));
    if (s.type === "arrow") {
      const d = distToSeg(x, y, s.x1, s.y1, s.x2, s.y2);
      return d < T;
    }
    if (s.type === "text") {
      if (s.w) return x > s.x && x < s.x + s.w && y > s.y && y < s.y + (s.h || 0.04);
      return Math.hypot(s.x - x, s.y - y) < 0.05;
    }
    return false;
  }

  function distToSeg(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1;
    const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy || 1)));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }

  async function save(shape) {
    const rec = await apiRef(`/api/documents/${state.docId}/annotations`, {
      method: "POST",
      body: JSON.stringify({ page: state.pageNum, layer: state.layer, shape }),
    });
    state.shapes.push(rec);
    drawAll();
  }

  /* ---- toolbar wiring -------------------------------------------------------- */

  /* Per-tool cursors ("eraser needs an eraser icon when using, and same for
     drawing tools"). Tiny inline SVGs with a white halo so they read on both
     the sheet and dark surfaces; hotspot at the working tip. */
  const cur = (svg, hx, hy, fallback) =>
    `url("data:image/svg+xml,${encodeURIComponent(svg)}") ${hx} ${hy}, ${fallback}`;
  const HALO = 'stroke="white" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round" fill="none"';
  const INKS = 'stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"';
  const CURSORS = {
    pen: cur(`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><g ${HALO}><path d="M3 21l3.4-1 12-12-2.4-2.4-12 12zM14.6 5.2l2.4 2.4"/></g><g ${INKS}><path d="M3 21l3.4-1 12-12-2.4-2.4-12 12zM14.6 5.2l2.4 2.4"/></g></svg>`, 2, 21, "crosshair"),
    rect: cur(`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><g ${HALO}><path d="M12 4v16M4 12h16"/><rect x="14" y="14" width="8" height="6"/></g><g ${INKS}><path d="M12 4v16M4 12h16"/><rect x="14" y="14" width="8" height="6"/></g></svg>`, 12, 12, "crosshair"),
    ellipse: cur(`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><g ${HALO}><path d="M12 4v16M4 12h16"/><ellipse cx="18" cy="17" rx="5" ry="4"/></g><g ${INKS}><path d="M12 4v16M4 12h16"/><ellipse cx="18" cy="17" rx="5" ry="4"/></g></svg>`, 12, 12, "crosshair"),
    arrow: cur(`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><g ${HALO}><path d="M4 20L18 6M18 6h-7M18 6v7"/></g><g ${INKS}><path d="M4 20L18 6M18 6h-7M18 6v7"/></g></svg>`, 4, 20, "crosshair"),
    text: "text",
    eraser: cur(`<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26"><g ${HALO}><path d="M6 20h9M4 17l9-9 6 6-6 6h-4z"/><path d="M9 12l6 6"/></g><g ${INKS}><path d="M6 20h9M4 17l9-9 6 6-6 6h-4z" fill="white"/><path d="M9 12l6 6"/></g></svg>`, 6, 18, "not-allowed"),
  };

  function setTool(tool) {
    state.tool = tool;
    document.querySelectorAll("[data-dw-tool]").forEach((b) =>
      b.classList.toggle("active", b.dataset.dwTool === tool));
    const c = ink();
    if (c) c.style.cursor = CURSORS[tool] || "crosshair";
  }

  function setColor(color) {
    state.color = color;
    document.querySelectorAll("[data-dw-color]").forEach((b) =>
      b.classList.toggle("active", b.dataset.dwColor === color));
  }

  async function go(delta) {
    const n = state.pageNum + delta;
    if (n < 1 || n > state.pageCount) return;
    state.pageNum = n;
    await renderPage();
  }

  function toolbarHTML(layerLabel) {
    const tools = [["pen", "Pen"], ["rect", "Box"], ["ellipse", "Circle"], ["arrow", "Arrow"], ["text", "Text"], ["eraser", "Eraser"]];
    return `
      <div class="dw-toolbar">
        <span class="eyebrow">Markup · ${layerLabel || "internal layer"}</span>
        ${tools.map(([t, label]) =>
          `<button class="btn sm ${t === state.tool ? "active" : ""}" data-dw-tool="${t}">${label}</button>`).join("")}
        <span class="dw-sep"></span>
        ${COLORS.map((c) =>
          `<button class="dw-swatch ${c === state.color ? "active" : ""}" data-dw-color="${c}" style="background:${c}" title="${c}"></button>`).join("")}
        <span style="flex:1"></span>
        <button class="btn sm" data-dw-page="-1">‹ Prev</button>
        <span id="dwPageMeta" class="mono muted">—</span>
        <button class="btn sm" data-dw-page="1">Next ›</button>
      </div>`;
  }

  function attach(container) {
    container.addEventListener("click", (e) => {
      const t = e.target.closest("[data-dw-tool]");
      if (t) return setTool(t.dataset.dwTool);
      const c = e.target.closest("[data-dw-color]");
      if (c) return setColor(c.dataset.dwColor);
      const p = e.target.closest("[data-dw-page]");
      if (p) return go(+p.dataset.dwPage);
    });
    const c = ink();
    c.addEventListener("pointerdown", onDown);
    c.addEventListener("pointermove", onMove);
    c.addEventListener("pointerup", onUp);
    setTool(state.tool);
  }

  /** Render one page of any PDF into a canvas — no markup layer, no state.
      Used by the reply comparison view to sit "what we sent" beside "what
      came back". */
  async function renderPdfPage(canvas, url, pageNum = 1, maxWidth = 520) {
    const pdf = await pdfjsLib.getDocument({ url }).promise;
    const page = await pdf.getPage(Math.min(Math.max(1, pageNum), pdf.numPages));
    const basevp = page.getViewport({ scale: 1 });
    const scale = Math.max(0.12, maxWidth / basevp.width);
    const vp = page.getViewport({ scale });
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(vp.width * dpr);
    canvas.height = Math.floor(vp.height * dpr);
    canvas.style.width = `${Math.floor(vp.width)}px`;
    canvas.style.height = `${Math.floor(vp.height)}px`;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    await page.render({ canvasContext: ctx, viewport: vp, intent: "print" }).promise;
    return pdf.numPages;
  }

  boot();
  return { open, attach, toolbarHTML, renderPdfPage, state };
})();
