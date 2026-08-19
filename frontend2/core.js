// PlanWise 2.0 — the runtime. The prototype ran on React under a design-canvas
// harness; this is the production equivalent of exactly its update model:
// every state change rebuilds the flat view model and re-renders the whole
// template, and the DOM is PATCHED IN PLACE (morphdom) rather than replaced —
// which is what keeps focus and caret alive while the CO letter preview
// updates under the user's typing. 1.x's innerHTML swap fought that problem
// in four documented places; this runtime makes it structural.
"use strict";

const esc = (s) => String(s ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#39;");

// ——— Handler table ————————————————————————————————————————————————————————
// The prototype's view model carries CLOSURES (every row, chip and cell binds
// its own function). A string template can't embed a closure, so each render
// assigns closures sequential tokens and the delegated listeners look them
// up. Rebuilt per render — exactly the lifetime React props had.
let _handlers = new Map();
let _hSeq = 0;
function H(fn) {
  if (!fn) return "";
  const id = "h" + (++_hSeq);
  _handlers.set(id, fn);
  return id;
}

// ——— Render loop ——————————————————————————————————————————————————————————
const _root = document.getElementById("app");
let _renderQueued = false;
let _afterRender = [];

function setState(patch, cb) {
  Object.assign(App.state, patch);
  if (cb) _afterRender.push(cb);
  if (_renderQueued) return;
  _renderQueued = true;
  queueMicrotask(renderNow);
}

function renderNow() {
  _renderQueued = false;
  _handlers = new Map();
  _hSeq = 0;
  const html = '<div id="app">' + App.template(App.renderVals()) + "</div>";
  morphdom(_root, html, {
    // Never fight the user for the box they are typing in: state echoes the
    // input's own value, so patching it would be a no-op at best and a caret
    // jump at worst. data-* handler tokens still need to land, so those are
    // copied by hand.
    onBeforeElUpdated(fromEl, toEl) {
      if (fromEl === document.activeElement &&
          (fromEl.tagName === "INPUT" || fromEl.tagName === "TEXTAREA")) {
        for (const a of ["data-input", "data-change", "data-click", "data-focus"]) {
          const v = toEl.getAttribute(a);
          if (v !== null) fromEl.setAttribute(a, v); else fromEl.removeAttribute(a);
        }
        const from = fromEl, to = toEl;
        ["placeholder", "aria-invalid", "aria-describedby", "style"].forEach((a) => {
          const v = to.getAttribute(a);
          if (v !== null && v !== from.getAttribute(a)) from.setAttribute(a, v);
        });
        return false;
      }
      return true;
    },
  });
  const cbs = _afterRender; _afterRender = [];
  cbs.forEach((cb) => { try { cb(); } catch (e) { console.error(e); } });
  App.afterRender && App.afterRender();
}

// ——— Event delegation ————————————————————————————————————————————————————
// One listener per event type on the root, dispatching through the handler
// table. This replaces both React's synthetic events and 1.x's 31 separately
// registered listeners (whose registration-order coupling caused a documented
// regression). e._el carries the element the token was found on — the ported
// prototype methods that used e.currentTarget read that instead.
function _dispatch(attr) {
  return (e) => {
    let el = e.target && e.target.closest ? e.target.closest("[" + attr + "]") : null;
    while (el) {
      const fn = _handlers.get(el.getAttribute(attr));
      if (fn) { e._el = el; fn(e); return; }
      el = el.parentElement && el.parentElement.closest("[" + attr + "]");
    }
  };
}
_root.addEventListener("click", _dispatch("data-click"));
_root.addEventListener("input", _dispatch("data-input"));
_root.addEventListener("change", _dispatch("data-change"));
_root.addEventListener("pointerdown", _dispatch("data-pointerdown"));
_root.addEventListener("focusin", _dispatch("data-focus"));
_root.addEventListener("submit", (e) => {
  const el = e.target.closest("[data-submit]");
  if (!el) return;
  e.preventDefault();
  const fn = _handlers.get(el.getAttribute("data-submit"));
  if (fn) { e._el = el; fn(e); }
});

// ——— Focus management ————————————————————————————————————————————————————
// The prototype's focusRef: retry across animation frames because the target
// exists only after the next render. Refs become data-ref names here.
function focusRef(name) {
  return () => {
    let n = 0;
    const t = () => {
      const el = document.querySelector('[data-ref="' + name + '"]');
      if (el) return el.focus();
      if (n++ < 30) requestAnimationFrame(t);
    };
    requestAnimationFrame(t);
  };
}

// ——— Chrome (theme / density / mode / accent) ————————————————————————————
function applyChrome() {
  const el = document.documentElement;
  const s = App.state;
  el.dataset.theme = s.theme;
  el.dataset.density = s.density;
  el.dataset.mode = s.mode;
  if (s.accent) { el.style.setProperty("--ac", s.accent); el.style.setProperty("--ah", s.accent); }
  else { el.style.removeProperty("--ac"); el.style.removeProperty("--ah"); }
}

function savePrefs(patch) {
  const s = App.state;
  const next = { theme: s.theme, density: s.density, mode: s.mode, accent: s.accent, ...patch };
  try { localStorage.setItem("pw.prefs", JSON.stringify(
    { theme: next.theme, density: next.density, mode: next.mode, accent: next.accent })); } catch (e) {}
  setState(patch, applyChrome);
}

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem("pw.prefs") || "{}") || {}; }
  catch (e) { return {}; }
}

// ——— Small shared utilities ———————————————————————————————————————————————
const debounce = (fn, ms) => {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
};

// Humanised "N days open" from an ISO timestamp (attention panel, registers).
function daysAgo(ts) {
  if (!ts) return "";
  const then = new Date(ts);
  if (isNaN(then)) return "";
  const days = Math.max(0, Math.floor((Date.now() - then.getTime()) / 86400000));
  if (days === 0) return "today";
  return days + (days === 1 ? " day ago" : " days ago");
}

// "US letter date" — 15 Aug 2026, the compact form the prototype's eyebrows use.
function usDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso);
  if (isNaN(d)) return iso;
  return d.getDate() + " " + ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()] + " " + d.getFullYear();
}
