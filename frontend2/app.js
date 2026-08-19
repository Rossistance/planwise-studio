// PlanWise 2.0 — the application. Structure ported from the prototype's
// single component class (state → renderVals() → template), with its seed
// constants replaced by the live registers: every number on screen comes from
// the same API the 1.x app used, and every mutation goes back through it.
// LOGIC-MERGE.md records, per element, which side of that trade won.
"use strict";

const PAGES = ["dash", "brief", "setup", "costs", "cos", "pos", "sched", "look", "docs", "rfis", "subs", "activity"];
// 1.x hash keys keep working — old deep links and bookmarks resolve.
const LEGACY_PAGE = { dashboard: "dash", overview: "setup", changeorders: "cos",
  schedule: "sched", lookahead: "look", drawings: "docs", submittals: "subs" };

const App = {
  state: {
    // — chrome (persisted per device)
    theme: "light", density: "comfortable", mode: "desk", accent: null,

    // — stage & auth (real; the prototype faked this)
    stage: "splash",            // splash | login | app
    auth: { mode: "login", email: "", pass: "", first: "", last: "",
            name: "", token: "", newPass: "", error: "", userName: "" },
    user: null,                 // {name, email, is_admin} once signed in

    // — routing & data
    job: null, page: "dash", sub: null,
    data: {},                   // per-kind payloads, keyed job|kind
    loading: {},

    // — rail
    railPin: "open", railHover: false,
    jobsOpen: false, jobQuery: "", jobHits: [],

    // — header / search
    query: "", searchOpen: false,

    // — attention
    attnOpen: true, attnTouched: false,

    // — vista pill
    vistaExpanded: true,

    // — overlays
    settingsOpen: false, keysOpen: false, tour: 0,
    confirm: null, detail: null, form: null, co: null, shareOpen: false,
    viewer: null,

    // — registers
    regSort: { col: null, dir: 1 }, poFilter: "All", recFilter: "All",

    // — schedule interactions
    schedCollapsed: {}, schedPeek: null, schedDrag: null,

    // — undo + announcements
    undo: null, live: "",
  },

  // ————— boot —————————————————————————————————————————————————————————————
  async boot() {
    Object.assign(this.state, loadPrefs());
    applyChrome();
    document.addEventListener("keydown", (e) => this.onKey(e));
    window.addEventListener("hashchange", () => this.route());

    // Splash once per browser session: the prototype models app launch, not
    // every F5 — resolved decision #10 says the login screen is the skip, and
    // a working tool must not cost 4.4 seconds per refresh. Recorded in
    // LOGIC-MERGE.md.
    let splashed = false;
    try { splashed = sessionStorage.getItem("pw.splashed") === "1"; } catch (e) {}
    if (!splashed) {
      try { sessionStorage.setItem("pw.splashed", "1"); } catch (e) {}
      this.state.stage = "splash";
      this._splashT = setTimeout(() => this.afterSplash(), 4400);
    }

    let status = {};
    try { status = await api("/api/auth/status"); } catch (e) {}
    this._status = status;
    if (status.needs_setup) this.state.auth.mode = "bootstrap";
    else if (status.pending) { this.state.auth.mode = "pending"; this.state.auth.userName = (status.user || {}).name || ""; this.watchApproval(); }
    else if (status.signed_in) {
      this.state.user = status.user;
      if (status.user && status.user.must_change_password) this.state.auth.mode = "must_change";
    } else {
      let has = false;
      try { has = localStorage.getItem("planwise.hasAccount") === "1"; } catch (e) {}
      this.state.auth.mode = has ? "login" : "register";
    }
    if (splashed) this.afterSplash();
    else setState({});           // paint the splash

    this.refreshHealth();
    setInterval(() => this.refreshHealth(), 90000);
  },

  afterSplash() {
    const signedIn = !!this.state.user && this.state.auth.mode !== "must_change";
    if (signedIn) {
      this.state.stage = "app";
      this.enterApp();
    } else {
      this.state.stage = "login";
      setState({}, focusRef("login"));
    }
  },

  enterApp() {
    let firstRun = true;
    try { firstRun = !localStorage.getItem("pw.tourDone"); } catch (e) {}
    this.state.tour = firstRun ? 1 : 0;
    this.route();
    // The prototype's timers: the attention panel tucks itself away after 10s
    // if untouched; the Vista pill collapses to a dot after 6s when fresh.
    clearTimeout(this._attnT); clearTimeout(this._vistaT);
    this._attnT = setTimeout(() => {
      if (!this.state.attnTouched && this.state.attnOpen) {
        setState({ attnOpen: false,
          live: "The needs attention panel tucked itself away. Its count stays on the button at the top of the screen." });
      }
    }, 10000);
    this._vistaT = setTimeout(() => {
      const h = this.state.data.health;
      if (!(h && h.vista && h.vista.stale)) setState({ vistaExpanded: false });
    }, 6000);
  },

  onUnauthorized() {
    if (this.state.stage === "login") return;
    this.state.user = null;
    this.state.auth.mode = "login";
    setState({ stage: "login" }, focusRef("login"));
  },
  onPending() {
    this.state.auth.mode = "pending";
    if (this.state.stage !== "login") setState({ stage: "login" });
    this.watchApproval();
  },
  watchApproval() {
    clearInterval(this._pendT);
    this._pendT = setInterval(async () => {
      let s = {};
      try { s = await fetch("/api/auth/status", { credentials: "same-origin" }).then((r) => r.json()); } catch (e) { return; }
      if (s.signed_in && !s.pending) {
        clearInterval(this._pendT);
        this.state.user = s.user;
        setState({ stage: "app", live: "Approved. Welcome to PlanWise." });
        this.enterApp();
      }
    }, 4000);
  },

  // ————— auth form ————————————————————————————————————————————————————————
  setAuthField: (key) => (e) => {
    App.state.auth[key] = e.target.value;
    setState({});
  },
  switchAuthMode: (mode) => () => {
    App.state.auth.mode = mode;
    App.state.auth.error = "";
    setState({});
  },

  async signIn() {
    const a = App.state.auth;
    a.error = "";
    try {
      if (a.mode === "bootstrap") {
        await api("/api/auth/bootstrap", { method: "POST",
          body: JSON.stringify({ token: a.token, name: a.name, password: a.pass }) });
      } else if (a.mode === "register") {
        const out = await api("/api/auth/register", { method: "POST",
          body: JSON.stringify({ email: a.email, first_name: a.first, last_name: a.last, password: a.pass }) });
        try { localStorage.setItem("planwise.hasAccount", "1"); } catch (e) {}
        if (out.user && out.user.pending) { a.mode = "pending"; a.userName = out.user.name; App.watchApproval(); setState({}); return; }
      } else if (a.mode === "must_change") {
        await api("/api/auth/password", { method: "POST",
          body: JSON.stringify({ new_password: a.newPass }) });
      } else if (a.mode === "pending") {
        return;
      } else {
        const out = await api("/api/auth/login", { method: "POST",
          body: JSON.stringify({ name: a.email, password: a.pass }) });
        try { localStorage.setItem("planwise.hasAccount", "1"); } catch (e) {}
        if (out.user && out.user.pending) { a.mode = "pending"; a.userName = out.user.name; App.watchApproval(); setState({}); return; }
        if (out.user && out.user.must_change_password) { App.state.user = out.user; a.mode = "must_change"; setState({}); return; }
      }
      const s = await api("/api/auth/status");
      App.state.user = s.user;
      a.pass = ""; a.newPass = "";
      setState({ stage: "app", live: "Signed in." });
      App.enterApp();
    } catch (err) {
      a.error = err.message;
      setState({});
    }
  },

  async signOut() {
    try { await api("/api/auth/logout", { method: "POST" }); } catch (e) {}
    App.state.user = null;
    App.state.auth.mode = "login";
    setState({ stage: "login", settingsOpen: false });
  },

  // ————— routing & data ———————————————————————————————————————————————————
  parseHash() {
    const m = /^#\/job\/([^/]+)(?:\/([a-z]+))?(?:\/([A-Za-z0-9_-]+))?/.exec(location.hash);
    if (!m) return null;
    let page = m[2] || "dash";
    page = LEGACY_PAGE[page] || page;
    if (!PAGES.includes(page)) page = "dash";
    return { job: decodeURIComponent(m[1]), page, sub: m[3] || null };
  },

  route() {
    const r = this.parseHash();
    if (!r) {
      // No job in the hash: land on the last one, or the first the registry
      // offers — a dashboard about nothing helps nobody.
      let last = null;
      try { last = localStorage.getItem("pw.lastJob"); } catch (e) {}
      if (last) { location.hash = "#/job/" + encodeURIComponent(last) + "/dash"; return; }
      setState({ job: null, page: "dash" });
      api("/api/jobs?limit=1").then((out) => {
        const first = (out.jobs || [])[0];
        if (first && !this.parseHash()) {
          location.hash = "#/job/" + encodeURIComponent(first.job_number) + "/dash";
        }
      }).catch(() => {});
      return;
    }
    const jobChanged = r.job !== this.state.job;
    if (jobChanged) {
      this.state.data = { health: this.state.data.health };
      try { localStorage.setItem("pw.lastJob", r.job); } catch (e) {}
    }
    setState({ job: r.job, page: r.page, sub: r.sub, jobsOpen: false, searchOpen: false, query: "" });
    this.loadFor(r.page, jobChanged);
  },

  go: (page, sub) => () => {
    const job = App.state.job;
    if (!job) return;
    location.hash = "#/job/" + encodeURIComponent(job) + "/" + page + (sub ? "/" + sub : "");
  },

  async loadFor(page, jobChanged) {
    const job = this.state.job;
    if (!job) return;
    const want = new Set(["job", "attention"]);
    if (page === "dash") want.add("history");
    if (page === "sched") want.add("schedule");
    if (page === "look") want.add("lookahead");
    if (page === "docs") want.add("documents");
    if (page === "rfis" || page === "subs") want.add("records");
    if (page === "activity") want.add("activity");
    if (page === "brief") want.add("briefing");
    for (const kind of want) {
      if (this.state.data[kind] !== undefined && !jobChanged && kind !== "attention") continue;
      this.load(kind);
    }
  },

  async load(kind) {
    const job = this.state.job;
    if (!job || this.state.loading[kind]) return;
    this.state.loading[kind] = true;
    const url = {
      job: `/api/jobs/${encodeURIComponent(job)}`,
      attention: `/api/jobs/${encodeURIComponent(job)}/attention`,
      history: `/api/jobs/${encodeURIComponent(job)}/history`,
      schedule: `/api/jobs/${encodeURIComponent(job)}/schedule`,
      lookahead: `/api/jobs/${encodeURIComponent(job)}/lookahead`,
      areas: `/api/jobs/${encodeURIComponent(job)}/lookahead/areas`,
      documents: `/api/jobs/${encodeURIComponent(job)}/documents`,
      records: `/api/jobs/${encodeURIComponent(job)}/records`,
      activity: `/api/jobs/${encodeURIComponent(job)}/activity?limit=200`,
      briefing: `/api/jobs/${encodeURIComponent(job)}/briefing`,
    }[kind];
    try {
      const body = await api(url);
      this.state.data[kind] = body;
      if (kind === "lookahead") this.load("areas");
    } catch (err) {
      this.state.data[kind] = { error: err.message };
    } finally {
      this.state.loading[kind] = false;
      setState({});
    }
  },

  // Refresh what a mutation touched, plus attention (items disappear when done).
  refresh(...kinds) {
    for (const k of new Set([...kinds, "attention"])) {
      this.state.data[k] = undefined;
      this.load(k);
    }
  },

  async refreshHealth() {
    try {
      const h = await api("/api/health");
      this.state.data.health = h;
      setState({});
    } catch (e) {}
  },

  // ————— chrome toggles ————————————————————————————————————————————————————
  toggleField() {
    const mode = App.state.mode === "field" ? "desk" : "field";
    savePrefs({ mode, live: mode === "field" ? "Field mode on. Targets and text are larger and contrast is raised." : "Field mode off." });
  },
  toggleDensity() {
    const density = App.state.density === "comfortable" ? "compact" : "comfortable";
    savePrefs({ density, live: "Row density set to " + density + "." });
  },
  toggleTheme() {
    const theme = App.state.theme === "light" ? "dark" : "light";
    savePrefs({ theme, live: theme === "dark" ? "Dark theme on." : "Light theme on." });
  },
  setAccent: (color) => () => {
    savePrefs({ accent: color, live: "Accent colour changed." });
  },

  // ————— rail ————————————————————————————————————————————————————————————
  railEnter() {
    clearTimeout(App._railT);
    if (App.state.railPin !== "auto" || App.state.railHover) return;
    App._railT = setTimeout(() => setState({ railHover: true }), 260);
  },
  railLeave() {
    clearTimeout(App._railT);
    if (App.state.railPin !== "auto") return;
    App._railT = setTimeout(() => setState({ railHover: false, jobsOpen: false }), 380);
  },
  toggleRail() {
    clearTimeout(App._railT);
    const s = App.state;
    if (s.railPin === "auto") {
      const railPin = s.railHover ? "open" : "closed";
      try { localStorage.setItem("pw.railPin", railPin); } catch (e) {}
      setState({ railPin, railHover: false, jobsOpen: false,
        live: railPin === "open" ? "Rail pinned open." : "Rail pinned closed. It stays as icons until you unpin it." });
      return;
    }
    try { localStorage.setItem("pw.railPin", "auto"); } catch (e) {}
    setState({ railPin: "auto", railHover: s.railPin === "open", jobsOpen: false,
      live: "Rail unpinned. It opens when you point at it and closes when you leave." });
  },

  openJobs() { setState({ jobsOpen: true }); App.searchJobs(App.state.jobQuery); },
  onJobQuery(e) {
    setState({ jobQuery: e.target.value, jobsOpen: true });
    App.searchJobs(e.target.value);
  },
  searchJobs: debounce(async (q) => {
    try {
      const out = await api("/api/jobs?q=" + encodeURIComponent(q || "") + "&limit=8");
      setState({ jobHits: out.jobs || [] });
    } catch (e) {}
  }, 160),
  pickJob: (num) => () => {
    setState({ jobsOpen: false, jobQuery: "" });
    location.hash = "#/job/" + encodeURIComponent(num) + "/dash";
  },

  // ————— header search (cross-entity, over the loaded registers) ——————————
  onQuery(e) {
    const q = e.target.value;
    setState({ query: q, searchOpen: q.trim().length > 0 });
  },
  onSearchFocus() { if (App.state.query.trim()) setState({ searchOpen: true }); },
  clearSearch() { setState({ query: "", searchOpen: false }, focusRef("search")); },

  searchIndex() {
    const d = this.state.data;
    const out = [];
    const jd = d.job || {};
    (jd.change_orders || []).forEach((c) => out.push({
      kind: c.kind === "customer" ? "Change order" : "Sub change order",
      label: "CO-" + (c.co_number || "?"), sub: c.description || "", page: "cos", sub2: c.id }));
    (jd.purchase_orders || []).forEach((p) => out.push({
      kind: "Purchase order", label: p.po_number || "(unnumbered)",
      sub: [p.vendor, p.description].filter(Boolean).join(" — "), page: "pos", sub2: p.id }));
    ((d.records || {}).records || []).forEach((r) => out.push({
      kind: r.kind === "rfi" ? "RFI" : "Submittal", label: r.number || "?", sub: r.title || "",
      page: r.kind === "rfi" ? "rfis" : "subs", sub2: r.id }));
    ((d.documents || {}).documents || []).forEach((doc) => out.push({
      kind: "Drawing", label: doc.name, sub: doc.page_count + " pages", page: "docs", sub2: doc.id }));
    (jd.cost_types || []).forEach((c) => out.push({
      kind: "Cost type", label: c.cost_type,
      sub: (c.phase_codes || []).slice(0, 2).join(", ") + " · " + money(c.actual_cost) + " spent to date",
      page: "costs" }));
    ((d.schedule || {}).tasks || []).forEach((t) => out.push({
      kind: "Schedule task", label: t.name || "?", sub: (t.start || "") + " to " + (t.finish || ""), page: "sched" }));
    NAV.forEach(([g, ab, items]) => items.forEach(([k, l]) => out.push({ kind: "Section", label: l, sub: g, page: k })));
    const contacts = ((jd.meta || {}).contacts || []);
    contacts.forEach((c) => out.push({ kind: "Contact", label: c.name || "", sub: [c.role, c.email].filter(Boolean).join(" · "), page: "setup" }));
    return out;
  },

  // ————— attention ————————————————————————————————————————————————————————
  attentionItems() {
    const items = ((this.state.data.attention || {}).items) || [];
    const tones = { er: ["var(--er)", "var(--ers)"], wn: ["var(--wn)", "var(--wns)"], bp: ["var(--bp)", "var(--bps)"] };
    return items.map((i) => ({
      kind: i.kind, color: (tones[i.tone] || tones.bp)[0], soft: (tones[i.tone] || tones.bp)[1],
      age: i.age || "", text: i.text, cta: i.cta,
      go: App.go(i.page, i.sub || undefined),
    }));
  },

  // ————— undo (decision I: reversal engine, client-orchestrated) ——————————
  // act() is called AFTER a mutation succeeded, with the activity id the
  // server returned; undo POSTs the reversal and refreshes what it touched.
  act(message, activityId, refreshKinds) {
    setState({ undo: { message, activityId, refreshKinds: refreshKinds || ["job"] }, live: message });
  },
  async doUndo() {
    const u = App.state.undo;
    if (!u) return;
    if (u.revertFn) {           // pure-client undo (rare)
      u.revertFn();
      setState({ undo: null, live: "Undone. " + u.message });
      return;
    }
    try {
      await api("/api/activity/" + u.activityId + "/reverse", { method: "POST" });
      setState({ undo: null, live: "Undone. " + u.message });
      App.refresh(...u.refreshKinds);
    } catch (err) {
      setState({ live: "Could not undo: " + err.message });
    }
  },
  dismissUndo() { setState({ undo: null }); },

  // ————— confirm dialog ———————————————————————————————————————————————————
  closeConfirm() { setState({ confirm: null }); },

  buildConfirm() {
    const c = this.state.confirm;
    if (!c) return { confirmOpen: "" };
    const tones = { pass: ["var(--ok)", "✓"], warn: ["var(--wn)", "!"], fail: ["var(--er)", "✗"] };
    return {
      confirmOpen: true, closeConfirm: App.closeConfirm,
      confirmEyebrow: c.eyebrow, confirmTitle: c.title, confirmBody: c.body,
      confirmChecks: c.checks.map(([kind, label, note]) => ({ label, note, color: tones[kind][0], mark: tones[kind][1] })),
      confirmVerdict: c.verdict,
      confirmVerdictStyle: "margin:12px 0 0;padding:11px 13px;border-radius:6px;font-size:12.5px;text-wrap:pretty;border:1px solid " +
        (c.blocked ? "var(--er)" : "var(--ln)") + ";background:" + (c.blocked ? "var(--ers)" : "var(--p2)") + ";color:" + (c.blocked ? "var(--er)" : "var(--mu)"),
      confirmLabel: c.blocked ? (c.blockedLabel || "Cannot reverse this") : c.label,
      confirmBlocked: !!c.blocked,
      confirmBtnStyle: "min-height:var(--tap);padding:9px 17px;border-radius:6px;font:600 13px var(--fd);letter-spacing:.03em;border:1px solid " +
        (c.blocked ? "var(--ln);background:var(--ln);color:var(--ft);cursor:not-allowed" : "var(--er);background:var(--er);color:#fff"),
      runConfirm: c.blocked ? () => {} : c.run,
    };
  },

  // ————— keyboard map (prototype onKey, verbatim order) ————————————————————
  onKey(e) {
    const s = this.state;
    if (s.stage !== "app") return;
    const tag = ((e.target && e.target.tagName) || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";
    if (e.key === "Escape") {
      if (s.viewer) return setState({ viewer: null });
      if (s.settingsOpen) return setState({ settingsOpen: false });
      if (s.confirm) return setState({ confirm: null });
      if (s.co) return App.coClose();
      if (s.shareOpen) return setState({ shareOpen: false });
      if (s.form) return setState({ form: null });
      if (s.detail) return setState({ detail: null });
      if (s.tour) return App.endTour();
      if (s.keysOpen) return setState({ keysOpen: false });
      if (s.searchOpen) return setState({ searchOpen: false });
      if (s.jobsOpen) return setState({ jobsOpen: false });
      return;
    }
    if (e.altKey) {
      const keys = [];
      NAV.forEach(([g, ab, items]) => items.forEach(([k]) => keys.push(k)));
      const i = keys.indexOf(s.page);
      if (e.key.toLowerCase() === "a") { e.preventDefault(); clearTimeout(this._attnT); return setState({ attnOpen: !s.attnOpen, attnTouched: true }); }
      if (e.key.toLowerCase() === "f") { e.preventDefault(); return App.toggleField(); }
      if (e.key.toLowerCase() === "d") { e.preventDefault(); return App.toggleDensity(); }
      if (e.key.toLowerCase() === "z") { e.preventDefault(); return App.doUndo(); }
      if (e.key === "[") { e.preventDefault(); return App.go(keys[Math.max(0, i - 1)])(); }
      if (e.key === "]") { e.preventDefault(); return App.go(keys[Math.min(keys.length - 1, i + 1)])(); }
      return;
    }
    if (typing) return;
    if (e.key === "/") { e.preventDefault(); const el = document.querySelector('[data-ref="search"]'); if (el) el.focus(); return; }
    if (e.key === "?") { e.preventDefault(); const open = !s.keysOpen; setState({ keysOpen: open }, open ? focusRef("keys") : undefined); return; }
  },

  // ————— tour / keys / settings ————————————————————————————————————————————
  startTour() { setState({ tour: 1 }, focusRef("tour")); },
  endTour() {
    try { localStorage.setItem("pw.tourDone", "1"); } catch (e) {}
    setState({ tour: 0 });
  },
  tourNext() { if (App.state.tour >= TOUR.length) return App.endTour(); setState({ tour: App.state.tour + 1 }, focusRef("tour")); },
  tourBack() { setState({ tour: Math.max(1, App.state.tour - 1) }, focusRef("tour")); },
  openSettings() { setState({ settingsOpen: true }, focusRef("settings")); },
  closeSettings() { setState({ settingsOpen: false }); },

  afterRender() {
    // Rail hover-open: mouseenter/leave don't bubble, so they bind directly to
    // the persistent element (morphdom keeps it) rather than delegating.
    const rail = document.getElementById("pw-rail");
    if (rail && !rail._hoverBound) {
      rail._hoverBound = true;
      rail.addEventListener("mouseenter", () => App.railEnter());
      rail.addEventListener("mouseleave", () => App.railLeave());
    }
  },
};

window.addEventListener("DOMContentLoaded", () => App.boot());

// ————— register (prototype regSpec/buildRegister, fed by the live data) ————
Object.assign(App, {
  regSpec() {
    const s = this.state;
    const d = s.data;
    const P = (text, right) => ({ kind: "plain", text, right: !!right });
    const S = (text) => ({ kind: "stamp", text });
    const jd = d.job || {};

    if (s.page === "costs") {
      const rows = (jd.cost_types || []).map((r) => {
        const open = r.open_committed;
        const u = r.approved_no_po;
        const committed = (r.actual_cost || 0) + (open || 0);
        const pct = r.current_estimate ? committed / r.current_estimate * 100 : null;
        const phases = r.phase_codes || [];
        const phaseLabel = phases.length === 0 ? (r.po_only ? "PO only — not in the Vista phase detail" : "")
          : "Phase " + phases[0] + (phases.length > 1 ? " +" + (phases.length - 1) : "");
        return {
          id: r.cost_type, key: r.cost_type, keySub: phaseLabel,
          sortVals: [r.cost_type, r.current_estimate, r.mtd_cost, r.actual_cost, open, u, committed, pct, r.projected_cost, r.variance],
          cells: [
            P(money(r.current_estimate), 1),
            r.mtd_cost === null || r.mtd_cost === undefined ? { kind: "plain", text: "not reported", right: 1, muted: 1 } : P(money(r.mtd_cost), 1),
            P(money(r.actual_cost), 1),
            !open ? { kind: "plain", text: "none open", right: 1, muted: 1 } : P(money(open), 1),
            !u ? { kind: "plain", text: "none", right: 1, muted: 1 } : { kind: "plain", text: money(u), right: 1, color: "var(--er)" },
            P(money(committed), 1),
            pct === null ? { kind: "plain", text: "no estimate", right: 1, muted: 1 }
              : { kind: "bar", text: pct.toFixed(1) + "%", w: Math.min(100, pct), color: pct > 95 ? "var(--er)" : (r.variance || 0) < 0 ? "var(--wn)" : "var(--bp)" },
            P(money(r.projected_cost), 1),
            { kind: "plain", text: signed(r.variance), right: 1, color: (r.variance || 0) < 0 ? "var(--er)" : "var(--ok)" }],
        };
      });
      const tot = (k) => (jd.cost_types || []).reduce((t, r) => t + (r[k] || 0), 0);
      const openTotal = tot("open_committed"), uncTotal = tot("approved_no_po");
      const estTotal = tot("current_estimate"), actTotal = tot("actual_cost");
      return { title: "Cost by type", source: "Source: Vista, as of " + usDate(jd.as_of), kind: "cost",
        caption: "Estimate, month to date, actual cost, open committed cost, approved work with no purchase order, committed total, share committed, projection and variance for each cost type on job " + s.job + ". Select a cost type to audit its phase codes and commitments.",
        footnote: "Estimate, month to date, actual and projected come from the nightly Vista extract. Open committed is recalculated from this job's purchase order register — the remaining amount on every open order, grouped by cost type — so the two screens can never disagree. Approved work with no purchase order is counted separately because it is exposure, not a commitment: nothing has been ordered against it yet.",
        columns: [["Cost type", 0, 1], ["Estimate", 1, 1], ["Month to date", 1, 1], ["Actual to date", 1, 1], ["Open committed", 1, 1], ["Approved, no PO", 1, 1], ["Committed total", 1, 1], ["Committed of estimate", 0, 1], ["Projected", 1, 1], ["Variance", 1, 1]],
        rows, total: ["All cost types", [money(estTotal), money(tot("mtd_cost")), money(actTotal), money(openTotal), uncTotal ? money(uncTotal) : "none", money(actTotal + openTotal),
          estTotal ? ((actTotal + openTotal) / estTotal * 100).toFixed(1) + "% committed" : "",
          money(tot("projected_cost")), signed(estTotal - actTotal === 0 ? 0 : tot("variance"))]] };
    }

    if (s.page === "activity") {
      const rows = ((d.activity || {}).activity || []).map((a) => ({
        id: String(a.id), key: a.action, keySub: a.detail || "",
        sortVals: [a.action, a.ts],
        cells: [P(usDate(a.ts) + a.ts.slice(10, 16).replace("T", ", ")), P(a.actor || "PlanWise"),
          S(a.reversal_of ? "Reversed" : a.revert ? "Reversible" : "Recorded")],
      }));
      return { title: "Activity log", source: rows.length + " entries", kind: "activity",
        caption: "Every edit, share and reply on job " + s.job + ", newest first, with who did it and when.",
        footnote: "The log is append-only. An undone action stays on the log with its reversal recorded beneath it.",
        columns: [["What happened", 0, 0], ["When", 0, 1], ["Who", 0, 0], ["State", 0, 0]], rows };
    }
    return null;
  },

  openDetail: (kind, id) => () => setState({ detail: { kind, id } }, focusRef("detail")),
  closeDetail() { setState({ detail: null }); },

  buildRegister() {
    const spec = this.regSpec();
    if (!spec) return { hasRegister: "" };
    const s = this.state;
    const align = (right) => right ? ";text-align:right;font-variant-numeric:tabular-nums" : "";
    const colStyle = (right) => "padding:10px 16px;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln);white-space:nowrap;text-align:" + (right ? "right" : "left");

    let rows = spec.rows.slice();
    const si = s.regSort.col;
    if (si !== null && spec.columns[si] && spec.columns[si][2] && !spec.noSort) {
      rows.sort((a, b) => {
        const av = a.sortVals[si], bv = b.sortVals[si];
        if (av === undefined || av === null) return 1;
        if (bv === undefined || bv === null) return -1;
        const c = typeof av === "string" ? av.localeCompare(bv) : av - bv;
        return c * s.regSort.dir;
      });
    }

    return {
      hasRegister: true,
      regTitle: spec.title, regSource: spec.source, regCaption: spec.caption, regFootnote: spec.footnote,
      regExtras: spec.extras || [],
      regHasFilters: !!spec.filters,
      regFilters: (spec.filters || []).map(([label, count]) => {
        const on = (spec.kind === "po" ? s.poFilter : s.recFilter) === label;
        return { label, count, pressed: on ? "true" : "false",
          pick: () => setState(spec.kind === "po" ? { poFilter: label } : { recFilter: label }),
          style: chip(on), countStyle: "font:600 10px var(--fm);padding:2px 6px;border-radius:999px;background:" + (on ? "var(--ac)" : "var(--ln)") + ";color:" + (on ? "var(--acink)" : "var(--mu)") };
      }),
      regColumns: spec.columns.map(([label, right, sortable], i) => ({
        label, style: colStyle(right),
        sortable: !!sortable,
        sort: si === i ? (s.regSort.dir === 1 ? "ascending" : "descending") : "none",
        arrow: si === i ? (s.regSort.dir === 1 ? "↑" : "↓") : "",
        click: () => setState({ regSort: { col: i, dir: si === i ? -s.regSort.dir : 1 } }),
      })),
      regRows: rows.map((r) => Object.assign({ hasSched: "", schedIdx: "", peekOpen: "" }, r.sched || {}, {
        rowStyle: (r.sched && s.schedDrag && s.schedDrag.kind === "row" && String(s.schedDrag.over) === r.sched.schedIdx && String(s.schedDrag.index) !== r.sched.schedIdx ? "background:var(--bps);box-shadow:inset 0 2px 0 var(--bp)" : "") +
          (r.sched && s.schedDrag && s.schedDrag.kind === "row" && String(s.schedDrag.index) === r.sched.schedIdx ? "opacity:.55;background:var(--p2)" : ""),
        headStyle: "text-align:left;font-weight:600;padding:var(--cellY) 16px;border-bottom:1px solid var(--ln);max-width:320px" +
          (r.edge ? ";border-left:3px solid " + r.edge : ""),
        key: r.key, keySub: r.keySub, open: App.openDetail(spec.kind, r.id),
        cells: r.cells.map((c) => ({
          isStamp: c.kind === "stamp", isBar: c.kind === "bar", isPlain: c.kind === "plain",
          text: c.text, stampStyle: c.kind === "stamp" ? stamp(STATUS_TONE[c.text] || "nt") : "",
          barW: (c.w || 0).toFixed(0) + "%", barColor: c.color || "var(--bp)",
          style: "padding:var(--cellY) 16px;border-bottom:1px solid var(--ln)" + align(c.right) +
            (c.color && c.kind === "plain" ? ";color:" + c.color : "") + (c.muted ? ";color:var(--ft);font-style:italic" : ""),
        })),
      })),
      regEmpty: rows.length === 0,
      regEmptyText: spec.emptyText || "Nothing on this register matches the filter you have selected. Choose All to see every item.",
      regHasTotal: !!spec.total,
      regTotalLabel: spec.total ? spec.total[0] : "",
      // The prototype's totals-row alignment was off by one (its arrays
      // skipped column 0 but aligned from column 1); here the cells align to
      // the columns they actually sit under.
      regTotalCells: spec.total ? spec.total[1].map((t, i) => ({ text: t, style: "padding:12px 16px;font:600 var(--fz) var(--fd);border-top:1px solid var(--ls);font-variant-numeric:tabular-nums;text-align:" + (spec.columns[i + 1] && spec.columns[i + 1][1] ? "right" : "left") })) : [],
    };
  },

  // ————— detail drawer (cost + activity kinds this phase) ——————————————————
  buildDetail() {
    const d = this.state.detail;
    if (!d) return { detailOpen: "" };
    const S = (id, title, rows) => ({ id: "ds-" + id, title, rows: rows.map(([label, value, note, style]) => ({ label, value, note: note || "", valueStyle: style || "" })) });
    const A = (list) => list.map(([what, who, when], i) => ({ what, who, when: when || "", color: i === list.length - 1 ? "var(--ac)" : "var(--ls)" }));
    const btn2 = (label, kind, click) => ({ label, style: btn(kind), hoverClass: kind === "primary" ? "hb-ah" : "hb-ls", click: click || (() => {}) });
    const out = { detailOpen: true, detailHasItems: "", detailHasNotes: "", detailNotes: [], detailActions: [], detailFootnote: "" };
    const jd = this.state.data.job || {};

    if (d.kind === "cost") {
      const c = (jd.cost_types || []).find((x) => x.cost_type === d.id) || {};
      const open = c.open_committed || 0;
      const u = c.approved_no_po || 0;
      const orders = (jd.purchase_orders || []).filter((p) => (p.cost_type || "Unassigned") === d.id && (p.status || "Open") === "Open");
      const spent = c.current_estimate ? (c.actual_cost || 0) / c.current_estimate : null;
      const over = (c.variance || 0) < 0;
      const rows2 = [
        ["Open committed", open === 0 ? "none open" : money(open), open === 0 ? "" : "Recalculated from the PO register", open === 0 ? "color:var(--ft);font-style:italic" : "font-variant-numeric:tabular-nums"],
        ["Open orders behind it", orders.length ? orders.map((p) => p.po_number || "(unnumbered)").join(", ") : "none", "", orders.length ? "" : "color:var(--ft);font-style:italic"],
        ["Committed total", money((c.actual_cost || 0) + open), "Actual plus open committed", "font-variant-numeric:tabular-nums"],
      ];
      if (u) rows2.push(["Approved work with no purchase order", money(u), "Exposure, not a commitment", "font-variant-numeric:tabular-nums;color:var(--er)"]);
      rows2.push(["Hours to date", c.hours_units === null || c.hours_units === undefined ? "not reported" : c.hours_units + " hours", "", c.hours_units === null || c.hours_units === undefined ? "color:var(--ft);font-style:italic" : ""]);
      rows2.push(["Phase codes", (c.phase_codes || []).join(", ") || (c.po_only ? "None — PO only" : "not reported")]);
      return Object.assign(out, {
        detailKind: "Cost type", detailTitle: d.id, detailStatus: over ? "Over estimate" : "Within estimate",
        detailStampStyle: stamp(over ? "er" : "ok"),
        detailMeta: ((c.phase_codes || [])[0] ? "Phase " + c.phase_codes[0] + " · " : "") + (spent === null ? "no estimate" : (spent * 100).toFixed(1) + "% spent"),
        detailSections: [
          S("ct-money", "Money", [["Estimate", money(c.current_estimate), "Vista", "font-variant-numeric:tabular-nums"], ["Month to date", c.mtd_cost === null || c.mtd_cost === undefined ? "not reported" : money(c.mtd_cost), c.mtd_cost === null || c.mtd_cost === undefined ? "" : "Vista", c.mtd_cost === null || c.mtd_cost === undefined ? "color:var(--ft);font-style:italic" : "font-variant-numeric:tabular-nums"], ["Actual to date", money(c.actual_cost), "Vista", "font-variant-numeric:tabular-nums"], ["Projected at completion", money(c.projected_cost), "Vista", "font-variant-numeric:tabular-nums"], ["Variance", signed(c.variance), "Derived", "font-variant-numeric:tabular-nums;color:" + (over ? "var(--er)" : "var(--ok)")]]),
          S("ct-commit", "Commitments", rows2),
        ],
        detailAudit: A([["Vista extract refreshed", "PlanWise", usDate(jd.as_of)]]),
        detailFootnote: "Vista owns the cost figures; corrections are made there and appear on the next extract. Open committed is PlanWise's own figure, recalculated from the purchase order register every time this panel opens.",
        detailActions: [btn2("Close this panel", "ghost", App.closeDetail), btn2("See purchase orders for this cost type", "ghost", () => { App.closeDetail(); App.go("pos")(); })],
      });
    }

    if (d.kind === "activity") {
      const a = (((this.state.data.activity || {}).activity) || []).find((x) => String(x.id) === String(d.id)) || {};
      return Object.assign(out, {
        detailKind: "Activity entry", detailTitle: a.action || "", detailStatus: a.reversal_of ? "Reversal" : a.revert ? "Reversible" : "Recorded",
        detailStampStyle: stamp(a.reversal_of ? "bp" : a.revert ? "ok" : "nt"),
        detailMeta: (a.ts || "") + " · " + (a.actor || "PlanWise"),
        detailSections: [S("a-what", "Entry", [["What happened", a.action || ""], ["Detail", a.detail || "not reported"], ["Who", a.actor || "PlanWise"], ["When", a.ts || ""], ["Object", a.object_kind ? a.object_kind + " " + (a.object_id || "") : "not recorded"]])],
        detailAudit: A([[a.action || "", a.actor || "PlanWise", a.ts || ""]]),
        detailFootnote: "The log is append-only. Reversing an entry records the reversal beneath it rather than deleting anything.",
        detailActions: [btn2("Close this panel", "ghost", App.closeDetail), btn2("Reverse this entry", "primary", App.reverseActivity(a.id))],
      });
    }
    return { detailOpen: "" };
  },

  // ————— activity reversal (confirm shows the SERVER's checks) —————————————
  reverseActivity: (id) => async () => {
    let gate;
    try { gate = await api("/api/activity/" + id + "/checks"); }
    catch (err) { setState({ live: err.message }); return; }
    const entry = gate.entry || {};
    setState({
      confirm: {
        eyebrow: "Reverse an activity entry",
        title: entry.action || "This entry",
        body: (entry.detail || "") + (entry.actor ? " Recorded by " + entry.actor + " on " + (entry.ts || "") + "." : ""),
        checks: gate.checks, blocked: gate.blocked,
        verdict: gate.verdict,
        label: "Reverse this entry",
        run: async () => {
          try {
            await api("/api/activity/" + id + "/reverse", { method: "POST" });
            const msg = "Reversed: " + (entry.action || "the entry") + ". The reversal is recorded on the log beneath the original.";
            setState({ confirm: null, detail: null, live: msg });
            App.refresh("activity", "job");
          } catch (err) {
            setState({ confirm: null, live: "Could not reverse: " + err.message });
          }
        },
      },
    }, focusRef("confirm"));
  },

  // ————— job setup handlers ————————————————————————————————————————————————
  setMeta: (key, label) => async (e) => {
    const value = e.target.value;
    App._savedKey = key;
    clearTimeout(App._savedT);
    try {
      const meta = await api("/api/jobs/" + encodeURIComponent(App.state.job) + "/meta",
        { method: "PATCH", body: JSON.stringify({ [key]: value || null }) });
      const jd = App.state.data.job;
      if (jd) jd.meta = meta;
      setState({ live: label + " saved as " + (value || "not set") + "." });
      App._savedT = setTimeout(() => { App._savedKey = null; setState({}); }, 2200);
    } catch (err) {
      setState({ live: "Could not save " + label + ": " + err.message });
    }
  },

  removeContact: (i) => async () => {
    const jd = App.state.data.job || {};
    const contacts = ((jd.meta || {}).contacts || []).slice();
    const gone = contacts[i];
    if (!gone) return;
    contacts.splice(i, 1);
    try {
      const meta = await api("/api/jobs/" + encodeURIComponent(App.state.job) + "/meta",
        { method: "PATCH", body: JSON.stringify({ contacts }) });
      jd.meta = meta;
      const acts = await api("/api/jobs/" + encodeURIComponent(App.state.job) + "/activity?limit=1");
      const aid = ((acts.activity || [])[0] || {}).id;
      App.act("Removed " + (gone.name || "a contact") + " from the contact list.", aid, ["job"]);
    } catch (err) {
      setState({ live: "Could not remove the contact: " + err.message });
    }
  },
});

// ————— forms (prototype formSpec/formErrors/buildForm; submits hit the API) —
Object.assign(App, {
  openForm: (kind, ctx) => () => {
    const spec = App.formSpec(kind, ctx || {});
    const values = {};
    spec.fields.forEach((f) => { values[f[0]] = f[3] && f[3].value !== undefined ? f[3].value : ""; });
    setState({ form: { kind, ctx: ctx || {}, values, items: spec.items ? [{ desc: "", amt: "" }] : [], clar: {}, pages: {}, days: {}, color: 0, submitted: false } });
  },
  closeForm() { setState({ form: null }); },
  setField: (id) => (e) => {
    const f = App.state.form;
    f.values[id] = e.target.value;
    setState({});
  },
  setItem: (i, key) => (e) => {
    const f = App.state.form;
    f.items = f.items.map((it, n) => n === i ? { ...it, [key]: e.target.value } : it);
    setState({});
  },
  addItem() { const f = App.state.form; f.items = f.items.concat([{ desc: "", amt: "" }]); setState({}); },
  removeItem: (i) => () => { const f = App.state.form; f.items = f.items.filter((it, n) => n !== i); setState({}); },
  toggleSet: (bag, id) => () => { const f = App.state.form; f[bag] = { ...f[bag], [id]: !f[bag][id] }; setState({}); },
  toggleFormDay: (d) => () => { const f = App.state.form; f.days = { ...f.days, [d]: !f.days[d] }; setState({}); },
  pickFormColor: (i) => () => { App.state.form.color = i; setState({}); },

  formSpec(kind, ctx) {
    if (kind === "contact") return {
      eyebrow: "New contact", title: "Add a job contact", submit: "Add this contact",
      intro: "Contacts are yours to keep current. They populate the recipient list on RFIs, submittals and change orders.",
      fields: [
        ["name", "Name", "text", { req: true, placeholder: "Dana Whitfield", hint: "As they sign their emails." }],
        ["role", "Role and company", "text", { req: true, wide: true, placeholder: "Owner's representative · WECC", hint: "Shown under their name on every register that lists them." }],
        ["phone", "Phone", "text", { req: true, placeholder: "806-555-0142", hint: "" }],
        ["email", "Email", "text", { req: true, placeholder: "name@customer.example", hint: "Packages and threads go to this address." }],
      ],
      review: "The contact becomes selectable as a recipient straight away. Removing a contact later is undoable.",
    };
    return { eyebrow: "", title: "", submit: "", intro: "", fields: [], review: "" };
  },

  formErrors(spec, f) {
    const errs = [];
    spec.fields.forEach((fd) => {
      const o = fd[3] || {};
      if (o.req && !String(f.values[fd[0]] || "").trim()) errs.push(fd[1] + " is required.");
    });
    if (f.values.amount !== undefined && String(f.values.amount).trim() && !(parseFloat(String(f.values.amount).replace(/[^0-9.-]/g, "")) > 0)) errs.push("Amount must be a number greater than zero.");
    if (spec.items) {
      const good = f.items.filter((i) => i.desc.trim() && parseFloat(String(i.amt).replace(/[^0-9.-]/g, "")));
      if (!good.length) errs.push("At least one breakout line needs a description and an amount.");
    }
    if (spec.days && !Object.keys(f.days || {}).filter((k) => f.days[k]).length) errs.push("Select at least one day this activity is worked.");
    return errs;
  },

  async submitForm() {
    const f = App.state.form;
    const spec = App.formSpec(f.kind, f.ctx);
    const errs = App.formErrors(spec, f);
    if (errs.length) {
      f.submitted = true;
      setState({ live: errs.length + " field" + (errs.length === 1 ? "" : "s") + " need attention before this can be created." });
      return;
    }
    try {
      if (f.kind === "contact") {
        const jd = App.state.data.job || {};
        const contacts = (((jd.meta || {}).contacts) || []).concat([{
          name: f.values.name.trim(), role: f.values.role.trim(),
          phone: f.values.phone.trim(), email: f.values.email.trim() }]);
        const meta = await api("/api/jobs/" + encodeURIComponent(App.state.job) + "/meta",
          { method: "PATCH", body: JSON.stringify({ contacts }) });
        if (jd) jd.meta = meta;
        const acts = await api("/api/jobs/" + encodeURIComponent(App.state.job) + "/activity?limit=1");
        const aid = ((acts.activity || [])[0] || {}).id;
        setState({ form: null });
        App.act(f.values.name.trim() + " added to the job contacts.", aid, ["job"]);
      }
    } catch (err) {
      setState({ live: "Could not save: " + err.message });
    }
  },

  buildForm() {
    const f = this.state.form;
    if (!f) return { formOpen: "" };
    const spec = this.formSpec(f.kind, f.ctx);
    const errs = this.formErrors(spec, f);
    const num = (v) => parseFloat(String(v || "").replace(/[^0-9.-]/g, "")) || 0;
    const control = "width:100%;min-height:var(--tap);padding:8px 11px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)";
    const itemsTotal = f.items.reduce((t, i) => t + num(i.amt), 0);
    const invalidIds = {};
    spec.fields.forEach((fd) => { const o = fd[3] || {}; if (o.req && !String(f.values[fd[0]] || "").trim()) invalidIds[fd[0]] = true; });
    const clarLib = (this.state.data.clarifications || {}).clarifications || [];

    return {
      formOpen: true, formEyebrow: spec.eyebrow, formTitle: spec.title, formIntro: spec.intro,
      formSubmitLabel: spec.submit, submitForm: () => App.submitForm(), closeForm: App.closeForm,
      formShowErrors: f.submitted && errs.length ? true : "",
      formErrorHeading: errs.length + " thing" + (errs.length === 1 ? "" : "s") + " to fix before this can be created",
      formErrors: errs.map((text) => ({ text })),
      formStatus: errs.length ? (f.submitted ? "Fix the items listed above." : "Required fields are marked.") : "Ready to create.",
      formFields: spec.fields.map((fd) => {
        const [id, label, type, o0] = fd; const o = o0 || {};
        const bad = f.submitted && invalidIds[id];
        return {
          id: "ff-" + id, label, type: type === "textarea" || type === "select" ? "text" : type,
          isInput: type === "text" || type === "date", isArea: type === "textarea", isSelect: type === "select",
          rows: o.rows || 3, value: f.values[id] || "", set: o.readOnly ? () => {} : App.setField(id),
          placeholder: o.placeholder || "", hint: bad ? label + " is required." : (o.hint || ""),
          hintId: "ff-" + id + "-hint", hintColor: bad ? "var(--er)" : "var(--ft)",
          invalid: bad ? "true" : "false",
          reqText: o.req ? "Required" : o.readOnly ? "Set by PlanWise" : "Optional",
          reqStyle: "margin-left:7px;font:500 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:" + (o.req ? "var(--ac)" : "var(--ft)"),
          wrap: "min-width:0" + (o.wide ? ";grid-column:1 / -1" : "") + (o.readOnly ? ";opacity:.72" : ""),
          control: control + (bad ? ";border-color:var(--er);background:var(--ers)" : "") + (o.readOnly ? ";background:var(--ln)" : "") + (type === "textarea" ? ";min-height:auto;resize:vertical;line-height:1.5" : ""),
          options: (o.options || []).map(([value, l]) => ({ value, label: l })),
        };
      }),
      formHasItems: !!spec.items,
      formItemsTitle: spec.items ? spec.items.title : "", formItemsHint: spec.items ? spec.items.hint : "",
      addItemLabel: spec.items ? spec.items.add : "", addItem: () => App.addItem(),
      formItemsTotalLabel: spec.items ? spec.items.total : "", formItemsTotal: money(itemsTotal),
      formItems: f.items.map((it, i) => ({
        n: i + 1, descId: "fi-d" + i, amtId: "fi-a" + i, desc: it.desc, amt: it.amt,
        placeholder: spec.items ? spec.items.placeholder : "",
        setDesc: App.setItem(i, "desc"), setAmt: App.setItem(i, "amt"), remove: App.removeItem(i),
      })),
      formHasDays: !!spec.days, formDays: [],
      formHasColors: !!spec.colors,
      formColors: AREA_COLORS.map(([name, color], i) => {
        const on = (f.color || 0) === i;
        return {
          name, pick: App.pickFormColor(i), pressed: on ? "true" : "false",
          label: name + (on ? ", selected" : ""),
          swatch: "width:13px;height:13px;border-radius:3px;background:" + color + ";flex:none",
          style: "display:inline-flex;align-items:center;gap:8px;min-height:var(--tap);padding:7px 13px;border-radius:6px;font:600 12px var(--fd);border:1px solid " +
            (on ? "var(--ac)" : "var(--ln)") + ";background:" + (on ? "var(--as)" : "var(--pn)") + ";color:" + (on ? "var(--ac)" : "var(--mu)"),
        };
      }),
      formHasClar: !!spec.clar,
      formClar: clarLib.map((c) => ({ id: "fc-" + c.id, text: c.text, on: !!f.clar[c.id], toggle: App.toggleSet("clar", c.id) })),
      formHasPages: !!spec.pages, formDocs: [], formHasAttached: "", formNoAttached: true, formAttached: [],
      formReview: spec.review,
    };
  },
});

// ————— view model + template ————————————————————————————————————————————————
Object.assign(App, {
  pageMeta() {
    const s = this.state;
    const d = s.data;
    const jd = d.job || {};
    const job = jd.job || {};
    const meta = PAGE_META[s.page] || PAGE_META.dash;
    const attn = (d.attention || {}).items || [];
    const sub = {
      "{jobline}": "Job " + (s.job || "") + (job.job_name ? " · " + job.job_name : ""),
      "{job}": "Job " + (s.job || ""),
      "{week}": "Week of " + usDate(((d.briefing || {}).week_start) || new Date().toISOString().slice(0, 10)),
      "{vista}": jd.as_of ? "Vista as of " + usDate(jd.as_of) : "Vista extract pending",
      "{costcount}": (() => { const n = (jd.cost_types || []).length; return n ? n + " cost type" + (n === 1 ? "" : "s") : "Cost types"; })(),
      "{cocounts}": (() => {
        const cos = jd.change_orders || [];
        const c = cos.filter((x) => x.kind === "customer").length;
        const sc = cos.filter((x) => x.kind === "subcontractor").length;
        return c + " customer · " + sc + " subcontractor";
      })(),
      "{cosummary}": (() => {
        const it = attn.find((i) => i.page === "cos");
        return it ? it.text : "Every change order on this job, customer and subcontractor.";
      })(),
      "{pocounts}": (() => {
        const pos = jd.purchase_orders || [];
        const open = pos.filter((p) => (p.status || "Open") === "Open").length;
        return pos.length + " purchase orders · " + open + " open";
      })(),
      "{schedcounts}": (() => {
        const sd = d.schedule || {};
        const n = (sd.tasks || []).length;
        return n ? n + " tasks · " + (sd.critical_count || 0) + " on the critical path" : "No schedule yet";
      })(),
      "{lookrange}": (() => {
        const ld = d.lookahead || {};
        return ld.start_date ? usDate(ld.start_date) : "This week";
      })(),
      "{doccounts}": (() => {
        const docs = (d.documents || {}).documents || [];
        const pages = docs.reduce((t, x) => t + (x.page_count || 0), 0);
        return docs.length + " sets · " + pages + " pages";
      })(),
      "{rficounts}": (() => {
        const recs = ((d.records || {}).records || []).filter((r) => r.kind === "rfi");
        const open = recs.filter((r) => r.status === "Sent" || r.status === "Draft").length;
        return recs.length + " on the register · " + open + " open";
      })(),
      "{rfisummary}": (() => {
        const it = attn.find((i) => i.page === "rfis");
        return it ? it.text : "Requests for information, numbered in sequence by PlanWise.";
      })(),
      "{subcounts}": (() => {
        const recs = ((d.records || {}).records || []).filter((r) => r.kind === "sub" || r.kind === "submittal");
        return recs.length + " on the register";
      })(),
      "{subsummary}": (() => {
        const it = attn.find((i) => i.page === "subs");
        return it ? it.text : "Submittals, numbered in sequence by PlanWise.";
      })(),
    };
    const fill = (t) => t.replace(/\{[a-z]+\}/g, (m) => sub[m] !== undefined ? sub[m] : m);
    return [fill(meta[0]), meta[1], fill(meta[2]), meta[3]];
  },

  pageActions() {
    const s = this.state;
    const d = s.data;
    const jd = d.job || {};
    const attn = (d.attention || {}).items || [];
    const mk = (label, kind, click, hoverGhost) => ({
      label, style: btn(kind), click: click || (() => {}),
      hoverClass: kind === "primary" ? "hb-ah" : "hb-ls",
    });
    const todo = (what) => () => setState({ live: what + " lands in v2.x." });
    switch (s.page) {
      case "dash": return [mk("Open the weekly briefing", "primary", App.go("brief")), mk("Export a snapshot", "ghost", todo("Snapshot export"))];
      case "brief": return [mk("Choose recipients and send", "primary", () => App.openShare && App.openShare()), mk("Preview the PDF", "ghost", todo("The briefing PDF"))];
      case "setup": return [mk("Add a contact", "primary", App.openForm("contact"))];
      case "costs": return [mk("Reconcile committed cost", "primary", App.go("pos")), mk("Export to Excel", "ghost", todo("Excel export"))];
      case "cos": {
        const unsent = (jd.change_orders || []).find((c) => c.kind === "customer" &&
          (!c.status || ["Draft", "Unsent", "Pending"].includes(c.status)) && (c.amount_submitted || 0) > 0);
        return unsent
          ? [mk("Send CO-" + (unsent.co_number || "?"), "primary", () => App.coSend ? App.coSend(unsent.id)() : null), mk("Compose a change order", "ghost", () => App.openCO ? App.openCO(null)() : null)]
          : [mk("Compose a change order", "primary", () => App.openCO ? App.openCO(null)() : null)];
      }
      case "pos": {
        const unc = (jd.approved_no_po || {}).cos || [];
        const acts = [];
        if (unc.length) acts.push(mk("Log the " + unc.length + " missing purchase order" + (unc.length === 1 ? "" : "s"), "primary", App.go("pos")));
        acts.push(mk("Log a PO from Vista", unc.length ? "ghost" : "primary", App.openForm("po")));
        acts.push(mk("Import a Vista PO export", "ghost", () => App.triggerPoImport ? App.triggerPoImport() : null));
        return acts;
      }
      case "sched": return [mk("Add a task", "primary", App.openForm("task")), mk("Import an updated schedule", "ghost", () => App.triggerSchedImport ? App.triggerSchedImport() : null)];
      case "look": return [mk("Share the look ahead", "primary", () => App.openShare && App.openShare()), mk("Seed it from the schedule", "ghost", () => App.seedLook ? App.seedLook() : null)];
      case "docs": return [mk("Upload a PDF set", "primary", () => App.triggerDocUpload ? App.triggerDocUpload() : null)];
      case "rfis": {
        const draft = attn.find((i) => i.page === "rfis" && i.text.includes("draft"));
        return draft ? [mk("Send the draft RFI", "primary", App.go("rfis", draft.sub || undefined)), mk("Start a new RFI", "ghost", App.openForm("rfi"))]
          : [mk("Start a new RFI", "primary", App.openForm("rfi"))];
      }
      case "subs": return [mk("Start a new submittal", "primary", App.openForm("sub"))];
      case "activity": return [mk("Export the log", "ghost", todo("Log export"))];
      default: return [];
    }
  },

  renderVals() {
    const s = this.state;
    const d = s.data;
    const jd = d.job || {};
    const job = jd.job || {};
    const meta = this.pageMeta();
    const attnItems = this.attentionItems();
    const attn = (d.attention || {}).items || [];

    // Badges: the count of attention items that deep-link to each page — one
    // derivation drives the panel, the header count and the rail badges.
    const badgeFor = {};
    attn.forEach((i) => { badgeFor[i.page] = (badgeFor[i.page] || 0) + 1; });
    const badgeCounts = { co: badgeFor.cos ? String(badgeFor.cos) : "",
      po: badgeFor.pos ? String(badgeFor.pos) : "",
      rfi: badgeFor.rfis ? String(badgeFor.rfis) : "",
      sub: badgeFor.subs ? String(badgeFor.subs) : "" };

    const wide = s.railPin === "open" || (s.railPin === "auto" && s.railHover);
    const navGroups = NAV.map(([label, ab, items], gi) => ({
      id: "nav-group-" + gi,
      label: wide ? label : ab,
      groupStyle: wide ? "margin-bottom:8px" : "margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid var(--ln)",
      headStyle: wide
        ? "margin:0;padding:4px 10px 2px;font:500 var(--lbl) var(--fm);letter-spacing:.18em;text-transform:uppercase;color:var(--ft);text-align:left"
        : "margin:0;padding:0 0 4px;font:600 8px var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft);text-align:center",
      items: items.map(([key, lbl, badgeKey]) => {
        const on = key === s.page;
        const badge = badgeCounts[badgeKey] !== undefined ? badgeCounts[badgeKey] : badgeKey;
        return {
          label: lbl, icon: ICONS[key], showLabel: wide, showIcon: !wide,
          badge: badge || "",
          aria: badge ? lbl + ", " + badge + " needing attention" : lbl,
          current: on ? "page" : "false",
          go: App.go(key),
          style: wide
            ? "width:100%;min-height:30px;display:flex;align-items:center;gap:9px;padding:5px 10px;border-radius:6px;font:600 13px var(--fd);letter-spacing:.02em;text-align:left;position:relative;color:" +
              (on ? "var(--ink)" : "var(--mu)") + ";background:" + (on ? "var(--as)" : "transparent")
            : "width:100%;min-height:34px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0;padding:4px 2px;border-radius:7px;position:relative;color:" +
              (on ? "var(--ac)" : "var(--mu)") + ";background:" + (on ? "var(--as)" : "transparent") + ";border:1px solid " + (on ? "var(--ac)" : "transparent"),
          edge: wide
            ? "width:3px;height:16px;border-radius:2px;flex:none;background:" + (on ? "var(--ac)" : "transparent")
            : "display:none",
          iconStyle: "width:19px;height:19px;flex:none;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round",
          badgeStyle: wide
            ? "font:600 10px var(--fm);min-width:19px;text-align:center;padding:3px 6px;border-radius:999px;background:var(--er);color:#fff"
            : "position:absolute;top:1px;right:3px;font:700 9px var(--fm);min-width:15px;text-align:center;padding:1px 4px;border-radius:999px;background:var(--er);color:#fff;box-shadow:0 0 0 2px var(--pn)",
        };
      }),
    }));

    const crumbSrc = [{ label: "Job " + (s.job || "—"), page: "dash" }];
    if (GROUP_OF[s.page] && s.page !== "dash") crumbSrc.push({ label: GROUP_OF[s.page] });
    crumbSrc.push({ label: meta[1] });
    const crumbs = crumbSrc.map((c, i) => {
      const last = i === crumbSrc.length - 1;
      return { label: c.label, isLast: last || !c.page, isLink: !last && !!c.page,
        sep: !last, go: c.page ? App.go(c.page) : () => {} };
    });

    const q = s.query.trim().toLowerCase();
    const results = q ? this.searchIndex().filter((r) =>
      (r.label + " " + r.sub + " " + r.kind).toLowerCase().indexOf(q) >= 0
    ).slice(0, 12).map((r) => ({ ...r, go: App.go(r.page, r.sub2 || undefined) })) : [];

    const health = d.health || {};
    const vh = health.vista || {};
    const vistaStale = !!vh.stale;
    const vistaAsOf = vh.as_of ? usDate(vh.as_of) : null;
    const tourStep = TOUR[s.tour - 1] || TOUR[0];
    const user = s.user || {};
    const initials = (user.name || "??").split(/\s+/).map((w) => w[0] || "").join("").slice(0, 2).toUpperCase();

    const recentActs = (((d.activity || {}).activity) || []).slice(0, 4).map((a) => ({
      text: (a.actor ? a.actor + " — " : "") + (a.detail || a.action), when: daysAgo(a.ts).replace(" ago", "") }));

    return {
      // rail
      navGroups,
      navStyle: "flex:1;overflow-y:auto;overflow-x:hidden;padding:" + (wide ? "6px 8px 8px" : "6px 7px 8px"),
      railCol: s.railPin === "open" ? RAIL_W + "px" : RAIL_N + "px",
      railWide: wide, railNarrow: !wide,
      railStyle: "border-right:1px solid var(--ln);background:var(--pn);display:flex;flex-direction:column;position:sticky;top:0;height:100vh;z-index:40;overflow:hidden;transition:width .36s " +
        (wide ? "cubic-bezier(.3,1.36,.4,1)" : "cubic-bezier(.4,.08,.16,1)") + ",box-shadow .32s ease" +
        (s.railPin === "open" ? ";width:" + RAIL_W + "px" : ";width:" + (wide ? RAIL_W : RAIL_N) + "px;box-shadow:" + (wide ? "var(--shp)" : "none")),
      toggleRail: App.toggleRail,
      brandRowStyle: "height:50px;display:flex;align-items:center;gap:" + (wide ? "8px" : "0") + ";padding:0 " + (wide ? "8px 0 6px" : "0") +
        ";border-bottom:1px solid var(--ln);flex:none;position:relative;justify-content:" + (wide ? "flex-start" : "center"),
      railPinnedAria: s.railPin !== "auto" ? "true" : "false",
      railPinAria: s.railPin === "open"
        ? "Rail pinned open. Select to unpin it, so it opens when you point at it and closes when you leave."
        : s.railPin === "closed"
        ? "Rail pinned closed. Select to unpin it, so it opens when you point at it."
        : "Rail unpinned. Select to pin it open.",
      railPinStyle: "margin-left:auto;margin-right:2px;flex:none;width:22px;height:22px;display:grid;place-content:center;border-radius:5px;border:1px solid " +
        (s.railPin === "auto" ? "transparent" : "var(--ac)") + ";background:" + (s.railPin === "auto" ? "transparent" : "var(--as)") +
        ";color:" + (s.railPin === "auto" ? "var(--ft)" : "var(--ac)"),
      railPinIconStyle: "width:15px;height:15px;display:block;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round",
      railPinFill: s.railPin === "auto" ? "none" : "currentColor",
      railPinSlash: s.railPin === "auto" ? "M4 20 20 4" : "",

      jobCardWrap: "padding:" + (wide ? "9px 12px " + (s.jobsOpen ? "0" : "3px") : "8px 7px 3px") + ";flex:none",
      jobCardStyle: "border:1px solid " + (s.jobsOpen ? "var(--ls)" : "var(--ln)") + ";border-radius:" + (s.jobsOpen ? "7px 7px 0 0" : "7px") +
        ";background:var(--p2);overflow:hidden" + (s.jobsOpen ? ";border-bottom-color:var(--ln)" : ""),
      jobQuery: s.jobQuery, onJobQuery: (e) => App.onJobQuery(e), openJobs: () => App.openJobs(),
      jobsOpen: s.jobsOpen && wide, jobsExpanded: s.jobsOpen ? "true" : "false",
      jobPlaceholder: "Search jobs by number or name",
      jobInputStyle: "width:100%;box-sizing:border-box;min-height:var(--tap);padding:8px 11px;border:none;background:var(--pn);font-size:12.5px;display:block",
      jobCurrentNum: (s.job || "No job") + (jd.as_of ? " · open now" : ""),
      jobCurrentName: job.job_name || (s.job ? "" : "Search for a job to begin"),
      jobListHeading: s.jobQuery.trim() ? "Matching jobs" : "Jobs",
      jobList: (s.jobHits || []).map((j) => ({
        num: j.job_number, name: j.job_name || "", status: j.financial_status || "",
        seen: j.job_status || "", pick: App.pickJob(j.job_number) })),
      jobsEmpty: (s.jobHits || []).length === 0,

      userInitials: initials, userName: user.name || "", userRole: user.is_admin ? "Administrator" : "Project team",
      userRowStyle: "border-top:1px solid var(--ln);padding:" + (wide ? "8px 12px 9px" : "8px 7px 9px") + ";flex:none",
      userJustify: wide ? "flex-start" : "center",
      openSettings: App.openSettings, closeSettings: App.closeSettings,
      settingsOpen: s.settingsOpen,

      toggleVista: () => setState({ vistaExpanded: !s.vistaExpanded }),
      vistaExpandedAria: s.vistaExpanded ? "true" : "false",
      vistaStale,
      vistaFull: vistaStale ? "Vista connection stale — last extract " + (vistaAsOf || "unknown") : "Vista data current to " + (vistaAsOf || "…"),
      vistaText: (s.vistaExpanded || vistaStale)
        ? (vistaStale ? "Connection stale" : "Current to " + (vistaAsOf || "…"))
        : "Data connected",
      vistaStyle: "margin:7px 0 0;width:100%;display:inline-flex;align-items:center;justify-content:" + (wide ? "flex-start" : "center") +
        ";gap:7px;min-height:" + (wide ? "32px" : "34px") + ";font:500 10.5px var(--fm);letter-spacing:.06em;padding:5px " + (wide ? "10px" : "4px") + ";border-radius:7px;border:1px solid " +
        (vistaStale ? "var(--wn)" : "var(--ln)") + ";background:" + (vistaStale ? "var(--wns)" : "var(--p2)") + ";color:" + (vistaStale ? "var(--wn)" : "var(--mu)") + ";white-space:nowrap",
      vistaTextStyle: "overflow:hidden;text-overflow:ellipsis;white-space:nowrap",
      vistaDotStyle: "width:7px;height:7px;border-radius:50%;flex:none;background:" + (vistaStale ? "var(--wn)" : "var(--ok)") +
        ";box-shadow:0 0 0 3px " + (vistaStale ? "var(--wns)" : "var(--oks)"),

      // header + search
      jobNumber: s.job || "",
      query: s.query, onQuery: (e) => App.onQuery(e), onSearchFocus: () => App.onSearchFocus(),
      searchOpen: s.searchOpen, results,
      resultSummary: results.length === 0
        ? "Nothing on this job matches “" + s.query + "”. Try a number like CO-04 or a vendor name."
        : results.length + (results.length === 1 ? " match" : " matches") + " for “" + s.query + "”",
      clearSearch: () => App.clearSearch(),

      // attention
      toggleAttn: () => { clearTimeout(App._attnT); setState({ attnOpen: !s.attnOpen, attnTouched: true }); },
      attnControls: "attention-panel",
      attnHasAny: attnItems.length > 0,
      attnOpen: s.attnOpen, attnExpanded: s.attnOpen ? "true" : "false",
      attnCol: s.attnOpen ? "308px" : "0px",
      attnCount: attnItems.length, attnItems, attnEmpty: attnItems.length === 0,
      attnCountStyle: "background:" + (attnItems.length ? "var(--er)" : "var(--ok)") + ";color:#fff;border-radius:999px;font:700 10px var(--fm);padding:3px 7px;letter-spacing:.02em",
      attnBtnStyle: "display:inline-flex;align-items:center;gap:8px;min-height:var(--tap);padding:6px 12px;border-radius:999px;flex:none;border:1px solid " +
        (s.attnOpen ? "var(--ac)" : "var(--ln)") + ";background:" + (s.attnOpen ? "var(--as)" : "var(--p2)") +
        ";color:" + (s.attnOpen ? "var(--ac)" : "var(--mu)") + ";font:600 12.5px var(--fd);letter-spacing:.03em;white-space:nowrap",
      attnActivity: recentActs,
      goActivity: App.go("activity"),

      // scaffold
      crumbs,
      pageEyebrow: meta[0], pageTitle: meta[1], pagePurpose: meta[2], nextStepLabel: meta[3],
      pageActions: this.pageActions(),
      liveMessage: s.live,

      // stage
      splashOn: s.stage === "splash",
      loginOn: s.stage === "login",
      auth: s.auth,
      setAuthField: App.setAuthField, switchAuthMode: App.switchAuthMode,
      signIn: () => App.signIn(),

      // undo
      undoOpen: !!s.undo, undoMessage: s.undo ? s.undo.message : "",
      doUndo: () => App.doUndo(), dismissUndo: App.dismissUndo,

      // overlays
      keysOpen: s.keysOpen,
      closeKeys: () => setState({ keysOpen: false }),
      tourOpen: s.tour > 0,
      tourStepLabel: "Step " + s.tour + " of " + TOUR.length,
      tourTitle: tourStep.title, tourBody: tourStep.body,
      tourHasBack: s.tour > 1,
      tourNextLabel: s.tour >= TOUR.length ? "Start using PlanWise" : "Next",
      tourNext: () => App.tourNext(), tourBack: () => App.tourBack(), endTour: () => App.endTour(),
      tourDots: TOUR.map((t, i) => ({ style: "width:7px;height:7px;border-radius:50%;background:" + (i < s.tour ? "var(--ac)" : "var(--ls)") })),

      appearanceRows: [
        { label: "Theme", note: "Light for the office, dark for a night shift or a dim trailer.",
          options: [["Light", "light"], ["Dark", "dark"]].map(([label, val]) => ({
            label, pressed: s.theme === val ? "true" : "false",
            pick: () => { if (s.theme !== val) App.toggleTheme(); }, style: chip(s.theme === val) })) },
        { label: "Accent colour", note: "The one orange action wears this. Pick what reads best on your screen.",
          options: [["Safety orange", null], ["Clay", "#B4531E"], ["Blueprint", "#1E5F8C"], ["Bronze", "#7A5C1F"]].map(([label, val]) => ({
            label, pressed: (s.accent || null) === val ? "true" : "false",
            pick: App.setAccent(val), style: chip((s.accent || null) === val),
            swatch: "width:11px;height:11px;border-radius:3px;background:" + (val || "#C7420A") + ";flex:none" })) },
        { label: "Field mode", note: "Larger targets and text, and raised contrast for bright sun and gloved hands.",
          options: [["Off", "desk"], ["On", "field"]].map(([label, val]) => ({
            label, pressed: s.mode === val ? "true" : "false",
            pick: () => { if (s.mode !== val) App.toggleField(); }, style: chip(s.mode === val) })) },
        { label: "Row density", note: "Roomy is easier to read; compact fits more of a long register on screen.",
          options: [["Roomy", "comfortable"], ["Compact", "compact"]].map(([label, val]) => ({
            label, pressed: s.density === val ? "true" : "false",
            pick: () => { if (s.density !== val) App.toggleDensity(); }, style: chip(s.density === val) })) },
      ],
      helpRows: [
        { label: "Keyboard shortcuts", note: "Every shortcut, and the order the Tab key moves through the page.",
          icon: "M3 6h18v12H3V6Zm4 3h.01M11 9h.01M15 9h.01M7 13h10",
          click: () => setState({ settingsOpen: false, keysOpen: true }) },
        { label: "Replay the guided tour", note: "Four steps covering the rail, the one orange action, the attention panel and undo.",
          icon: "M12 21a9 9 0 1 0-9-9m0 0V7m0 5h5m5.5-1.5L12 12",
          click: () => setState({ settingsOpen: false, tour: 1 }) },
        { label: "Sign out", note: "Ends this session on this device. Your drafts and registers stay on the server.",
          icon: "M9 21H5V3h4M16 17l5-5-5-5M21 12H9",
          click: () => App.signOut() },
      ],
      settingsExtra: "",

      // page bodies
      ...this.buildConfirm(),
      ...this.buildRegister(),
      ...this.buildDetail(),
      ...this.buildForm(),
      ...(typeof buildPageVals === "function" ? buildPageVals(this) : {}),
    };
  },

  template(v) {
    const s = this.state;
    if (s.stage === "splash") return uiSkipLinks() + uiSplash(v);
    if (s.stage === "login") return uiLogin({ ...v, loginOn: true });
    return uiSkipLinks()
      + `<div style="display:grid;grid-template-columns:${v.railCol} minmax(0,1fr);min-height:100vh;background:var(--bg)">
        ${uiRail(v)}
        <div style="display:flex;flex-direction:column;min-width:0">
          ${uiHeader(v)}
          <div style="display:grid;grid-template-columns:minmax(0,1fr) ${v.attnCol};align-items:start">
            <main id="main-content" style="min-width:0;padding:0 0 80px">
              ${uiScaffold(v)}
              <div style="padding:16px 20px 0">
                ${typeof pageBody === "function" ? pageBody(s.page, v) : ""}
                ${uiRegister(v)}
              </div>
            </main>
            ${uiAttention(v)}
          </div>
        </div>
      </div>`
      + uiConfirm(v) + uiDetail(v) + uiForm(v) + uiSettings(v) + uiKeys(v) + uiTour(v) + uiUndo(v);
  },
});
