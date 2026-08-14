/* PlanWise shell — router, identity, and the five Phase-1 pages.
   One rule drives all formatting: a value Vista did not report renders as
   "not reported", never as $0.00. */

"use strict";

const $ = (sel) => document.querySelector(sel);
const main = $("#main");

const money = (v) =>
  v === null || v === undefined
    ? null
    : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

/** "$21,000.00" | "21000" | "" -> number | null */
const parseMoney = (s) => {
  const n = parseFloat(String(s).replace(/[^0-9.eE-]/g, ""));
  return Number.isFinite(n) ? n : null;
};
const pct = (v) => (v === null || v === undefined ? null : (v * 100).toFixed(1) + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Table cell that says "not reported" instead of lying with $0.00. */
const cell = (text, cls = "") =>
  text === null || text === undefined
    ? `<td class="num none">not reported</td>`
    : `<td class="num ${cls}">${text}</td>`;

const val = (text) => (text === null || text === undefined
  ? `<span class="none">not reported</span>` : esc(text));

/* ---- identity (Phase 5a: real accounts) ------------------------------------- */

/* The session lives in an HttpOnly cookie, so this is only ever a display
   name — nothing here identifies the user to the server. The cookie rides
   along automatically because every call is same-origin. */
let currentUser = null;

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body) headers["Content-Type"] = "application/json";
  const method = (opts.method || "GET").toUpperCase();

  let r;
  try {
    r = await fetch(path, { ...opts, headers, credentials: "same-origin" });
  } catch (netErr) {
    // No network. Reads fall back to the last copy we held — labelled with
    // when it was taken, never passed off as current (D2). Writes queue.
    if (method === "GET") {
      const cached = await OFFLINE.get(path);
      if (cached) { OFFLINE.markServed(cached.at); return cached.body; }
      throw new Error("You're offline and this hasn't been loaded before.");
    }
    if (OFFLINE.queueable(path, opts)) {
      OFFLINE.enqueue(path, { ...opts, method });
      return { queued: true };
    }
    throw new Error("You're offline — this one needs a connection.");
  }

  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    // A session can expire mid-session (or be revoked when an account is
    // disabled). Bounce straight to sign-in rather than leaving the page
    // throwing errors at every interaction.
    if (r.status === 401) { currentUser = null; showSignIn(); }
    // Keyed on the flag, NOT on 403: "Administrators only" is also a 403 and
    // must not throw an approved user onto the waiting screen.
    if (body.pending === true) showSignIn({ pending: true });
    throw new Error(body.detail || `${r.status} ${r.statusText}`);
  }
  if (method === "GET") { OFFLINE.put(path, body); OFFLINE.markLive(); }
  return body;
}

const authBox = () => $("#identity");

function signInHTML(status, error) {
  const err = error ? `<div class="error" style="margin-bottom:10px">${esc(error)}</div>` : "";
  if (status.needs_setup) {
    return `<h2>Set up PlanWise</h2>
      <div class="sub">This instance has no administrator yet. The setup token is in
        <span class="mono">planwise/setup_token.txt</span> in the data directory on the server —
        having it proves you can reach the machine, not just the address.</div>
      ${err}
      <form id="authForm" data-mode="bootstrap">
        <div class="field"><label>Setup token</label><input name="token" required autocomplete="off"></div>
        <div class="field"><label>Your name</label><input name="name" required autocomplete="username"></div>
        <div class="field"><label>Choose a password</label>
          <input name="password" type="password" required minlength="8" autocomplete="new-password"></div>
        <div class="dialog-actions"><button class="btn primary" type="submit">Create administrator</button></div>
      </form>`;
  }
  if (status.must_change) {
    return `<h2>Choose your own password</h2>
      <div class="sub">You're signed in with a temporary password. Set your own to continue.</div>
      ${err}
      <form id="authForm" data-mode="change">
        <div class="field"><label>Temporary password</label>
          <input name="current" type="password" required autocomplete="current-password"></div>
        <div class="field"><label>New password</label>
          <input name="new" type="password" required minlength="8" autocomplete="new-password"></div>
        <div class="dialog-actions"><button class="btn primary" type="submit">Set password</button></div>
      </form>`;
  }
  if (status.pending) return waitingHTML(status);
  if (status.register) {
    return `<h2>Create your account</h2>
      <div class="sub">Sign up with your work email. An administrator approves new
        accounts before they see job data — usually within a few minutes.</div>
      ${err}
      <form id="authForm" data-mode="register">
        <div class="field"><label>Work email</label>
          <input name="email" type="email" required autocomplete="email"></div>
        <div class="row2">
          <div class="field"><label>First name</label>
            <input name="first_name" required autocomplete="given-name"></div>
          <div class="field"><label>Last name</label>
            <input name="last_name" required autocomplete="family-name"></div>
        </div>
        <div class="field"><label>Set a password</label>
          <input name="password" type="password" required minlength="8" autocomplete="new-password"></div>
        <div class="dialog-actions"><button class="btn primary" type="submit">Request access</button></div>
      </form>
      <div class="authswap">Already have an account?
        <button class="link" data-auth-mode="login">Sign in</button></div>`;
  }
  return `<h2>Sign in</h2>
    <div class="sub">Your name is recorded on everything you change — the team shares this data.</div>
    ${err}
    <form id="authForm" data-mode="login">
      <div class="field"><label>Work email</label>
        <input name="name" required autocomplete="username"></div>
      <div class="field"><label>Password</label>
        <input name="password" type="password" required autocomplete="current-password"></div>
      <div class="dialog-actions"><button class="btn primary" type="submit">Sign in</button></div>
    </form>
    <div class="authswap">First time here?
      <button class="link" data-auth-mode="register">Create an account</button></div>`;
}

/* The approval gate. A registered account is genuinely signed in — it just
   can't see anything yet — so this is a held door rather than an error, and
   it says so plainly rather than looking like a failure. */
function waitingHTML(status) {
  const approved = status.approved;
  return `<h2>${approved ? "Approved" : "Request under review"}</h2>
    <div class="waitbox">
      <div class="spinner${approved ? " done" : ""}" aria-hidden="true"></div>
      <div>
        <div class="waitstatus">${approved
          ? "You're in — taking you to PlanWise…"
          : "Waiting for an administrator to approve your access."}</div>
        <div class="hint small muted">${approved ? ""
          : `Signed in as <span class="mono">${esc(status.user?.email || "")}</span>.
             They're notified on their phone, so this is usually quick. You can
             leave this open — it updates by itself.`}</div>
      </div>
    </div>
    ${approved ? "" : `<div class="dialog-actions">
      <button class="btn" data-auth-signout>Sign out</button></div>`}`;
}

/* Poll while the door is shut. /api/auth/status is an open path, so it keeps
   answering a pending session; it is fetched raw and never cached, so the
   answer is always the server's current one. */
let waitTimer = null;

function watchForApproval() {
  clearTimeout(waitTimer);
  waitTimer = setTimeout(async () => {
    let status;
    try { status = await (await fetch("/api/auth/status")).json(); }
    catch { watchForApproval(); return; }          // offline: keep waiting

    if (!status.signed_in) {
      // The account is gone — denied, or removed. The server can't say which:
      // the row no longer exists. Fall back to sign-in with neutral wording
      // rather than inventing a reason.
      showSignIn({ ...status, pending: false },
                 "That account is no longer active. Ask your administrator.");
      return;
    }
    if (status.pending) { watchForApproval(); return; }

    $("#identityBody").innerHTML = waitingHTML({ ...status, approved: true });
    setTimeout(async () => { if (signedIn(status.user)) await boot(); }, 900);
  }, 4000);
}

/* Which card a returning browser opens on. A machine that has signed in
   before gets Sign in; a brand-new one gets Create an account, because on a
   fresh device that is overwhelmingly what's wanted. Either way both are one
   click apart, so a wrong guess costs nothing. */
const SEEN_KEY = "planwise.hasAccount";
const hasAccountHere = () => localStorage.getItem(SEEN_KEY) === "1";

async function showSignIn(status, error) {
  if (!status) {
    try { status = await (await fetch("/api/auth/status")).json(); }
    catch { status = { needs_setup: false }; }
  }
  if (status.register === undefined && !status.needs_setup && !status.must_change
      && !status.pending) {
    status = { ...status, register: !hasAccountHere() };
  }
  $("#identityBody").innerHTML = signInHTML(status, error);
  authBox().classList.remove("hidden");
  $("#authForm")?.querySelector("input")?.focus();
  if (status.pending) watchForApproval();
}

function signedIn(user) {
  currentUser = user.name;
  // Companion tokens are per person now, so a cached one belongs to whoever
  // was signed in before. Kept, it would draft this person's mail from that
  // person's mailbox — or more likely just 401 confusingly.
  companionToken = null;
  $("#userChip").textContent = user.name;
  $("#userChip").dataset.admin = user.is_admin ? "1" : "";
  // Pending is checked BEFORE must_change: an admin who resets a pending
  // account's password sets both, and showing the change-password card to
  // someone who can't reach the app yet is a dead end.
  if (user.pending) { showSignIn({ pending: true, user }); return false; }
  if (user.must_change_password) { showSignIn({ must_change: true }); return false; }
  localStorage.setItem(SEEN_KEY, "1");
  authBox().classList.add("hidden");
  return true;
}

authBox().addEventListener("click", async (e) => {
  const swap = e.target.closest("[data-auth-mode]");
  if (swap) {
    showSignIn({ register: swap.dataset.authMode === "register" });
    return;
  }
  if (e.target.closest("[data-auth-signout]")) {
    clearTimeout(waitTimer);
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    currentUser = null;
    showSignIn({ register: false });
  }
});

authBox().addEventListener("submit", async (e) => {
  const f = e.target.closest("#authForm");
  if (!f) return;
  e.preventDefault();
  const data = Object.fromEntries(new FormData(f).entries());
  const mode = f.dataset.mode;
  const route = { bootstrap: "/api/auth/bootstrap", login: "/api/auth/login",
                  register: "/api/auth/register",
                  change: "/api/auth/password" }[mode];
  const btn = f.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const out = await api(route, { method: "POST", body: JSON.stringify(data) });
    if (signedIn(out.user)) { await boot(); }
  } catch (err) {
    const status = mode === "bootstrap" ? { needs_setup: true }
                 : mode === "change" ? { must_change: true }
                 : { register: mode === "register" };
    showSignIn(status, err.message);
  }
});

async function boot() {
  const status = await (await fetch("/api/auth/status")).json();
  if (!status.signed_in) { await showSignIn(status); return; }
  if (!signedIn(status.user)) return;
  route();
  refreshOutbox();
  // Arriving from the "access request" push lands straight on the queue.
  if (location.hash === "#users" && status.user.is_admin) openSettings("users");
}

/* ---- theme ------------------------------------------------------------------ */

$("#themeBtn").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme === "dark";
  if (dark) delete root.dataset.theme; else root.dataset.theme = "dark";
  localStorage.setItem("planwise.theme", dark ? "light" : "dark");
});

/* ---- freshness -------------------------------------------------------------- */

async function loadHealth() {
  const el = $("#freshness");
  try {
    const h = await api("/api/health");
    if (!h.vista.ok) {
      el.className = "chip err";
      el.innerHTML = `<span class="dot"></span>Vista unavailable`;
      el.title = h.vista.detail;
      return;
    }
    const v = h.vista;
    el.className = "chip " + (v.stale ? "warn" : "ok");
    el.innerHTML = `<span class="dot"></span>VISTA · ${v.age_hours}h · ${v.job_count.toLocaleString()} jobs`;
    el.title = `Extract as of ${v.as_of} (schema v${v.schema_version})\n${h.workbook}`;
  } catch (e) {
    el.className = "chip err";
    el.innerHTML = `<span class="dot"></span>Vista unavailable`;
    el.title = e.message;
  }
}

/* ---- job search -------------------------------------------------------------- */

const search = $("#jobSearch");
const results = $("#jobResults");
let timer;

search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(runSearch, 140); });
search.addEventListener("blur", () => setTimeout(() => results.classList.add("hidden"), 160));

async function runSearch() {
  const q = search.value.trim();
  if (!q) { results.classList.add("hidden"); return; }
  try {
    const { jobs } = await api(`/api/jobs?q=${encodeURIComponent(q)}&limit=25`);
    results.innerHTML = jobs.map((j) =>
      `<li data-job="${esc(j.job_number)}">
         <span class="rnum">${esc(j.job_number)}</span>
         <span class="rname">${esc(j.job_name ?? "")}</span>
         <span class="rstat">${esc(j.financial_status ?? "")}</span>
       </li>`).join("") || `<li><span class="rname none">No match</span></li>`;
    results.classList.remove("hidden");
  } catch { results.classList.add("hidden"); }
}

results.addEventListener("mousedown", (e) => {
  const li = e.target.closest("li[data-job]");
  if (!li) return;
  results.classList.add("hidden");
  search.value = li.dataset.job;
  location.hash = `/job/${encodeURIComponent(li.dataset.job)}/dashboard`;
});

/* ---- router ------------------------------------------------------------------- */

const PAGES = [
  ["dashboard", "Dashboard"],
  ["overview", "Overview"],
  ["costs", "Cost Breakdown"],
  ["changeorders", "Change Orders"],
  ["pos", "Invoices / POs"],
  ["schedule", "Schedule"],
  ["lookahead", "Look Ahead"],
  ["drawings", "Drawings"],
  ["rfis", "RFIs"],
  ["submittals", "Submittals"],
];

let current = { job: null, page: "dashboard", sub: null, data: null };

function parseHash() {
  const m = (location.hash || "").match(/^#\/job\/([^/]+)(?:\/([a-z]+))?(?:\/([A-Za-z0-9_-]+))?/);
  return m ? { job: decodeURIComponent(m[1]), page: m[2] || "dashboard", sub: m[3] || null } : null;
}

window.addEventListener("hashchange", route);

/* The access-request notification deep-links to #users. Tapping it while
   PlanWise is already open only changes the hash — no reload — so the queue
   has to open from here as well as from boot(). */
window.addEventListener("hashchange", () => {
  if (location.hash === "#users" && $("#userChip").dataset.admin) openSettings("users");
});

async function route() {
  const target = parseHash();
  if (!target) return;
  const reload = target.job !== current.job || !current.data;
  if (target.job !== current.job) docsCache = null;
  // Entering the Look Ahead re-reads it. This is a shared server (D9) — a PM
  // in another browser can be editing the same sheet, and a cache that only
  // refreshed on a job change would show their work as though it never
  // happened. Cheap call, local server.
  if (target.page === "lookahead" && current.page !== "lookahead") laCache = null;
  current.job = target.job;
  current.page = PAGES.some(([k]) => k === target.page) ? target.page : "dashboard";
  current.sub = target.sub;
  if (reload) {
    main.innerHTML = `<p class="placeholder">Loading ${esc(current.job)}…</p>`;
    try {
      current.data = await api(`/api/jobs/${encodeURIComponent(current.job)}`);
    } catch (e) {
      current.data = null;
      main.innerHTML = `<div class="error">${esc(e.message)}</div>`;
      return;
    }
    search.value = current.job;
  }
  render();
}

async function refreshJob() {
  current.data = await api(`/api/jobs/${encodeURIComponent(current.job)}`);
  render();
}

/* ---- shared chrome -------------------------------------------------------------- */

function stampFor(status) {
  const s = (status || "").toLowerCase();
  if (!s) return "";
  const cls = s.includes("on track") ? "ok"
    : s.includes("overbilled") || s.includes("loss") || s.includes("overrun") ? "err"
    : s.includes("no contract") ? "neutral" : "warn";
  return `<span class="stamp ${cls}">${esc(status)}</span>`;
}

function titleblock(d) {
  const j = d.job;
  return `
  <div class="titleblock">
    <div class="tb-cell tb-main">
      <div class="eyebrow">Project</div>
      <h1>${esc(j.job_name ?? "Unnamed job")}</h1>
    </div>
    <div class="tb-cell"><div class="eyebrow">Job No.</div><div class="tb-val mono">${esc(j.job_number)}</div></div>
    <div class="tb-cell"><div class="eyebrow">Contract</div><div class="tb-val num">${money(j.current_contract) ?? "—"}</div></div>
    <div class="tb-cell"><div class="eyebrow">Type</div><div class="tb-val">${esc(j.contract_type ?? "—")}</div></div>
    <div class="tb-cell"><div class="eyebrow">Status</div><div>${stampFor(j.financial_status) || "—"}</div></div>
  </div>`;
}

function tabs(d) {
  const counts = {
    changeorders: d.change_orders.length,
    pos: d.purchase_orders.length,
  };
  return `<nav class="tabs">${PAGES.map(([key, label]) => `
    <button class="${key === current.page ? "active" : ""}" data-page="${key}">
      ${label}${counts[key] !== undefined ? `<span class="count">${counts[key]}</span>` : ""}
    </button>`).join("")}</nav>`;
}

main.addEventListener("click", (e) => {
  const t = e.target.closest(".tabs button[data-page]");
  if (t) location.hash = `/job/${encodeURIComponent(current.job)}/${t.dataset.page}`;
});

function render() {
  const d = current.data;
  if (!d) return;
  const page = { dashboard, overview, costs, changeorders, pos, drawings,
                 schedule: schedulePage, lookahead: lookaheadPage,
                 rfis: recordsPage, submittals: recordsPage }[current.page];
  main.innerHTML = titleblock(d) + tabs(d) + page(d);
  applySorts();
  labelCells();
  if (current.page === "drawings") afterDrawingsRender();
  if (current.page === "lookahead") afterLookaheadRender();
  if (current.page === "rfis" || current.page === "submittals") afterRecordsRender();
}

/* ---- mobile: every cell carries its own column caption ---------------------------------
   On a phone the tables reflow into cards (styles.css), which means the header
   row disappears and every cell has to say what it is. Stamping data-label
   from the column header does that generically: one function covers every
   table on every page, including ones not written yet, with no per-table
   mapping to keep in sync. Cheap enough to run on every render. */

function labelCells() {
  main.querySelectorAll("table.tbl").forEach((table) => {
    const heads = [...table.querySelectorAll("thead th")].map(
      (th) => th.dataset.label ?? th.textContent.replace(/[↕↑↓]/g, "").trim());
    table.querySelectorAll("tbody tr").forEach((row) => {
      [...row.cells].forEach((cell, i) => {
        const label = heads[i];
        // Skip the action column and anything unlabelled — a caption reading
        // "" is worse than no caption.
        if (label) cell.dataset.label = label;
        else delete cell.dataset.label;
      });
    });
  });
}

/* ---- sortable table columns ------------------------------------------------------------
   One generic sorter for every table. Sorts the DOM rather than the data so it
   works on any table without per-table field mapping, and the chosen column
   is remembered per table so it survives the re-render after every edit.

   Two things it has to respect:
     * grouped rows — a PO's invoice lines carry data-subrow and travel with
       their parent instead of scattering;
     * missing values — "not reported" always sinks to the bottom, in both
       directions, so an empty cell never outranks a real number. */

const sortState = {};  // tableKey -> {col, dir}

const SORT_BLANK = /^(|—|-|not reported)$/i;

function sortValue(row, i) {
  const td = row.cells[i];
  if (!td) return null;
  const field = td.querySelector("input, select, textarea");
  const raw = (field ? field.value : td.textContent).trim();
  if (SORT_BLANK.test(raw)) return null;

  // currency / percent / plain number — strip symbols, keep the sign
  const numeric = raw.replace(/[$,%\s]/g, "").replace(/^\((.*)\)$/, "-$1");
  if (numeric && !isNaN(numeric)) return { n: parseFloat(numeric) };

  const t = Date.parse(raw);
  if (!isNaN(t) && /[-/]/.test(raw)) return { n: t };

  return { s: raw.toLowerCase() };
}

function rowGroups(tbody) {
  const groups = [];
  for (const row of tbody.rows) {
    if (row.dataset.subrow !== undefined && groups.length) groups[groups.length - 1].push(row);
    else groups.push([row]);
  }
  return groups;
}

function sortTable(table, col, dir) {
  const tbody = table.tBodies[0];
  if (!tbody || tbody.rows.length < 2) return;
  const groups = rowGroups(tbody);
  if (groups.length < 2) return;

  groups
    .map((g, i) => ({ g, i, v: sortValue(g[0], col) }))
    .sort((a, b) => {
      if (a.v === null && b.v === null) return a.i - b.i;
      if (a.v === null) return 1;          // blanks sink, both directions
      if (b.v === null) return -1;
      const cmp = "n" in a.v && "n" in b.v
        ? a.v.n - b.v.n
        : String(a.v.s ?? a.v.n).localeCompare(String(b.v.s ?? b.v.n), undefined, { numeric: true });
      return cmp !== 0 ? cmp * dir : a.i - b.i;   // stable
    })
    .forEach(({ g }) => g.forEach((row) => tbody.appendChild(row)));
}

function applySorts() {
  main.querySelectorAll("table.tbl[data-sort-key]").forEach((table) => {
    const head = table.tHead?.rows[0];
    if (!head) return;
    const state = sortState[table.dataset.sortKey];
    [...head.cells].forEach((th, i) => {
      if (th.dataset.nosort !== undefined || !th.textContent.trim()) return;
      th.classList.add("sortable");
      th.title = "Sort by this column";
      // Clear first: applySorts runs on click without a re-render, so adding
      // blind left both direction classes on and the arrow was correct only
      // because of stylesheet order.
      th.classList.remove("sort-asc", "sort-desc");
      if (state && state.col === i) th.classList.add(state.dir > 0 ? "sort-asc" : "sort-desc");
    });
    if (state) sortTable(table, state.col, state.dir);
  });
}

main.addEventListener("click", (e) => {
  const th = e.target.closest("table.tbl[data-sort-key] th");
  if (!th || th.dataset.nosort !== undefined || !th.textContent.trim()) return;
  const table = th.closest("table");
  const col = th.cellIndex;
  const prev = sortState[table.dataset.sortKey];
  sortState[table.dataset.sortKey] =
    prev && prev.col === col ? { col, dir: -prev.dir } : { col, dir: 1 };
  applySorts();
});

/* ---- page: dashboard -------------------------------------------------------------- */

function dashboard(d) {
  const j = d.job, ar = d.contract_ar || {};
  const committed = d.cost_types.reduce((s, r) => s + (r.open_committed || 0), 0);
  const cos = d.change_orders.filter((c) => c.kind === "customer");
  const coApproved = cos.reduce((s, c) => s + (c.amount_approved || 0), 0);
  const coPending = cos.reduce((s, c) => s + (c.amount_pending || 0), 0);
  const budgetLeft = (j.current_estimate ?? 0) - (j.actual_cost ?? 0);

  const strip = (cells) => `<div class="index-strip">${cells.map(([l, v, cls]) => `
    <div class="cell"><div class="n ${v === null ? "none" : ""} ${cls || ""}">${v ?? "not reported"}</div>
    <div class="l eyebrow">${l}</div></div>`).join("")}</div>`;

  return `
    ${strip([
      ["Original Contract", money(j.original_contract)],
      ["Change Orders", money(j.change_order_revenue)],
      ["Current Contract", money(j.current_contract)],
      ["Billed to Date", money(j.actual_billed)],
      ["Collected", money(ar.collected ?? null)],
      ["Retainage Held", money(ar.retainage ?? null)],
    ])}
    ${strip([
      ["Current Estimate", money(j.current_estimate)],
      ["Actual Cost (JTD)", money(j.actual_cost)],
      ["Cost This Month", money(j.mtd_cost)],
      ["Open / Committed", money(committed) , ],
      ["Unapproved AP", money(j.unapproved_ap)],
      ["Budget Remaining", money(j.current_estimate === null || j.actual_cost === null ? null : budgetLeft), budgetLeft >= 0 ? "pos" : "neg"],
      ["% Complete", pct(j.pct_complete)],
    ])}

    <div class="panel">
      <div class="panel-head"><h3>Cost by Type</h3><span class="sub">Vista · as of ${esc((d.as_of || "").slice(0, 10))}</span></div>
      <div class="panel-body flush">${costTable(d, /*compact=*/true)}</div>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>Change Orders</h3>
        <span class="sub">${cos.length} customer · ${d.change_orders.length - cos.length} subcontractor</span></div>
      <div class="panel-body">
        <div class="form-grid">
          <div><div class="eyebrow">Approved (register)</div><div class="tb-val num">${money(coApproved)}</div></div>
          <div><div class="eyebrow">Pending (register)</div><div class="tb-val num">${money(coPending)}</div></div>
          <div><div class="eyebrow">CO Revenue (Vista)</div><div class="tb-val num">${money(j.change_order_revenue) ?? "—"}</div></div>
          <div><div class="eyebrow">Register vs Vista</div>
            ${j.change_order_revenue === null ? `<span class="none">no Vista value</span>`
              : Math.abs(coApproved - j.change_order_revenue) < 0.01
                ? `<span class="stamp ok">Reconciled</span>`
                : `<span class="stamp warn">Δ ${money(coApproved - j.change_order_revenue)}</span>`}</div>
        </div>
      </div>
    </div>
  `;
}

/* ---- page: overview --------------------------------------------------------------- */

/* Order matters: Compliance sits directly under Identity & Contract
   (annotation, 2026-08-08), then Personnel, then Contacts. */
const META_SECTIONS = [
  ["Compliance", [
    ["bond_required", "Bond Required", ["", "Yes", "No"]],
    ["insurance_cert", "Insurance Cert", ["", "Yes", "No"]],
    ["certified_payroll", "Certified Payroll", ["", "Yes", "No"]],
    ["pla_davis_bacon", "PLA / Davis-Bacon", ["", "Yes", "No"]],
  ]],
  ["Personnel", [
    ["project_manager", "Project Manager"],
    ["superintendent", "Site Superintendent"],
    ["field_leader", "Field Leader"],
    ["estimator", "Estimator"],
  ]],
];

function overview(d) {
  const j = d.job, ar = d.contract_ar || {}, m = d.meta;
  const ro = (label, v, src = "vista") => `
    <div class="field"><label>${label}<span class="src-tag">${src}</span></label>
    <div class="ro">${v ?? '<span class="none">not reported</span>'}</div></div>`;

  const input = (key, label, opts) => opts
    ? `<div class="field"><label>${label}<span class="src-tag">pm</span></label>
       <select data-meta="${key}">${opts.map((o) =>
         `<option value="${esc(o)}" ${(m[key] || "") === o ? "selected" : ""}>${esc(o) || "—"}</option>`).join("")}</select></div>`
    : `<div class="field"><label>${label}<span class="src-tag">pm</span></label>
       <input data-meta="${key}" value="${esc(m[key] || "")}" placeholder="—"></div>`;

  return `
    <div class="panel">
      <div class="panel-head"><h3>Identity & Contract</h3>
        <span class="sub">Vista-sourced — edits happen in Vista, not here</span></div>
      <div class="panel-body"><div class="form-grid">
        ${ro("Job Number", esc(j.job_number))}
        ${ro("Project Name", esc(j.job_name ?? ""))}
        ${ro("Customer Status", stampFor(j.financial_status))}
        ${ro("Job Status", esc(j.job_status ?? ""))}
        ${ro("Contract Type", esc(j.contract_type ?? ""))}
        ${ro("Original Contract", money(j.original_contract))}
        ${ro("Change Order Revenue", money(j.change_order_revenue))}
        ${ro("Current Contract", money(j.current_contract))}
        ${ro("Billed to Date", money(j.actual_billed))}
        ${ro("Collected to Date", money(ar.collected ?? null))}
        ${ro("Retainage Balance", money(ar.retainage ?? null))}
        ${ro("Size Band", esc(j.size_band ?? ""))}
      </div></div>
    </div>

    ${META_SECTIONS.map(([title, fields]) => `
    <div class="panel">
      <div class="panel-head"><h3>${title}</h3><span class="sub">PM-entered · saved as you type</span></div>
      <div class="panel-body"><div class="form-grid">
        ${fields.map(([key, label, opts]) => input(key, label, opts)).join("")}
      </div></div>
    </div>`).join("")}

    <div class="panel">
      <div class="panel-head"><h3>Customer & Contacts</h3>
        <button class="btn sm" data-add-contact>+ Contact</button></div>
      <div class="panel-body">
        <div class="form-grid" style="margin-bottom:14px">
          ${input("customer_address", "Customer Address")}
        </div>
        ${(m.contacts || []).map((c, i) => `
        <div class="form-grid contact-row" style="margin-bottom:10px">
          <div class="field"><label>Name<span class="src-tag">pm</span></label>
            <input data-contact="${i}" data-cfield="name" value="${esc(c.name || "")}" placeholder="—"></div>
          <div class="field"><label>Role<span class="src-tag">pm</span></label>
            <input data-contact="${i}" data-cfield="role" value="${esc(c.role || "")}" placeholder="—"></div>
          <div class="field"><label>Phone<span class="src-tag">pm</span></label>
            <input data-contact="${i}" data-cfield="phone" value="${esc(c.phone || "")}" placeholder="—"></div>
          <div class="field"><label>Email<span class="src-tag">pm</span></label>
            <input data-contact="${i}" data-cfield="email" value="${esc(c.email || "")}" placeholder="—"></div>
          <div class="field"><label>&nbsp;</label>
            <button class="link danger" data-del-contact="${i}">remove</button></div>
        </div>`).join("") || `<div class="none">No contacts yet — use + Contact.</div>`}
      </div>
    </div>
  `;
}

async function saveContacts(contacts) {
  current.data.meta.contacts = contacts;
  await api(`/api/jobs/${encodeURIComponent(current.job)}/meta`, {
    method: "PATCH", body: JSON.stringify({ contacts }),
  });
}

main.addEventListener("change", async (e) => {
  const el = e.target.closest("[data-meta]");
  if (el) {
    await api(`/api/jobs/${encodeURIComponent(current.job)}/meta`, {
      method: "PATCH", body: JSON.stringify({ [el.dataset.meta]: el.value }),
    });
    current.data.meta = await api(`/api/jobs/${encodeURIComponent(current.job)}`).then((d) => d.meta);
    return;
  }
  const c = e.target.closest("[data-contact]");
  if (c) {
    const contacts = current.data.meta.contacts || [];
    contacts[+c.dataset.contact][c.dataset.cfield] = e.target.value;
    await saveContacts(contacts);
  }
});

/* ---- page: cost breakdown ----------------------------------------------------------- */

function costTable(d, compact = false) {
  const rows = d.cost_types;
  const sum = (f) => rows.reduce((s, r) => (r[f] == null ? s : s + r[f]), 0);
  const varTotal = sum("current_estimate") - sum("actual_cost");
  /* Phase codes are classifiers — "92-100 - Underground" tells you where the
     money sits. One cost type can span several, so the extras are counted
     rather than allowed to wrap the column; the full list is on hover. */
  const phaseCodes = (r) => {
    const codes = r.phase_codes || [];
    if (!codes.length) return `<span class="none">—</span>`;
    const first = String(codes[0]).split(" - ")[0];
    const rest = codes.length - 1;
    return `<span title="${esc(codes.join("\n"))}">${esc(first)}${
      rest ? ` <span class="muted">+${rest}</span>` : ""}</span>`;
  };

  return `
    <table class="tbl" data-sort-key="costs-${compact ? "compact" : "full"}">
      <thead><tr>
        <th>Cost Type</th>${compact ? "" : `<th>Phase Code</th>`}
        <th class="num">Estimate</th><th class="num">Month to Date</th>
        <th class="num">Actual (JTD)</th><th class="num">Projected</th>
        <th class="num">Variance</th><th class="num">% Complete</th>
        <th class="num" title="Derived from the PO register (D8): remaining value of open POs">Open / Committed</th>
        ${compact ? "" : `<th class="num">Hours / Units</th>`}
      </tr></thead>
      <tbody>
        ${rows.map((r) => `<tr>
          <td>${esc(r.cost_type)}${r.po_only ? `<span class="tag" title="No Vista cost lines — exists only on the PO register">PO only</span>` : ""}</td>
          ${compact ? "" : `<td class="mono">${phaseCodes(r)}</td>`}
          ${cell(money(r.current_estimate))}
          ${cell(money(r.mtd_cost))}
          ${cell(money(r.actual_cost))}
          ${cell(money(r.projected_cost))}
          ${cell(money(r.variance), r.variance === null ? "" : r.variance >= 0 ? "pos" : "neg")}
          ${cell(pct(r.pct_complete))}
          ${cell(money(r.open_committed))}
          ${compact ? "" : cell(r.hours_units === null ? null : r.hours_units.toLocaleString("en-US", { maximumFractionDigits: 1 }))}
        </tr>`).join("")}
      </tbody>
      <tfoot><tr>
        <td>Total</td>${compact ? "" : "<td></td>"}
        <td class="num">${money(sum("current_estimate"))}</td>
        <td class="num">${money(sum("mtd_cost"))}</td>
        <td class="num">${money(sum("actual_cost"))}</td>
        <td class="num">${money(sum("projected_cost"))}</td>
        <td class="num ${varTotal >= 0 ? "pos" : "neg"}">${money(varTotal)}</td>
        <td class="num"></td>
        <td class="num">${money(sum("open_committed"))}</td>
        ${compact ? "" : `<td class="num"></td>`}
      </tr></tfoot>
    </table>`;
}

function costs(d) {
  return `
    <div class="panel">
      <div class="panel-head"><h3>Cost Breakdown</h3>
        <span class="sub">${d.cost_types.filter((r) => !r.po_only).length} cost types on this job · Vista as of ${esc((d.as_of || "").slice(0, 10))}</span></div>
      <div class="panel-body flush">${costTable(d)}</div>
    </div>
    <div class="note">
      Everything here is Vista-sourced except <b>Open / Committed</b>, which derives from
      the PO register (open POs' remaining value). Cost types are whatever this job
      actually carries — nothing is padded in or dropped.
    </div>`;
}

/* ---- page: change orders ------------------------------------------------------------ */

/* The document bar above each change order register.
   Which change order it acts on is an explicit choice rather than "the last
   one", because a register with eight COs on it makes "the current one"
   meaningless — and sending the wrong change order to a customer is not a
   mistake you can take back. */
let coDocSel = { customer: null, subcontractor: null };
let coPreview = null;        // {kind, coId} — the inline PDF currently shown
let coPreviewRev = 0;        // bumped to bust the iframe's cache of the PDF
let coItems = [];            // breakout rows being edited, mirrored to the server
let coClarifOpen = false;
let coClarifLib = null;      // the standing library, fetched once
let coClarifPick = new Set();
const coMsg = (kind, t) => {
  const el = document.querySelector(`#coMsg-${kind}`);
  if (el) el.textContent = t;
};

function coDocBar(d, kind, list) {
  const isSub = kind === "subcontractor";
  const sel = coDocSel[kind] || (list[0] && list[0].id) || "";
  const label = (c) => `#${c.co_number || c.cust_co_number || "—"}`
    + (c.description ? ` · ${String(c.description).slice(0, 46)}` : "");

  if (!list.length) {
    return `<div class="note" style="margin:10px 12px">No ${isSub ? "subcontractor " : ""}change
      orders yet — add one below and the ${isSub ? "log document" : "customer letter"} becomes available.</div>`;
  }

  return `
    <div class="la-toolbar" style="padding:10px 12px">
      <select data-co-select="${kind}" style="max-width:340px">
        ${list.map((c) => `<option value="${c.id}" ${c.id === sel ? "selected" : ""}>${esc(label(c))}</option>`).join("")}
      </select>
      <button class="btn sm" data-co-preview="${kind}">Preview PDF</button>
      ${isSub
        ? `<button class="btn primary sm" data-co-share="${kind}">Send PDF</button>`
        : `<button class="btn sm" data-co-clarify>Clarifications &amp; Exceptions</button>
           <button class="btn primary sm" data-co-share="${kind}">Share to Customer</button>`}
      <button class="btn sm" data-co-pdf="${kind}">Download PDF</button>
      <button class="btn sm" data-co-docx="${kind}">Download Word</button>
      <span class="hint small muted" id="coMsg-${kind}"></span>
    </div>
    ${!isSub && coClarifOpen ? clarificationPicker() : ""}
    ${coPreview && coPreview.kind === kind ? `
      <div class="co-compose">
        ${isSub ? "" : composePane(list.find((c) => c.id === coPreview.coId) || {})}
        <div class="la-preview" style="margin:0">
          <iframe title="Change order preview" id="coFrame"
            src="/api/jobs/${encodeURIComponent(current.job)}/cos/${coPreview.coId}/document.pdf#toolbar=1&v=${coPreviewRev}"></iframe>
        </div>
      </div>` : ""}`;
}

/* Writing the letter, beside the letter.
   The narrative and the breakout are what a PM actually composes; putting
   them next to the preview means you watch the document change as you type
   rather than editing a form and guessing. Saves are debounced and the frame
   reloads on the way back, so "live" costs one request per pause, not one per
   keystroke. */
function composePane(co) {
  const rows = coItems.length ? coItems : [{ description: "", amount: "" }];
  const total = coItems.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0);
  return `
    <div class="co-editor">
      <label class="eyebrow">What changed and why</label>
      <textarea id="coNarrative" rows="7" data-co-narr="${co.id}"
        placeholder="This is to notify … of several changes in scope to the above-referenced project. Additional information and clarification has been provided by the engineering team that requires an adjustment to …">${esc(co.narrative || "")}</textarea>

      <label class="eyebrow" style="margin-top:12px">Breakout pricing</label>
      <div class="co-items">
        ${rows.map((r, i) => `
          <div class="co-item">
            <input data-item-desc="${i}" value="${esc(r.description || "")}"
              placeholder="Cable Tray Install">
            <input data-item-amt="${i}" class="num" inputmode="decimal"
              value="${esc(r.amount ?? "")}" placeholder="0.00">
            <button class="link danger" data-item-del="${i}" title="Remove this line">×</button>
          </div>`).join("")}
      </div>
      <div class="co-item-foot">
        <button class="btn sm" data-item-add>+ Line</button>
        <span class="grow"></span>
        <span class="eyebrow">Total</span>
        <b class="num">${coItems.length ? money(total) : "—"}</b>
      </div>
      <div class="hint small muted">Leave the breakout empty and the letter shows the
        amount typed on the register. Add lines and they are itemised, totalled, and the
        register follows them — a credit is a negative number.</div>
    </div>`;
}

/* Tick the standing ones, type a new one. New wording is saved to the library
   as well as this change order — the whole point is that the second time
   someone needs it, it is already on the list. */
function clarificationPicker() {
  if (!coClarifLib) return `<div class="note" style="margin:0 12px 10px">loading the standing list…</div>`;
  return `
    <div class="panel sub-panel" style="margin:0 12px 10px">
      <div class="panel-head"><h3>Clarifications &amp; Exceptions</h3>
        <span class="sub">${coClarifPick.size} selected · customer letter only</span></div>
      <div class="panel-body">
        <div class="clarif-list">
          ${coClarifLib.map((c) => `
            <label class="clarif">
              <input type="checkbox" data-clarif="${esc(c.text)}"
                ${coClarifPick.has(c.text) ? "checked" : ""}>
              <span>${esc(c.text)}</span>
              ${c.seeded ? "" : `<button class="link small" data-clarif-archive="${c.id}"
                 title="Remove from the standing list. Change orders that already used it keep it.">remove</button>`}
            </label>`).join("")}
        </div>
        <form class="inline-form" id="addClarif" style="margin-top:10px">
          <input name="text" class="grow" placeholder="Add a new clarification or exception…" required>
          <button class="btn sm" type="submit">Add</button>
        </form>
        <div class="hint small muted">Wording you add is kept for next time. Selections are saved
          to this change order and appear on its letter — editing the list later never changes a
          letter that has already gone out.</div>
      </div>
    </div>`;
}

function coSection(d, kind, title) {
  const list = d.change_orders.filter((c) => c.kind === kind);
  const approved = list.reduce((s, c) => s + (c.amount_approved || 0), 0);
  const pending = list.reduce((s, c) => s + (c.amount_pending || 0), 0);
  const isSub = kind === "subcontractor";

  // Money cells display formatted currency; raw number appears on focus,
  // formatting returns on blur (annotation: "formatted as dollar amounts").
  const ec = (co, field, type = "text", cls = "") =>
    type === "money"
      ? `<input class="ecell num" type="text" inputmode="decimal"
          value="${esc(money(co[field]) ?? "")}" data-co="${co.id}" data-field="${field}" data-money>`
      : `<input class="ecell ${cls}" type="${type}"
          value="${esc(co[field] ?? "")}" data-co="${co.id}" data-field="${field}">`;

  return `
    <div class="panel">
      <div class="panel-head"><h3>${title}</h3>
        <span class="sub num">Approved ${money(approved)} · Pending ${money(pending)}</span></div>
      <div class="panel-body flush">
        ${coDocBar(d, kind, list)}
        <form class="inline-form top" data-co-form="${kind}">
          <input name="co_number" placeholder="CO #" style="width:80px" required>
          ${isSub ? `<input name="subcontractor" class="grow" placeholder="Subcontractor">`
                  : `<input name="cust_co_number" placeholder="Cust. CO #" style="width:110px">`}
          <input name="description" class="grow" placeholder="Description">
          <input name="amount_submitted" type="number" step="0.01" placeholder="Submitted $" style="width:120px">
          <input name="amount_approved" type="number" step="0.01" placeholder="Approved $" style="width:120px">
          <button class="btn primary sm" type="submit">+ ${isSub ? "Sub CO" : "Change Order"}</button>
        </form>
        <table class="tbl" data-sort-key="co-${kind}">
          <thead><tr>
            <th>CO #</th>${isSub ? "<th>Subcontractor</th>" : "<th>Cust. CO #</th>"}
            <th>Date</th><th style="width:26%">Description</th>
            <th class="num">Submitted</th><th class="num">Pending</th><th class="num">Approved</th>
            <th>Approved By</th><th></th>
          </tr></thead>
          <tbody>
            ${list.map((co) => `<tr>
              <td>${ec(co, "co_number")}</td>
              <td>${isSub ? ec(co, "subcontractor") : ec(co, "cust_co_number")}</td>
              <td>${ec(co, "date_submitted", "date")}</td>
              <td>${ec(co, "description")}</td>
              <td>${ec(co, "amount_submitted", "money")}</td>
              <td>${ec(co, "amount_pending", "money")}</td>
              <td>${ec(co, "amount_approved", "money")}</td>
              <td>${ec(co, "approved_by")}</td>
              <td><button class="link danger" data-del-co="${co.id}">delete</button></td>
            </tr>`).join("") || `<tr><td colspan="9" class="none">None yet.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>`;
}

function changeorders(d) {
  const j = d.job;
  const custApproved = d.change_orders
    .filter((c) => c.kind === "customer")
    .reduce((s, c) => s + (c.amount_approved || 0), 0);
  const delta = j.change_order_revenue === null ? null : custApproved - j.change_order_revenue;
  return `
    ${coSection(d, "customer", "Customer Change Orders")}
    ${coSection(d, "subcontractor", "Subcontractor Change Orders")}
    <div class="note">
      Vista reports <b>${money(j.change_order_revenue) ?? "no"}</b> change-order revenue on this job.
      ${delta === null ? "" : Math.abs(delta) < 0.01
        ? `The customer register reconciles exactly.`
        : `The customer register differs by <b>${money(delta)}</b> — worth a look.`}
      Subcontractor COs are cost-side and intentionally excluded from that comparison.
    </div>`;
}

/* ---- page: invoices / POs ------------------------------------------------------------ */

let invoiceFormPo = null; // PO id whose inline invoice form is open

/* Approved subcontractor change orders, waiting for a purchase order.
   An approved sub CO is an agreement: the sub is owed the money and will
   invoice against it — but they cannot invoice against a change order, only
   against a PO. Leaving these on the Change Orders tab meant the commitment
   existed on one page and the paperwork that satisfies it on another, with
   nothing joining them. */
function subCoCommitments(d) {
  const covered = new Set((d.purchase_orders || [])
    .map((p) => p.source_co_id).filter(Boolean));
  const waiting = (d.change_orders || []).filter(
    (c) => c.kind === "subcontractor" && (c.amount_approved || 0) > 0
           && !covered.has(c.id));
  if (!waiting.length) return "";

  const total = waiting.reduce((s, c) => s + (c.amount_approved || 0), 0);
  return `
    <div class="panel">
      <div class="panel-head"><h3>Approved Sub COs Awaiting a PO</h3>
        <span class="sub num">${waiting.length} · ${money(total)} committed, not yet on a PO</span></div>
      <div class="panel-body flush">
        <table class="tbl">
          <thead><tr>
            <th>CO #</th><th>Subcontractor</th><th>Description</th>
            <th class="num">Approved</th><th></th>
          </tr></thead>
          <tbody>
            ${waiting.map((c) => `<tr>
              <td class="mono">${esc(c.co_number ?? "—")}</td>
              <td>${esc(c.subcontractor ?? "—")}</td>
              <td>${esc(c.description ?? "—")}</td>
              <td class="num">${money(c.amount_approved)}</td>
              <td><button class="link" data-co-to-po="${c.id}">issue PO</button></td>
            </tr>`).join("")}
          </tbody>
        </table>
        <div class="note">These are agreed with the subcontractor and will be invoiced against.
          Issuing the PO copies the number, vendor, description and amount across; the change
          order stays the record of what was agreed.</div>
      </div>
    </div>`;
}

function pos(d) {
  const list = d.purchase_orders;
  const vistaTypes = d.cost_types.filter((r) => !r.po_only).map((r) => r.cost_type);
  const invoiced = (po) => (po.invoices || []).reduce((s, i) => s + (i.amount || 0), 0);
  const amt = (po) => po.adjusted_amount ?? po.original_amount;
  const totalPO = list.reduce((s, p) => s + (amt(p) || 0), 0);
  const totalInv = list.reduce((s, p) => s + invoiced(p), 0);
  const open = list.filter((p) => (p.status || "Open") === "Open");
  const openRemaining = open.reduce((s, p) => s + ((amt(p) ?? 0) - invoiced(p)), 0);

  return `
    <div class="index-strip">
      <div class="cell"><div class="n num">${money(totalPO)}</div><div class="l eyebrow">Total PO Value</div></div>
      <div class="cell"><div class="n num">${money(totalInv)}</div><div class="l eyebrow">Invoiced</div></div>
      <div class="cell"><div class="n num">${money(openRemaining)}</div><div class="l eyebrow">Open Commitment</div></div>
      <div class="cell"><div class="n num">${open.length} / ${list.length}</div><div class="l eyebrow">Open POs</div></div>
    </div>

    ${subCoCommitments(d)}

    <div class="panel">
      <div class="panel-head"><h3>Purchase Order Register</h3>
        <span class="sub">PM-entered · feeds Open/Committed on the Cost Breakdown · PO-PDF import lands with the pipeline</span></div>
      <div class="panel-body flush">
        <form class="inline-form top" id="addPO">
          <input name="po_number" placeholder="PO #" style="width:110px" required>
          <input name="vendor" placeholder="Vendor" style="width:170px">
          <input name="description" class="grow" placeholder="Description">
          <input name="adjusted_amount" type="number" step="0.01" placeholder="Amount" style="width:110px" required>
          <select name="cost_type">
            <option value="">Cost type…</option>
            ${vistaTypes.map((t) => `<option>${esc(t)}</option>`).join("")}
          </select>
          <button class="btn primary sm" type="submit">+ Purchase Order</button>
        </form>
        <table class="tbl" data-sort-key="pos">
          <thead><tr>
            <th>PO #</th><th>Vendor</th><th>Description</th><th>Cost Type</th><th>Status</th>
            <th class="num">PO Value</th><th class="num">Invoiced</th><th class="num">Remaining</th><th></th>
          </tr></thead>
          <tbody>
            ${list.map((po) => `
            <tr>
              <td class="mono">${esc(po.po_number ?? "—")}</td>
              <td>${esc(po.vendor ?? "—")}</td>
              <td>${esc(po.description ?? "")}</td>
              <td>
                <select class="ecell" data-po="${po.id}" data-field="cost_type">
                  <option value="">unassigned</option>
                  ${vistaTypes.map((t) => `<option ${po.cost_type === t ? "selected" : ""}>${esc(t)}</option>`).join("")}
                </select>
              </td>
              <td>
                <select class="ecell" data-po="${po.id}" data-field="status">
                  ${["Open", "Closed"].map((s) => `<option ${(po.status || "Open") === s ? "selected" : ""}>${s}</option>`).join("")}
                </select>
              </td>
              ${cell(money(amt(po)))}
              ${cell(money(invoiced(po)))}
              ${cell(money(amt(po) === null ? null : amt(po) - invoiced(po)))}
              <td style="white-space:nowrap">
                <button class="link" data-inv-po="${po.id}">+ invoice</button>
                &nbsp;<button class="link danger" data-del-po="${po.id}">delete</button>
              </td>
            </tr>
            ${(po.invoices || []).map((inv) => `
            <tr data-subrow>
              <td></td>
              <td colspan="4" class="mono muted">↳ inv ${esc(inv.invoice_number ?? "—")}${inv.date ? ` · ${esc(inv.date)}` : ""}${inv.created_by ? ` · by ${esc(inv.created_by)}` : ""}</td>
              <td></td>
              ${cell(money(inv.amount))}
              <td></td>
              <td><button class="link danger" data-del-inv="${inv.id}" data-of-po="${po.id}">remove</button></td>
            </tr>`).join("")}
            ${invoiceFormPo === po.id ? `
            <tr data-subrow><td></td><td colspan="8">
              <form class="inline-form" data-inv-form="${po.id}" style="border:none;padding:8px 0">
                <input name="invoice_number" placeholder="Invoice #" style="width:130px" required>
                <input name="date" type="date" style="width:150px">
                <input name="amount" type="number" step="0.01" placeholder="Amount" style="width:120px" required>
                <button class="btn primary sm" type="submit">Add Invoice</button>
                <button class="btn sm" type="button" data-cancel-inv>Cancel</button>
              </form>
            </td></tr>` : ""}`).join("") || `<tr><td colspan="9" class="none">No purchase orders yet.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>`;
}

/* ---- page: drawings workspace (Phase 2) ---------------------------------------------- */

let docsCache = null; // {job, docs}

function drawings(d) {
  if (current.sub) {
    const doc = docsCache?.docs.find((x) => x.id === current.sub);
    return `
      <div class="dw-workspace">
        <div class="dw-head">
          <button class="btn sm" data-dw-back>‹ Library</button>
          <span class="tb-val">${esc(doc?.name ?? "Document")}</span>
          <span class="muted small">${doc ? `${doc.page_count} pages · uploaded by ${esc(doc.uploaded_by ?? "—")}` : ""}</span>
        </div>
        ${DW.toolbarHTML(null)}
        <div id="dwCanvasHolder" class="dw-holder">
          <canvas id="dwPdf"></canvas>
          <canvas id="dwInk"></canvas>
        </div>
        <div class="note">Markups here are the <b>internal layer</b> — persistent WECC/AXIS
        redlines, visible team-wide, never included in anything sent to a customer.</div>
      </div>`;
  }

  if (!docsCache || docsCache.job !== current.job) {
    loadDocs();
    return `<p class="placeholder">Loading document library…</p>`;
  }

  const docs = docsCache.docs;
  const fmtSize = (b) => b > 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.round(b / 1e3) + " KB";
  const errs = uploadErrors.splice(0);
  return `
    ${errs.map((m) => `<div class="error" style="margin-bottom:10px">${esc(m)}</div>`).join("")}
    <div class="panel">
      <div class="panel-head"><h3>Document Library</h3>
        <label class="btn primary sm" style="cursor:pointer">Upload PDF
          <input id="docUpload" type="file" accept="application/pdf" multiple hidden>
        </label>
      </div>
      <div class="panel-body flush">
        <table class="tbl" data-sort-key="documents">
          <thead><tr>
            <th>Document</th><th class="num">Pages</th><th class="num">Size</th>
            <th class="num">Internal Markups</th><th>Uploaded</th><th></th>
          </tr></thead>
          <tbody>
            ${docs.map((doc) => `<tr class="clickable" data-open-doc="${doc.id}">
              <td>${esc(doc.name)}</td>
              <td class="num">${doc.page_count ?? "—"}</td>
              <td class="num">${fmtSize(doc.size_bytes || 0)}</td>
              <td class="num">${doc.internal_annotation_count || ""}</td>
              <td class="small muted">${esc((doc.uploaded_at || "").slice(0, 10))} · ${esc(doc.uploaded_by ?? "—")}</td>
              <td><button class="link danger" data-del-doc="${doc.id}">delete</button></td>
            </tr>`).join("") || `<tr><td colspan="6" class="none">No documents yet — upload a drawing set to begin.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
    <div class="note">One library feeds everything: the RFI and Submittal pipeline (Phase 3)
    picks pages from these same sets. Originals are immutable — markups live on layers.</div>`;
}

async function loadDocs() {
  const { documents } = await api(`/api/jobs/${encodeURIComponent(current.job)}/documents`);
  docsCache = { job: current.job, docs: documents };
  if (current.page === "drawings") render();
}

function afterDrawingsRender() {
  if (!current.sub) return;
  if (!docsCache || docsCache.job !== current.job) { loadDocs(); return; }
  const ws = main.querySelector(".dw-workspace");
  DW.attach(ws);
  DW.open(current.sub, api).catch((e) => {
    main.querySelector(".dw-holder").innerHTML = `<div class="error">${esc(e.message)}</div>`;
  });
}

main.addEventListener("click", async (e) => {
  if (e.target.closest("[data-dw-back]")) {
    location.hash = `/job/${encodeURIComponent(current.job)}/drawings`;
    return;
  }
  const del = e.target.closest("[data-del-doc]");
  if (del) {
    e.stopPropagation();
    if (!armed(del)) return;
    await api(`/api/documents/${del.dataset.delDoc}`, { method: "DELETE" });
    return loadDocs();
  }
  const row = e.target.closest("[data-open-doc]");
  if (row && !e.target.closest("button")) {
    location.hash = `/job/${encodeURIComponent(current.job)}/drawings/${row.dataset.openDoc}`;
  }
});

main.addEventListener("change", async (e) => {
  if (e.target.id !== "docUpload") return;
  for (const file of e.target.files) {
    const form = new FormData();
    form.append("file", file);
    const headers = currentUser ? { "X-PlanWise-User": currentUser } : {};
    const r = await fetch(`/api/jobs/${encodeURIComponent(current.job)}/documents`,
      { method: "POST", body: form, headers });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      uploadErrors.push(`${file.name}: ${body.detail || r.statusText}`);
    }
  }
  await loadDocs();
});

let uploadErrors = [];

/* ---- page: Schedule (Phase 4) --------------------------------------------------------- */

let schedCache = null;   // {job, data}

/* Zoom levels for the chart. Named the way Project names them, because that's
   what the people using this will look for. */
const SCHED_ZOOM = { day: 26, week: 9, month: 2.6, quarter: 1.0 };
let schedZoom = "month";
/* Continuous zoom on top of the named stops. The presets jump ~3x apiece,
   which is fine for "show me the year" and useless for "a bit wider" — a
   106-row schedule at month is unreadable and at week is three screens.
   Factor multiplies whichever stop is selected; the label keeps naming the
   stop so the mental model stays Project's. */
let schedZoomFactor = 1;
const ZOOM_MIN = 0.35, ZOOM_MAX = 6;
const schedPx = () => SCHED_ZOOM[schedZoom] * schedZoomFactor;

/* Column widths, dragged by the user and remembered per browser. Field crews
   and estimators want different things visible: one lives in Task Name, the
   other in dates and float. */
const GX_COLS = ["id", "name", "dur", "start", "finish", "pred", "pct", "float"];
const GX_DEFAULT_W = { id: 46, name: 260, dur: 54, start: 104, finish: 104,
                       pred: 116, pct: 46, float: 52 };
let schedColW = loadColW();

function loadColW() {
  try {
    const saved = JSON.parse(localStorage.getItem("planwise.schedCols") || "{}");
    return { ...GX_DEFAULT_W, ...saved };
  } catch { return { ...GX_DEFAULT_W }; }
}

function saveColW() {
  try { localStorage.setItem("planwise.schedCols", JSON.stringify(schedColW)); }
  catch { /* private mode: widths just don't persist */ }
}

/* Written as CSS custom properties so a drag repaints by changing one
   variable, rather than re-rendering 106 rows on every mousemove. */
function colWStyle() {
  return GX_COLS.map((c) => `--gxw-${c}:${Math.round(schedColW[c])}px`).join(";");
}
let schedCollapsed = new Set();   // ids of summary rows folded shut
let schedStaged = null;           // an import waiting to be reviewed

const ROW_H = 24;                 // one grid row and one chart row, in lockstep

function schedulePage(d) {
  if (!schedCache || schedCache.job !== current.job) {
    loadSchedule();
    return `<p class="placeholder">Loading schedule…</p>`;
  }
  const s = schedCache.data;
  const mpp = s.mpp || {};

  const head = `
    <div class="panel">
      <div class="panel-head"><h3>Schedule</h3>
        <span class="sub">${s.tasks.length} tasks · ${s.critical_count} on the critical path
        ${s.project_start ? `· ${esc(s.project_start)} → ${esc(s.project_finish)}` : ""}</span></div>
      <div class="inline-form top" style="border-top:none;border-bottom:1px solid var(--line-strong)">
        <label class="btn primary sm" style="cursor:pointer">Import Schedule
          <input id="schedUpload" type="file"
                 accept=".mpp,.xml,.mspdi,.pdf,.xlsx,.xlsm,.csv" hidden>
        </label>
        <select id="schedMode" title="How an import treats tasks already here">
          <option value="replace">Replace — update matching, drop what's gone</option>
          <option value="merge">Merge — update matching, keep the rest</option>
        </select>
        <span class="grow small muted">
          Microsoft Project (.mpp${mpp.available ? "" : " needs Java here"}), MSPDI .xml,
          a <b>printed schedule PDF</b>, or a spreadsheet (.xlsx/.csv) such as a Smartsheet export.
        </span>
        <span id="schedMsg" class="small muted"></span>
      </div>
    </div>`;

  if (schedStaged && schedStaged.id) return head + importReview(schedStaged);

  if (!s.tasks.length) {
    return head + `
      <div class="panel"><div class="panel-body">
        <div class="none">No schedule yet — import one above, or add tasks by hand below.</div>
      </div></div>` + schedTaskForm();
  }

  return head + ganttWorkspace(s) + schedTaskForm() + `
    <div class="note">Dates, float and the critical path are computed in <b>working days</b>
    against this job's calendar (${esc((s.calendar || {}).workdays || "1111100")
      .split("").map((c, i) => c === "1" ? "MTWTFSS"[i] : "").join("") || "Mon–Fri"}),
    the way Microsoft Project measures them. An imported date is treated as the earliest a task
    may start: dependencies push work later, never earlier. Summary rows roll up their children
    and stay out of the network.</div>`;
}

/* ---- the split pane: grid left, chart right, one scroll ------------------------------- */

function ganttWorkspace(s) {
  const rows = visibleRows(s.tasks);
  const start = new Date(s.project_start + "T00:00:00");
  const finish = new Date(s.project_finish + "T00:00:00");
  const totalDays = Math.max(1, Math.round((finish - start) / 86400000) + 1);
  const px = schedPx();
  const chartW = Math.max(360, Math.round(totalDays * px));
  const off = (iso) => Math.round((new Date(iso + "T00:00:00") - start) / 86400000);
  const x = (iso) => off(iso) * px;

  const byId = Object.fromEntries(s.tasks.map((t) => [t.id, t]));
  const rowIndex = Object.fromEntries(rows.map((t, i) => [t.id, i]));

  return `
    <div class="panel"><div class="panel-body flush">
      <div class="gx-toolbar">
        <div class="gx-zoom">
          ${Object.keys(SCHED_ZOOM).map((z) => `<button class="btn sm ${z === schedZoom ? "primary" : ""}"
             data-sched-zoom="${z}">${z[0].toUpperCase() + z.slice(1)}</button>`).join("")}
        </div>
        <div class="gx-zoom" style="margin-left:8px">
          <button class="btn sm" data-sched-zoomstep="-1" title="Zoom out (Ctrl + scroll on the chart)">−</button>
          <span class="mono muted small" style="min-width:44px;text-align:center"
                title="Relative to the ${schedZoom} preset">${Math.round(schedZoomFactor * 100)}%</span>
          <button class="btn sm" data-sched-zoomstep="1" title="Zoom in (Ctrl + scroll on the chart)">+</button>
          ${schedZoomFactor !== 1 ? `<button class="link small" data-sched-zoomstep="0">reset</button>` : ""}
        </div>
        <span class="grow"></span>
        <button class="btn sm" data-sched-fold="all">Collapse all</button>
        <button class="btn sm" data-sched-fold="none">Expand all</button>
        ${schedColsResized() ? `<button class="link small" data-sched-cols-reset>reset columns</button>` : ""}
        <button class="btn sm danger" data-sched-clear>Clear schedule</button>
      </div>
      <div class="gx" id="gx" style="${colWStyle()}">
        <div class="gx-grid">
          <div class="gx-head">
            <div class="gx-th gx-c-id">ID${colGrip("id")}</div>
            <div class="gx-th gx-c-name">Task Name${colGrip("name")}</div>
            <div class="gx-th gx-c-dur num">Dur${colGrip("dur")}</div>
            <div class="gx-th gx-c-date gx-c-start">Start${colGrip("start")}</div>
            <div class="gx-th gx-c-date gx-c-finish">Finish${colGrip("finish")}</div>
            <div class="gx-th gx-c-pred">Predecessors${colGrip("pred")}</div>
            <div class="gx-th gx-c-pct num">%${colGrip("pct")}</div>
            <div class="gx-th gx-c-float num">Float</div>
          </div>
          <div class="gx-body" id="gxGrid">${rows.map(gridRow).join("")}</div>
        </div>
        <div class="gx-chart" id="gxChart">
          ${timescale(start, totalDays, px, chartW)}
          <div class="gx-canvas" style="width:${chartW}px;height:${rows.length * ROW_H}px">
            ${weekendShading(start, totalDays, px, rows.length)}
            ${todayLine(start, totalDays, px, rows.length)}
            <svg class="gx-links" width="${chartW}" height="${rows.length * ROW_H}">
              ${linkArrows(s.links || [], byId, rowIndex, x)}
            </svg>
            ${rows.map((t, i) => chartRow(t, i, x, px)).join("")}
          </div>
        </div>
      </div>
    </div></div>`;
}

const colGrip = (c) => `<span class="gx-grip" data-gx-grip="${c}" title="Drag to resize"></span>`;
const schedColsResized = () =>
  GX_COLS.some((c) => Math.round(schedColW[c]) !== GX_DEFAULT_W[c]);

/* Column resizing. Dragged live against CSS variables so a 106-row grid
   doesn't re-render on every mousemove — only the width variable changes,
   and the browser reflows. The committed width is saved on release. */
function startColDrag(ev, col) {
  ev.preventDefault();
  const gx = document.querySelector("#gx");
  if (!gx) return;
  const startX = ev.clientX;
  const startW = schedColW[col];
  const move = (e) => {
    const w = Math.max(28, Math.min(640, startW + (e.clientX - startX)));
    schedColW[col] = w;
    gx.style.setProperty(`--gxw-${col}`, `${Math.round(w)}px`);
  };
  const up = () => {
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", up);
    document.body.classList.remove("col-resizing");
    saveColW();
    render();                       // repaint the toolbar's "reset columns"
  };
  document.body.classList.add("col-resizing");
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
}

/* Summary folding. A 106-row imported schedule is unreadable fully expanded,
   and Project users expect the triangle. */
function visibleRows(tasks) {
  const out = [];
  let hideUnder = null;
  for (const t of tasks) {
    const lvl = Math.max(1, t.outline_level || 1);
    if (hideUnder !== null && lvl > hideUnder) continue;
    hideUnder = null;
    out.push(t);
    if (t.is_summary && schedCollapsed.has(t.id)) hideUnder = lvl;
  }
  return out;
}

function gridRow(t) {
  const lvl = Math.max(1, t.outline_level || 1);
  const twist = t.is_summary
    ? `<button class="gx-twist" data-sched-fold-row="${t.id}"
         title="${schedCollapsed.has(t.id) ? "Expand" : "Collapse"}">${
         schedCollapsed.has(t.id) ? "▸" : "▾"}</button>`
    : `<span class="gx-twist"></span>`;
  const fl = t.total_float === null || t.total_float === undefined ? "" : `${t.total_float}d`;
  return `<div class="gx-row ${t.is_summary ? "is-summary" : ""} ${t.is_critical ? "is-crit" : ""}"
            data-row="${t.id}">
    <div class="gx-td gx-c-id">${esc(t.external_id || "")}</div>
    <div class="gx-td gx-c-name" style="padding-left:${2 + (lvl - 1) * 13}px">
      ${twist}<input class="ecell" value="${esc(t.name || "")}" data-task="${t.id}" data-field="name">
    </div>
    <div class="gx-td gx-c-dur num">${t.duration_days ?? ""}${
      t.duration_unit === "ed" ? " ed" : ""}</div>
    <div class="gx-td gx-c-date gx-c-start"><input class="ecell" type="date" value="${esc(t.start || "")}"
        data-task="${t.id}" data-field="start"></div>
    <div class="gx-td gx-c-date gx-c-finish"><input class="ecell" type="date" value="${esc(t.finish || "")}"
        data-task="${t.id}" data-field="finish"></div>
    <div class="gx-td gx-c-pred"><input class="ecell" value="${esc(t.predecessors || "")}"
        placeholder="—" title="e.g. 12, 14FS+2d, 9SS"
        data-task="${t.id}" data-field="predecessors"></div>
    <div class="gx-td gx-c-pct num"><input class="ecell num" type="number" min="0" max="100"
        value="${t.percent_complete ?? 0}" data-task="${t.id}" data-field="percent_complete"></div>
    <div class="gx-td gx-c-float num ${t.is_critical ? "neg" : ""}">${fl}</div>
    <button class="gx-del link danger" data-del-task="${t.id}" title="Delete task">×</button>
  </div>`;
}

function chartRow(t, i, x, px) {
  const top = i * ROW_H;
  if (!t.start) return "";
  const a = x(t.start);
  const b = t.finish ? x(t.finish) + px : a + px;
  const w = Math.max(3, b - a);
  const done = Math.max(0, Math.min(100, t.percent_complete || 0));
  const tip = `${t.name} · ${t.start} → ${t.finish || t.start}` +
    (t.total_float != null ? ` · float ${t.total_float}d` : "");

  if (t.is_milestone) {
    return `<div class="gx-ms" style="left:${a}px;top:${top + 6}px" title="${esc(tip)}"></div>`;
  }
  if (t.is_summary) {
    // Project draws summaries as a bracket, not a bar.
    return `<div class="gx-sum" style="left:${a}px;top:${top + 8}px;width:${w}px"
              title="${esc(tip)}"></div>`;
  }
  return `<div class="gx-bar ${t.is_critical ? "crit" : ""}"
            style="left:${a}px;top:${top + 6}px;width:${w}px" title="${esc(tip)}">
            <i style="width:${done}%"></i></div>`;
}

function timescale(start, totalDays, px, chartW) {
  const months = [];
  const weeks = [];
  const cur = new Date(start); cur.setDate(1);
  while (true) {
    const o = Math.round((cur - start) / 86400000);
    if (o > totalDays) break;
    const next = new Date(cur); next.setMonth(next.getMonth() + 1);
    const wpx = Math.round((Math.min(totalDays, (next - start) / 86400000) - Math.max(0, o)) * px);
    if (wpx > 0) {
      months.push(`<div class="gx-tick" style="left:${Math.max(0, o) * px}px;width:${wpx}px">${
        cur.toLocaleDateString("en-US", { month: "short", year: "2-digit" })}</div>`);
    }
    cur.setMonth(cur.getMonth() + 1);
  }
  // The lower tier only earns its space when zoomed in enough to read it.
  if (px >= SCHED_ZOOM.week) {
    const w = new Date(start);
    w.setDate(w.getDate() - ((w.getDay() + 6) % 7));      // back to Monday
    while ((w - start) / 86400000 <= totalDays) {
      const o = Math.round((w - start) / 86400000);
      if (o >= 0) {
        weeks.push(`<div class="gx-tick sm" style="left:${o * px}px;width:${7 * px}px">${
          w.getDate()}</div>`);
      }
      w.setDate(w.getDate() + 7);
    }
  }
  return `<div class="gx-scale" style="width:${chartW}px">
    <div class="gx-tier">${months.join("")}</div>
    ${weeks.length ? `<div class="gx-tier lower">${weeks.join("")}</div>` : ""}
  </div>`;
}

function weekendShading(start, totalDays, px, rowCount) {
  if (px < SCHED_ZOOM.week) return "";      // invisible and expensive when zoomed out
  const out = [];
  const d = new Date(start);
  for (let i = 0; i < totalDays; i++) {
    if (d.getDay() === 6) {
      out.push(`<div class="gx-weekend" style="left:${i * px}px;width:${2 * px}px;
                 height:${rowCount * ROW_H}px"></div>`);
    }
    d.setDate(d.getDate() + 1);
  }
  return out.join("");
}

function todayLine(start, totalDays, px, rowCount) {
  const o = Math.round((new Date(new Date().toDateString()) - start) / 86400000);
  if (o < 0 || o > totalDays) return "";
  return `<div class="gx-today" style="left:${o * px}px;height:${rowCount * ROW_H}px"
            title="today"></div>`;
}

/* Elbow connectors, the way Project draws them: out of the predecessor, down
   or up to the successor's row, then into its start with an arrowhead. */
function linkArrows(links, byId, rowIndex, x) {
  const out = [];
  for (const lk of links) {
    const p = byId[lk.pred_id], s = byId[lk.succ_id];
    if (!p || !s || !p.start || !s.start) continue;
    const pi = rowIndex[p.id], si = rowIndex[s.id];
    if (pi === undefined || si === undefined) continue;   // folded away
    const py = pi * ROW_H + ROW_H / 2;
    const sy = si * ROW_H + ROW_H / 2;
    const pxEnd = lk.link_type === "SS" || lk.link_type === "SF"
      ? x(p.start) : x(p.finish || p.start) + 6;
    const sxStart = lk.link_type === "FF" || lk.link_type === "SF"
      ? x(s.finish || s.start) : x(s.start);
    const mid = Math.max(pxEnd + 6, sxStart - 8);
    const dashed = lk.inferred ? ` stroke-dasharray="3 2"` : "";
    out.push(`<path d="M${pxEnd},${py} H${mid} V${sy} H${sxStart}"
      fill="none" class="gx-link"${dashed}></path>
      <path d="M${sxStart},${sy} l-5,-3 l0,6 z" class="gx-arrow"></path>`);
  }
  return out.join("");
}

/* ---- the import review screen --------------------------------------------------------
   A schedule import replaces the plan the whole team works to, and a PDF's
   dependencies are traced from arrows rather than stated. So: show what was
   read, say plainly what could not be, and let a human decide each proposed
   link before anything moves. */

function importReview(v) {
  const c = v.counts;
  const links = v.links || [];
  return `
    <div class="panel">
      <div class="panel-head"><h3>Review this import</h3>
        <span class="sub">${esc(v.filename)} · read as ${esc((v.source || "").toUpperCase())}</span></div>
      <div class="panel-body">
        <div class="note" style="margin-bottom:12px">
          <b>${c.tasks} tasks</b> · ${c.dated} with dates · ${c.milestones} milestones ·
          ${c.summaries} summary rows${links.length ? ` · <b>${links.length} proposed dependencies</b>` : ""}.
          Nothing has been applied yet.
        </div>

        ${v.warnings.length ? `<div class="field" style="margin-bottom:12px">
          <label>Worth knowing</label>
          <ul class="gx-warn">${v.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
        </div>` : ""}

        ${links.length ? `<div class="field" style="margin-bottom:12px">
          <label>Proposed dependencies — tick the ones to keep</label>
          <div class="hint small muted" style="margin-bottom:6px">
            These were traced from the arrows drawn on the chart, not read from a
            column — this file doesn't state its dependencies. Anything you leave
            unticked is discarded. Nothing here has moved a date.
          </div>
          <div class="gx-links-review">
            ${links.map((l) => `<label class="gx-linkrow">
              <input type="checkbox" data-link-pick="${esc(l.id)}"
                     ${l.confidence >= 0.45 ? "checked" : ""}>
              <span class="mono">${esc(l.pred_external_id)}</span>
              <span class="muted">${esc(l.pred_name || "")}</span>
              <b>→</b>
              <span class="mono">${esc(l.succ_external_id)}</span>
              <span class="muted">${esc(l.succ_name || "")}</span>
              <span class="tag">${esc(l.link_type)}</span>
              <span class="small ${l.confidence >= 0.45 ? "" : "muted"}">confidence ${
                Math.round(l.confidence * 100)}%</span>
            </label>`).join("")}
          </div>
          <div style="margin-top:6px">
            <button class="btn sm" data-link-all="1">Tick all</button>
            <button class="btn sm" data-link-all="0">Untick all</button>
          </div>
        </div>` : ""}

        <details style="margin-bottom:12px">
          <summary class="small">Preview the ${c.tasks} tasks</summary>
          <div class="gx-preview">
            <table class="tbl">
              <thead><tr><th>ID</th><th>WBS</th><th>Task</th><th class="num">Dur</th>
                <th>Start</th><th>Finish</th><th class="num">%</th></tr></thead>
              <tbody>${v.tasks.slice(0, 400).map((t) => `<tr>
                <td class="mono">${esc(t.external_id || "")}</td>
                <td class="mono small">${esc(t.wbs || "")}</td>
                <td style="padding-left:${4 + ((t.outline_level || 1) - 1) * 12}px">${esc(t.name)}</td>
                <td class="num">${t.duration_days ?? ""}</td>
                <td>${esc(t.start || "")}</td><td>${esc(t.finish || "")}</td>
                <td class="num">${t.percent_complete ?? 0}</td></tr>`).join("")}</tbody>
            </table>
          </div>
        </details>
      </div>
      <div class="dialog-actions" style="position:static;margin:0;border-radius:0">
        <span class="grow small muted" id="schedReviewMsg"></span>
        <button class="btn" data-import-discard="${esc(v.id)}">Discard</button>
        <button class="btn primary" data-import-commit="${esc(v.id)}">
          Apply ${c.tasks} tasks${links.length ? " + ticked links" : ""}</button>
      </div>
    </div>`;
}

function schedTaskForm() {
  return `
    <div class="panel"><div class="panel-body flush">
      <form class="inline-form top" id="addTask" style="border-bottom:none">
        <input name="name" class="grow" placeholder="Task name" required>
        <input name="start" type="date" title="Start">
        <input name="finish" type="date" title="Finish">
        <input name="predecessors" placeholder="Predecessors (IDs)" style="width:150px">
        <button class="btn primary sm" type="submit">+ Task</button>
      </form>
    </div></div>`;
}

async function loadSchedule() {
  const job = encodeURIComponent(current.job);
  const data = await api(`/api/jobs/${job}/schedule`);
  schedCache = { job: current.job, data };
  // An import waiting on review belongs to the JOB, not to the tab that
  // uploaded it. Without this, refreshing the page — or a colleague opening
  // it — would lose a staged import with no way back to it.
  if (!schedStaged) {
    try {
      const staged = await api(`/api/jobs/${job}/schedule/import/staged`);
      if (staged && staged.id) schedStaged = { ...staged, mode: "replace" };
    } catch { /* nothing staged is the normal case */ }
  }
  if (current.page === "schedule") render();
}

const schedMsg = (t) => { const el = document.querySelector("#schedMsg"); if (el) el.textContent = t; };

main.addEventListener("change", async (e) => {
  if (e.target.id === "schedUpload") {
    const file = e.target.files[0];
    if (!file) return;
    const mode = document.querySelector("#schedMode")?.value || "replace";
    schedMsg(`reading ${file.name}…`);
    const form = new FormData();
    form.append("file", file);
    const headers = currentUser ? { "X-PlanWise-User": currentUser } : {};
    const r = await fetch(
      `/api/jobs/${encodeURIComponent(current.job)}/schedule/import?mode=${mode}`,
      { method: "POST", body: form, headers });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { schedMsg(`couldn't read that file: ${body.detail || r.statusText}`); return; }
    if (body.staged) {
      // Something to decide: proposed dependencies, or warnings worth reading.
      schedStaged = body;
      schedMsg("");
      render();
      return;
    }
    schedStaged = null;
    await loadSchedule();
    schedMsg(`${body.added} added, ${body.updated} updated`
      + (body.removed ? `, ${body.removed} removed` : "")
      + ` from ${(body.source || "").toUpperCase()}`);
    return;
  }
  const t = e.target.closest("[data-task]");
  if (t) {
    await api(`/api/jobs/${encodeURIComponent(current.job)}/schedule/tasks/${t.dataset.task}`, {
      method: "PATCH", body: JSON.stringify({ [t.dataset.field]: e.target.value }) });
    await loadSchedule();
  }
});

/* Grips are mousedown, not click — a click fires only after release, by which
   time the drag is over. */
main.addEventListener("mousedown", (e) => {
  const grip = e.target.closest("[data-gx-grip]");
  if (grip) startColDrag(e, grip.dataset.gxGrip);
});

/* ---- change order documents ------------------------------------------------------- */

const coSelected = (kind) => {
  const el = document.querySelector(`[data-co-select="${kind}"]`);
  return (el && el.value) || coDocSel[kind];
};

/* The server refuses a customer letter with nobody to address it to. That is
   not an error to apologise for — it's a missing prerequisite with an obvious
   next step, so say what's needed and put them on the page that fixes it. */
function handleCoError(err, kind) {
  const d = err && err.detail;
  if (d && d.needs_contact) {
    coMsg(kind, `${d.detail} Taking you to Overview…`);
    setTimeout(() => {
      location.hash = `/job/${encodeURIComponent(current.job)}/overview`;
    }, 1400);
    return true;
  }
  return false;
}

main.addEventListener("change", (e) => {
  const sel = e.target.closest("[data-co-select]");
  if (sel) {
    const kind = sel.dataset.coSelect;
    coDocSel[kind] = sel.value;
    if (coPreview && coPreview.kind === kind) { coPreview = null; render(); }
    return;
  }
  const cl = e.target.closest("[data-clarif]");
  if (cl) {
    cl.checked ? coClarifPick.add(cl.dataset.clarif) : coClarifPick.delete(cl.dataset.clarif);
    saveClarifications();
  }
});

/* Read the breakout back out of the DOM rather than tracking every keystroke
   in state — the inputs are the source of truth while you're typing in them,
   and re-rendering on each character would steal the caret. */
function readItems() {
  return [...document.querySelectorAll("[data-item-desc]")].map((el, i) => ({
    description: el.value,
    amount: (document.querySelector(`[data-item-amt="${i}"]`) || {}).value || "",
  }));
}

async function saveItems() {
  const coId = coSelected("customer");
  if (!coId) return;
  const items = readItems()
    .filter((r) => (r.description || "").trim())
    .map((r) => ({ description: r.description, amount: parseFloat(r.amount) || 0 }));
  const out = await api(`/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/items`,
                        { method: "PUT", body: JSON.stringify({ items }) });
  coItems = out.items.map((r) => ({ description: r.description, amount: r.amount }));
  refreshCoPreview();
  return out;
}

/* Reload the embedded PDF. The URL carries a revision so the browser fetches
   the new document instead of showing the one it already has. */
function refreshCoPreview() {
  coPreviewRev += 1;
  const f = document.querySelector("#coFrame");
  if (f && coPreview) {
    f.src = `/api/jobs/${encodeURIComponent(current.job)}/cos/${coPreview.coId}`
          + `/document.pdf#toolbar=1&v=${coPreviewRev}`;
  }
}

let coSaveTimer = null;
const debounceCoSave = (fn) => {
  clearTimeout(coSaveTimer);
  coSaveTimer = setTimeout(fn, 700);
};

main.addEventListener("input", (e) => {
  const narr = e.target.closest("[data-co-narr]");
  if (narr) {
    debounceCoSave(async () => {
      await api(`/api/jobs/${encodeURIComponent(current.job)}/cos/${narr.dataset.coNarr}`,
                { method: "PATCH", body: JSON.stringify({ narrative: narr.value }) });
      const c = (current.data.change_orders || []).find((x) => x.id === narr.dataset.coNarr);
      if (c) c.narrative = narr.value;            // keep the cache honest
      refreshCoPreview();
    });
    return;
  }
  if (e.target.closest("[data-item-desc]") || e.target.closest("[data-item-amt]")) {
    debounceCoSave(saveItems);
  }
});

async function saveClarifications() {
  const coId = coSelected("customer");
  if (!coId) return;
  await api(`/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/clarifications`,
            { method: "PATCH", body: JSON.stringify({ clarifications: [...coClarifPick] }) });
  coMsg("customer", `${coClarifPick.size} clarification${coClarifPick.size === 1 ? "" : "s"} on this change order.`);
  if (coPreview) { coPreview = null; render(); }   // the letter changed
}

main.addEventListener("submit", async (e) => {
  const f = e.target.closest("#addClarif");
  if (!f) return;
  e.preventDefault();
  const text = f.text.value.trim();
  if (!text) return;
  try {
    await api("/api/co-clarifications", { method: "POST", body: JSON.stringify({ text }) });
    coClarifLib = (await api("/api/co-clarifications")).clarifications;
    coClarifPick.add(text);                        // adding it means wanting it
    await saveClarifications();
    render();
  } catch (err) { coMsg("customer", err.message); }
});

main.addEventListener("click", async (e) => {
  const prev = e.target.closest("[data-co-preview]");
  if (prev) {
    const kind = prev.dataset.coPreview;
    const coId = coSelected(kind);
    if (!coId) return coMsg(kind, "Pick a change order first.");
    try {
      // Ask for it before showing the frame: an iframe that 409s renders the
      // browser's error page, which tells nobody to go and add a contact.
      const r = await fetch(`/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/document.pdf`);
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        if (handleCoError(body, kind)) return;
        return coMsg(kind, (body.detail && body.detail.detail) || body.detail || `HTTP ${r.status}`);
      }
      const closing = coPreview && coPreview.coId === coId;
      coPreview = closing ? null : { kind, coId };
      if (!closing && kind === "customer") {
        coItems = ((await api(
          `/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/items`)).items || [])
          .map((r) => ({ description: r.description, amount: r.amount }));
      }
      coMsg(kind, "");
      render();
    } catch (err) { coMsg(kind, err.message); }
    return;
  }

  const clarify = e.target.closest("[data-co-clarify]");
  if (clarify) {
    coClarifOpen = !coClarifOpen;
    if (coClarifOpen) {
      if (!coClarifLib) coClarifLib = (await api("/api/co-clarifications")).clarifications;
      // Load what this change order already carries, so the ticks reflect
      // reality instead of starting blank every time the panel opens.
      const coId = coSelected("customer");
      const cur = coId && await api(
        `/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/clarifications`).catch(() => null);
      coClarifPick = new Set((cur && cur.clarifications) || []);
    }
    render();
    return;
  }

  const arch = e.target.closest("[data-clarif-archive]");
  if (arch) {
    await api(`/api/co-clarifications/${arch.dataset.clarifArchive}`, { method: "DELETE" });
    coClarifLib = (await api("/api/co-clarifications")).clarifications;
    render();
    return;
  }

  const toPo = e.target.closest("[data-co-to-po]");
  if (toPo) {
    const co = (current.data.change_orders || []).find((c) => c.id === toPo.dataset.coToPo);
    if (!co) return;
    // Pre-filled from the agreement, then editable like any other PO — the
    // number and cost type are the PM's call, but nobody should retype a
    // vendor and an amount that are already recorded three rows away.
    const num = prompt(`PO number for ${co.subcontractor || "this subcontractor"} `
      + `(Sub CO #${co.co_number || "—"}, ${money(co.amount_approved)}):`,
      `PO-${co.co_number || ""}`);
    if (num === null) return;
    await api(`/api/jobs/${encodeURIComponent(current.job)}/pos`, {
      method: "POST",
      body: JSON.stringify({
        po_number: num.trim(),
        vendor: co.subcontractor || "",
        description: co.description || `Sub CO ${co.co_number || ""}`.trim(),
        adjusted_amount: co.amount_approved,
        original_amount: co.amount_approved,
        cost_type: "Subcontractor",
        source_co_id: co.id,
      }),
    });
    await refreshJob();
    return;
  }

  const addItem = e.target.closest("[data-item-add]");
  if (addItem) {
    coItems = [...readItems(), { description: "", amount: "" }];
    render();
    return;
  }

  const delItem = e.target.closest("[data-item-del]");
  if (delItem) {
    const rows = readItems();
    rows.splice(Number(delItem.dataset.itemDel), 1);
    coItems = rows;
    await saveItems();
    render();
    return;
  }

  const dlpdf = e.target.closest("[data-co-pdf]");
  if (dlpdf) {
    const kind = dlpdf.dataset.coPdf;
    const coId = coSelected(kind);
    if (!coId) return coMsg(kind, "Pick a change order first.");
    const ok = await downloadEml(
      `/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/document.pdf`,
      (t) => coMsg(kind, t));
    if (ok) coMsg(kind, "PDF downloaded.");
    return;
  }

  const docx = e.target.closest("[data-co-docx]");
  if (docx) {
    const kind = docx.dataset.coDocx;
    const coId = coSelected(kind);
    if (!coId) return coMsg(kind, "Pick a change order first.");
    const ok = await downloadEml(
      `/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/document.docx`,
      (t) => coMsg(kind, t));
    if (ok) coMsg(kind, "Word document downloaded — edit and send it however you like.");
    return;
  }

  const share = e.target.closest("[data-co-share]");
  if (share) {
    const kind = share.dataset.coShare;
    const coId = coSelected(kind);
    if (!coId) return coMsg(kind, "Pick a change order first.");
    try {
      coMsg(kind, "building the document…");
      const doc = await api(`/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/share`);
      await companionFetch("/draft", {
        to: doc.to, subject: doc.subject, body: doc.body,
        attachments: doc.attachments,
      });
      coMsg(kind, kind === "subcontractor"
        ? "Opened in your Outlook — the To line is blank, add the subcontractor and Send."
        : `Opened in your Outlook — addressed to ${doc.contacts.map((c) => c.name).join(", ")}, `
          + "Word and PDF both attached. Review and Send.");
    } catch (err) {
      if (handleCoError(err, kind)) return;
      const emlPath = `/api/jobs/${encodeURIComponent(current.job)}/cos/${coId}/share.eml`;
      if (noCompanion(err)) {
        coMsg(kind, "No Outlook companion on this device.");
        offerEml(`#coMsg-${kind}`, emlPath, "Take it as an email file instead:");
      } else {
        coMsg(kind, `Couldn't draft via the companion: ${err.message}.`);
        offerEml(`#coMsg-${kind}`, emlPath, "You can still send it from this PC's Outlook:");
      }
    }
  }
});

/* Ctrl + wheel over the chart, the gesture every drawing tool has trained
   people to try. Passive:false because preventDefault has to stop the browser
   zooming the whole page instead. */
main.addEventListener("wheel", (e) => {
  if (!e.ctrlKey || !e.target.closest("#gxChart")) return;
  e.preventDefault();
  schedZoomFactor = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX,
    schedZoomFactor * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
  render();
}, { passive: false });

main.addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del-task]");
  if (del) {
    if (!armed(del)) return;
    await api(`/api/jobs/${encodeURIComponent(current.job)}/schedule/tasks/${del.dataset.delTask}`,
              { method: "DELETE" });
    await loadSchedule();
    return;
  }

  const zoom = e.target.closest("[data-sched-zoom]");
  if (zoom) { schedZoom = zoom.dataset.schedZoom; schedZoomFactor = 1; render(); return; }

  const step = e.target.closest("[data-sched-zoomstep]");
  if (step) {
    const dir = Number(step.dataset.schedZoomstep);
    schedZoomFactor = dir === 0 ? 1
      : Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, schedZoomFactor * (dir > 0 ? 1.35 : 1 / 1.35)));
    render();
    return;
  }

  if (e.target.closest("[data-sched-cols-reset]")) {
    schedColW = { ...GX_DEFAULT_W };
    saveColW();
    render();
    return;
  }

  const clear = e.target.closest("[data-sched-clear]");
  if (clear) {
    const n = (schedCache?.data?.tasks || []).length;
    // Typed confirmation rather than an "are you sure": this throws away an
    // import that may have taken a review pass to get right, and there is no
    // undo. The count is in the prompt so nobody clears the wrong job.
    const answer = prompt(`Delete all ${n} tasks and their dependencies on `
      + `${current.job}? Your working calendar is kept.\n\nType DELETE to confirm:`);
    if ((answer || "").trim().toUpperCase() !== "DELETE") return;
    await api(`/api/jobs/${encodeURIComponent(current.job)}/schedule/tasks`,
              { method: "DELETE" });
    schedCollapsed.clear();
    await loadSchedule();
    return;
  }

  const foldRow = e.target.closest("[data-sched-fold-row]");
  if (foldRow) {
    const id = foldRow.dataset.schedFoldRow;
    schedCollapsed.has(id) ? schedCollapsed.delete(id) : schedCollapsed.add(id);
    render();
    return;
  }

  const foldAll = e.target.closest("[data-sched-fold]");
  if (foldAll) {
    schedCollapsed = foldAll.dataset.schedFold === "all"
      ? new Set((schedCache?.data.tasks || []).filter((t) => t.is_summary).map((t) => t.id))
      : new Set();
    render();
    return;
  }

  // --- the import review screen ---
  const pickAll = e.target.closest("[data-link-all]");
  if (pickAll) {
    const on = pickAll.dataset.linkAll === "1";
    document.querySelectorAll("[data-link-pick]").forEach((c) => { c.checked = on; });
    return;
  }

  const discard = e.target.closest("[data-import-discard]");
  if (discard) {
    await api(`/api/schedule/import/${discard.dataset.importDiscard}/discard`,
              { method: "POST" }).catch(() => {});
    schedStaged = null;
    await loadSchedule();
    schedMsg("Import discarded — the schedule is unchanged.");
    return;
  }

  const commit = e.target.closest("[data-import-commit]");
  if (commit) {
    const accepted = [...document.querySelectorAll("[data-link-pick]")]
      .filter((c) => c.checked).map((c) => c.dataset.linkPick);
    const msg = (t) => { const el = $("#schedReviewMsg"); if (el) el.textContent = t; };
    commit.disabled = true;
    msg("applying…");
    try {
      const out = await api(`/api/schedule/import/${commit.dataset.importCommit}/commit`, {
        method: "POST",
        body: JSON.stringify({ mode: schedStaged?.mode || "replace",
                               accepted_link_ids: accepted }) });
      schedStaged = null;
      await loadSchedule();
      schedMsg(`${out.added} added, ${out.updated} updated`
        + (out.removed ? `, ${out.removed} removed` : "")
        + (out.links_accepted ? `, ${out.links_accepted} dependencies accepted` : "")
        + (out.links_rejected ? ` (${out.links_rejected} rejected)` : ""));
    } catch (err) {
      commit.disabled = false;
      msg(`couldn't apply it: ${err.message}`);
    }
  }
});

/* The two panes scroll as one — that lock is most of what makes this read as
   MS Project rather than as a table with a picture beside it.

   Listener on DOCUMENT, not on `main`: scroll events don't bubble, and a
   capturing listener on an intermediate ancestor never saw them. document
   with capture is the one place that reliably does, and it survives the
   innerHTML replacement that every render does. */
document.addEventListener("scroll", (e) => {
  const grid = document.querySelector("#gxGrid");
  const chart = document.querySelector("#gxChart");
  if (!grid || !chart) return;
  if (e.target === grid && Math.abs(chart.scrollTop - grid.scrollTop) > 1) {
    chart.scrollTop = grid.scrollTop;
  } else if (e.target === chart && Math.abs(grid.scrollTop - chart.scrollTop) > 1) {
    grid.scrollTop = chart.scrollTop;
  }
}, true);

/* "+ Task" had no handler at all — the form rendered, the generic submit
   listener preventDefault()ed and returned, and the button did nothing. The
   Schedule page has therefore never been able to add a task by hand. */
main.addEventListener("submit", async (e) => {
  const f = e.target.closest("#addTask");
  if (!f) return;
  e.preventDefault();
  const body = Object.fromEntries(
    [...new FormData(f).entries()].filter(([, v]) => String(v).trim() !== ""));
  if (!body.name) return;
  const btn = f.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    await api(`/api/jobs/${encodeURIComponent(current.job)}/schedule/tasks`,
              { method: "POST", body: JSON.stringify(body) });
    f.reset();
    await loadSchedule();
  } catch (err) {
    schedMsg(`couldn't add that task: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
});

/* ---- page: Two-Week Look Ahead (Phase 4) ---------------------------------------------- */

let laCache = null;        // {job, data}
let laPreview = null;      // null | "customer" | "team" — inline PDF preview
let laPreviewPage = 1;
let laPreviewPages = 1;
let laAreasOpen = false;   // work-area editor: set-up, so it stays out of the way
let laShareWeeks = null;   // null = share whatever the grid shows

const LA_STATUSES = ["Planned", "In Progress", "Complete", "Blocked", "Deferred"];

function laStampCls(s) {
  return s === "Complete" ? "ok" : s === "Blocked" ? "err"
       : s === "In Progress" ? "info" : s === "Deferred" ? "warn" : "neutral";
}

function lookaheadPage(d) {
  if (!laCache || laCache.job !== current.job) {
    loadLookahead();
    return `<p class="placeholder">Loading look ahead…</p>`;
  }
  const p = laCache.data;
  const items = p.items || [];
  const days = p.days || [];

  const areas = p.areas || [];
  const byId = Object.fromEntries(areas.map((a) => [a.id, a]));

  // Ticks are stored 21 days wide whatever's on show, so dropping back to two
  // weeks hides week three rather than discarding it. `sendWeeks` is what a
  // share/preview actually carries — never more than the sheet holds.
  const weeks = p.weeks || 2;
  const sendWeeks = Math.min(laShareWeeks || weeks, weeks);

  const dayCls = (day) =>
    `la-day ${day.weekend ? "weekend" : ""} ${day.index % 7 === 0 ? "wk-start" : ""}`;
  // data-label is what each day cell prints above its checkbox once the grid
  // wraps into weeks on a phone — "Sun9" from textContent would be unreadable.
  const dayHead = days.map((day) => `
    <th class="${dayCls(day)}" title="${esc(day.date)}" data-label="${day.dow} ${day.day}">
      <span class="dow">${day.dow}</span><span class="dom">${day.day}</span>
    </th>`).join("");

  // Collapsed by default and collapsed again after every edit: this panel is
  // set-up, and the grid is the thing you came to look at. Collapsed it shows
  // the swatches so you can still see at a glance what's in play.
  const inUse = areas.filter((a) => a.active);
  // Wrapped in a .field like Prepared By and Start Date, so the label sits on
  // their label line and the card's box lines up with their inputs.
  const areaCard = `
    <div class="field">
      <label>Work Areas <span class="hint">optional</span></label>
      <div class="minicard ${laAreasOpen ? "open" : ""}">
      <button class="minicard-head" data-la-areas-toggle>
        <span><span class="caret">${laAreasOpen ? "▾" : "▸"}</span> ${areas.length ? `${inUse.length} in use` : "none yet"}</span>
        <span class="sub">${inUse.map((a) =>
          `<span class="la-swatch sm" style="background:${esc(a.color)}" title="${esc(a.name)}"></span>`).join("")}</span>
      </button>
      ${!laAreasOpen ? "" : `<div class="minicard-body">
        ${areas.map((a) => `<div class="la-area-row ${a.active ? "" : "retired"}">
          <span class="la-swatch" style="background:${esc(a.color)}"></span>
          <input class="ecell" value="${esc(a.name)}" data-la-area="${a.id}" data-field="name">
          <label class="chk" title="Tick while this area is in use. Untick and its rows go back to no area — the area itself stays, ready to tick on again.">
            <input type="checkbox" data-la-area="${a.id}" data-field="active" ${a.active ? "checked" : ""}></label>
          <span class="small muted" title="rows using this area">${items.filter((i) => i.work_area_id === a.id).length}</span>
          <button class="link danger" data-del-area="${a.id}" title="Remove — rows keep their work, they just lose the colour">×</button>
        </div>`).join("") || `<p class="none">None yet — rows stay uncoloured.</p>`}
        <form class="la-area-add" data-area-form="${esc(current.job)}">
          <input name="name" placeholder="Add a work area…" required>
          <button class="btn sm" type="submit">+</button>
        </form>
      </div>`}
      </div>
    </div>`;

  const preview = !laPreview ? "" : `
    <div class="panel">
      <div class="panel-head">
        <h3>${laPreview === "team" ? "Internal" : "Customer"} PDF preview</h3>
        <span class="sub">${sendWeeks} week${sendWeeks === 1 ? "" : "s"} · ${laPreview === "team"
          ? "the full sheet — tools and materials included"
          : "what the customer receives — no tools or materials"}</span></div>
      <div class="inline-form top" style="border-top:none;border-bottom:1px solid var(--line-strong)">
        <button class="btn sm" data-la-pv-page="-1" ${laPreviewPage <= 1 ? "disabled" : ""}>‹ Prev</button>
        <span class="small muted" id="laPvPages">page ${laPreviewPage}</span>
        <button class="btn sm" data-la-pv-page="1">Next ›</button>
        <a class="btn sm" href="/api/lookahead/${p.id}/pdf?audience=${laPreview}&weeks=${sendWeeks}"
           target="_blank">Open / Download</a>
        <button class="btn sm" data-la-preview="">Close</button>
      </div>
      <div class="panel-body la-preview"><canvas id="laPvCanvas"></canvas></div>
    </div>`;

  // The column exists only while at least one area is ticked "in use" — not
  // merely defined. Untick them all and it disappears entirely; tick one and
  // it's back, so there's somewhere to assign from. Un-ticking releases that
  // area's rows server-side, so a row can never hold an area that's off.
  // (The PDF is stricter still: it prints the column only when a row actually
  // uses an area, so an in-use-but-unassigned area costs no width on paper.)
  const showAreas = areas.some((a) => a.active);
  const areaCell = (i) => {
    const opts = areas.filter((a) => a.active);
    const chosen = byId[i.work_area_id];
    // The wrapper pins the column width: a bare <select> sizes itself to its
    // widest option, which is exactly what pushed the grid into a scroll bar.
    return `<td class="la-area-cell" style="border-left:3px solid ${chosen ? esc(chosen.color) : "transparent"}">
      <div class="la-area-wrap"><select class="ecell la-area" data-la="${i.id}" data-field="work_area_id"
        title="${chosen ? esc(chosen.name) : "No work area"}">
        <option value="">— no area —</option>
        ${opts.map((a) => `<option value="${a.id}" ${a.id === i.work_area_id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}
      </select></div></td>`;
  };

  // Wrapping cells, never a scroll bar: a textarea that grows to its content
  // (see growCells) so nothing is ever hidden behind an overflow.
  const cell = (i, field, placeholder, cls = "") => `<td class="la-text ${cls}">
    <textarea class="ecell la-wrap" rows="1" data-la="${i.id}"
      data-field="${field}" placeholder="${placeholder}">${esc(i[field] || "")}</textarea></td>`;

  return `
    <div class="panel">
      <div class="panel-head"><h3>${weeks === 3 ? "Three" : "Two"}-Week Look Ahead</h3>
        <span class="sub">${esc(p.start_date)} → ${esc(p.end_date)} · ${items.length} activities</span></div>
      <div class="inline-form top" style="border-top:none;border-bottom:1px solid var(--line-strong)">
        <span class="seg" title="Three weeks keeps a rolling plan on screen; dropping back to two hides week three, it doesn't delete it">
          ${[2, 3].map((n) => `<button class="btn sm ${weeks === n ? "active" : ""}"
            data-la-weeks="${n}" data-period="${p.id}">${n} wk</button>`).join("")}
        </span>
        <button class="btn sm" data-la-seed="${p.id}" title="Pull schedule tasks that overlap this window">Seed from Schedule</button>
        <button class="btn sm ${laPreview === "customer" ? "active" : ""}" data-la-preview="customer"
          title="The customer PDF — no tools or materials">Preview Customer PDF</button>
        <button class="btn sm ${laPreview === "team" ? "active" : ""}" data-la-preview="team"
          title="The internal PDF — everything, including tools and materials">Preview Internal PDF</button>
        <button class="btn primary sm" data-la-share="${p.id}" data-audience="customer"
          title="Drafts the customer version into YOUR Outlook — tools and materials removed">Share to Customer</button>
        <button class="btn sm" data-la-share="${p.id}" data-audience="team"
          title="Drafts the full internal version with a blank To line for you to address">Share with My Team</button>
        ${weeks === 3 ? `<label class="chk" title="Plan three weeks, send the near-term two. Week three stays on your grid either way.">
          <input type="checkbox" id="laSend3" ${sendWeeks === 3 ? "checked" : ""}> send all 3 weeks</label>` : ""}
        <span id="laMsg" class="small muted"></span>
      </div>
      <div class="panel-body">
        <div class="la-setup">
          <div class="field"><label>Prepared By</label>
            <input data-la-period="${p.id}" data-field="prepared_by" value="${esc(p.prepared_by || "")}" placeholder="—"></div>
          <div class="field"><label>Start Date</label>
            <input type="date" id="laStart" value="${esc(p.start_date)}"></div>
          ${areaCard}
        </div>
      </div>
      <div class="panel-body flush">
        <form class="inline-form" data-la-form="${p.id}">
          <input name="description" class="grow" placeholder="Task name & description" required>
          <input name="requirements" placeholder="Requirements for customer" style="width:200px">
          <input name="notes" placeholder="Operation notes" style="width:180px">
          <button class="btn primary sm" type="submit">+ Task</button>
        </form>
        <div class="la-scroll">
        <table class="tbl la-grid ${weeks === 3 ? "wk3" : ""}">
          <thead><tr>
            <th class="la-task">Task Name &amp; Description</th>
            ${showAreas ? `<th class="la-area-cell">Work Area</th>` : ""}${dayHead}
            <th class="la-text">Requirements for Customer</th>
            <th class="la-text">Operation Notes</th>
            <th class="la-text internal">Tools Needed</th>
            <th class="la-text internal">Material Needed</th>
            <th class="la-x"></th>
          </tr></thead>
          <tbody>
            ${items.map((i) => {
              const area = byId[i.work_area_id];
              // The row's colour drives the band AND its ticked days (see .la-check).
              return `<tr ${area ? `style="--row-color:${esc(area.color)};--row-ink:#fff"` : ""}>
              <td class="la-task" style="border-left:4px solid ${area ? esc(area.color) : "transparent"}">
                ${i.task_id ? `<span class="tag" title="Pulled from the imported project schedule. Edit it freely — re-seeding never overwrites your changes.">FROM SCHEDULE</span>` : ""}
                <textarea class="ecell la-wrap" rows="1" data-la="${i.id}" data-field="description"
                  placeholder="Task name & description">${esc(i.description || "")}</textarea></td>
              ${showAreas ? areaCell(i) : ""}
              ${days.map((day) => `
                <td class="${dayCls(day)}">
                  <input type="checkbox" class="la-check" data-day-item="${i.id}" data-day-index="${day.index}"
                    ${i.days && i.days[day.index] === "1" ? "checked" : ""}
                    title="${esc(day.dow)} ${day.day}"></td>`).join("")}
              ${cell(i, "requirements", "Access, outage, escort…")}
              ${cell(i, "notes", "Operation notes…")}
              ${cell(i, "tools", "Internal only…", "internal")}
              ${cell(i, "materials", "Internal only…", "internal")}
              <td class="la-x"><button class="link danger" data-del-la="${i.id}" title="Remove">×</button></td>
            </tr>`; }).join("") || `<tr><td colspan="${days.length + 6 + (showAreas ? 1 : 0)}" class="none">Nothing planned yet — seed from the schedule or add a task above.</td></tr>`}
          </tbody>
        </table>
        </div>
      </div>
    </div>

    ${preview}

    <div class="note">Tick the days each task is worked. Lines pulled in by
    <b>Seed from Schedule</b> are marked <span class="tag">FROM SCHEDULE</span> and stay
    fully editable — re-seeding adds only newly-overlapping schedule tasks and never
    overwrites what you've changed or typed.
    <b>Tools Needed</b> and <b>Material Needed</b> are internal: they appear on
    <b>Share with My Team</b> only and are never built into the customer version.
    Either share drafts into <b>your</b> Outlook; you review and send.</div>`;
}

/** Grow every wrapping cell to its content, so a long note is fully visible
    instead of hiding behind a scroll bar. */
function growCells() {
  main.querySelectorAll("textarea.la-wrap").forEach((t) => {
    t.style.height = "auto";
    t.style.height = `${t.scrollHeight}px`;
  });
}

async function afterLookaheadRender() {
  growCells();
  const canvas = document.querySelector("#laPvCanvas");
  if (!canvas || !laCache) return;
  const p = laCache.data;
  const wk = Math.min(laShareWeeks || p.weeks || 2, p.weeks || 2);
  const url = `/api/lookahead/${p.id}/pdf?audience=${laPreview}&weeks=${wk}`;
  const width = Math.max(320, (canvas.parentElement.clientWidth || 900) - 8);
  try {
    const pages = await DW.renderPdfPage(canvas, url, laPreviewPage, width);
    laPreviewPages = pages;
    const label = document.querySelector("#laPvPages");
    if (label) label.textContent = `page ${laPreviewPage} of ${pages}`;
    const next = document.querySelector('[data-la-pv-page="1"]');
    if (next) next.disabled = laPreviewPage >= pages;
  } catch (err) { laMsg(`preview failed: ${err.message}`); }
}

main.addEventListener("input", (e) => {
  if (e.target.classList.contains("la-wrap")) {
    e.target.style.height = "auto";
    e.target.style.height = `${e.target.scrollHeight}px`;
  }
});

async function loadLookahead(start) {
  const q = start ? `?start=${encodeURIComponent(start)}` : "";
  const data = await api(`/api/jobs/${encodeURIComponent(current.job)}/lookahead${q}`);
  laCache = { job: current.job, data };
  if (current.page === "lookahead") render();
}

const laMsg = (t) => { const el = document.querySelector("#laMsg"); if (el) el.textContent = t; };

main.addEventListener("change", async (e) => {
  if (e.target.id === "laStart") { await loadLookahead(e.target.value); return; }
  if (e.target.id === "laSend3") { laShareWeeks = e.target.checked ? 3 : 2; render(); return; }

  // Day tick. Optimistic: the checkbox already shows the new state, so the
  // cached bitmap is patched in place rather than re-rendering the grid —
  // a full re-render here would fight rapid ticking across a row.
  const day = e.target.closest("[data-day-item]");
  if (day) {
    const item = await api(`/api/lookahead/items/${day.dataset.dayItem}/day/${day.dataset.dayIndex}`, {
      method: "POST", body: JSON.stringify({ on: e.target.checked }) });
    const cached = laCache.data.items.find((x) => x.id === day.dataset.dayItem);
    if (cached) cached.days = item.days;
    return;
  }

  const period = e.target.closest("[data-la-period]");
  if (period) {
    await api(`/api/lookahead/${period.dataset.laPeriod}`, {
      method: "PATCH", body: JSON.stringify({ [period.dataset.field]: e.target.value }) });
    laCache.data[period.dataset.field] = e.target.value;
    return;
  }

  const area = e.target.closest("[data-la-area]");
  if (area) {
    const value = area.dataset.field === "active" ? (e.target.checked ? 1 : 0) : e.target.value;
    await api(`/api/lookahead/areas/${area.dataset.laArea}`, {
      method: "PATCH", body: JSON.stringify({ [area.dataset.field]: value }) });
    await loadLookahead(laCache.data.start_date);
    return;
  }

  const i = e.target.closest("[data-la]");
  if (i) {
    // Cleared cells go back as null, not "", so an unset work area really is
    // unset rather than an id that matches nothing.
    const value = e.target.value === "" ? null : e.target.value;
    await api(`/api/lookahead/items/${i.dataset.la}`, {
      method: "PATCH", body: JSON.stringify({ [i.dataset.field]: value }) });
    laCache.data.items.find((x) => x.id === i.dataset.la)[i.dataset.field] = value;
    if (i.dataset.field === "work_area_id") render();   // repaint the colour band
  }
});

main.addEventListener("submit", async (e) => {
  const f = e.target;
  if (f.dataset.areaForm) {
    e.preventDefault();
    await api(`/api/jobs/${encodeURIComponent(f.dataset.areaForm)}/lookahead/areas`, {
      method: "POST", body: JSON.stringify({ name: f.name.value }) });
    f.reset();
    await loadLookahead(laCache.data.start_date);
    return;
  }
  if (!f.dataset.laForm) return;
  e.preventDefault();
  const body = Object.fromEntries([...new FormData(f).entries()].filter(([, v]) => v !== ""));
  body.at_top = true;                       // newest line lands on top of the grid
  await api(`/api/lookahead/${f.dataset.laForm}/items`, {
    method: "POST", body: JSON.stringify(body) });
  f.reset();
  await loadLookahead(laCache.data.start_date);
});

main.addEventListener("click", async (e) => {
  const areasToggle = e.target.closest("[data-la-areas-toggle]");
  if (areasToggle) { laAreasOpen = !laAreasOpen; render(); return; }

  const wk = e.target.closest("[data-la-weeks]");
  if (wk) {
    const n = Number(wk.dataset.laWeeks);
    if (n === (laCache.data.weeks || 2)) return;
    laShareWeeks = null;                       // follow the grid again
    await api(`/api/lookahead/${wk.dataset.period}`, {
      method: "PATCH", body: JSON.stringify({ weeks: n }) });
    await loadLookahead(laCache.data.start_date);
    return;
  }

  const pv = e.target.closest("[data-la-preview]");
  if (pv) {
    const want = pv.dataset.laPreview;
    laPreview = (!want || want === laPreview) ? null : want;   // click again to close
    laPreviewPage = 1;
    render();
    return;
  }
  const pvPage = e.target.closest("[data-la-pv-page]");
  if (pvPage) {
    const next = laPreviewPage + Number(pvPage.dataset.laPvPage);
    if (next < 1 || next > laPreviewPages) return;
    laPreviewPage = next;
    render();
    return;
  }
  const seed = e.target.closest("[data-la-seed]");
  if (seed) {
    laMsg("seeding…");
    const res = await api(`/api/lookahead/${seed.dataset.laSeed}/seed`, { method: "POST" });
    await loadLookahead(laCache.data.start_date);
    laMsg(res.seeded
      ? `${res.seeded} activit${res.seeded === 1 ? "y" : "ies"} added from the schedule`
      : "no new schedule tasks overlap this window");
    return;
  }
  const del = e.target.closest("[data-del-la]");
  if (del) {
    if (!armed(del)) return;
    await api(`/api/lookahead/items/${del.dataset.delLa}`, { method: "DELETE" });
    await loadLookahead(laCache.data.start_date);
    return;
  }
  const delArea = e.target.closest("[data-del-area]");
  if (delArea) {
    if (!armed(delArea)) return;
    await api(`/api/lookahead/areas/${delArea.dataset.delArea}`, { method: "DELETE" });
    await loadLookahead(laCache.data.start_date);
    return;
  }
  const share = e.target.closest("[data-la-share]");
  if (share) {
    const team = share.dataset.audience === "team";
    const held = laCache.data.weeks || 2;
    const send = Math.min(laShareWeeks || held, held);
    try {
      laMsg("building the PDF…");
      const doc = await api(`/api/lookahead/${share.dataset.laShare}/share`
        + `?audience=${share.dataset.audience}&weeks=${send}`);
      await companionFetch("/draft", {
        to: doc.to, subject: doc.subject, html: doc.html,
        attachments: [{ filename: doc.filename, content_b64: doc.pdf_b64 }],
      });
      const span = `${doc.weeks}-week sheet`;
      laMsg(team
        ? `Opened in your Outlook — ${span}, tools and materials included. The To line is blank; add your team and Send.`
        : doc.contacts.length
        ? `Opened in your Outlook — ${span} addressed to ${doc.contacts.map((c) => c.name).join(", ")}, PDF attached. Review and Send.`
        : `Opened in your Outlook — ${span}, PDF attached. No customer contacts on Overview yet, so the To line is blank — add contacts there to have it filled in.`);
    } catch (err) {
      // No companion means no desktop Outlook to draft into — which on a
      // phone isn't a failure, it's the platform. Offer the handoff instead
      // of an error nobody can act on. (D10 has no iOS equivalent: no COM.)
      const emlPath = `/api/lookahead/${share.dataset.laShare}/share.eml`
        + `?audience=${share.dataset.audience}&weeks=${send}`;
      if (noCompanion(err)) {
        await queueForDesk({
          job_number: current.job, kind: "lookahead",
          target_id: share.dataset.laShare,
          audience: share.dataset.audience, weeks: send,
        }, laMsg, `${send}-week sheet`);
        offerEml("#laMsg", emlPath, "Or, if this PC has Outlook:");
      } else {
        // The companion answered and refused (bad pairing, Outlook down).
        // Real error, shown — but the .eml still gets the sheet out today.
        laMsg(`Couldn't draft via the companion: ${err.message}.`);
        offerEml("#laMsg", emlPath, "You can still send it from this PC's Outlook:");
      }
    }
  }
});

/* ---- pages: RFIs / Submittals (Phase 3a) ---------------------------------------------- */

let recCache = null;   // {job, records}
let recDetail = null;  // open record id (current.sub)

const REC_STATUSES = {
  rfi: ["Draft", "Sent", "Answered", "Closed"],
  submittal: ["Draft", "Sent", "Approved", "Approved as Noted", "Revise & Resubmit", "Rejected", "Closed"],
};

function stampClsFor(status) {
  const s = (status || "").toLowerCase();
  if (s.startsWith("approved") || s === "answered") return "ok";
  if (s === "revise & resubmit" || s === "draft") return "warn";
  if (s === "rejected") return "err";
  if (s === "sent") return "info";
  return "neutral";
}

function recordsPage(d) {
  const kind = current.page === "rfis" ? "rfi" : "submittal";
  const label = kind === "rfi" ? "RFI" : "Submittal";

  if (!recCache || recCache.job !== current.job) {
    loadRecords();
    return `<p class="placeholder">Loading…</p>`;
  }
  const list = recCache.records.filter((r) => r.kind === kind);

  if (current.sub) {
    const rec = recCache.records.find((r) => r.id === current.sub);
    if (!rec) return `<div class="error">Record not found.</div>`;
    return recordDetail(d, rec, label);
  }

  return `
    <div class="panel">
      <div class="panel-head"><h3>${label}s</h3>
        <span class="sub">${list.length} on the register</span></div>
      <div class="panel-body flush">
        <form class="inline-form top" data-rec-form="${kind}">
          <input name="number" placeholder="${label} #" style="width:110px" required>
          <input name="title" class="grow" placeholder="Title / subject">
          ${kind === "submittal" ? `<input name="spec_section" placeholder="Spec section" style="width:130px">` : ""}
          <input name="to_name" placeholder="To (name)" style="width:140px">
          <input name="due_date" type="date" style="width:150px">
          <button class="btn primary sm" type="submit">+ ${label}</button>
        </form>
        <table class="tbl" data-sort-key="records-${kind}">
          <thead><tr>
            <th>${label} #</th><th style="width:30%">Title</th><th>Status</th>
            <th>To</th><th>Due</th><th class="num">Pages</th><th class="num">Markups</th><th></th>
          </tr></thead>
          <tbody>
            ${list.map((r) => `<tr class="clickable" data-open-rec="${r.id}">
              <td class="mono">${esc(r.number ?? "—")}</td>
              <td>${esc(r.title ?? "")}</td>
              <td><span class="stamp ${stampClsFor(r.status)}">${esc(r.status)}</span></td>
              <td>${esc(r.to_name ?? "—")}</td>
              <td class="small">${esc(r.due_date ?? "—")}</td>
              <td class="num">${r.attachments.length || ""}</td>
              <td class="num">${r.markup_count || ""}</td>
              <td><button class="link danger" data-del-rec="${r.id}">delete</button></td>
            </tr>`).join("") || `<tr><td colspan="8" class="none">No ${label}s yet.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
    <div class="note">Each ${label} carries its own markup layer. Pages you attach are
    extracted from the library originals and composited with <b>that layer only</b> —
    internal redlines are excluded by construction. AI drafting and the Outlook
    hand-off arrive in Phase 3b.</div>`;
}

/* ---- communication (Phase 3b): draft -> Outlook -> replies ---------------- */

const COMPANION = "http://127.0.0.1:8772";
let companionToken = null;
let recDrafts = {};   // record_id -> draft
let recReplies = {};  // record_id -> replies[]

async function companionFetch(path, body) {
  if (companionToken === null) {
    companionToken = (await api("/api/companion/token")).token;
  }
  const r = await fetch(COMPANION + path, body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, token: companionToken }) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `companion ${r.status}`);
  return data;
}

function communicationPanel(rec, label) {
  const draft = recDrafts[rec.id];
  const replies = recReplies[rec.id] || [];
  return `
    <div class="panel">
      <div class="panel-head"><h3>Communication</h3>
        <span class="sub" id="companionStatus">companion: checking…</span></div>
      <div class="panel-body">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
          <button class="btn sm" data-gen-draft="${rec.id}">${draft ? "Regenerate Draft" : "Draft with AI"}</button>
          ${draft ? `<button class="btn primary sm" data-outlook-draft="${rec.id}"
            title="Creates a draft (with the package attached) in YOUR Outlook — you press Send there">Create Outlook Draft</button>` : ""}
          ${rec.status !== "Draft" ? `<button class="btn sm" data-check-replies="${rec.id}">Check for Replies</button>` : ""}
          <span id="commMsg" class="small muted"></span>
        </div>
        ${draft ? `
        <div class="field" style="margin-bottom:10px"><label>Email Subject
          <span class="src-tag">${esc(draft.source)}</span></label>
          <input data-draft-field="subject" data-draft-rec="${rec.id}" value="${esc(draft.subject || "")}"></div>
        <div class="field"><label>Email Body — review before it goes anywhere</label>
          <textarea data-draft-field="body" data-draft-rec="${rec.id}" rows="8" style="width:100%">${esc(draft.body || "")}</textarea></div>`
        : `<div class="none">No email draft yet. "Draft with AI" writes one from the ${label}'s
           details and markups (falls back to a clean template when AI is unconfigured).</div>`}

        ${replies.length ? `<h2 style="margin-top:18px">Replies</h2>` : ""}
        ${replies.map((rep) => `
        <div class="panel" style="margin-top:8px">
          <div class="panel-head">
            <h3 class="small">${esc(rep.from_name || rep.from_email || "Unknown sender")}
              <span class="muted">· ${esc((rep.received_at || "").slice(0, 16))}</span></h3>
            ${rep.confirmed_at
              ? `<span class="stamp ok">Confirmed · ${esc(rep.confirmed_by || "")}</span>`
              : `<span class="stamp warn">Awaiting PM confirmation</span>`}
          </div>
          <div class="panel-body">
            <div class="small" style="white-space:pre-wrap;max-height:140px;overflow-y:auto;margin-bottom:10px">${esc((rep.body || "").slice(0, 1200))}</div>
            ${rep.attachments.length ? `<div class="small" style="margin-bottom:10px">Returned files:
              ${rep.attachments.map((a) => `
                <a href="/api/replies/${rep.id}/attachments/${a.id}" target="_blank">${esc(a.filename)}</a>${
                  comparable(a.filename) ? `
                  <button class="link" data-compare-reply="${rep.id}" data-compare-att="${a.id}"
                    data-compare-name="${esc(a.filename)}" style="margin-left:6px">${
                      compareView && compareView.attId === a.id ? "hide comparison" : "compare with what we sent"}</button>` : ""}`).join(" · ")}</div>` : ""}
            ${compareView && compareView.replyId === rep.id ? `
            <div class="compare">
              <div class="compare-head">
                <span class="eyebrow">We sent</span>
                <span class="eyebrow">They returned · ${esc(compareView.name)}</span>
              </div>
              <div class="compare-panes">
                <div class="compare-pane"><canvas id="cmpSent"></canvas></div>
                <div class="compare-pane">${compareView.image
                  ? `<img id="cmpBackImg" alt="${esc(compareView.name)}"
                       src="/api/replies/${compareView.replyId}/attachments/${compareView.attId}">`
                  : `<canvas id="cmpBack"></canvas>`}</div>
              </div>
              <div class="compare-nav">
                <button class="btn sm" data-cmp-page="-1">‹ Prev</button>
                <span id="cmpMeta" class="mono muted">page ${compareView.page || 1}</span>
                <button class="btn sm" data-cmp-page="1">Next ›</button>
              </div>
              ${compareView.image ? `<div class="hint small muted" style="padding:0 8px 8px;text-align:center">
                They returned an image, so the pages belong to our package — the picture stays put beside whichever page you're on.</div>` : ""}
            </div>` : ""}
            ${rep.confirmed_at ? "" : `
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
              <span class="eyebrow">AI proposes (${esc(rep.proposal_source)})</span>
              <select data-rep-status="${rep.id}">
                ${REC_STATUSES[rec.kind].map((s) => `<option ${rep.proposed_status === s ? "selected" : ""}>${s}</option>`).join("")}
              </select>
              <button class="btn primary sm" data-confirm-reply="${rep.id}">Confirm &amp; Apply</button>
            </div>
            ${rec.kind === "rfi" ? `<div class="field" style="margin-top:8px"><label>Proposed Answer (editable)</label>
              <textarea data-rep-answer="${rep.id}" rows="3" style="width:100%">${esc(rep.proposed_answer || "")}</textarea></div>` : ""}`}
          </div>
        </div>`).join("")}
      </div>
    </div>`;
}

/* What can sit in the right-hand pane.
   A customer answering an RFI sends back whatever their phone or their markup
   tool produced: a re-marked PDF, a screenshot, a photo of the drawing on a
   tailgate. Only PDFs used to offer the comparison, so an image reply landed
   as a bare link with nothing to check it against — the audit trail silently
   went missing on exactly the reply that most needed looking at. */
const IMAGE_RE = /\.(png|jpe?g|gif|webp|bmp|avif)$/i;
const comparable = (name) => /\.pdf$/i.test(name || "") || IMAGE_RE.test(name || "");
const isImageReply = (name) => IMAGE_RE.test(name || "");

/* Sent-vs-returned. The outbound package and the file they sent back, side by
   side — the visual audit trail for a marked-up RFI. */
async function renderCompare() {
  if (!compareView) return;
  const sent = document.querySelector("#cmpSent");
  if (!sent) return;
  const page = compareView.page || 1;
  const width = Math.max(240, Math.floor((main.clientWidth - 120) / 2));
  const meta = document.querySelector("#cmpMeta");
  try {
    const nSent = await DW.renderPdfPage(
      sent, `/api/records/${current.sub}/package`, page, width);

    if (compareView.image) {
      // An image has no pages, so the navigation belongs to the sent package
      // alone; the returned picture stays put beside whichever page you're on.
      compareView.pages = nSent;
      if (meta) meta.textContent = nSent > 1
        ? `sent page ${page} / ${nSent} · returned image`
        : "returned image";
      return;
    }

    const back = document.querySelector("#cmpBack");
    if (!back) return;
    const nBack = await DW.renderPdfPage(
      back, `/api/replies/${compareView.replyId}/attachments/${compareView.attId}`,
      page, width);
    compareView.pages = Math.max(nSent, nBack);
    if (meta) meta.textContent = `page ${page} / ${compareView.pages}`;
  } catch (err) {
    if (meta) meta.textContent = `could not render: ${err.message}`;
  }
}

main.addEventListener("click", async (e) => {
  const cmp = e.target.closest("[data-compare-reply]");
  if (cmp) {
    compareView = compareView && compareView.attId === cmp.dataset.compareAtt
      ? null
      : { replyId: cmp.dataset.compareReply, attId: cmp.dataset.compareAtt,
          name: cmp.dataset.compareName, page: 1,
          image: isImageReply(cmp.dataset.compareName) };
    return render();
  }
  const nav = e.target.closest("[data-cmp-page]");
  if (nav && compareView) {
    const next = (compareView.page || 1) + Number(nav.dataset.cmpPage);
    if (next < 1 || (compareView.pages && next > compareView.pages)) return;
    compareView.page = next;
    return renderCompare();
  }
});

async function loadCommData(recId) {
  const [draft, replies] = await Promise.all([
    api(`/api/records/${recId}/draft`),
    api(`/api/records/${recId}/replies`),
  ]);
  recDrafts[recId] = draft && draft.record_id ? draft : null;
  recReplies[recId] = replies.replies;
}

/** Auto-detect the actual send: if this Draft record's thread has a message
    in Outlook's Sent Items, flip it to Sent with Outlook's own timestamp.
    The PM never bookkeeps what Outlook already knows. */
async function detectSent(recId) {
  const rec = recCache?.records.find((r) => r.id === recId);
  const draft = recDrafts[recId];
  if (!rec || rec.status !== "Draft" || !draft?.subject) return;
  try {
    const res = await companionFetch("/sent", {
      queries: [{ record_id: recId, subject: draft.subject }] });
    const hit = res.sent.find((s) => s.record_id === recId);
    if (hit) {
      await api(`/api/records/${recId}/sent`, {
        method: "POST", body: JSON.stringify({ sent_at: hit.sent_on }) });
      await loadRecords();
      commMsg(`Send detected in Outlook (${(hit.sent_on || "").slice(0, 16)}) — status is now Sent.`);
    }
  } catch { /* companion offline — detection just waits for next open */ }
}

async function refreshCompanionChip() {
  const el = document.querySelector("#companionStatus");
  if (!el) return;
  try {
    const h = await companionFetch("/health");
    if (!h.paired) {
      el.innerHTML = `companion: running but not connected — open
        <span class="mono">http://127.0.0.1:8772/pair</span> and sign in`;
      return;
    }
    // Pairings are per person now. A companion belonging to someone else will
    // refuse to draft, and saying so here beats a 401 at the moment of send.
    if (h.paired_user && currentUser && h.paired_user !== currentUser) {
      el.textContent = `companion: connected as ${h.paired_user}, not you — `
        + `drafting from this PC would use their mailbox`;
      return;
    }
    if (!h.outlook) { el.textContent = "companion: running, Outlook unreachable"; return; }
    // The live watcher is the story now; the sweep is a footnote. Say which
    // is actually working, because "polling armed" while the watcher is down
    // would read as healthy when detection had quietly gone back to minutes.
    const p = h.poll || {}, w = h.watch || {};
    const live = w.running
      ? ` · watching live${w.last_event ? `, last event ${w.last_event.slice(11, 16)}` : ""}`
      : ` · LIVE WATCH DOWN${w.error ? ` (${w.error})` : ""} — falling back to the sweep`;
    // Say what the backstop is actually watching. "0 threads" alone read as
    // "nothing is being watched" while a drafted record was in fact on the
    // list — the two are counted separately, and hiding one of them made a
    // working sweep look idle.
    const watching = [
      p.threads ? `${p.threads} awaiting reply` : "",
      p.drafts ? `${p.drafts} awaiting send` : "",
    ].filter(Boolean).join(", ") || "nothing open";
    const sweep = p.last_error
      ? ` · sweep error: ${p.last_error}`
      : p.interval_seconds ? ` · backstop every ${p.interval_seconds}s (${watching})` : "";
    el.textContent = `companion: Outlook connected${h.account ? " · " + h.account : ""}${live}${sweep}`;
  } catch {
    el.innerHTML = `companion: not running — start <span class="mono">companion.bat</span> on this PC`;
  }
}

const commMsg = (t) => { const el = document.querySelector("#commMsg"); if (el) el.textContent = t; };

main.addEventListener("click", async (e) => {
  const gen = e.target.closest("[data-gen-draft]");
  if (gen) {
    commMsg("drafting…");
    recDrafts[gen.dataset.genDraft] = await api(`/api/records/${gen.dataset.genDraft}/draft`, { method: "POST" });
    return render();
  }
  const od = e.target.closest("[data-outlook-draft]");
  if (od) {
    const recId = od.dataset.outlookDraft;
    const rec = recCache.records.find((r) => r.id === recId);
    const draft = recDrafts[recId];
    try {
      commMsg("building package…");
      let attachments = [];
      if (rec.attachments.length) {
        const pkg = await fetch(`/api/records/${recId}/package`);
        if (!pkg.ok) throw new Error((await pkg.json()).detail || "package failed");
        const buf = new Uint8Array(await pkg.arrayBuffer());
        let bin = ""; buf.forEach((b) => (bin += String.fromCharCode(b)));
        attachments = [{ filename: `${rec.kind.toUpperCase()}-${rec.number || recId}.pdf`,
                         content_b64: btoa(bin) }];
      }
      commMsg("creating Outlook draft…");
      const res = await companionFetch("/draft", {
        to: rec.to_email || "", subject: draft.subject, body: draft.body, attachments });
      commMsg(res.unresolved?.length
        ? `Opened in your Outlook, but it could not resolve ${res.unresolved.join(", ")} — pick the address before sending.`
        : "Opened in your Outlook — review and press Send there.");
    } catch (err) {
      // Same two-way fallback as the look ahead: no companion on this machine
      // is a platform fact, not a failure — queue for a desk that has one, or
      // take the email file for this PC's own Outlook right now.
      const emlPath = `/api/records/${recId}/share.eml`;
      const what = `${rec.kind.toUpperCase()}${rec.number ? "-" + rec.number : ""}`;
      if (noCompanion(err)) {
        await queueForDesk({ job_number: rec.job_number, kind: "record",
                             target_id: recId }, commMsg, what);
        offerEml("#commMsg", emlPath, "Or, if this PC has Outlook:");
      } else {
        commMsg(`Couldn't draft via the companion: ${err.message}.`);
        offerEml("#commMsg", emlPath, "You can still send it from this PC's Outlook:");
      }
    }
    return;
  }
  const cr = e.target.closest("[data-check-replies]");
  if (cr) {
    const recId = cr.dataset.checkReplies;
    const rec = recCache.records.find((r) => r.id === recId);
    const draft = recDrafts[recId];
    if (!draft?.subject) { commMsg("no draft subject to match the thread by"); return; }
    try {
      commMsg("scanning your inbox…");
      const known = new Set((recReplies[recId] || []).map((r) => `${r.from_email}|${r.received_at}`));
      const res = await companionFetch("/scan", {
        queries: [{ record_id: recId, subject: draft.subject, since: rec.sent_at }] });
      let added = 0;
      for (const rep of res.replies) {
        if (known.has(`${rep.from_email}|${rep.received_at}`)) continue;
        await api(`/api/records/${recId}/replies`, { method: "POST", body: JSON.stringify(rep) });
        added++;
      }
      await loadCommData(recId);
      commMsg(added
        ? `${added} new repl${added === 1 ? "y" : "ies"} captured — review below.`
        : `no new replies on this thread (scanned ${res.scanned ?? 0} messages since it was sent)`);
      render();
    } catch (err) { commMsg(`failed: ${err.message}`); }
    return;
  }
  const conf = e.target.closest("[data-confirm-reply]");
  if (conf) {
    const id = conf.dataset.confirmReply;
    const status = document.querySelector(`[data-rep-status="${id}"]`)?.value;
    const answer = document.querySelector(`[data-rep-answer="${id}"]`)?.value;
    await api(`/api/replies/${id}/confirm`, {
      method: "POST", body: JSON.stringify({ status, answer }) });
    await Promise.all([loadRecords(), loadCommData(current.sub)]);
    return;
  }
});

main.addEventListener("change", async (e) => {
  const el = e.target.closest("[data-draft-rec]");
  if (!el) return;
  const recId = el.dataset.draftRec;
  const d = recDrafts[recId];
  d[el.dataset.draftField] = el.value;
  recDrafts[recId] = await api(`/api/records/${recId}/draft`, {
    method: "PATCH", body: JSON.stringify({ subject: d.subject, body: d.body }) });
});

function recordDetail(d, rec, label) {
  const docs = docsCache?.docs || [];
  const statuses = REC_STATUSES[rec.kind];
  const field = (key, lab, type = "text") => `
    <div class="field"><label>${lab}</label>
    <input data-rec="${rec.id}" data-field="${key}" type="${type}" value="${esc(rec[key] ?? "")}" placeholder="—"></div>`;
  const area = (key, lab) => `
    <div class="field" style="grid-column:1/-1"><label>${lab}</label>
    <textarea data-rec="${rec.id}" data-field="${key}" rows="3" style="width:100%">${esc(rec[key] ?? "")}</textarea></div>`;

  return `
    <div class="dw-head">
      <button class="btn sm" data-rec-back>‹ ${label}s</button>
      <span class="tb-val">${esc(rec.number ?? "(unnumbered)")} · ${esc(rec.title ?? "")}</span>
      <span class="stamp ${stampClsFor(rec.status)}">${esc(rec.status)}</span>
      <span style="flex:1"></span>
      <a class="btn sm" href="/api/records/${rec.id}/package" target="_blank"
         title="The outbound PDF: attached pages + this record's markups only">Download Package</a>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>${label} Details</h3>
        <select data-rec="${rec.id}" data-field="status" style="min-width:170px">
          ${statuses.map((s) => `<option ${rec.status === s ? "selected" : ""}>${s}</option>`).join("")}
        </select></div>
      <div class="panel-body"><div class="form-grid">
        ${field("number", `${label} #`)}
        ${field("title", "Title / Subject")}
        ${rec.kind === "submittal" ? field("spec_section", "Spec Section") : ""}
        ${field("to_name", "To (Name)")}
        ${field("to_email", "To (Email)")}
        ${field("due_date", "Due", "date")}
        ${rec.kind === "rfi" ? area("question", "Question") + area("answer", "Answer (from reply · PM-confirmed)") : ""}
      </div></div>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>Attached Pages</h3>
        <span class="sub">extracted + composited with this ${label}'s layer only</span></div>
      <div class="panel-body flush">
        <form class="inline-form top" data-att-form="${rec.id}">
          <select name="document_id" required>
            <option value="">Document…</option>
            ${docs.map((doc) => `<option value="${doc.id}">${esc(doc.name)} (${doc.page_count}p)</option>`).join("")}
          </select>
          <input name="page" type="number" min="1" placeholder="Page #" style="width:90px" required>
          <button class="btn primary sm" type="submit">Attach Page</button>
          ${docs.length ? "" : `<span class="none">Upload documents on the Drawings tab first.</span>`}
        </form>
        <table class="tbl" data-sort-key="attachments">
          <thead><tr><th>Document</th><th class="num">Page</th><th>Added</th><th></th><th></th></tr></thead>
          <tbody>
          ${rec.attachments.map((a) => `<tr class="${recMarkup && recMarkup.attId === a.id ? "row-active" : ""}">
            <td>${esc(a.document_name)}</td>
            <td class="num">${a.page} / ${a.page_count}</td>
            <td class="small muted">${esc((a.added_at || "").slice(0, 10))} · ${esc(a.added_by ?? "—")}</td>
            <td><button class="link" data-markup-att="${a.id}" data-doc="${a.document_id}" data-page="${a.page}">${
              recMarkup && recMarkup.attId === a.id ? "close markup" : "open &amp; mark up"}</button></td>
            <td><button class="link danger" data-del-att="${a.id}">remove</button></td>
          </tr>`).join("") || `<tr><td colspan="5" class="none">No pages attached yet.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>

    ${recMarkup ? markupPanel(rec, label) : ""}
    ${communicationPanel(rec, label)}`;
}

/* Markup opens INLINE on the record, not by navigating to the Drawings tab —
   bouncing to another tab and back through a breadcrumb was not a navigation
   anyone would guess. Same tool, same layer model, rendered in place. */
function markupPanel(rec, label) {
  return `
    <div class="panel dw-workspace">
      <div class="panel-head">
        <h3>Markup · ${esc(recMarkup.docName)} <span class="muted" style="font-weight:400">page ${recMarkup.page}</span></h3>
        <button class="btn sm" data-close-markup>Close markup</button>
      </div>
      <div class="panel-body">
        ${DW.toolbarHTML(`${label} ${rec.number || ""} layer`)}
        <div id="dwCanvasHolder" class="dw-holder">
          <canvas id="dwPdf"></canvas>
          <canvas id="dwInk"></canvas>
        </div>
        <div class="note">These markups belong to this ${label} alone and are what goes out
        in its package. Internal redlines are not shown here and are never sent.</div>
      </div>
    </div>`;
}

async function loadRecords() {
  const { records } = await api(`/api/jobs/${encodeURIComponent(current.job)}/records`);
  recCache = { job: current.job, records };
  if (current.page === "rfis" || current.page === "submittals") render();
}

function afterRecordsRender() {
  if (!current.sub) { recMarkup = null; compareView = null; return; }
  // detail view needs the doc list for the attach form
  if (!docsCache || docsCache.job !== current.job) loadDocs().then(render);
  // communication data loads lazily on first open of a record
  if (!(current.sub in recDrafts)) {
    loadCommData(current.sub).then(() => { render(); detectSent(current.sub); });
  } else {
    detectSent(current.sub);
  }
  if (recMarkup) {
    const ws = main.querySelector(".dw-workspace");
    if (ws) {
      DW.attach(ws);
      DW.open(recMarkup.docId, api, { layer: recMarkup.layer, page: recMarkup.page })
        .catch((e) => { const h = main.querySelector(".dw-holder");
                        if (h) h.innerHTML = `<div class="error">${esc(e.message)}</div>`; });
    }
  }
  if (compareView) renderCompare();
  refreshCompanionChip();
}

let recMarkup = null;    // {attId, docId, docName, page, layer} — inline markup
let compareView = null;  // {replyId, attId, name} — sent-vs-returned

main.addEventListener("click", async (e) => {
  if (e.target.closest("[data-rec-back]")) {
    location.hash = `/job/${encodeURIComponent(current.job)}/${current.page}`;
    return;
  }
  const open = e.target.closest("[data-open-rec]");
  if (open && !e.target.closest("button")) {
    location.hash = `/job/${encodeURIComponent(current.job)}/${current.page}/${open.dataset.openRec}`;
    return;
  }
  const delRec = e.target.closest("[data-del-rec]");
  if (delRec) {
    if (!armed(delRec)) return;
    await api(`/api/records/${delRec.dataset.delRec}`, { method: "DELETE" });
    return loadRecords();
  }
  const delAtt = e.target.closest("[data-del-att]");
  if (delAtt) {
    if (!armed(delAtt)) return;
    await api(`/api/records/${current.sub}/attachments/${delAtt.dataset.delAtt}`, { method: "DELETE" });
    return loadRecords();
  }
  if (e.target.closest("[data-close-markup]")) { recMarkup = null; return render(); }
  const mark = e.target.closest("[data-markup-att]");
  if (mark) {
    if (recMarkup && recMarkup.attId === mark.dataset.markupAtt) { recMarkup = null; return render(); }
    const rec = recCache.records.find((r) => r.id === current.sub);
    const att = rec.attachments.find((a) => a.id === mark.dataset.markupAtt);
    recMarkup = {
      attId: mark.dataset.markupAtt,
      docId: mark.dataset.doc,
      docName: att?.document_name || "Document",
      page: +mark.dataset.page,
      layer: `${rec.kind}:${rec.id}`,
    };
    render();
    main.querySelector(".dw-workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

main.addEventListener("submit", async (e) => {
  const f = e.target;
  if (f.dataset.recForm) {
    e.preventDefault();
    const body = Object.fromEntries([...new FormData(f).entries()].filter(([, v]) => v !== ""));
    await api(`/api/jobs/${encodeURIComponent(current.job)}/records`, {
      method: "POST", body: JSON.stringify({ ...body, kind: f.dataset.recForm }),
    });
    return loadRecords();
  }
  if (f.dataset.attForm) {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(f).entries());
    await api(`/api/records/${f.dataset.attForm}/attachments`, {
      method: "POST", body: JSON.stringify(body),
    });
    return loadRecords();
  }
});

main.addEventListener("change", async (e) => {
  const el = e.target.closest("[data-rec]");
  if (!el) return;
  await api(`/api/records/${el.dataset.rec}`, {
    method: "PATCH", body: JSON.stringify({ [el.dataset.field]: e.target.value }),
  });
  const { records: recs } = await api(`/api/jobs/${encodeURIComponent(current.job)}/records`);
  recCache = { job: current.job, records: recs };
  if (el.dataset.field === "status") render(); // stamp needs repaint
});

/* ---- mutations ------------------------------------------------------------------------ */

const jobApi = (path, opts) =>
  api(`/api/jobs/${encodeURIComponent(current.job)}${path}`, opts);

main.addEventListener("submit", async (e) => {
  const f = e.target;
  e.preventDefault();
  const body = Object.fromEntries([...new FormData(f).entries()].filter(([, v]) => v !== ""));
  if (f.id === "addPO") {
    await jobApi("/pos", { method: "POST", body: JSON.stringify(body) });
  } else if (f.dataset.coForm) {
    await jobApi("/cos", { method: "POST", body: JSON.stringify({ ...body, kind: f.dataset.coForm }) });
  } else if (f.dataset.invForm) {
    await jobApi(`/pos/${f.dataset.invForm}/invoices`, { method: "POST", body: JSON.stringify(body) });
    invoiceFormPo = null;
  } else {
    return;
  }
  await refreshJob();
});

/* money cells: raw number while editing, currency at rest */
main.addEventListener("focusin", (e) => {
  const el = e.target;
  if (el.matches?.("[data-money]")) {
    const n = parseMoney(el.value);
    el.value = n === null ? "" : String(n);
    el.select?.();
  }
});
main.addEventListener("focusout", (e) => {
  const el = e.target;
  if (el.matches?.("[data-money]")) {
    const n = parseMoney(el.value);
    el.value = n === null ? "" : money(n);
  }
});

main.addEventListener("change", async (e) => {
  const value = e.target.dataset.money !== undefined ? parseMoney(e.target.value) : e.target.value;
  const po = e.target.closest("[data-po]");
  if (po) {
    await jobApi(`/pos/${po.dataset.po}`, {
      method: "PATCH", body: JSON.stringify({ [po.dataset.field]: value }),
    });
    await refreshJob();
    return;
  }
  const co = e.target.closest("[data-co]");
  if (co) {
    await jobApi(`/cos/${co.dataset.co}`, {
      method: "PATCH", body: JSON.stringify({ [co.dataset.field]: value }),
    });
    current.data = await api(`/api/jobs/${encodeURIComponent(current.job)}`); // totals move; no rerender to keep focus
  }
});

/** Two-step inline delete — first click arms ("sure?"), second within 2.6s
    fires. Native confirm()/prompt() are suppressed in embedded panes, which
    read as "the button does nothing". */
function armed(btn) {
  if (btn.dataset.armed) { btn.dataset.armed = ""; return true; }
  btn.dataset.armed = "1";
  const label = btn.textContent;
  btn.textContent = "sure?";
  setTimeout(() => {
    if (btn.isConnected && btn.dataset.armed) { btn.dataset.armed = ""; btn.textContent = label; }
  }, 2600);
  return false;
}

main.addEventListener("click", async (e) => {
  const delPo = e.target.closest("[data-del-po]");
  if (delPo) {
    if (!armed(delPo)) return;
    await jobApi(`/pos/${delPo.dataset.delPo}`, { method: "DELETE" });
    return refreshJob();
  }
  const delCo = e.target.closest("[data-del-co]");
  if (delCo) {
    if (!armed(delCo)) return;
    await jobApi(`/cos/${delCo.dataset.delCo}`, { method: "DELETE" });
    return refreshJob();
  }
  const delInv = e.target.closest("[data-del-inv]");
  if (delInv) {
    if (!armed(delInv)) return;
    await jobApi(`/pos/${delInv.dataset.ofPo}/invoices/${delInv.dataset.delInv}`, { method: "DELETE" });
    return refreshJob();
  }
  const addInv = e.target.closest("[data-inv-po]");
  if (addInv) {
    invoiceFormPo = invoiceFormPo === addInv.dataset.invPo ? null : addInv.dataset.invPo;
    return render();
  }
  if (e.target.closest("[data-cancel-inv]")) {
    invoiceFormPo = null;
    return render();
  }
  const addContact = e.target.closest("[data-add-contact]");
  if (addContact) {
    const contacts = current.data.meta.contacts || [];
    contacts.push({ name: "", role: "", phone: "", email: "" });
    await saveContacts(contacts);
    return render();
  }
  const delContact = e.target.closest("[data-del-contact]");
  if (delContact) {
    if (!armed(delContact)) return;
    const contacts = current.data.meta.contacts || [];
    contacts.splice(+delContact.dataset.delContact, 1);
    await saveContacts(contacts);
    return render();
  }
});

/* Coming back from Outlook (alt-tab) re-checks the open record's send state —
   the natural moment right after the PM pressed Send. */
window.addEventListener("focus", () => {
  if (current.sub && (current.page === "rfis" || current.page === "submittals")) {
    detectSent(current.sub);
  }
  // Coming back to the tab re-reads the look ahead, for the same reason
  // route() does: someone else may have been editing it meanwhile.
  if (current.page === "lookahead" && laCache) loadLookahead(laCache.data.start_date);
});

/* ---- settings dialog (AI, spend, companion pairing) ------------------------------------ */

const settingsDlg = $("#settingsDlg");

$("#settingsBtn").addEventListener("click", () => openSettings());

async function openSettings(focus) {
  settingsDlg.classList.remove("hidden");
  const { settings, spend } = await api("/api/settings");
  const f = (key, label, type = "text", placeholder = "") => `
    <div class="field" style="margin-bottom:10px"><label>${label}</label>
    <input data-setting="${key}" type="${type}" value="${esc(settings[key] || "")}" placeholder="${placeholder}"></div>`;
  $("#settingsBody").innerHTML = `
    <div class="dialog-body">
    <div class="field" style="margin-bottom:10px"><label>AI Provider</label>
      <select data-setting="ai_provider">
        <option value="anthropic" ${settings.ai_provider === "anthropic" ? "selected" : ""}>Anthropic</option>
        <option value="openai" ${settings.ai_provider === "openai" ? "selected" : ""}>OpenAI</option>
      </select></div>
    ${f("ai_model_anthropic", "Anthropic model")}
    ${f("ai_model_openai", "OpenAI model")}
    ${f("anthropic_api_key", "Anthropic API key (company)", "text", "sk-ant-…")}
    ${f("openai_api_key", "OpenAI API key (company)", "text", "sk-…")}
    ${f("ai_spend_cap_monthly", "Monthly AI spend cap (USD, whole team)", "number")}
    <div class="field" style="margin-bottom:10px"><label>Background reply polling</label>
      <select data-setting="reply_poll_enabled">
        <option value="1" ${settings.reply_poll_enabled === "1" ? "selected" : ""}>On — each companion checks its own inbox</option>
        <option value="0" ${settings.reply_poll_enabled !== "1" ? "selected" : ""}>Off — manual "Check for Replies" only</option>
      </select>
      <div class="hint small muted">Replies and sends are detected <b>live</b>, within a second,
        by watching Outlook directly. This sweep is only a safety net for what events miss —
        a batch arriving all at once, or time when the companion wasn't running.</div></div>
    ${f("reply_poll_seconds", "Backstop sweep every (seconds)", "number")}
    <div class="note" style="margin-bottom:10px">
      This month: ~$${(spend.spent_est || 0).toFixed(2)} of $${(spend.cap || 0).toFixed(2)} (estimates).
      At the cap, drafting falls back to templates — nothing breaks.</div>
    <div class="field" style="margin-bottom:12px"><label>Outlook companion</label>
      <div class="hint small muted">Mail is drafted in <b>your own</b> Outlook, on the PC in
        front of you — so the companion installs per person. It pairs by signing in with
        your PlanWise email and password; there is no token to copy. Without one, sharing
        still works: PlanWise hands you an email file that opens in Outlook as a draft.</div></div>
    <div id="usersPane"></div>
    <div class="field" style="margin-bottom:12px"><label>Notifications on this device</label>
      <div class="inline-form" style="border:none;background:none;padding:0;gap:8px">
        <span class="grow small" id="pushState">checking…</span>
        <button class="btn sm" data-push-toggle>…</button>
        <button class="btn sm" data-push-test>Send test</button>
      </div>
      <div class="hint small muted">Tells you when an RFI or submittal gets a reply.
        Each device subscribes separately.</div></div>
    <div class="field" style="margin-bottom:12px"><label>Your account</label>
      <div class="inline-form" style="border:none;background:none;padding:0;gap:8px">
        <span class="grow small">Signed in as <b>${esc(currentUser || "—")}</b></span>
        <button class="btn sm" data-change-password>Change password</button>
        <button class="btn sm" data-sign-out>Sign out</button>
      </div>
      <div id="pwPane"></div></div>
    <div id="activityPane"></div>
    </div>
    <div class="dialog-actions">
      <button class="btn sm" data-show-activity style="margin-right:auto">Activity Log</button>
      <button class="btn" data-close-settings>Close</button>
      <button class="btn primary" data-save-settings>Save</button>
    </div>`;
  refreshPushUI();
  if ($("#userChip").dataset.admin) {
    await refreshUsers();
    if (focus === "users") $("#usersPane")?.scrollIntoView({ block: "start" });
  }
}

/* ---- Settings -> Users (administrators only) --------------------------------------------
   Registration is self-service, so this is where a request becomes access.
   Pending sits at the top and leads with the EMAIL: with no server-side mail
   there is nothing verifying the address, which makes this screen itself the
   verification step. Approving a stranger you don't recognise is the failure
   mode to design against, so the address is the biggest thing on the row. */

async function refreshUsers() {
  const pane = $("#usersPane");
  if (!pane) return;
  let users;
  try { users = (await api("/api/users")).users || []; }
  catch { pane.innerHTML = ""; return; }           // not an admin: show nothing

  const pending = users.filter((u) => u.pending);
  const active = users.filter((u) => !u.pending);
  const me = (currentUser || "").toLowerCase();

  const row = (u) => {
    const isMe = u.name.toLowerCase() === me;
    const acts = [];
    if (u.pending) {
      acts.push(`<button class="link" data-user-approve="${esc(u.name)}">Approve</button>`);
      acts.push(`<button class="link" data-user-delete="${esc(u.name)}">Deny</button>`);
    } else {
      if (!isMe) {
        acts.push(`<button class="link" data-user-disable="${esc(u.name)}"
          data-to="${u.disabled ? "0" : "1"}">${u.disabled ? "Enable" : "Disable"}</button>`);
        acts.push(`<button class="link" data-user-admin="${esc(u.name)}"
          data-to="${u.is_admin ? "0" : "1"}">${u.is_admin ? "Remove admin" : "Make admin"}</button>`);
      }
      acts.push(`<button class="link" data-user-email="${esc(u.name)}">${u.email ? "Change email" : "Add email"}</button>`);
      acts.push(`<button class="link" data-user-password="${esc(u.name)}">Reset password</button>`);
      if (!isMe) acts.push(`<button class="link" data-user-delete="${esc(u.name)}">Remove</button>`);
    }
    return `<div class="urow">
      <div class="uwho">
        <div class="uname">${esc(u.name)}
          ${u.is_admin ? '<span class="tag">admin</span>' : ""}
          ${u.disabled ? '<span class="tag">disabled</span>' : ""}
          ${isMe ? '<span class="tag">you</span>' : ""}</div>
        <div class="umail">${esc(u.email || "no email on this account")}</div>
      </div>
      <div class="uacts">${acts.join("")}</div>
    </div>`;
  };

  pane.innerHTML = `
    <div class="field" style="margin-bottom:12px"><label>Users</label>
      ${pending.length ? `<div class="upending">
        <div class="small" style="margin-bottom:4px"><b>${pending.length} waiting for approval.</b>
          Check the email address — it's the only thing identifying them.</div>
        ${pending.map(row).join("")}
      </div>` : ""}
      ${active.map(row).join("")}
      <div id="userMsg" class="hint small muted" style="margin-top:6px"></div>
    </div>`;
}

const userMsg = (t) => { const el = $("#userMsg"); if (el) el.textContent = t; };

settingsDlg.addEventListener("click", async (e) => {
  const hit = (attr) => e.target.closest(`[data-user-${attr}]`);
  const run = async (fn, done) => {
    try { await fn(); await refreshUsers(); userMsg(done); }
    catch (err) { userMsg(err.message); }
  };

  const ap = hit("approve");
  if (ap) return run(
    () => api(`/api/users/${encodeURIComponent(ap.dataset.userApprove)}/approved`, { method: "POST" }),
    `${ap.dataset.userApprove} is in — their screen lets them through within a few seconds.`);

  const del = hit("delete");
  if (del) {
    const name = del.dataset.userDelete;
    if (!confirm(`Remove ${name}? Their sign-in stops working immediately and anything `
      + `they queued but never sent is discarded. Work they did stays in the record.`)) return;
    return run(() => api(`/api/users/${encodeURIComponent(name)}`, { method: "DELETE" }),
               `${name} removed.`);
  }

  const dis = hit("disable");
  if (dis) return run(
    () => api(`/api/users/${encodeURIComponent(dis.dataset.userDisable)}/disabled`,
              { method: "POST", body: JSON.stringify({ disabled: dis.dataset.to === "1" }) }),
    dis.dataset.to === "1" ? "Disabled — their sessions are gone too." : "Enabled.");

  const adm = hit("admin");
  if (adm) return run(
    () => api(`/api/users/${encodeURIComponent(adm.dataset.userAdmin)}/admin`,
              { method: "POST", body: JSON.stringify({ is_admin: adm.dataset.to === "1" }) }),
    adm.dataset.to === "1" ? "They can now approve people too." : "Admin removed.");

  const mail = hit("email");
  if (mail) {
    const name = mail.dataset.userEmail;
    const email = prompt(`Email address for ${name} — this is what they sign in with:`);
    if (!email) return;
    return run(() => api(`/api/users/${encodeURIComponent(name)}/email`,
                         { method: "POST", body: JSON.stringify({ email }) }),
               `${name} now signs in with ${email}.`);
  }

  const pw = hit("password");
  if (pw) {
    const name = pw.dataset.userPassword;
    const password = prompt(`Temporary password for ${name} (at least 8 characters). `
      + `They'll be made to change it on their next sign-in:`);
    if (!password) return;
    return run(() => api(`/api/users/${encodeURIComponent(name)}/password`,
                         { method: "POST", body: JSON.stringify({ password }) }),
               `Done — give ${name} that password; they'll replace it themselves.`);
  }
});

/* Notification controls under Settings. Per device, because a subscription
   belongs to one browser install — being signed in on your phone says nothing
   about whether your phone has agreed to buzz. */
async function refreshPushUI() {
  const label = $("#pushState"), toggle = $("[data-push-toggle]"), test = $("[data-push-test]");
  if (!label) return;
  const s = await pushState();
  if (!s.supported) {
    label.textContent = s.reason;
    toggle.classList.add("hidden");
    test.classList.add("hidden");
    return;
  }
  toggle.classList.remove("hidden");
  label.textContent = s.subscribed ? "On for this device"
    : s.permission === "denied" ? "Blocked in your browser settings"
    : "Off for this device";
  toggle.textContent = s.subscribed ? "Turn off" : "Turn on";
  toggle.dataset.pushToggle = s.subscribed ? "off" : "on";
  test.classList.toggle("hidden", !s.subscribed);
}

settingsDlg.addEventListener("click", async (e) => {
  const toggle = e.target.closest("[data-push-toggle]");
  const test = e.target.closest("[data-push-test]");
  if (!toggle && !test) return;
  const label = $("#pushState");
  try {
    if (test) {
      const r = await api("/api/push/test", { method: "POST" });
      label.textContent = r.sent ? `Sent to ${r.sent} device(s) — watch for it.`
                                 : "Nothing sent; this device isn't subscribed.";
      return;
    }
    label.textContent = "working…";
    if (toggle.dataset.pushToggle === "on") await enablePush();
    else await disablePush();
    await refreshPushUI();
  } catch (err) { label.textContent = err.message; }
});

/* Account controls under Settings: sign out, and change your own password. */
settingsDlg.addEventListener("click", async (e) => {
  if (e.target.closest("[data-sign-out]")) {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    location.reload();
    return;
  }
  if (!e.target.closest("[data-change-password]")) return;
  $("#pwPane").innerHTML = `
    <form id="pwForm" class="inline-form" style="margin-top:8px;gap:8px;flex-wrap:wrap">
      <input name="current" type="password" placeholder="Current password" required
             autocomplete="current-password" style="width:150px">
      <input name="new" type="password" placeholder="New password (8+)" required minlength="8"
             autocomplete="new-password" style="width:150px">
      <button class="btn primary sm" type="submit">Update</button>
      <span class="small muted" id="pwMsg"></span>
    </form>`;
});

settingsDlg.addEventListener("submit", async (e) => {
  const f = e.target.closest("#pwForm");
  if (!f) return;
  e.preventDefault();
  const msg = $("#pwMsg");
  try {
    await api("/api/auth/password", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(f).entries())) });
    // Every other device signed out; this one got a fresh cookie back.
    $("#pwPane").innerHTML = `<div class="small" style="margin-top:8px">
      Password changed. Any other device you were signed in on has been signed out.</div>`;
  } catch (err) { msg.textContent = err.message; }
});

/* Activity log lives under Settings (walkthrough verdict: keep the tracking,
   demote the page). Job-scoped when a job is open, global otherwise. */
settingsDlg.addEventListener("click", async (e) => {
  if (!e.target.closest("[data-show-activity]")) return;
  const pane = $("#activityPane");
  if (pane.dataset.open) { pane.dataset.open = ""; pane.innerHTML = ""; return; }
  pane.dataset.open = "1";
  pane.innerHTML = `<div class="muted small" style="margin-top:12px">Loading…</div>`;
  const { activity } = current.job
    ? await api(`/api/jobs/${encodeURIComponent(current.job)}/activity?limit=100`)
    : await api("/api/activity?limit=100");
  pane.innerHTML = `
    <h2 style="margin:16px 0 6px;font-size:14px">Activity
      <span class="muted" style="font-weight:400">${current.job ? `· job ${esc(current.job)}` : "· all jobs"}</span></h2>
    <div style="max-height:300px;overflow-y:auto;border:1px solid var(--line);border-radius:var(--radius)">
      <table class="tbl"><tbody>
        ${activity.map((a) => `<tr>
          <td class="mono small" style="white-space:nowrap">${esc((a.ts || "").slice(0, 16).replace("T", " "))}</td>
          <td class="small">${esc(a.actor || "—")}</td>
          <td class="small"><span class="badge">${esc(a.action)}</span></td>
          <td class="small muted">${esc(a.detail || "")}</td>
        </tr>`).join("") || `<tr><td class="none">Nothing recorded yet.</td></tr>`}
      </tbody></table>
    </div>`;
});

settingsDlg.addEventListener("click", async (e) => {
  if (e.target === settingsDlg || e.target.closest("[data-close-settings]")) {
    settingsDlg.classList.add("hidden");
    return;
  }
  if (e.target.closest("[data-save-settings]")) {
    const fields = {};
    settingsDlg.querySelectorAll("[data-setting]").forEach((el) => {
      fields[el.dataset.setting] = el.value;
    });
    await api("/api/settings", { method: "PATCH", body: JSON.stringify(fields) });
    settingsDlg.classList.add("hidden");
  }
});

/* ---- mobile -> desk handoff for Outlook (Phase 5g) --------------------------------------
   D10 puts mail through each person's own DESKTOP Outlook over COM, which is
   what avoids Graph, tenant approval and stored credentials entirely. iOS has
   no COM and no equivalent, so "draft this into my Outlook" simply cannot be
   satisfied from a phone.

   So the send is prepared in the field and drafted at a desk. It still leaves
   from the account of the person who asked for it — only the moment moves. */

/** A companion that isn't there fails at the network layer, which reads very
    differently from a companion that answered and refused. Only the former is
    the handoff case; the latter is a real error worth showing. */
function noCompanion(err) {
  const m = (err && err.message) || "";
  return /failed to fetch|networkerror|load failed|connection refused/i.test(m);
}

/** Fetch a server-built .eml and hand it to the browser as a download.
    The file opens in this PC's own Outlook as an editable draft (X-Unsent) —
    the share path for machines with no companion installed. Plain fetch, not
    api(): the response is binary, and the session cookie rides along. */
async function downloadEml(path, say) {
  try {
    const r = await fetch(path);
    if (!r.ok) {
      let detail = `HTTP ${r.status}`;
      try { detail = (await r.json()).detail || detail; } catch { /* not JSON */ }
      throw new Error(detail);
    }
    const blob = await r.blob();
    const cd = r.headers.get("content-disposition") || "";
    const name = (cd.match(/filename="([^"]+)"/) || [])[1] || "planwise-share.eml";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    return true;
  } catch (err) {
    if (say) say(`couldn't build the email file: ${err.message}`);
    return false;
  }
}

/** Append the .eml escape hatch to a message bar (which was just written with
    textContent, so a real button node is added rather than markup). */
function offerEml(sel, path, lead) {
  const el = document.querySelector(sel);
  if (!el) return;
  const btn = document.createElement("button");
  btn.className = "link";
  btn.textContent = "Download email (.eml)";
  btn.addEventListener("click", async () => {
    const ok = await downloadEml(path, (t) => { el.textContent = t; });
    if (ok) el.textContent = "Downloaded — double-click the file and it opens in Outlook as a draft. Review and Send.";
  });
  el.append(` ${lead || "Or:"} `, btn);
}

async function queueForDesk(item, say, what) {
  try {
    await api("/api/outbox", { method: "POST", body: JSON.stringify(item) });
    say(`No Outlook on this device — the ${what} is queued. Open PlanWise at your `
      + `desk and it'll offer to draft it into your Outlook.`);
    refreshOutbox();
  } catch (err) { say(`couldn't queue it: ${err.message}`); }
}

let outboxItems = [];

async function refreshOutbox() {
  if (!currentUser) return;
  try { outboxItems = (await api("/api/outbox")).items || []; }
  catch { outboxItems = []; }
  paintOutbox();
}

function paintOutbox() {
  const bar = $("#outbox");
  if (!bar) return;
  if (!outboxItems.length) { bar.classList.add("hidden"); bar.innerHTML = ""; return; }
  const n = outboxItems.length;
  bar.innerHTML = `<b>${n}</b> item${n === 1 ? "" : "s"} prepared in the field, waiting to be
    drafted into your Outlook: ${outboxItems.map((i) => esc(i.label || i.kind)).join(", ")}.
    <button class="link" data-draft-outbox>Draft ${n === 1 ? "it" : "them"} now</button>
    <button class="link" data-dismiss-outbox>not now</button>`;
  bar.classList.remove("hidden");
}

document.addEventListener("click", async (e) => {
  if (e.target.closest("[data-dismiss-outbox]")) {
    $("#outbox").classList.add("hidden");
    return;
  }
  if (!e.target.closest("[data-draft-outbox]")) return;

  const bar = $("#outbox");
  let drafted = 0;
  for (const item of [...outboxItems]) {
    try {
      // Rendered now, not when it was queued, so what goes out reflects the
      // current sheet rather than a snapshot from the van.
      const doc = await api(`/api/outbox/${item.id}/document`);
      // display:false — a window per queued item would be obnoxious. The
      // Drafts folder is brought to the front once, at the end, instead.
      // Records draft as plain text (body); look aheads as html — the
      // companion branches on whichever is present.
      await companionFetch("/draft", {
        display: false,
        to: doc.to, subject: doc.subject, html: doc.html, body: doc.body,
        attachments: doc.pdf_b64
          ? [{ filename: doc.filename, content_b64: doc.pdf_b64 }] : [],
      });
      await api(`/api/outbox/${item.id}/drafted`, { method: "POST" });
      drafted += 1;
    } catch (err) {
      // Refresh FIRST: paintOutbox() rewrites this bar, so setting the
      // message before it would silently repaint the failure away.
      await refreshOutbox();
      bar.innerHTML = noCompanion(err)
        ? `<b>Still no Outlook companion here.</b> These keep until you're at a machine
           running one — or take them as email files for this PC's own Outlook: `
        : `<b>Couldn't draft that one:</b> ${esc(err.message)}`;
      if (noCompanion(err) && outboxItems.length) {
        const dl = document.createElement("button");
        dl.className = "link";
        dl.textContent = `Download email file${outboxItems.length === 1 ? "" : "s"}`;
        dl.addEventListener("click", async () => {
          let got = 0;
          for (const it of [...outboxItems]) {
            // Download first, mark drafted after — the claim is repeatable,
            // the mark is the one-shot, so a failed download costs nothing.
            if (await downloadEml(`/api/outbox/${it.id}/eml`)) {
              await api(`/api/outbox/${it.id}/drafted`, { method: "POST" }).catch(() => {});
              got += 1;
            }
          }
          await refreshOutbox();
          bar.innerHTML = got
            ? `<b>${got} email file${got === 1 ? "" : "s"} downloaded.</b> Double-click each —
               it opens in Outlook as a draft. Review and Send.`
            : `<b>Couldn't build the email files.</b> They're still queued.`;
          bar.classList.remove("hidden");
        });
        bar.appendChild(dl);
      }
      bar.classList.remove("hidden");
      return;
    }
  }
  await refreshOutbox();
  if (drafted && !outboxItems.length) {
    // Outlook's Explorer doesn't repaint for items written by an external
    // MAPI session, so bring the folder forward rather than leaving them
    // apparently missing.
    await companionFetch("/show-drafts", {}).catch(() => {});
    bar.innerHTML = `<b>${drafted} draft${drafted === 1 ? "" : "s"} created in your Outlook.</b>
      Your Drafts folder is open — review and Send from there.`;
    bar.classList.remove("hidden");
    setTimeout(() => bar.classList.add("hidden"), 10000);
  }
});

/* ---- offline status bar (Phase 5f) ------------------------------------------------------
   The rule is honesty, not reassurance: say plainly when what's on screen was
   taken from cache and when it was taken, and say how many changes are still
   waiting to go out. Silence would be the failure mode — a stale number that
   looks live is the exact bug this app was rebuilt to stop telling (D2). */

function netbarHTML(s) {
  const bits = [];
  if (!s.online) bits.push(`<b>Offline.</b>`);
  if (s.servedFrom) {
    const t = new Date(s.servedFrom);
    const mins = Math.round((Date.now() - t) / 60000);
    const when = mins < 1 ? "moments ago"
      : mins < 60 ? `${mins} min ago`
      : t.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    bits.push(`Showing data saved <b>${when}</b> — not live.`);
  }
  if (s.pending) {
    bits.push(`<b>${s.pending}</b> change${s.pending === 1 ? "" : "s"} waiting to sync`
      + (s.online ? ` <button class="link" data-sync-now>sync now</button>` : ""));
  }
  return bits.join(" ");
}

function paintNetbar(s) {
  const bar = $("#netbar");
  if (!bar) return;
  const html = netbarHTML(s);
  bar.innerHTML = html;
  bar.classList.toggle("hidden", !html);
  bar.classList.toggle("warn", !s.online || !!s.servedFrom);
}

OFFLINE.subscribe(paintNetbar);

OFFLINE.onFlush(({ sent, rejected }) => {
  if (rejected.length) {
    // A change the server refused can never succeed on retry, so it is
    // reported rather than left to block the queue forever.
    const first = rejected[0];
    alertBanner(`${rejected.length} offline change${rejected.length === 1 ? " was" : "s were"} `
      + `rejected on sync (${first.status}: ${first.detail}). They have been discarded.`);
  }
  // Pull the server's version back down. route() is not enough: it only
  // refetches when the job changed, so staying on the same page after a sync
  // would leave the stale copy — and its "not live" banner — on screen.
  if (sent && current.job) {
    laCache = docsCache = recCache = null;
    refreshJob().catch(() => {});
  }
});

function alertBanner(text) {
  const bar = $("#netbar");
  if (!bar) return;
  bar.innerHTML = `<b>${esc(text)}</b>`;
  bar.classList.remove("hidden");
  bar.classList.add("err");
  setTimeout(() => { bar.classList.remove("err"); paintNetbar(OFFLINE.state()); }, 12000);
}

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-sync-now]")) OFFLINE.flush();
});

/* ---- installable app + notifications (Phase 5e) ---------------------------------------- */

/* The worker holds the app shell so PlanWise opens with no signal, and
   receives pushes so a reply reaches a phone in the field. Registration is
   deliberately fire-and-forget: a browser without service workers (or a page
   served over plain http from a LAN IP) should lose the extras, not the app. */
async function registerWorker() {
  if (!("serviceWorker" in navigator)) return null;
  try { return await navigator.serviceWorker.register("/sw.js", { scope: "/" }); }
  catch (err) { console.warn("service worker not registered:", err.message); return null; }
}

const b64ToBytes = (b64) => {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
};

/** Where notifications stand for THIS device: the browser's permission and
    whether this particular install is subscribed are different questions. */
async function pushState() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return { supported: false, reason: "This browser can't do notifications." };
  }
  // iOS only offers Web Push to a home-screen install. Saying so is far
  // better than a permission prompt that never appears.
  const standalone = window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone === true;
  const iOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  if (iOS && !standalone) {
    return { supported: false, needsInstall: true,
             reason: "On iPhone, add PlanWise to your Home Screen first — Share → Add to Home Screen." };
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  return { supported: true, permission: Notification.permission, subscribed: !!sub, sub };
}

async function enablePush() {
  const state = await pushState();
  if (!state.supported) throw new Error(state.reason);
  if (Notification.permission === "denied") {
    throw new Error("Notifications are blocked for this site in your browser settings.");
  }
  if (Notification.permission !== "granted") {
    if (await Notification.requestPermission() !== "granted") {
      throw new Error("Notifications weren't allowed.");
    }
  }
  const { key, available } = await api("/api/push/key");
  if (!available || !key) throw new Error("The server isn't set up for notifications.");

  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription()
    || await reg.pushManager.subscribe({ userVisibleOnly: true,
                                         applicationServerKey: b64ToBytes(key) });
  await api("/api/push/subscribe", { method: "POST", body: JSON.stringify(sub.toJSON()) });
  return sub;
}

async function disablePush() {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  await api("/api/push/unsubscribe", { method: "POST",
                                       body: JSON.stringify({ endpoint: sub.endpoint }) });
  await sub.unsubscribe();
}

/* ---- boot ------------------------------------------------------------------------------ */

/* Nothing renders until the server confirms a live session — the page must not
   flash job data at someone who turns out not to be signed in. */
boot().then(loadHealth);
registerWorker();
