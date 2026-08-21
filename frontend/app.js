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
    railPin: (() => { try { const v = localStorage.getItem("pw.railPin"); return v === "open" || v === "closed" || v === "auto" ? v : "open"; } catch (e) { return "open"; } })(),
    railHover: false,
    isMobile: false, mobileNav: false,
    jobsOpen: false, jobQuery: "", jobHits: [],

    // — header / search
    query: "", searchOpen: false,

    // — attention
    attnOpen: true, attnTouched: false,

    // — vista pill
    vistaExpanded: true,

    // — overlays
    settingsOpen: false, keysOpen: false, tour: 0,
    confirm: null, detail: null, form: null, co: null,
    viewer: null,

    // — registers
    regSort: { col: null, dir: 1 }, poFilter: "All", recFilter: "All",

    // — schedule interactions
    schedCollapsed: {}, schedPeek: null, schedDrag: null,
    schedZoom: 1, schedStaged: null,
    replyEdit: null,
    tool: "Pin", ink: "#A9291D", weight: 2.5, zoom: 1, markText: "",
    briefAudience: "customer",
    shareOpen: false, recipients: {}, shareItems: {},

    // — CO composer + PO import
    coPreview: true, coNewClar: "", poImport: null,

    // — undo + announcements
    undo: null, live: "",
  },

  // ————— boot —————————————————————————————————————————————————————————————
  async boot() {
    Object.assign(this.state, loadPrefs());
    applyChrome();
    document.addEventListener("keydown", (e) => this.onKey(e));
    window.addEventListener("hashchange", () => this.route());
    window.addEventListener("focus", () => App.detectSent());

    // Phones get the drawer shell; coarse pointers with no saved preference
    // get field mode (bigger targets) without being asked.
    const mq = matchMedia("(max-width: 860px)");
    this.state.isMobile = mq.matches;
    const onMq = (e) => setState({ isMobile: e.matches, mobileNav: false });
    if (mq.addEventListener) mq.addEventListener("change", onMq); else mq.addListener(onMq);
    try {
      const prefs = JSON.parse(localStorage.getItem("pw.prefs") || "{}");
      if (!prefs.mode && matchMedia("(pointer: coarse)").matches)
        document.documentElement.dataset.mode = "field";
    } catch (e) {}

    // Splash on EVERY fresh page load, signed in or not — the owner's
    // 2026-08-20 call, overriding resolved decision #10's once-per-session
    // model. Hash navigation inside the app never reloads the document, so
    // this fires only when the page itself starts.
    const splashed = false;
    this.state.stage = "splash";
    this._splashT = setTimeout(() => this.afterSplash(), 6200);

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
    this.initOffline();
    // The service worker registers only once 2.0 IS the root app — at /v2
    // (the dev mount) a root-scoped worker would hijack the 1.x shell.
    if ("serviceWorker" in navigator && !location.pathname.startsWith("/v2")) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
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
    const fj = (this._status || {}).field_jobs || [];
    if (fj.length) { this.state.stage = "app"; this.enterFieldShell(); return; }
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
    if (App.state.mobileNav) App.state.mobileNav = false;
    const job = App.state.job;
    if (!job) return;
    location.hash = "#/job/" + encodeURIComponent(job) + "/" + page + (sub ? "/" + sub : "");
  },

  async loadFor(page, jobChanged) {
    const job = this.state.job;
    if (!job) return;
    const want = new Set(["job", "attention"]);
    if (this.state.shell === "field") {
      ["job", "lookahead", "areas", "documents", "records", "attention"].forEach((k) => want.add(k));
    }
    if (page === "dash") want.add("history");
    if (page === "sched") { want.add("schedule"); this.loadStagedImport && this.loadStagedImport(); }
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
      if (h.banner && document.title.indexOf("sandbox") < 0) document.title = "PlanWise — sandbox";
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
  pinRail: (next) => () => {
    clearTimeout(App._railT);
    try { localStorage.setItem("pw.railPin", next); } catch (e) {}
    setState({ railPin: next, jobsOpen: false,
      railHover: next === "auto" ? App.state.railPin === "open" : false,
      live: next === "open" ? "Rail pinned open."
        : next === "closed" ? "Rail pinned closed. It stays as icons until you unpin it."
        : "Rail unpinned. It opens when you point at it and closes when you leave." });
  },

  // The collapsed job button: open the rail to switch jobs, without leaving
  // it stuck open — a closed pin softens to auto so it tucks away after.
  expandRail() {
    clearTimeout(App._railT);
    if (App.state.railPin === "closed") {
      try { localStorage.setItem("pw.railPin", "auto"); } catch (e) {}
    }
    setState({ railPin: App.state.railPin === "open" ? "open" : "auto", railHover: true });
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
    const kinds = refreshKinds || ["job"];
    setState({ undo: { message, activityId, refreshKinds: kinds }, live: message });
    // The mutation happened server-side; every act() pulls the fresh truth
    // (and the attention list, which is derived from it) back down.
    App.refresh(...kinds);
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

  openViewer: (docId, page, mode, ctx) => () => {
    setState({ viewer: { docId, page: page || 1, mode: mode || "markup", ctx: ctx || {}, compare: null } });
  },

  afterRender() {
    if (this.state.viewer) this.paintViewerCanvases();
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
        caption: "Estimate, cost this month, actual cost, open purchase order commitments, approved work with no purchase order, committed total, share of estimate committed, projection and variance for each cost type on job " + s.job + ". Select a cost type to audit its phase codes and commitments.",
        footnote: "Estimate, month to date, actual and projected come from the nightly Vista extract. Open committed is recalculated from this job's purchase order register — the remaining amount on every open order, grouped by cost type — so the two screens can never disagree. Approved work with no purchase order is counted separately because it is exposure, not a commitment: nothing has been ordered against it yet.",
        columns: [["Cost type", 0, 1], ["Estimate", 1, 1], ["This month", 1, 1], ["Actual", 1, 1], ["Open PO", 1, 1], ["No PO", 1, 1], ["Committed", 1, 1], ["Of estimate", 0, 1], ["Projected", 1, 1], ["Variance", 1, 1]],
        rows, total: ["All cost types", [money(estTotal), money(tot("mtd_cost")), money(actTotal), money(openTotal), uncTotal ? money(uncTotal) : "none", money(actTotal + openTotal),
          estTotal ? ((actTotal + openTotal) / estTotal * 100).toFixed(1) + "% committed" : "",
          money(tot("projected_cost")), signed(estTotal - actTotal === 0 ? 0 : tot("variance"))]] };
    }

    if (s.page === "sched") {
      const tasks = App.schedTasks();
      const rows = tasks.map((t, ti) => {
        const critical = !!t.is_critical;
        const pct = Math.round(t.percent_complete || 0);
        const primary = App.primaryPred(t.id);
        const predName = primary ? ((tasks.find((x) => x.id === primary.pred_id) || {}).external_id || "?") : "";
        return { id: t.id, key: t.name || "?",
          keySub: "Task " + (t.external_id || "—") + (t.outline_level ? " · level " + t.outline_level : "") + (predName ? " · after " + predName + " " + (primary.link_type || "FS") : ""),
          sortVals: [t.name, t.duration_days, t.start, t.finish, pct, t.total_float],
          edge: taskColor(t.external_id || ti + 1), sched: App.schedRowProps(ti),
          cells: [P(t.duration_days !== null && t.duration_days !== undefined ? Math.round(t.duration_days) + " d" : "—", 1), P(t.start || ""), P(t.finish || ""),
            { kind: "bar", text: pct + "%", w: pct, color: pct === 0 ? "var(--ls)" : taskColor(t.external_id || ti + 1) },
            P(t.total_float === null || t.total_float === undefined ? "—" : Math.round(t.total_float) + " d", 1),
            S(t.is_summary ? "Summary" : critical ? "Critical" : "Has float")] };
      });
      return { title: "Schedule tasks", source: tasks.length + " tasks · " + (((s.data.schedule || {}).critical_count) || 0) + " on the critical path", kind: "task",
        caption: "Schedule tasks on job " + s.job + " with duration, start, finish, percent complete, float and whether the task is on the critical path. Select a task name to edit it.",
        footnote: "Float is in working days on the job calendar, computed by the engine — never typed. Tasks with zero float move the finish date if they slip. Drag the ⠿ grip to reorder rows, or open + to edit dates, predecessor, successors and dependency type in place — the Gantt follows every change. Tasks added or edited in PlanWise keep their changes when the customer's schedule is re-imported.",
        columns: [["Task", 0, 1], ["Duration", 1, 1], ["Start", 0, 1], ["Finish", 0, 1], ["Complete", 0, 1], ["Float", 1, 1], ["Path", 0, 0]],
        rows, noSort: !!s.schedDrag, emptyText: "No tasks yet. Import a schedule or add the first task." };
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
    const colStyle = (right) => "padding:9px 10px;font:500 var(--lbl) var(--fm);letter-spacing:.09em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln);white-space:nowrap;text-align:" + (right ? "right" : "left");

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
        headStyle: "text-align:left;font-weight:600;padding:var(--cellY) 10px;border-bottom:1px solid var(--ln);max-width:320px" +
          (r.edge ? ";border-left:3px solid " + r.edge : ""),
        key: r.key, keySub: r.keySub, open: App.openDetail(spec.kind, r.id),
        cells: r.cells.map((c) => ({
          isStamp: c.kind === "stamp", isBar: c.kind === "bar", isPlain: c.kind === "plain",
          text: c.text, stampStyle: c.kind === "stamp" ? stamp(STATUS_TONE[c.text] || "nt") : "",
          barW: (c.w || 0).toFixed(0) + "%", barColor: c.color || "var(--bp)",
          style: "padding:var(--cellY) 10px;border-bottom:1px solid var(--ln)" + align(c.right) +
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
      regTotalCells: spec.total ? spec.total[1].map((t, i) => ({ text: t, style: "padding:12px 10px;font:600 var(--fz) var(--fd);border-top:1px solid var(--ls);font-variant-numeric:tabular-nums;text-align:" + (spec.columns[i + 1] && spec.columns[i + 1][1] ? "right" : "left") })) : [],
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
          id: "ff-" + id, label, type: type === "textarea" || type === "select" ? "text" : type,  // password passes through
          isInput: type === "text" || type === "date" || type === "password", isArea: type === "textarea", isSelect: type === "select",
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
      case "brief": return [mk("Choose recipients and send", "primary", App.openShareWith(this.state.briefAudience === "team" ? { "brief-int": true } : { "brief-cust": true })), mk("Preview the PDF", "ghost", todo("The briefing PDF"))];
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
      case "look": return [mk("Share the look ahead", "primary", App.openShareWith({ "look-cust": true })), mk("Seed it from the schedule", "ghost", () => App.seedLook ? App.seedLook() : null)];
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

    // The phone drawer is always the full rail — labels, job card, groups.
    const wide = s.isMobile || s.railPin === "open" || (s.railPin === "auto" && s.railHover);
    const navGroups = NAV.map(([label, ab, items], gi) => ({
      id: "nav-group-" + gi,
      label: wide ? label : ab,
      groupStyle: wide ? "margin-bottom:6px" : "margin-bottom:4px;padding-bottom:4px;border-bottom:1px solid var(--ln)",
      headStyle: wide
        ? "margin:0;padding:4px 10px 2px;font:500 var(--lbl) var(--fm);letter-spacing:.18em;text-transform:uppercase;color:var(--ft);text-align:left"
        : "margin:0;padding:0 0 4px;font:600 8px var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft);text-align:center",
      items: items.map(([key, lbl, badgeKey]) => {
        const on = key === s.page;
        const badge = badgeCounts[badgeKey] !== undefined ? badgeCounts[badgeKey] : badgeKey;
        return {
          label: lbl, icon: ICONS[key], showLabel: wide, showIcon: true,
          badge: badge || "",
          aria: badge ? lbl + ", " + badge + " needing attention" : lbl,
          current: on ? "page" : "false",
          go: App.go(key),
          style: wide
            ? "width:100%;min-height:30px;display:flex;align-items:center;gap:8px;padding:4px 8px;border-radius:6px;font:600 13px var(--fd);letter-spacing:.02em;text-align:left;position:relative;color:" +
              (on ? "var(--ink)" : "var(--mu)") + ";background:" + (on ? "var(--as)" : "transparent")
            : "width:100%;min-height:30px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0;padding:3px 2px;border-radius:7px;position:relative;color:" +
              (on ? "var(--ac)" : "var(--mu)") + ";background:" + (on ? "var(--as)" : "transparent") + ";border:1px solid " + (on ? "var(--ac)" : "transparent"),
          edge: wide
            ? "width:3px;height:16px;border-radius:2px;flex:none;background:" + (on ? "var(--ac)" : "transparent")
            : "display:none",
          iconStyle: "width:18px;height:18px;flex:none;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round",
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
      // On phones the rail is position:fixed — OUT of grid flow — so its
      // track must not exist at all: a fixed child does not occupy its cell,
      // and the page content would land in the 0px rail column and lay out
      // zero-wide, painting only by overflow (the 2026-08-20 phone jank).
      railCol: s.isMobile ? "" : (s.railPin === "open" ? RAIL_W + "px" : RAIL_N + "px"),
      railWide: wide, railNarrow: !wide,
      railStyle: s.isMobile
        ? "position:fixed;left:0;top:0;bottom:0;width:min(280px,84vw);z-index:126;background:var(--pn);border-right:1px solid var(--ls);display:flex;flex-direction:column;overflow:hidden;box-shadow:var(--shp);transition:transform .3s cubic-bezier(.3,1,.4,1);transform:" +
          (s.mobileNav ? "translateX(0)" : "translateX(-105%)")
        : "border-right:1px solid var(--ln);background:var(--pn);display:flex;flex-direction:column;position:sticky;top:0;height:100vh;z-index:40;overflow:hidden;transition:width .36s " +
        (wide ? "cubic-bezier(.3,1.36,.4,1)" : "cubic-bezier(.4,.08,.16,1)") + ",box-shadow .32s ease" +
        (s.railPin === "open" ? ";width:" + RAIL_W + "px" : ";width:" + (wide ? RAIL_W : RAIL_N) + "px;box-shadow:" + (wide ? "var(--shp)" : "none")),
      railScrim: s.isMobile && s.mobileNav,
      mobileMenu: s.isMobile,
      mobileNavOpen: s.mobileNav,
      toggleMobileNav: () => setState({ mobileNav: !App.state.mobileNav }),
      closeMobileNav: () => setState({ mobileNav: false }),
      railPinGo: wide
        ? App.pinRail(s.railPin === "open" ? "closed" : "open")
        : App.pinRail(s.railPin === "closed" ? "auto" : "closed"),
      expandRail: () => App.expandRail(),
      brandRowStyle: wide
        ? "height:50px;display:flex;align-items:center;gap:8px;padding:0 8px 0 6px;border-bottom:1px solid var(--ln);flex:none;position:relative;justify-content:flex-start"
        : "display:flex;flex-direction:column;align-items:center;gap:3px;padding:6px 0 5px;border-bottom:1px solid var(--ln);flex:none;position:relative",
      railPinnedAria: s.railPin !== "auto" ? "true" : "false",
      railPinAria: wide
        ? (s.railPin === "open"
          ? "Rail pinned open. Select to pin it closed — icons only, no opening as you point at it."
          : "Rail unpinned. Select to pin it open.")
        : (s.railPin === "closed"
          ? "Rail pinned closed. Select to unpin it, so it opens when you point at it."
          : "Select to pin the rail closed — icons only."),
      railPinStyle: (wide ? "margin-left:auto;margin-right:2px;width:22px;height:22px;" : "width:20px;height:20px;") +
        "flex:none;display:grid;place-content:center;border-radius:5px;border:1px solid " +
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
      attnBtnLabel: s.isMobile ? "Attention" : "Needs attention",
      attnMobile: s.isMobile,
      attnPanelStyle: s.isMobile
        ? "position:fixed;inset:50px 0 0 0;width:auto;z-index:118;background:var(--pn);overflow-y:auto;animation:fadein .18s ease-out"
        : "width:308px;border-left:1px solid var(--ln);background:var(--pn);position:sticky;top:50px;height:calc(100vh - 50px);overflow-y:auto;animation:fadein .18s ease-out",
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
      devBanner: ((d.health || {}).banner) || "",
      splashOn: s.stage === "splash",
      loginOn: s.stage === "login",
      auth: s.auth,
      setAuthField: App.setAuthField, switchAuthMode: App.switchAuthMode,
      signIn: () => App.signIn(),

      // undo
      undoOpen: !!s.undo, undoMessage: s.undo ? s.undo.message : "",
      undoBottom: s.shell === "field" ? "170px" : "22px",
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
      settingsExtra: this.buildSettingsExtra(),

      // Offline + outbox bars (1.x surfaces, token-styled)
      netBar: (() => {
        const net = s.net || {};
        if (net.online === false) return { tone: "var(--er)", soft: "var(--ers)",
          text: "Offline. Reads come from the last copy this device held" +
            (net.pending ? "; " + net.pending + (net.pending === 1 ? " change is queued" : " changes are queued") + " to send when the connection returns." : "."),
          retry: null };
        if (net.servedAt) return { tone: "var(--wn)", soft: "var(--wns)",
          text: "Showing data from " + daysAgo(net.servedAt) + " — the server could not be reached.",
          retry: () => location.reload() };
        return null;
      })(),
      outboxBar: (() => {
        const items = (s.data.outbox || []).filter((i) => !i.drafted_at);
        if (!items.length) return null;
        return {
          text: items.length + (items.length === 1 ? " send queued from the field is waiting for a desk with Outlook." : " sends queued from the field are waiting for a desk with Outlook."),
          drain: () => App.drainOutbox(),
          emlOne: items.length === 1 ? App.outboxEml(items[0].id) : null,
        };
      })(),

      // POs page: exposure + import review view models
      poImport: s.poImport ? {
        filename: s.poImport.filename, warnings: s.poImport.warnings,
        rows: s.poImport.rows,
        poImportSet: App.poImportSet,
        poImportAccept: () => App.poImportAccept(),
        poImportDiscard: () => setState({ poImport: null }),
      } : null,
      poImportSet: App.poImportSet,
      poImportAccept: () => App.poImportAccept(),
      poImportDiscard: () => setState({ poImport: null }),
      poImportCostTypes: [...new Set((jd.cost_types || []).map((c) => c.cost_type))],
      uncovered: ((jd.approved_no_po || {}).cos || []).map((u) => ({
        n: u.co_number || "?", sub: u.subcontractor || "", desc: u.description || "",
        amt: money(u.amount_approved), issue: App.issuePoFromCo(u.id) })),
      uncoveredTotal: money((jd.approved_no_po || {}).total || 0),

      // page bodies
      ...this.buildConfirm(),
      ...this.buildCO(),
      ...this.buildSched(),
      ...this.buildLook(),
      ...this.buildThread(),
      ...this.buildViewer(),
      ...this.buildShare(),
      ...this.buildField(),
      ...this.buildBrief(),
      ...this.buildRegister(),
      ...this.buildDetail(),
      ...this.buildForm(),
      ...(typeof buildPageVals === "function" ? buildPageVals(this) : {}),
    };
  },

  template(v) {
    const s = this.state;
    if (s.stage === "splash") return uiSkipLinks() + uiSplash(v);
    if (s.stage === "app" && s.shell === "field")
      return uiFieldApp(v) + uiConfirm(v) + uiForm(v) + uiViewer(v) + uiShare(v) + uiUndo(v) + uiBars(v);
    if (s.stage === "login") return uiLogin({ ...v, loginOn: true });
    return uiSkipLinks()
      + `<div style="display:grid;grid-template-columns:${v.railCol} minmax(0,1fr);min-height:100vh;background:var(--bg)">
        ${uiRail(v)}
        <div style="display:flex;flex-direction:column;min-width:0">
          ${uiHeader(v)}
          <div style="display:grid;grid-template-columns:minmax(0,1fr) ${v.attnMobile ? "0px" : v.attnCol};align-items:start">
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
      + uiConfirm(v) + uiDetail(v) + uiForm(v) + uiCO(v) + uiViewer(v) + uiShare(v) + uiSettings(v) + uiKeys(v) + uiTour(v) + uiUndo(v) + uiBars(v);
  },
});

// ————— companion send ladder (1.x logic, kept: LOGIC-MERGE) ————————————————
// Try the local Outlook companion; a NETWORK failure means "no companion on
// this machine" (normal on a phone) and falls to the .eml download, while a
// companion that answered and refused shows its real message. Both paths
// still deliver something.
const COMPANION = "http://127.0.0.1:8772";
let companionToken = null;

async function companionFetch(path, body) {
  if (companionToken === null) companionToken = (await api("/api/companion/token")).token;
  const r = await fetch(COMPANION + path, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, token: companionToken }) });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(out.detail || "Companion error " + r.status);
  return out;
}
const isNetErr = (err) => /failed to fetch|networkerror|load failed|connection refused/i.test(err.message || "");

function downloadEmlUrl(url, live) {
  // Binary response, cookie rides along; synthesized <a download>.
  fetch(url, { credentials: "same-origin" }).then(async (r) => {
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
    const blob = await r.blob();
    const cd = r.headers.get("content-disposition") || "";
    const name = (/filename="?([^\";]+)"?/.exec(cd) || [])[1] || "planwise.eml";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    if (live) setState({ live });
  }).catch((err) => setState({ live: "Could not download the email file: " + err.message }));
}

// ————— change order composer (prototype chrome; real endpoints) ————————————
Object.assign(App, {
  nextCoNumber(kind) {
    const cos = ((this.state.data.job || {}).change_orders || []).filter((c) => c.kind === kind);
    const max = cos.reduce((m, c) => Math.max(m, parseInt(String(c.co_number || "").replace(/[^0-9]/g, "")) || 0), 0);
    const n = max + 1;
    return (kind === "subcontractor" ? "S-" : "") + (n < 10 ? "0" : "") + n;
  },

  // "Compose a change order" CREATES the row first (as Unsent), then opens
  // the composer on it — a real id from the first keystroke is what lets the
  // preview pane show the real letter PDF instead of a simulation.
  openCO: (id, kind) => async () => {
    const job = App.state.job;
    try {
      let co;
      let isNew = false;
      if (!id) {
        isNew = true;
        co = await api(`/api/jobs/${encodeURIComponent(job)}/cos`, { method: "POST",
          body: JSON.stringify({ kind: kind || "customer", co_number: App.nextCoNumber(kind || "customer"),
            status: "Unsent", date_submitted: new Date().toISOString().slice(0, 10) }) });
        App.refresh("job");
      } else {
        co = ((App.state.data.job || {}).change_orders || []).find((c) => c.id === id);
        if (!co) throw new Error("No such change order.");
      }
      const [items, sel, lib] = await Promise.all([
        api(`/api/jobs/${encodeURIComponent(job)}/cos/${co.id}/items`),
        api(`/api/jobs/${encodeURIComponent(job)}/cos/${co.id}/clarifications`),
        api("/api/co-clarifications"),
      ]);
      App.state.data.clarifications = lib;
      const clar = {};
      const libRows = lib.clarifications || [];
      (sel.clarifications || []).forEach((c) => {
        const hit = libRows.find((l) => l.text === (c.text || c));
        if (hit) clar[hit.id] = true;
      });
      setState({ co: {
        id: co.id, kind: co.kind, isNew,
        num: co.co_number || "", cust: co.cust_co_number || "",
        date: co.date_submitted || new Date().toISOString().slice(0, 10),
        cause: co.raised_from || "", desc: co.description || "",
        narrative: co.narrative || "", subcontractor: co.subcontractor || "",
        status: co.status || "Unsent",
        items: (items.items || []).length ? (items.items || []).map((i) => ({ desc: i.description || "", amt: i.amount === null ? "" : String(i.amount) })) : [{ desc: "", amt: "" }],
        clar, submitted: false, touched: false, previewRev: 0, saving: false,
      }, coPreview: !App.state.isMobile, coNewClar: "" }, focusRef("co"));
      App.refreshCoPreview();
    } catch (err) {
      setState({ live: "Could not open the composer: " + err.message });
    }
  },

  coClose: async () => {
    const co = App.state.co;
    setState({ co: null });
    // A CO created empty and abandoned untouched is deleted quietly — closing
    // an accidental composer must not leave a blank row on the register.
    if (co && co.isNew && !co.touched && !co.desc && !co.narrative &&
        !co.items.some((i) => i.desc.trim() || String(i.amt).trim())) {
      try {
        await api(`/api/jobs/${encodeURIComponent(App.state.job)}/cos/${co.id}`, { method: "DELETE" });
        App.refresh("job");
      } catch (e) {}
    }
  },

  coSet: (key) => (e) => {
    const co = App.state.co;
    co[key] = e.target.value;
    co.touched = true;
    setState({});
    App.debouncedCoSave();
  },
  coSetItem: (i, key) => (e) => {
    const co = App.state.co;
    co.items = co.items.map((it, n) => n === i ? { ...it, [key]: e.target.value } : it);
    co.touched = true;
    setState({});
    App.debouncedCoSave();
  },
  coAddItem() { const co = App.state.co; co.items = co.items.concat([{ desc: "", amt: "" }]); co.touched = true; setState({}); },
  coRemoveItem: (i) => () => { const co = App.state.co; co.items = co.items.filter((it, n) => n !== i); co.touched = true; setState({}); App.debouncedCoSave(); },
  coToggleClar: (id) => () => {
    const co = App.state.co;
    co.clar = { ...co.clar, [id]: !co.clar[id] };
    co.touched = true;
    setState({});
    App.debouncedCoSave();
  },
  coSetNewClar(e) { setState({ coNewClar: e.target.value }); },
  coTogglePreview() { setState({ coPreview: !App.state.coPreview }); },

  async coAddClar() {
    const text = (App.state.coNewClar || "").trim();
    if (!text) { setState({ live: "Write the clarification before adding it." }); return; }
    try {
      const row = await api("/api/co-clarifications", { method: "POST", body: JSON.stringify({ text }) });
      const lib = await api("/api/co-clarifications");
      App.state.data.clarifications = lib;
      const co = App.state.co;
      co.clar = { ...co.clar, [row.id]: true };
      co.touched = true;
      setState({ coNewClar: "", live: "Clarification added to the library and ticked on this change order." });
      App.debouncedCoSave();
    } catch (err) {
      setState({ live: "Could not add it: " + err.message });
    }
  },

  coErrors(co) {
    const errs = [];
    if (co.kind === "customer") {
      if (!co.desc.trim()) errs.push("Description is required — it prints as the subject of the letter.");
      if (!co.date) errs.push("Date submitted is required.");
      if (!co.cause) errs.push("Say what raised this change order.");
      if (!co.narrative.trim()) errs.push("The narrative is required. It is what the customer reads to understand the entitlement.");
      const good = co.items.filter((i) => i.desc.trim() && parseFloat(String(i.amt).replace(/[^0-9.-]/g, "")));
      if (!good.length) errs.push("At least one breakout line needs a description and an amount.");
    } else {
      if (!co.desc.trim()) errs.push("Description is required — it is the line on the log.");
      if (!co.subcontractor.trim()) errs.push("Name the subcontractor.");
    }
    return errs;
  },

  // Persist the draft: fields + breakout lines + clarification selection.
  // Debounced 700ms so the letter preview tracks typing without a request
  // per keystroke (1.x behavior, kept).
  async coPersist() {
    const co = App.state.co;
    if (!co || co.saving) return;
    co.saving = true;
    try {
      const job = encodeURIComponent(App.state.job);
      await api(`/api/jobs/${job}/cos/${co.id}`, { method: "PATCH", body: JSON.stringify({
        co_number: co.num || null, cust_co_number: co.cust || null,
        date_submitted: co.date || null, description: co.desc || null,
        narrative: co.narrative || null, raised_from: co.cause || null,
        subcontractor: co.subcontractor || null }) });
      const items = co.items.filter((i) => i.desc.trim() || String(i.amt).trim())
        .map((i) => ({ description: i.desc.trim(), amount: parseFloat(String(i.amt).replace(/[^0-9.-]/g, "")) || 0 }));
      await api(`/api/jobs/${job}/cos/${co.id}/items`, { method: "PUT", body: JSON.stringify({ items }) });
      if (co.kind === "customer") {
        const lib = ((App.state.data.clarifications || {}).clarifications) || [];
        const texts = lib.filter((l) => co.clar[l.id]).map((l) => l.text);
        await api(`/api/jobs/${job}/cos/${co.id}/clarifications`, { method: "PATCH", body: JSON.stringify({ clarifications: texts }) });
      }
      App.refreshCoPreview();
      App.refresh("job");
    } catch (err) {
      setState({ live: "Could not save the draft: " + err.message });
    } finally {
      co.saving = false;
    }
  },
  debouncedCoSave: debounce(() => App.coPersist(), 700),

  refreshCoPreview() {
    const co = App.state.co;
    if (!co) return;
    co.previewRev++;
    setState({});
  },

  async coSubmit() { await App.coPersist(); const co = App.state.co; if (!co) return;
    const errs = App.coErrors(co);
    if (errs.length) { co.submitted = true; setState({ live: errs.length + " thing" + (errs.length === 1 ? "" : "s") + " to fix before this can be saved." }); return; }
    setState({ co: null, live: (co.num ? "CO-" + co.num : "The change order") + " saved as a draft. Nothing has gone to the customer." });
    App.refresh("job");
  },

  // Save-and-send: the 1.x companion ladder behind the prototype's button.
  async coSaveAndSend() {
    const co = App.state.co;
    if (!co) return;
    const errs = App.coErrors(co);
    if (errs.length) { co.submitted = true; setState({ live: errs.length + " thing" + (errs.length === 1 ? "" : "s") + " to fix before this can go out." }); return; }
    await App.coPersist();
    App.coSend(co.id, true)();
  },

  coSend: (coId, fromComposer) => async () => {
    const job = encodeURIComponent(App.state.job);
    let payload;
    try {
      payload = await api(`/api/jobs/${job}/cos/${coId}/share`);
    } catch (err) {
      if (err.body && err.body.needs_contact) {
        setState({ co: null, live: "This job has no customer contact with an email address yet. Taking you to Job setup to add one." });
        setTimeout(() => App.go("setup")(), 1400);
        return;
      }
      setState({ live: err.message });
      return;
    }
    try {
      await companionFetch("/draft", { to: payload.to, subject: payload.subject,
        body: payload.body, attachments: payload.attachments, display: true });
      const upd = await api(`/api/jobs/${job}/cos/${coId}`, { method: "PATCH",
        body: JSON.stringify({ status: "Awaiting Outlook" }) });
      setState({ co: null });
      App.act("The change order letter is drafted in Outlook with the PDF and Word copies attached. It shows as Awaiting Outlook until you press Send there.",
        upd.activity_id, ["job"]);
    } catch (err) {
      const eml = `/api/jobs/${job}/cos/${coId}/share.eml`;
      if (isNetErr(err)) {
        setState({ co: null, live: "No Outlook companion on this machine — downloading the email file instead. Open it and press Send." });
        downloadEmlUrl(eml, "Email file downloaded. Open it in Outlook and press Send.");
      } else {
        setState({ co: null, live: "The companion answered but refused: " + err.message + " — downloading the email file instead." });
        downloadEmlUrl(eml);
      }
    }
  },

  coDelete: (coId) => () => {
    const co = ((App.state.data.job || {}).change_orders || []).find((c) => c.id === coId) || {};
    setState({
      confirm: {
        eyebrow: "Remove a change order", title: "CO-" + (co.co_number || "?") + (co.description ? " · " + co.description : ""),
        body: "This removes the change order and its breakout lines from the register.",
        checks: [
          ["pass", "The register", "The register total drops by " + money(co.amount_submitted || 0) + " the moment this is removed."],
          [co.status === "Approved" ? "warn" : "pass", "Approval state", co.status === "Approved" ? "This change order shows as Approved. Vista's change order revenue will no longer reconcile against the register until the next extract explains it." : "It has not been approved, so nothing downstream references it."],
        ],
        blocked: false,
        verdict: "Removing is undoable — the reversal restores the row with its lines and clarifications.",
        label: "Remove this change order",
        run: async () => {
          try {
            await api(`/api/jobs/${encodeURIComponent(App.state.job)}/cos/${coId}`, { method: "DELETE" });
            const acts = await api(`/api/jobs/${encodeURIComponent(App.state.job)}/activity?limit=1`);
            setState({ confirm: null, detail: null });
            App.act("CO-" + (co.co_number || "?") + " removed from the register.", ((acts.activity || [])[0] || {}).id, ["job"]);
          } catch (err) { setState({ confirm: null, live: err.message }); }
        },
      },
    }, focusRef("confirm"));
  },

  buildCO() {
    const co = this.state.co;
    if (!co) return { coOpen: "" };
    const errs = this.coErrors(co);
    const num = (v) => parseFloat(String(v || "").replace(/[^0-9.-]/g, "")) || 0;
    const total = co.items.reduce((t, i) => t + num(i.amt), 0);
    const control = "width:100%;min-height:var(--tap);padding:8px 11px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)";
    const isCust = co.kind === "customer";
    const defs = isCust ? [
      ["num", "PlanWise number", "text", { hint: "Assigned in sequence. Change it only to match paper already in the file." }],
      ["cust", "Customer change order number", "text", { placeholder: "CUST-0000", hint: "Leave blank. The customer assigns this on receipt." }],
      ["date", "Date submitted", "date", { req: true, hint: "The date the letter is dated." }],
      ["cause", "Raised from", "select", { req: true, options: [["", "Choose one"], ["Field direction", "Field direction"], ["RFI answer", "RFI answer"], ["Revised drawing", "Revised drawing"], ["Owner request", "Owner request"]], hint: "What entitles the firm to this change." }],
      ["desc", "Description", "text", { req: true, wide: true, placeholder: "Transformer pad anchor revision", hint: "Prints as the subject of the letter." }],
      ["narrative", "Narrative", "textarea", { req: true, wide: true, rows: 7, placeholder: "Set out what was found, what direction was given, what work is required, and why it is a change rather than included work.", hint: "This is the part the customer actually reads. Say what happened, in order, and name the document or direction that caused it." }],
    ] : [
      ["num", "PlanWise number", "text", { hint: "Assigned in sequence." }],
      ["subcontractor", "Subcontractor", "text", { req: true, placeholder: "Caprock Boring", hint: "Whose change this is." }],
      ["date", "Date submitted", "date", { req: true, hint: "" }],
      ["desc", "Description", "text", { req: true, wide: true, placeholder: "Bore alignment change", hint: "The line on the log." }],
    ];
    const lib = ((this.state.data.clarifications || {}).clarifications) || [];
    const jd = this.state.data.job || {};
    const job = jd.job || {};
    const previewUrl = `/api/jobs/${encodeURIComponent(this.state.job)}/cos/${co.id}/document.pdf?rev=${co.previewRev}`;
    return {
      coOpen: true, coClose: () => App.coClose(),
      coEyebrow: co.isNew ? "New change order" : "Editing CO-" + co.num,
      coTitle: co.isNew && !co.desc ? "Compose a change order" : co.desc || "CO-" + co.num,
      coStateLabel: co.status === "Unsent" || co.status === "Draft" ? "Draft — editable" : co.status,
      coStateStyle: stamp(STATUS_TONE[co.status] || "wn"),
      coPreviewOn: this.state.coPreview,
      coPreviewAria: this.state.coPreview ? "true" : "false",
      coPreviewLabel: this.state.coPreview ? "Hide the preview" : "Show the preview",
      coPreviewBtnStyle: "min-height:var(--tap);padding:7px 13px;border-radius:6px;font:600 12.5px var(--fd);white-space:nowrap;border:1px solid " +
        (this.state.coPreview ? "var(--ac)" : "var(--ln)") + ";background:" + (this.state.coPreview ? "var(--as)" : "var(--pn)") + ";color:" + (this.state.coPreview ? "var(--ac)" : "var(--mu)"),
      coCols: this.state.isMobile ? "minmax(0,1fr)"
        : (this.state.coPreview ? "minmax(0,1fr) minmax(0,1.05fr)" : "minmax(0,1fr)"),
      coEditorHidden: this.state.isMobile && this.state.coPreview,
      coShowErrors: co.submitted && errs.length ? true : "",
      coErrorHeading: errs.length + " thing" + (errs.length === 1 ? "" : "s") + " to fix",
      coErrors: errs.map((text) => ({ text })),
      coIsCustomer: isCust,
      coPreviewUrl: previewUrl,
      coPreviewNote: isCust
        ? "Live preview · the actual letter PDF, refreshed as you type"
        : "Live preview · the subcontractor change order log, refreshed as you type",
      coFields: defs.map(([key, label, type, o]) => {
        const bad = co.submitted && o.req && !String(co[key] || "").trim();
        return {
          id: "co-" + key, label, type: type === "date" ? "date" : "text",
          isInput: type === "text" || type === "date", isArea: type === "textarea", isSelect: type === "select",
          rows: o.rows || 3, value: co[key] || "", set: App.coSet(key),
          placeholder: o.placeholder || "", hint: bad ? label + " is required." : o.hint,
          hintId: "co-" + key + "-hint", hintColor: bad ? "var(--er)" : "var(--ft)", invalid: bad ? "true" : "false",
          reqText: o.req ? "Required" : "Optional",
          reqStyle: "margin-left:7px;font:500 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:" + (o.req ? "var(--ac)" : "var(--ft)"),
          wrap: "min-width:0" + (o.wide ? ";grid-column:1 / -1" : ""),
          control: control + (bad ? ";border-color:var(--er);background:var(--ers)" : "") + (type === "textarea" ? ";min-height:auto;resize:vertical;line-height:1.55" : ""),
          options: (o.options || []).map(([value, l]) => ({ value, label: l })),
        };
      }),
      coItems: co.items.map((it, i) => ({
        n: i + 1, descId: "coi-d" + i, amtId: "coi-a" + i, desc: it.desc, amt: it.amt,
        setDesc: App.coSetItem(i, "desc"), setAmt: App.coSetItem(i, "amt"), remove: App.coRemoveItem(i),
      })),
      coAddItem: () => App.coAddItem(), coTotal: money(total),
      coClar: lib.map((c) => ({
        id: "coc-" + c.id, text: c.text, on: !!co.clar[c.id], toggle: App.coToggleClar(c.id), isNew: !c.seeded,
      })),
      coNewClar: this.state.coNewClar || "", coSetNewClar: (e) => App.coSetNewClar(e), coAddClar: () => App.coAddClar(),
      coFootnote: co.isNew
        ? "Saving keeps this as a draft on the register. Nothing reaches the customer until you send it, and sending is undoable."
        : "Changes are saved to the draft as you type. A change order that has gone to the customer should not be edited here.",
      coSaveLabel: co.isNew ? "Save as a draft" : "Save changes",
      coSubmit: () => App.coSubmit(), coSaveAndSend: () => App.coSaveAndSend(),
      coSendLabel: isCust ? "Save and draft the email in Outlook" : "Save and draft the log email in Outlook",
    };
  },
});

// ————— register specs: cos, pos, rfis/subs, docs (prototype branches, live
// data) — appended into regSpec by wrapping it —————————————————————————————
(() => {
  const base = App.regSpec.bind(App);
  App.regSpec = function () {
    const s = this.state;
    const d = s.data;
    const jd = d.job || {};
    const P = (text, right) => ({ kind: "plain", text, right: !!right });
    const S = (text) => ({ kind: "stamp", text });

    if (s.page === "cos") {
      const all = (jd.change_orders || []).map((c) => ({
        id: c.id, n: c.co_number || "?", kind: c.kind,
        cust: c.kind === "customer" ? (c.cust_co_number || "—") : (c.subcontractor || "—"),
        date: c.date_submitted || "", desc: c.description || "",
        status: c.status || (c.amount_approved ? "Approved" : "Draft"),
        amt: c.amount_submitted, appr: c.amount_approved, by: c.approved_by || "—",
      }));
      const rows = all.filter((c) => s.recFilter === "All" || c.status === s.recFilter).map((c) => ({
        id: c.id, key: "CO-" + c.n,
        keySub: c.kind === "subcontractor" ? "Subcontractor · " + c.cust : (c.cust === "—" ? "No customer number yet" : c.cust),
        sortVals: ["CO-" + c.n, c.date, c.desc, c.amt, c.status],
        cells: [P(c.date), P(c.desc), P(money(c.amt), 1), S(c.status), P(c.appr ? money(c.appr) : "not reported")],
      }));
      const counts = { All: all.length };
      ["Approved", "Sent", "Awaiting Outlook", "Draft", "Unsent"].forEach((k) => { counts[k] = all.filter((c) => c.status === k).length; });
      const custTotal = all.filter((c) => c.kind === "customer").reduce((t, c) => t + (c.amt || 0), 0);
      return { title: "Change order register", source: all.filter((c) => c.kind === "customer").length + " customer · " + all.filter((c) => c.kind === "subcontractor").length + " subcontractor", kind: "co",
        caption: "Change orders on job " + s.job + " with date, description, amount, status and approved amount. Select a change order number to audit its breakout lines and clarifications.",
        footnote: "Approved amounts come from the customer's paperwork and are entered when it lands. A change order stays Unsent until the letter goes out, and only a sent change order can be approved.",
        filters: ["All", "Approved", "Sent", "Awaiting Outlook", "Draft", "Unsent"].map((k) => [k, counts[k]]),
        columns: [["Change order", 0, 1], ["Submitted", 0, 1], ["Description", 0, 1], ["Amount", 1, 1], ["Status", 0, 1], ["Approved", 1, 1]],
        rows, total: ["Total submitted", ["", "", money(all.reduce((t, c) => t + (c.amt || 0), 0)), "", money(all.reduce((t, c) => t + (c.appr || 0), 0))]],
        extras: [
          { label: "Compose a change order", click: App.openCO(null, "customer"), hoverClass: "hb-fill",
            style: "min-height:var(--tap);padding:7px 14px;border-radius:6px;border:1px solid var(--ac);background:var(--as);color:var(--ac);font:600 12.5px var(--fd);letter-spacing:.03em;white-space:nowrap" },
          { label: "Log a subcontractor CO", click: App.openCO(null, "subcontractor"), hoverClass: "hb-ls",
            style: "min-height:var(--tap);padding:7px 14px;border-radius:6px;border:1px solid var(--ln);background:var(--pn);font:600 12.5px var(--fd);white-space:nowrap" },
        ] };
    }

    if (s.page === "pos") {
      const all = (jd.purchase_orders || []).map((p) => {
        const inv = (p.invoices || []).reduce((t, i) => t + (i.amount || 0), 0);
        const amt = p.adjusted_amount !== null && p.adjusted_amount !== undefined ? p.adjusted_amount : p.original_amount;
        return { id: p.id, n: p.po_number || "(unnumbered)", vendor: p.vendor || "", desc: p.description || "",
          ct: p.cost_type || "Unassigned", orig: amt, inv, status: p.status || "Open" };
      });
      const rows = all.filter((p) => s.poFilter === "All" || p.status === s.poFilter).map((p) => {
        const pct = p.orig ? p.inv / p.orig * 100 : 0;
        const rem = (p.orig || 0) - p.inv;
        return { id: p.id, key: p.n, keySub: p.vendor, sortVals: [p.n, p.vendor, p.ct, p.orig, p.inv, rem, p.status],
          cells: [P(p.desc), P(p.ct), P(money(p.orig), 1), P(money(p.inv), 1),
            { kind: "plain", text: p.orig === null ? "unpriced" : rem <= 0 ? "Fully invoiced" : money(rem), right: 1, color: rem <= 0 ? "var(--ft)" : p.status === "Open" ? "var(--ok)" : "var(--ink)" },
            { kind: "bar", text: pct.toFixed(0) + "%", w: Math.min(100, pct), color: pct > 95 ? "var(--wn)" : "var(--bp)" }, S(p.status)] };
      });
      const counts = { All: all.length, Open: all.filter((p) => p.status === "Open").length, Closed: all.filter((p) => p.status === "Closed").length };
      const remTotal = all.reduce((t, p) => t + (p.status === "Open" ? Math.max(0, (p.orig || 0) - p.inv) : 0), 0);
      return { title: "Purchase order register", source: all.length + " purchase orders logged", kind: "po",
        caption: "Purchase orders logged against job " + s.job + " with vendor, cost type, original amount, invoiced to date, remaining to invoice and status. Select a purchase order number to audit its invoices.",
        footnote: "Purchase orders are raised in Vista. PlanWise logs them so the register can feed open committed cost: the total below is the remaining column summed across open orders only, and it is the same figure the cost breakdown shows. A closed order contributes nothing even if it was never fully invoiced.",
        filters: ["All", "Open", "Closed"].map((k) => [k, counts[k]]),
        columns: [["Purchase order", 0, 1], ["Description", 0, 0], ["Cost type", 0, 1], ["Original", 1, 1], ["Invoiced", 1, 1], ["Remaining to invoice", 1, 1], ["Invoiced of order", 0, 0], ["Status", 0, 1]],
        rows, total: ["All purchase orders · remaining counts open orders only", ["", "", money(all.reduce((t, p) => t + (p.orig || 0), 0)), money(all.reduce((t, p) => t + p.inv, 0)), money(remTotal), "", ""]] };
    }

    if ((s.page === "rfis" || s.page === "subs") && !s.sub) {
      const isR = s.page === "rfis";
      const base2 = ((d.records || {}).records || []).filter((r) => isR ? r.kind === "rfi" : r.kind !== "rfi");
      const rows = base2.filter((r) => s.recFilter === "All" || r.status === s.recFilter).map((r) => {
        const pages = (r.attachments || []).length;
        const marks = r.markup_count || 0;
        return { id: r.id, key: r.number || "?", keySub: r.title || "",
          sortVals: [r.number, r.status, r.to_name, r.due_date],
          cells: [P(isR ? "Question" : (r.spec_section || "—")), S(r.status || "Draft"), P(r.to_name || "Not yet sent"), P(r.due_date || ""),
            P(pages ? pages + (pages === 1 ? " page" : " pages") + (marks ? " · " + marks + (marks === 1 ? " mark" : " marks") : "") : "No pages")] };
      });
      const st = isR ? ["All", "Draft", "Sent", "Answered", "Closed"] : ["All", "Draft", "Sent", "Approved", "Revise & Resubmit"];
      const counts = {}; st.forEach((k) => { counts[k] = k === "All" ? base2.length : base2.filter((r) => r.status === k).length; });
      return { title: isR ? "RFI register" : "Submittal register", source: base2.length + " on the register", kind: isR ? "rfi" : "sub",
        caption: (isR ? "Requests for information" : "Submittals") + " on job " + s.job + " with status, recipient, due date and attached pages. Select a number to audit the full record and its thread.",
        footnote: isR ? "A reply is matched to its RFI from the Outlook thread, but the answer is not published to the field until a project manager confirms it." : "Nothing goes out without a project manager review. A returned submittal keeps its history when it is resubmitted.",
        filters: st.map((k) => [k, counts[k]]),
        columns: [[isR ? "RFI" : "Submittal", 0, 1], [isR ? "Type" : "Spec section", 0, 0], ["Status", 0, 1], [isR ? "Sent to" : "Reviewer", 0, 1], ["Due", 0, 1], ["Attached pages", 0, 0]],
        rows };
    }

    if (s.page === "docs") {
      const docs = ((d.documents || {}).documents) || [];
      const rows = docs.map((doc) => ({
        id: doc.id, key: doc.name, keySub: (doc.page_count || 0) + " pages",
        sortVals: [doc.name, doc.page_count, doc.uploaded_at, doc.annotation_count],
        cells: [P(String(doc.page_count || 0), 1), P((doc.uploaded_by || "") + " · " + usDate(doc.uploaded_at)),
          P(!doc.annotation_count ? "No markups" : doc.annotation_count + " markups"), S(doc.annotation_count ? "Marked" : "Clean")],
      }));
      return { title: "Drawing and specification library", source: docs.length + " sets on this job", kind: "doc",
        caption: "Drawing sets and specifications uploaded to job " + s.job + ", with page count, who uploaded them and how many markups they carry.",
        footnote: "Originals are immutable. Redlines live on layers: the internal team layer stays in the building, and each RFI or submittal carries its own layer that goes out with its package.",
        columns: [["Set or specification", 0, 1], ["Pages", 1, 1], ["Uploaded", 0, 1], ["Markups", 0, 1], ["State", 0, 0]], rows,
        emptyText: "No drawing sets on this job yet. Upload a PDF set to start the library." };
    }

    return base();
  };
})();

// ————— detail drawers: co + po (prototype branches, live data) ——————————————
(() => {
  const base = App.buildDetail.bind(App);
  App.buildDetail = function () {
    const d = this.state.detail;
    if (!d || (d.kind !== "co" && d.kind !== "po")) return base();
    const S = (id, title, rows) => ({ id: "ds-" + id, title, rows: rows.map(([label, value, note, style]) => ({ label, value, note: note || "", valueStyle: style || "" })) });
    const A = (list) => list.map(([what, who, when], i) => ({ what, who, when: when || "", color: i === list.length - 1 ? "var(--ac)" : "var(--ls)" }));
    const btn2 = (label, kind, click) => ({ label, style: btn(kind), hoverClass: kind === "primary" ? "hb-ah" : "hb-ls", click: click || (() => {}) });
    const out = { detailOpen: true, detailHasItems: "", detailHasNotes: "", detailNotes: [], detailActions: [], detailFootnote: "" };
    const jd = this.state.data.job || {};
    const audit = (((this.state.data.activity || {}).activity) || []);

    if (d.kind === "co") {
      const c = (jd.change_orders || []).find((x) => x.id === d.id) || {};
      const status = c.status || (c.amount_approved ? "Approved" : "Draft");
      const trail = audit.filter((a) => a.object_id === c.id).slice(0, 6).reverse()
        .map((a) => [a.detail || a.action, a.actor || "PlanWise", usDate(a.ts)]);
      const isCust = c.kind === "customer";
      const editable = ["Unsent", "Draft", null, undefined, ""].includes(c.status);
      return Object.assign(out, {
        detailKind: isCust ? "Customer change order" : "Subcontractor change order",
        detailTitle: "CO-" + (c.co_number || "?") + (c.description ? " · " + c.description : ""),
        detailStatus: status, detailStampStyle: stamp(STATUS_TONE[status] || "nt"),
        detailMeta: "Submitted " + (c.date_submitted || "—") + " · " + money(c.amount_submitted),
        detailSections: [
          S("co-id", "Identification", [["PlanWise number", "CO-" + (c.co_number || "?")],
            isCust ? ["Customer change order number", c.cust_co_number || "Not issued — the customer assigns this on receipt", c.cust_co_number ? "From the customer" : ""] : ["Subcontractor", c.subcontractor || "not reported"],
            ["Kind", isCust ? "Customer" : "Subcontractor"], ["Date submitted", c.date_submitted || "not reported"]]),
          S("co-money", "Money", [["Amount submitted", money(c.amount_submitted), "PlanWise", "font-variant-numeric:tabular-nums"],
            ["Amount approved", c.amount_approved ? money(c.amount_approved) : "not reported", c.amount_approved ? "Entered from the approval" : "", c.amount_approved ? "font-variant-numeric:tabular-nums" : "color:var(--ft);font-style:italic"],
            ["Approved by", c.approved_by || "not reported", "", c.approved_by ? "" : "color:var(--ft);font-style:italic"]]),
          S("co-src", "Where this came from", [["Raised from", c.raised_from || "not recorded"], ["Narrative", c.narrative ? "On the letter" : "Not written yet"]]),
        ],
        detailAudit: A(trail.length ? trail : [["Change order created in PlanWise", c.created_by || "—", usDate(c.created_at)]]),
        detailFootnote: editable ? "Nothing has gone to the customer yet. Sending is undoable." : "A change order that has gone out should be corrected by a follow-up letter, not an edit.",
        detailActions: [
          btn2("Close this panel", "ghost", App.closeDetail),
          btn2("Remove CO-" + (c.co_number || "?"), "ghost", () => { App.closeDetail(); App.coDelete(c.id)(); }),
          btn2("Open the composer", editable ? "ghost" : "ghost", () => { App.closeDetail(); App.openCO(c.id)(); }),
          ...(editable && isCust ? [btn2("Send CO-" + (c.co_number || "?"), "primary", () => { App.closeDetail(); App.coSend(c.id)(); })] : []),
        ],
      });
    }

    // d.kind === "po"
    const p = (jd.purchase_orders || []).find((x) => x.id === d.id) || {};
    const inv = (p.invoices || []);
    const invTotal = inv.reduce((t, i) => t + (i.amount || 0), 0);
    const amt = p.adjusted_amount !== null && p.adjusted_amount !== undefined ? p.adjusted_amount : p.original_amount;
    const srcCo = p.source_co_id ? (jd.change_orders || []).find((c) => c.id === p.source_co_id) : null;
    const trail = audit.filter((a) => a.object_id === p.id).slice(0, 6).reverse()
      .map((a) => [a.detail || a.action, a.actor || "PlanWise", usDate(a.ts)]);
    return Object.assign(out, {
      detailKind: "Purchase order", detailTitle: (p.po_number || "(unnumbered)") + (p.vendor ? " · " + p.vendor : ""),
      detailStatus: p.status || "Open", detailStampStyle: stamp(STATUS_TONE[p.status || "Open"] || "nt"),
      detailMeta: (p.cost_type || "Unassigned") + " · " + money(amt) + " ordered",
      detailSections: [
        S("po-id", "Order", [["Purchase order number", p.po_number || "(unnumbered)"], ["Vendor", p.vendor || "not reported"],
          ["Description", p.description || "not reported"], ["Cost type", p.cost_type || "Unassigned"],
          ["Order date", p.order_date || "not reported"], ["Ordered by", p.ordered_by || "not reported"],
          ...(srcCo ? [["Raised against", "Sub CO-" + (srcCo.co_number || "?") + " · " + (srcCo.subcontractor || ""), "Covers the commitment"]] : [])]),
        S("po-money", "Money", [["Original amount", money(p.original_amount), "PlanWise", "font-variant-numeric:tabular-nums"],
          ["Adjusted amount", p.adjusted_amount !== null && p.adjusted_amount !== undefined ? money(p.adjusted_amount) : "not adjusted", "", p.adjusted_amount !== null && p.adjusted_amount !== undefined ? "font-variant-numeric:tabular-nums" : "color:var(--ft);font-style:italic"],
          ["Invoiced to date", money(invTotal), "", "font-variant-numeric:tabular-nums"],
          ["Remaining on the order", amt === null || amt === undefined ? "unpriced" : money(amt - invTotal), "", "font-variant-numeric:tabular-nums;color:" + (amt !== null && amt - invTotal <= 0 ? "var(--er)" : "var(--ok)")],
          ["Counts toward committed cost", (p.status || "Open") === "Open" ? "Yes, open committed" : "No, order is closed"]]),
      ],
      detailHasItems: inv.length > 0,
      detailItems: inv.map((i) => ({ label: "Invoice " + (i.invoice_number || "?") + " · " + (i.date || ""), value: money(i.amount), color: "var(--ink)" })),
      detailItemsTitle: "Invoices against this order", detailItemsCol1: "Invoice", detailItemsCol2: "Amount",
      detailItemsTotalLabel: "Invoiced to date", detailItemsTotal: money(invTotal),
      detailAudit: A(trail.length ? trail : [["Purchase order logged", p.created_by || "—", usDate(p.created_at)]]),
      detailFootnote: "Open committed cost on the cost breakdown is the sum of the remaining amounts on open orders.",
      detailActions: [
        btn2("Close this panel", "ghost", App.closeDetail),
        btn2((p.status || "Open") === "Open" ? "Close this order" : "Reopen this order", "ghost", App.togglePoStatus(p.id)),
        btn2("Record an invoice", "primary", () => { App.closeDetail(); App.openForm("invoice", { po: p.id })(); }),
      ],
    });
  };
})();

// ————— PO handlers: status flip, issue from sub CO, PDF import ———————————————
Object.assign(App, {
  togglePoStatus: (poId) => async () => {
    const p = ((App.state.data.job || {}).purchase_orders || []).find((x) => x.id === poId) || {};
    const next = (p.status || "Open") === "Open" ? "Closed" : "Open";
    try {
      const upd = await api(`/api/jobs/${encodeURIComponent(App.state.job)}/pos/${poId}`,
        { method: "PATCH", body: JSON.stringify({ status: next }) });
      setState({ detail: null });
      App.act((p.po_number || "The order") + " is now " + next + "." +
        (next === "Closed" ? " Its remaining value no longer counts toward open committed cost." : " Its remaining value counts toward open committed cost again."),
        upd.activity_id, ["job"]);
    } catch (err) { setState({ live: err.message }); }
  },

  triggerPoImport() {
    let input = document.getElementById("po-import-input");
    if (!input) {
      input = document.createElement("input");
      input.type = "file"; input.accept = ".pdf"; input.id = "po-import-input";
      input.style.display = "none";
      document.body.appendChild(input);
      input.addEventListener("change", () => {
        if (input.files && input.files[0]) App.runPoImport(input.files[0]);
        input.value = "";
      });
    }
    input.click();
  },

  async runPoImport(file) {
    setState({ live: "Reading " + file.name + "…" });
    try {
      const fd = new FormData();
      fd.append("file", file);
      const out = await fetch(`/api/jobs/${encodeURIComponent(App.state.job)}/pos/import`,
        { method: "POST", body: fd, credentials: "same-origin" }).then(async (r) => {
          const b = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(b.detail || r.status);
          return b;
        });
      if (!(out.candidates || []).length) {
        setState({ live: out.detail || "No purchase agreement number was found in that file." });
        return;
      }
      setState({ poImport: {
        filename: file.name,
        warnings: out.warnings || [],
        rows: out.candidates.map((c) => ({ ...c,
          cost_type: c.cost_type || "", accepted: !c.already_on_register })),
      }, live: out.candidates.length + (out.candidates.length === 1 ? " purchase agreement read from " : " purchase agreements read from ") + file.name + ". Nothing is written until you accept." });
    } catch (err) {
      setState({ live: "Couldn't read that file: " + err.message });
    }
  },

  poImportSet: (i, key) => (e) => {
    const im = App.state.poImport;
    im.rows[i][key] = key === "accepted" ? e.target.checked : e.target.value;
    setState({});
  },

  async poImportAccept() {
    const im = App.state.poImport;
    const rows = im.rows.filter((r) => r.accepted);
    if (!rows.length) { setState({ live: "Tick at least one order to log." }); return; }
    try {
      let last = null;
      for (const r of rows) {
        last = await api(`/api/jobs/${encodeURIComponent(App.state.job)}/pos`, { method: "POST",
          body: JSON.stringify({ po_number: r.po_number, vendor: r.vendor, description: r.description,
            original_amount: parseFloat(String(r.amount || "").replace(/[$,]/g, "")) || null,
            cost_type: r.cost_type || null, order_date: r.order_date || null }) });
      }
      setState({ poImport: null });
      App.act(rows.length + (rows.length === 1 ? " purchase order logged from " : " purchase orders logged from ") + im.filename + ". Open committed cost has gone up by their remaining value.",
        last && last.activity_id, ["job"]);
    } catch (err) { setState({ live: "Could not log the orders: " + err.message }); }
  },

  issuePoFromCo: (coId) => () => {
    const c = ((App.state.data.job || {}).change_orders || []).find((x) => x.id === coId) || {};
    App.openForm("po", { source_co_id: coId, vendor: c.subcontractor || "",
      desc: c.description || "", amount: c.amount_approved })();
  },
});

// ————— form kinds: po, invoice, rfi, sub (prototype specs, real submits) ————
(() => {
  const baseSpec = App.formSpec.bind(App);
  App.formSpec = function (kind, ctx) {
    const jd = this.state.data.job || {};
    const contacts = ((jd.meta || {}).contacts || []).filter((c) => c.email);
    const costTypes = [...new Set((jd.cost_types || []).map((c) => c.cost_type))];
    if (kind === "po") {
      const pre = ctx || {};
      return {
        eyebrow: pre.source_co_id ? "Cover a commitment" : "Log a record",
        title: pre.source_co_id ? "Issue the purchase order this sub CO is waiting on" : "Log a purchase order from Vista",
        submit: "Log this purchase order",
        intro: pre.source_co_id
          ? "Logging this order covers the approved subcontractor change order: the exposure line clears and the value moves into open committed cost."
          : "Purchase orders are raised in Vista. Logging one here records it against the job so it feeds open committed cost. This does not create anything in Vista.",
        fields: [
          ["number", "Vista purchase order number", "text", { req: true, placeholder: "P" + (this.state.job || "") + "-01", hint: "Exactly as Vista numbered it. PlanWise does not assign this." }],
          ["vendor", "Vendor", "text", { req: true, value: pre.vendor || "", placeholder: "Cinco Steel Supply", hint: "The name that appears on the vendor's invoices." }],
          ["desc", "Description", "textarea", { req: true, rows: 2, wide: true, value: pre.desc || "", placeholder: "Galvanized structures, Bays 2–4", hint: "What is being bought, in the words the field would use." }],
          ["ct", "Cost type", "select", { req: true, value: pre.source_co_id ? "Subcontract" : "", hint: "Determines which line of the cost breakdown this commits against.", options: [["", "Choose one"]].concat(costTypes.map((o) => [o, o])) }],
          ["date", "Order date", "date", { req: true, value: new Date().toISOString().slice(0, 10), hint: "" }],
          ["amount", "Original amount, US dollars", "text", { req: true, value: pre.amount ? String(pre.amount) : "", placeholder: "412600.00", hint: "Numbers only. Enter the amount on the order, not the invoiced amount." }],
        ],
        review: "Logging this order adds its full amount to open committed cost and to the remaining-to-invoice column. Invoices are recorded against it afterwards from its own panel.",
      };
    }
    if (kind === "invoice") {
      const po = ((jd.purchase_orders || []).find((p) => p.id === (ctx || {}).po)) || {};
      const amt = po.adjusted_amount !== null && po.adjusted_amount !== undefined ? po.adjusted_amount : po.original_amount;
      const rem = amt === null || amt === undefined ? null : amt - (po.invoices || []).reduce((t, i) => t + (i.amount || 0), 0);
      return {
        eyebrow: "Against " + (po.po_number || "this order"), title: "Record an invoice", submit: "Record this invoice",
        intro: "This records a vendor invoice against " + (po.po_number || "the order") + ". It reduces the remaining amount on the order; it does not approve the invoice for payment.",
        fields: [
          ["number", "Invoice number", "text", { req: true, placeholder: "4412", hint: "Exactly as the vendor wrote it." }],
          ["date", "Invoice date", "date", { req: true, value: new Date().toISOString().slice(0, 10), hint: "" }],
          ["amount", "Amount, US dollars", "text", { req: true, placeholder: "0.00", hint: rem === null ? "The order is unpriced." : money(rem) + " remains on this order." }],
        ],
        review: "The invoice is recorded against " + (po.po_number || "the order") + " and appears in its invoice list and in invoiced-to-date on the register.",
      };
    }
    if (kind === "rfi" || kind === "sub") {
      const isR = kind === "rfi";
      return {
        eyebrow: "New record",
        title: isR ? "New request for information" : "New submittal",
        submit: isR ? "Create this RFI" : "Create this submittal",
        intro: "This creates a draft. Drafts never leave the building — you send it from the register once the question and pages are right.",
        fields: [
          ["title", "Title", "text", { req: true, wide: true, placeholder: isR ? "Control building conduit stub-up count" : "Relay panel shop drawings — Bay 3", hint: "Short enough to read on the register." }],
          isR ? ["question", "Question", "textarea", { req: true, rows: 4, wide: true, placeholder: "State the conflict, cite the sheet, and ask one answerable question.", hint: "One question per RFI. Two questions in one RFI get one answer." }]
              : ["spec", "Spec section", "text", { placeholder: "26 05 26 — Grounding and Bonding", hint: "The section this submittal answers to, if it has one. Leave blank for a submittal that answers to a drawing rather than a specification." }],
          ["to", "Send to", "select", { req: true, options: [["", "Choose a recipient"]].concat(contacts.map((c) => [c.email, (c.name || c.email) + " — " + c.email])), hint: contacts.length ? "Their email is filled in from the job contacts." : "No contacts with an email yet — add one on Job setup first." }],
          ["due", "Reply needed by", "date", { req: true, hint: "Set this from the schedule, not from hope." }],
        ],
        review: "The record is created as a Draft with the pages you attached. It stays in PlanWise until you send it, and the outbound package carries only this record's own layer.",
      };
    }
    return baseSpec(kind, ctx);
  };

  const baseSubmit = App.submitForm.bind(App);
  App.submitForm = async function () {
    const f = App.state.form;
    if (!f) return;
    if (!["po", "invoice", "rfi", "sub"].includes(f.kind)) return baseSubmit();
    const spec = App.formSpec(f.kind, f.ctx);
    const errs = App.formErrors(spec, f);
    if (errs.length) {
      f.submitted = true;
      setState({ live: errs.length + " field" + (errs.length === 1 ? "" : "s") + " need attention before this can be created." });
      return;
    }
    const job = encodeURIComponent(App.state.job);
    const num = (vv) => parseFloat(String(vv || "").replace(/[^0-9.-]/g, "")) || null;
    try {
      if (f.kind === "po") {
        const out = await api(`/api/jobs/${job}/pos`, { method: "POST", body: JSON.stringify({
          po_number: f.values.number, vendor: f.values.vendor, description: f.values.desc,
          cost_type: f.values.ct || null, order_date: f.values.date || null,
          original_amount: num(f.values.amount), source_co_id: (f.ctx || {}).source_co_id || null }) });
        setState({ form: null });
        App.act(f.values.number + " logged for " + money(num(f.values.amount)) +
          ((f.ctx || {}).source_co_id ? ". The commitment it covers has left the exposure list." : ". Open committed cost has gone up by the same amount."),
          out.activity_id, ["job"]);
      } else if (f.kind === "invoice") {
        const poId = (f.ctx || {}).po;
        const out = await api(`/api/jobs/${job}/pos/${poId}/invoices`, { method: "POST", body: JSON.stringify({
          invoice_number: f.values.number, date: f.values.date || null, amount: num(f.values.amount) }) });
        setState({ form: null });
        App.act("Invoice " + f.values.number + " for " + money(num(f.values.amount)) + " recorded.", out.activity_id, ["job"]);
      } else {
        const contacts = (((App.state.data.job || {}).meta || {}).contacts || []);
        const to = contacts.find((c) => c.email === f.values.to) || {};
        const out = await api(`/api/jobs/${job}/records`, { method: "POST", body: JSON.stringify({
          kind: f.kind === "rfi" ? "rfi" : "submittal",
          number: App.nextRecordNumber(f.kind),
          title: f.values.title, question: f.values.question || null,
          spec_section: f.values.spec || null,
          to_name: to.name || null, to_email: f.values.to || null,
          due_date: f.values.due || null }) });
        setState({ form: null });
        const acts = await api(`/api/jobs/${job}/activity?limit=1`);
        App.act((out.number || "The record") + " created as a Draft. Nothing has been sent.",
          ((acts.activity || [])[0] || {}).id, ["records"]);
        App.refresh("records");
      }
    } catch (err) {
      setState({ live: "Could not create it: " + err.message });
    }
  };
})();

Object.assign(App, {
  nextRecordNumber(kind) {
    const recs = ((this.state.data.records || {}).records || []).filter((r) => kind === "rfi" ? r.kind === "rfi" : r.kind !== "rfi");
    const max = recs.reduce((m, r) => Math.max(m, parseInt(String(r.number || "").replace(/[^0-9]/g, "")) || 0), 0);
    const n = max + 1;
    return (kind === "rfi" ? "RFI-" : "SUB-") + (n < 100 ? "0" : "") + n;
  },
});

// ————— POs page body: exposure panel + import review above the register ————
function pagePos(v) {
  let out = "";
  if (v.poImport) {
    out += `<section aria-labelledby="poimp-heading" style="background:var(--pn);border:1px solid var(--ac);border-radius:8px;box-shadow:var(--sh);margin-bottom:14px">
      <div style="padding:12px 16px;border-bottom:1px solid var(--ln);display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <h2 id="poimp-heading" style="margin:0;flex:1;font:600 15px var(--fd)">Read from ${esc(v.poImport.filename)}</h2>
        <p style="margin:0;font:11.5px var(--fm);color:var(--ft)">Nothing is written until you accept</p>
      </div>
      ${v.poImport.warnings.map((w) => `<p style="margin:0;padding:10px 16px;border-bottom:1px solid var(--ln);background:var(--wns);color:var(--wn);font-size:var(--fzs);text-wrap:pretty">${esc(w)}</p>`).join("")}
      <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:var(--fzs)">
        <thead><tr>
          ${["Log it", "Purchase order", "Vendor", "Description", "Amount", "Cost type", "Read from"].map((h) => `<th scope="col" style="text-align:left;padding:9px 12px;font:500 var(--lbl) var(--fm);letter-spacing:.12em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln);white-space:nowrap">${h}</th>`).join("")}
        </tr></thead>
        <tbody>
          ${v.poImport.rows.map((r, i) => `<tr style="${r.already_on_register ? "background:var(--ers)" : ""}">
            <td style="padding:8px 12px;border-bottom:1px solid var(--ln)"><input type="checkbox" ${r.accepted ? "checked" : ""} data-change="${H(v.poImportSet(i, "accepted"))}" aria-label="Log ${esc(r.po_number)}" style="width:19px;height:19px;accent-color:var(--ac)"></td>
            <td style="padding:8px 12px;border-bottom:1px solid var(--ln)"><input type="text" value="${esc(r.po_number)}" data-input="${H(v.poImportSet(i, "po_number"))}" class="fi2" style="min-width:110px;min-height:32px;padding:5px 8px;border:1px solid var(--ln);border-radius:5px;background:var(--p2);font:12px var(--fm)">${r.already_on_register ? `<span style="display:block;margin-top:3px;font:600 10px var(--fm);color:var(--er)">already on the register</span>` : ""}</td>
            <td style="padding:8px 12px;border-bottom:1px solid var(--ln)"><input type="text" value="${esc(r.vendor)}" data-input="${H(v.poImportSet(i, "vendor"))}" class="fi2" style="min-width:130px;min-height:32px;padding:5px 8px;border:1px solid var(--ln);border-radius:5px;background:var(--p2);font-size:12px"></td>
            <td style="padding:8px 12px;border-bottom:1px solid var(--ln)"><input type="text" value="${esc(r.description)}" data-input="${H(v.poImportSet(i, "description"))}" class="fi2" style="min-width:170px;min-height:32px;padding:5px 8px;border:1px solid var(--ln);border-radius:5px;background:var(--p2);font-size:12px"></td>
            <td style="padding:8px 12px;border-bottom:1px solid var(--ln)"><input type="text" inputmode="decimal" value="${esc(r.amount === null || r.amount === undefined ? "" : r.amount)}" data-input="${H(v.poImportSet(i, "amount"))}" class="fi2" style="width:110px;min-height:32px;padding:5px 8px;border:1px solid var(--ln);border-radius:5px;background:var(--p2);font:12px var(--fm);text-align:right"></td>
            <td style="padding:8px 12px;border-bottom:1px solid var(--ln)">
              <select data-change="${H(v.poImportSet(i, "cost_type"))}" style="min-height:32px;padding:5px 8px;border:1px solid var(--ln);border-radius:5px;background:var(--p2);font-size:12px">
                <option value="">Choose one</option>
                ${v.poImportCostTypes.map((ct) => `<option value="${esc(ct)}" ${ct === r.cost_type ? "selected" : ""}>${esc(ct)}</option>`).join("")}
              </select>
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid var(--ln);font:11px var(--fm);color:var(--ft);max-width:220px">${esc(r.evidence || "")}${r.phase ? " · Phase " + esc(r.phase) : ""}</td>
          </tr>`).join("")}
        </tbody>
      </table>
      </div>
      <div style="display:flex;gap:9px;align-items:center;padding:12px 16px;background:var(--p2);flex-wrap:wrap">
        <p style="margin:0;flex:1;font-size:12px;color:var(--mu);text-wrap:pretty">The number comes from the document, never the filename — Vista's export sometimes injects an extra digit that means nothing. Amounts are what the agreement's subtotal said; correct anything the reader got wrong before accepting.</p>
        <button data-click="${H(v.poImportDiscard)}" class="hb-ls" style="min-height:var(--tap);padding:9px 15px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 13px var(--fd)">Discard</button>
        <button data-click="${H(v.poImportAccept)}" class="hb-ah" style="min-height:var(--tap);padding:9px 17px;border:1px solid var(--ac);border-radius:6px;background:var(--ac);color:var(--acink);font:600 13px var(--fd);letter-spacing:.03em;box-shadow:0 0 0 3px var(--as)">Log the ticked orders</button>
      </div>
    </section>`;
  }
  if (v.uncovered.length) {
    out += `<section aria-labelledby="unc-heading" style="background:var(--pn);border:1px solid var(--er);border-radius:8px;box-shadow:var(--sh);margin-bottom:14px">
      <div style="padding:12px 16px;border-bottom:1px solid var(--ln);display:flex;align-items:center;gap:9px;flex-wrap:wrap">
        <span aria-hidden="true" style="width:8px;height:8px;border-radius:50%;background:var(--er);box-shadow:0 0 0 3px var(--ers)"></span>
        <h2 id="unc-heading" style="margin:0;flex:1;font:600 15px var(--fd)">Approved subcontractor work with no purchase order</h2>
        <p style="margin:0;font:600 12px var(--fm);color:var(--er)">${esc(v.uncoveredTotal)} exposed</p>
      </div>
      <ul style="list-style:none;margin:0;padding:0">
        ${v.uncovered.map((u) => `<li style="display:flex;gap:12px;align-items:center;padding:11px 16px;border-bottom:1px solid var(--ln)">
          <span style="flex:1;min-width:0">
            <span style="display:block;font:600 var(--fzs) var(--fd)">Sub CO-${esc(u.n)} · ${esc(u.sub)}</span>
            <span style="display:block;font-size:12.5px;color:var(--mu)">${esc(u.desc)}</span>
          </span>
          <span style="font:600 13px var(--fm);font-variant-numeric:tabular-nums">${esc(u.amt)}</span>
          <button data-click="${H(u.issue)}" class="hb-fill" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ac);border-radius:6px;background:var(--as);color:var(--ac);font:600 12.5px var(--fd);white-space:nowrap">Issue the purchase order</button>
        </li>`).join("")}
      </ul>
      <p style="margin:0;padding:11px 16px;font-size:12px;color:var(--ft);text-wrap:pretty">Exposure, not a commitment: the money is owed in principle but nothing has been ordered against it. Issuing the purchase order moves it into open committed cost, where the cost breakdown can see it.</p>
    </section>`;
  }
  return out;
}

// ————— schedule (prototype interactions on the SERVER engine — decision H) —
// The prototype shipped a client 8-pass relaxation engine; the repo's CPM
// engine (all four link types, real job calendar, computed float and critical
// path) is strictly richer, so the client keeps only presentation and
// gestures. Every date edit PATCHes the task and announces the engine's own
// `moved` list — "N dependent tasks moved with it" is the server's truth.
Object.assign(App, {
  schedTasks() {
    return ((this.state.data.schedule || {}).tasks) || [];
  },
  schedLinks() {
    return ((this.state.data.schedule || {}).links) || [];
  },
  // Hierarchy is positional, exactly the prototype's rule: a row's children
  // are the following rows with a greater outline level.
  taskChildIdx(tasks, i) {
    const lvl = tasks[i].outline_level || 0;
    const kids = [];
    for (let j = i + 1; j < tasks.length; j++) {
      if ((tasks[j].outline_level || 0) <= lvl) break;
      kids.push(j);
    }
    return kids;
  },
  schedHiddenSet(tasks) {
    const hidden = {};
    tasks.forEach((t, i) => {
      if (!t.collapsed) return;
      this.taskChildIdx(tasks, i).forEach((j) => { hidden[j] = true; });
    });
    return hidden;
  },
  primaryPred(taskId) {
    const links = this.schedLinks().filter((l) => l.succ_id === taskId);
    return links[0] || null;
  },
  extraPreds(taskId) {
    return this.schedLinks().filter((l) => l.succ_id === taskId).slice(1);
  },

  async schedPatch(taskId, patch, phrase) {
    try {
      const out = await api(`/api/jobs/${encodeURIComponent(this.state.job)}/schedule/tasks/${taskId}`,
        { method: "PATCH", body: JSON.stringify(patch) });
      const moved = out.moved || [];
      const msg = phrase + (moved.length
        ? " " + moved.length + (moved.length === 1 ? " dependent task moved with it." : " dependent tasks moved with it.")
        : "");
      App.act(msg, out.activity_id, ["schedule"]);
    } catch (err) {
      setState({ live: "Could not apply that: " + err.message });
      App.refresh("schedule");
    }
  },

  setSchedDate: (taskId, field) => (e) => {
    const vv = e.target.value;
    if (!vv) return;
    const t = App.schedTasks().find((x) => x.id === taskId) || {};
    App.schedPatch(taskId, { [field]: vv },
      "“" + (t.name || "?") + "” " + field + " set to " + vv + ".");
  },

  setSchedPred: (taskId) => async (e) => {
    const predId = e.target.value;
    const t = App.schedTasks().find((x) => x.id === taskId) || {};
    const current = App.primaryPred(taskId);
    try {
      if (current) await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/links/${current.id}`, { method: "DELETE" });
      if (predId) {
        await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/links`, { method: "POST",
          body: JSON.stringify({ pred_id: predId, succ_id: taskId, link_type: (current || {}).link_type || "FS" }) });
        const p = App.schedTasks().find((x) => x.id === predId) || {};
        setState({ live: "“" + (t.name || "?") + "” now follows “" + (p.name || "?") + "” (" + ((current || {}).link_type || "FS") + ")." });
      } else {
        setState({ live: "Predecessor removed from “" + (t.name || "?") + "”." });
      }
      App.refresh("schedule");
    } catch (err) { setState({ live: err.message }); App.refresh("schedule"); }
  },

  setSchedDep: (taskId) => async (e) => {
    const type = e.target.value;
    const current = App.primaryPred(taskId);
    if (!current) return;
    const t = App.schedTasks().find((x) => x.id === taskId) || {};
    try {
      await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/links/${current.id}`, { method: "DELETE" });
      await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/links`, { method: "POST",
        body: JSON.stringify({ pred_id: current.pred_id, succ_id: taskId, link_type: type, lag_days: current.lag_days || 0 }) });
      setState({ live: "“" + (t.name || "?") + "” dependency is now " + type + "." });
      App.refresh("schedule");
    } catch (err) { setState({ live: err.message }); App.refresh("schedule"); }
  },

  addSchedSucc: (taskId) => async (e) => {
    const succId = e.target.value;
    if (!succId) return;
    const t = App.schedTasks().find((x) => x.id === taskId) || {};
    const sTask = App.schedTasks().find((x) => x.id === succId) || {};
    try {
      await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/links`, { method: "POST",
        body: JSON.stringify({ pred_id: taskId, succ_id: succId, link_type: "FS" }) });
      setState({ live: "“" + (sTask.name || "?") + "” now follows “" + (t.name || "?") + "” (FS)." });
      App.refresh("schedule");
    } catch (err) { setState({ live: err.message }); }
  },

  dropSchedLink: (linkId, phrase) => async () => {
    try {
      await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/links/${linkId}`, { method: "DELETE" });
      setState({ live: phrase });
      App.refresh("schedule");
    } catch (err) { setState({ live: err.message }); }
  },

  toggleSchedCollapse: (taskId) => async () => {
    const t = App.schedTasks().find((x) => x.id === taskId) || {};
    const next = t.collapsed ? 0 : 1;
    t.collapsed = next;   // optimistic — the caret flips under the pointer
    setState({ live: next
      ? "“" + (t.name || "?") + "” collapsed. Its subtasks are hidden but still scheduled."
      : "“" + (t.name || "?") + "” expanded." });
    try {
      await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/tasks/${t.id}`,
        { method: "PATCH", body: JSON.stringify({ collapsed: next }) });
    } catch (err) {}
  },

  toggleSchedPeek: (taskId) => () => {
    setState({ schedPeek: App.state.schedPeek === taskId ? null : taskId });
  },

  // Shared peek/drag bindings for one task — the prototype's schedRowProps,
  // consumed by BOTH the Gantt list and the register's peek row.
  schedRowProps(i) {
    const tasks = this.schedTasks();
    const t = tasks[i];
    const peek = this.state.schedPeek === t.id;
    const preds = this.schedLinks().filter((l) => l.succ_id === t.id);
    const primary = preds[0] || null;
    const succs = this.schedLinks().filter((l) => l.pred_id === t.id);
    const nameOf = (id) => { const x = tasks.find((y) => y.id === id) || {}; return (x.external_id ? x.external_id + " · " : "") + (x.name || "?"); };
    const hasKids = this.taskChildIdx(tasks, i).length > 0;
    return {
      hasSched: true, schedIdx: String(i),
      gripDown: App.schedRowDown(i),
      peekOpen: peek, togglePeek: App.toggleSchedPeek(t.id),
      peekAria: (peek ? "Close the details for " : "Peek at the dates and dependencies of ") + (t.name || "?"),
      peekChevron: peek ? "−" : "+",
      peekStart: t.start || "", peekFinish: t.finish || "",
      // Handoff resolved decision #4: a summary's dates are derived from its
      // children — the engine overwrites anything typed, so don't offer it.
      datesDisabled: !!t.is_summary && hasKids,
      setStart: App.setSchedDate(t.id, "start"), setFinish: App.setSchedDate(t.id, "finish"),
      predValue: primary ? primary.pred_id : "",
      predOpts: [{ value: "", label: "None" }].concat(tasks.filter((x) => x.id !== t.id).map((x) => ({ value: x.id, label: nameOf(x.id) }))),
      setPred: App.setSchedPred(t.id),
      depValue: primary ? primary.link_type || "FS" : "FS",
      depShow: !!primary,
      depOpts: DEP_TYPES.map(([value, label]) => ({ value, label: value + " — " + label })),
      setDep: App.setSchedDep(t.id),
      // Handoff resolved decision #2: one primary predecessor is editable;
      // the rest are listed read-only.
      morePreds: preds.slice(1).map((l) => nameOf(l.pred_id) + " (" + (l.link_type || "FS") + ")").join(", "),
      succChips: succs.map((l) => ({
        label: nameOf(l.succ_id) + " (" + (l.link_type || "FS") + ")" + (l.inferred && !l.confirmed_at ? " · inferred" : ""),
        drop: App.dropSchedLink(l.id, "“" + nameOf(l.succ_id).split("· ").pop() + "” no longer follows “" + (t.name || "?") + "”."),
        dropAria: "Remove the dependency: " + nameOf(l.succ_id) + " no longer follows " + (t.name || "?"),
      })),
      succNone: succs.length === 0,
      succOpts: [{ value: "", label: "Add a successor…" }].concat(
        tasks.filter((x) => x.id !== t.id && !succs.some((l) => l.succ_id === x.id)).map((x) => ({ value: x.id, label: nameOf(x.id) }))),
      addSucc: App.addSchedSucc(t.id),
    };
  },

  // ————— drags (prototype pointer handlers, verbatim mechanics) ————————————
  schedBarDown: (i) => (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    e.preventDefault();
    const track = e._el.parentElement;
    const rect = track.getBoundingClientRect();
    const gs = App.ganttSpan();
    App._schedDrag = { kind: "bar", i, x0: e.clientX, w: rect.width, spanMs: gs.span, delta: 0 };
    App._schedMoveH = (ev) => App.schedDragMove(ev);
    App._schedUpH = () => App.schedDragUp();
    document.addEventListener("pointermove", App._schedMoveH);
    document.addEventListener("pointerup", App._schedUpH);
  },
  schedRowDown: (i) => (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    e.preventDefault();
    App._schedDrag = { kind: "row", i, over: i };
    App._schedMoveH = (ev) => App.schedDragMove(ev);
    App._schedUpH = () => App.schedDragUp();
    document.addEventListener("pointermove", App._schedMoveH);
    document.addEventListener("pointerup", App._schedUpH);
  },
  schedDragMove(ev) {
    const d = App._schedDrag;
    if (!d) return;
    if (d.kind === "bar") {
      const days = Math.round((ev.clientX - d.x0) / d.w * (d.spanMs / 86400000));
      if (days !== d.delta) { d.delta = days; setState({ schedDrag: { kind: "bar", index: d.i, delta: days } }); }
      return;
    }
    const el = document.elementFromPoint(ev.clientX, ev.clientY);
    const row = el && el.closest ? el.closest("[data-sched-row]") : null;
    const parsed = row ? parseInt(row.getAttribute("data-sched-row")) : NaN;
    const over = isNaN(parsed) ? d.over : parsed;
    if (over !== d.over) { d.over = over; setState({ schedDrag: { kind: "row", index: d.i, over } }); }
  },
  schedDragUp() {
    document.removeEventListener("pointermove", App._schedMoveH);
    document.removeEventListener("pointerup", App._schedUpH);
    const d = App._schedDrag;
    App._schedDrag = null;
    setState({ schedDrag: null });
    if (!d) return;
    if (d.kind === "bar" && d.delta) App.confirmSchedMove(d.i, d.delta);
    if (d.kind === "row" && d.over !== d.i) App.confirmSchedReorder(d.i, d.over);
  },

  confirmSchedMove(i, delta) {
    const tasks = this.schedTasks();
    const t = tasks[i];
    const MS = 86400000;
    const shift = (iso) => new Date(new Date(iso + "T00:00:00Z").getTime() + delta * MS).toISOString().slice(0, 10);
    const ns = shift(t.start), nf = shift(t.finish);
    const dir = delta > 0 ? "later" : "earlier";
    const succs = this.schedLinks().filter((l) => l.pred_id === t.id);
    const checks = [
      ["pass", "The move", "“" + (t.name || "?") + "” shifts " + Math.abs(delta) + (Math.abs(delta) === 1 ? " day " : " days ") + dir + ": " + ns + " to " + nf + ". Duration is unchanged."],
      succs.length
        ? ["warn", "Downstream tasks", "The engine reschedules every dependent task to keep its constraints satisfied — the exact list is announced when the move applies. " + succs.length + (succs.length === 1 ? " task follows this one directly." : " tasks follow this one directly.")]
        : ["pass", "Downstream tasks", "Nothing else depends on these dates. No other bar moves."],
      t.is_critical
        ? ["warn", "Critical path", "This task is on the critical path. Moving it " + dir + (delta > 0 ? " moves the job finish date." : " may create float elsewhere.")]
        : ["pass", "Critical path", "This task carries float, so the finish date should hold."],
    ];
    // Dates only push (handoff resolved decision #1): the stored start is a
    // floor, so a drag EARLIER can be pulled back by the network the moment
    // the engine recomputes. Say so before it happens.
    if (delta < 0 && this.primaryPred(t.id)) {
      checks.splice(1, 0, ["warn", "Its own predecessor",
        "This task follows another. Constraints push, never pull — if the move lands before what its predecessor allows, the engine holds it at the earliest date the network permits."]);
    }
    setState({
      confirm: {
        eyebrow: "Confirm a schedule move", title: t.name || "?",
        body: "You dragged this bar on the Gantt. Nothing has changed yet — the move applies when you confirm it, and it is undoable afterwards.",
        checks, blocked: false,
        verdict: "The Gantt and the register update together the moment you confirm.",
        label: "Move this task",
        run: () => {
          setState({ confirm: null });
          App.schedPatch(t.id, { start: ns, finish: nf },
            "“" + (t.name || "?") + "” moved to " + ns + " – " + nf + ".");
        },
      },
    }, focusRef("confirm"));
  },

  confirmSchedReorder(from, over) {
    const tasks = this.schedTasks();
    if (over === undefined || over === null || isNaN(over) || over === from) return;
    const block = [from].concat(this.taskChildIdx(tasks, from));
    if (block.includes(over)) return;
    const t = tasks[from], target = tasks[over];
    setState({
      confirm: {
        eyebrow: "Confirm a register reorder", title: t.name || "?",
        body: "You dragged this row. Reordering changes reading order only — dates, dependencies and the Gantt bars stay exactly as they are.",
        checks: [
          ["pass", "The move", "“" + (t.name || "?") + "”" + (block.length > 1 ? " and its " + (block.length - 1) + " subtask" + (block.length === 2 ? "" : "s") : "") + " move " + (over > from ? "below" : "above") + " “" + (target.name || "?") + "”."],
          ["pass", "Dates", "No dates change. A reorder is presentation only."],
        ],
        blocked: false,
        verdict: "The register and the Gantt re-list in the new order when you confirm.",
        label: "Reorder the register",
        run: async () => {
          setState({ confirm: null });
          // Rebuild the order client-side, then persist a fresh sort_order
          // for every task whose position changed.
          const rows = tasks.slice();
          const lift = block.map((j) => rows[j]);
          const rest = rows.filter((x, j) => !block.includes(j));
          let at = rest.findIndex((x) => x.id === target.id);
          if (at < 0) at = rest.length - 1;
          const insertAt = over > from ? at + 1 : at;
          const next = rest.slice(0, insertAt).concat(lift, rest.slice(insertAt));
          try {
            for (let k = 0; k < next.length; k++) {
              if ((next[k].sort_order ?? null) !== k) {
                await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/tasks/${next[k].id}`,
                  { method: "PATCH", body: JSON.stringify({ sort_order: k }) });
              }
            }
            setState({ live: "“" + (t.name || "?") + "” moved " + (over > from ? "below" : "above") + " “" + (target.name || "?") + "” on the register. Dates and dependencies are untouched." });
            App.refresh("schedule");
          } catch (err) { setState({ live: err.message }); App.refresh("schedule"); }
        },
      },
    }, focusRef("confirm"));
  },

  clearSchedule() {
    const n = App.schedTasks().length;
    setState({
      confirm: {
        eyebrow: "Clear the schedule", title: "Remove every task on job " + App.state.job,
        body: "The way back from a bad import. Every task and every dependency goes; the working calendar survives, because working days are a property of the job, not the tasks.",
        checks: [
          ["warn", "The removal", n + (n === 1 ? " task" : " tasks") + " and every link between them are removed."],
          ["pass", "Look ahead", "Look-ahead rows seeded from these tasks keep their own rows; they simply stop pointing anywhere."],
          ["warn", "No undo", "Clearing is not reversible from the undo bar. Re-import the schedule file to rebuild."],
        ],
        blocked: false,
        verdict: "The register and the Gantt empty the moment you confirm.",
        label: "Clear the schedule",
        run: async () => {
          try {
            await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/tasks`, { method: "DELETE" });
            setState({ confirm: null, live: "Schedule cleared." });
            App.refresh("schedule");
          } catch (err) { setState({ confirm: null, live: err.message }); }
        },
      },
    }, focusRef("confirm"));
  },

  // ————— import (1.x staging flow, kept — richer than the prototype's) ————
  triggerSchedImport() {
    let input = document.getElementById("sched-import-input");
    if (!input) {
      input = document.createElement("input");
      input.type = "file"; input.accept = ".mpp,.xml,.mspdi,.pdf,.xlsx,.xlsm,.csv";
      input.id = "sched-import-input"; input.style.display = "none";
      document.body.appendChild(input);
      input.addEventListener("change", () => {
        if (input.files && input.files[0]) App.runSchedImport(input.files[0]);
        input.value = "";
      });
    }
    input.click();
  },
  async runSchedImport(file) {
    setState({ live: "Reading " + file.name + "…" });
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/import?mode=replace`,
        { method: "POST", body: fd, credentials: "same-origin" });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(out.detail || r.status);
      if (out.committed) {
        setState({ live: "Imported " + (out.tasks ?? "the") + " tasks from " + file.name + "." });
        App.refresh("schedule");
      } else {
        setState({ live: "Staged " + file.name + " for review — nothing lands until you commit it." });
        App.refresh("schedule");
        App.loadStagedImport();
      }
    } catch (err) {
      setState({ live: "Couldn't read that file: " + err.message });
    }
  },
  async loadStagedImport() {
    try {
      const staged = await api(`/api/jobs/${encodeURIComponent(App.state.job)}/schedule/import/staged`);
      if (!staged || !staged.id) { setState({ schedStaged: null }); return; }
      const detail = await api(`/api/schedule/import/${staged.id}`);
      detail.accept = {};
      (detail.links || []).forEach((l) => { detail.accept[l.id] = (l.confidence || 0) >= 0.45; });
      setState({ schedStaged: detail });
    } catch (e) { setState({ schedStaged: null }); }
  },
  async commitStagedImport(mode) {
    const st = App.state.schedStaged;
    if (!st) return;
    try {
      const ids = Object.keys(st.accept).filter((k) => st.accept[k]);
      await api(`/api/schedule/import/${st.id}/commit`, { method: "POST",
        body: JSON.stringify({ mode: mode || "replace", accepted_link_ids: ids }) });
      setState({ schedStaged: null, live: "Import committed. The schedule below is what landed." });
      App.refresh("schedule");
    } catch (err) { setState({ live: err.message }); }
  },
  async discardStagedImport() {
    const st = App.state.schedStaged;
    if (!st) return;
    try {
      await api(`/api/schedule/import/${st.id}/discard`, { method: "POST" });
      setState({ schedStaged: null, live: "Import discarded. Nothing changed." });
    } catch (err) { setState({ live: err.message }); }
  },

  // ————— Gantt frame (real project span, padded to month edges) ————————————
  ganttSpan() {
    const sd = this.state.data.schedule || {};
    const start = sd.project_start ? new Date(sd.project_start + "T00:00:00Z") : new Date();
    const finish = sd.project_finish ? new Date(sd.project_finish + "T00:00:00Z") : new Date(start.getTime() + 120 * 86400000);
    const t0 = Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), 1);
    const t1 = Date.UTC(finish.getUTCFullYear(), finish.getUTCMonth() + 1, 1);
    return { t0, t1, span: Math.max(t1 - t0, 86400000) };
  },
  schedZoomIn() { setState({ schedZoom: Math.min(6, (App.state.schedZoom || 1) * 1.4) }); },
  schedZoomOut() { setState({ schedZoom: Math.max(0.5, (App.state.schedZoom || 1) / 1.4) }); },
  schedZoomReset() { setState({ schedZoom: 1 }); },
});

// ————— schedule view models: Gantt rows + register branch ————————————————
Object.assign(App, {
  buildSched() {
    const s = this.state;
    if (s.page !== "sched") return {};
    const sd = s.data.schedule || {};
    const tasks = this.schedTasks();
    const links = this.schedLinks();
    const gs = this.ganttSpan();
    const zoom = s.schedZoom || 1;
    const hidden = this.schedHiddenSet(tasks);
    const drag = s.schedDrag;
    const today = Date.now();
    const todayPct = Math.min(100, Math.max(0, (today - gs.t0) / gs.span * 100));

    // Month header cells across the real project span.
    const months = [];
    for (let t = gs.t0; t < gs.t1;) {
      const d = new Date(t);
      months.push({ label: ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getUTCMonth()] +
        (d.getUTCMonth() === 0 || t === gs.t0 ? " ’" + String(d.getUTCFullYear()).slice(2) : ""),
        style: "flex:1;font:500 10px var(--fm);letter-spacing:.08em;color:var(--ft);text-align:left;border-left:1px solid " + (t === gs.t0 ? "transparent" : "var(--ln)") + ";padding-left:5px" });
      t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
    }

    const ms = (iso) => new Date((iso || "") + "T00:00:00Z").getTime();
    const num = (t) => t.external_id || "";
    const ganttRows = tasks.map((t, i) => ({ t, i })).filter((p) => !hidden[p.i]).map(({ t, i }) => {
      const dragMs = drag && drag.kind === "bar" && drag.index === i ? drag.delta * 86400000 : 0;
      // Bars draw from the ENGINE's early dates where it computed them: a
      // stored date is a floor (push-only, D43), so the bar the field sees
      // must be where the network actually puts the work, not the floor.
      const barStart = t.early_start || t.start;
      const barFinish = t.early_finish || t.finish;
      const start = (ms(barStart) + dragMs - gs.t0) / gs.span * 100;
      const end = (ms(barFinish) + 86400000 + dragMs - gs.t0) / gs.span * 100;
      const w = Math.max(0.8, end - start);
      const pct = Math.round(t.percent_complete || 0);
      const done = pct >= 100;
      const color = taskColor(num(t) || i + 1);
      const summary = !!t.is_summary;
      const milestone = !!t.is_milestone && !summary;
      const kids = this.taskChildIdx(tasks, i);
      const collapsed = !!t.collapsed;
      const rowOver = drag && drag.kind === "row" && drag.over === i && drag.index !== i;
      const rowLift = drag && drag.kind === "row" && drag.index === i;
      const primary = links.find((l) => l.succ_id === t.id);
      const pr = primary ? tasks.find((x) => x.id === primary.pred_id) : null;
      const critical = !!t.is_critical;
      const floatTxt = t.total_float === null || t.total_float === undefined ? "" : Math.round(t.total_float) + " d float";
      return {
        ...this.schedRowProps(i),
        num: num(t), name: t.name || "?", idx: String(i),
        edit: App.openTaskForm(t.id),
        rowStyle: "border-bottom:1px solid var(--ln);background:" + (rowOver ? "var(--bps)" : rowLift ? "var(--p2)" : "transparent") +
          (rowOver ? ";box-shadow:inset 0 2px 0 var(--bp)" : "") + (rowLift ? ";opacity:.55" : ""),
        caretShow: kids.length > 0,
        caret: collapsed ? "▸" : "▾",
        caretAria: (collapsed ? "Expand" : "Collapse") + " " + (t.name || "?") + ", " + kids.length + (kids.length === 1 ? " subtask" : " subtasks"),
        toggleCollapse: App.toggleSchedCollapse(t.id),
        kidCount: collapsed && kids.length ? "+" + kids.length : "",
        swatch: "width:10px;height:10px;border-radius:3px;flex:none;background:" + color + (critical ? ";box-shadow:0 0 0 2px var(--ers)" : ""),
        nameStyle: "text-align:left;font:" + (summary ? "600" : "500") + " 12.5px var(--fd);color:var(--bp);text-decoration:underline;text-underline-offset:3px;min-height:24px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0",
        indentStyle: "display:inline-block;width:" + ((t.outline_level || 0) * 12) + "px;flex:none",
        trackStyle: "position:absolute;left:0;right:0;top:11px;height:4px;border-radius:2px;background:var(--ln)",
        barDown: App.schedBarDown(i),
        isMilestone: milestone,
        msStyle: "position:absolute;top:6px;left:calc(" + start.toFixed(2) + "% - 7px);width:14px;height:14px;background:" + color + ";transform:rotate(45deg);border-radius:2px;cursor:grab;touch-action:none" + (critical ? ";box-shadow:0 0 0 2px var(--ers)" : ""),
        barStyle: "position:absolute;top:" + (summary ? "8px" : "6px") + ";left:" + start.toFixed(2) + "%;width:" + w.toFixed(2) + "%;height:" + (summary ? "10px" : "14px") +
          ";border-radius:" + (summary ? "2px" : "4px") + ";background:" + taskSoft(num(t) || i + 1) + ";border:" + (critical ? "2px" : "1px") + " solid " + color + ";overflow:hidden;cursor:grab;touch-action:none" +
          (summary ? ";clip-path:polygon(0 0,100% 0,100% 100%,calc(100% - 6px) 55%,6px 55%,0 100%)" : "") +
          (dragMs ? ";box-shadow:0 3px 10px rgba(24,27,30,.25);cursor:grabbing" : ""),
        fillStyle: "display:block;height:100%;width:" + pct + "%;background:" + color + ";opacity:" + (done ? ".55" : "1") + ";pointer-events:none",
        todayStyle: "position:absolute;top:0;bottom:0;left:" + todayPct.toFixed(2) + "%;width:1px;background:var(--ac);opacity:.5",
        aria: (t.name || "?") + ", " + (barStart || "") + " to " + (barFinish || "") + ", " + pct + "% complete, " +
          (critical ? "on the critical path" : floatTxt || "float not computed") +
          (pr ? ", follows " + (pr.name || "?") + " " + (DEP_NAME[primary.link_type] || primary.link_type || "FS") : "") +
          ". Drag the bar to move it; changes ask for confirmation.",
      };
    });

    return {
      hasSchedule: tasks.length > 0,
      schedEmpty: tasks.length === 0,
      ganttMonths: months,
      ganttRows,
      ganttMinWidth: Math.max(760, Math.round(months.length * 90 * zoom)),
      ganttRange: (sd.project_start ? usDate(sd.project_start) : "—") + " – " + (sd.project_finish ? usDate(sd.project_finish) : "—") + " · today " + usDate(new Date().toISOString().slice(0, 10)),
      schedZoomIn: () => App.schedZoomIn(), schedZoomOut: () => App.schedZoomOut(), schedZoomReset: () => App.schedZoomReset(),
      schedZoomLabel: Math.round((s.schedZoom || 1) * 100) + "%",
      openNewTask: App.openForm("task"),
      triggerSchedImport: () => App.triggerSchedImport(),
      clearSchedule: () => App.clearSchedule(),
      calendarNote: (() => {
        const cal = sd.calendar || {};
        const mask = cal.workdays || "1111100";
        const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].filter((d2, i2) => mask[i2] === "1").join(", ");
        const hol = (cal.holidays || []).length;
        return "Working days: " + days + (hol ? " · " + hol + " holidays" : "") + ". Float is in working days on this calendar.";
      })(),
      mppNote: ((sd.mpp || {}).available === false) ? "Binary .mpp import needs Java on the server; XML, PDF, Excel and CSV import regardless." : "",
      staged: s.schedStaged ? {
        counts: s.schedStaged.counts || {},
        warnings: s.schedStaged.warnings || [],
        links: (s.schedStaged.links || []).map((l) => ({
          ...l, on: !!s.schedStaged.accept[l.id],
          toggle: () => { s.schedStaged.accept[l.id] = !s.schedStaged.accept[l.id]; setState({}); },
        })),
        tickAll: (on) => () => { (s.schedStaged.links || []).forEach((l) => { s.schedStaged.accept[l.id] = on; }); setState({}); },
        commit: () => App.commitStagedImport("replace"),
        discard: () => App.discardStagedImport(),
      } : null,
    };
  },

  openTaskForm: (taskId) => () => {
    const t = App.schedTasks().find((x) => x.id === taskId) || {};
    App.openForm("task", { taskId, task: t })();
  },
});

// task form kind + submit (extends the chain built in part 6)
(() => {
  const baseSpec = App.formSpec.bind(App);
  App.formSpec = function (kind, ctx) {
    if (kind !== "task") return baseSpec(kind, ctx);
    const t = (ctx || {}).task || {};
    const editing = !!(ctx || {}).taskId;
    const tasks = this.schedTasks();
    const primary = editing ? this.primaryPred(t.id) : null;
    return {
      eyebrow: editing ? "Editing a task" : "New task",
      title: editing ? "Edit this schedule task" : "Add a schedule task",
      submit: editing ? "Save these changes" : "Add this task",
      intro: editing
        ? "The schedule is a working tool, not a frozen import. Editing a task moves its bar on the Gantt immediately and recalculates what the register shows."
        : "Add work the imported schedule never had. Tasks added here are marked as PlanWise-owned so an import cannot silently overwrite them.",
      fields: [
        ["name", "Task", "text", { req: true, wide: true, value: t.name || "", placeholder: "Relay panel terminations, Bay 3", hint: "The words the crew and the customer would both recognise." }],
        ["start", "Start", "date", { req: true, value: t.start || new Date().toISOString().slice(0, 10), hint: "" }],
        ["finish", "Finish", "date", { req: true, value: t.finish || "", hint: "Must be on or after the start date." }],
        ["pct", "Percent complete", "text", { req: true, value: String(Math.round(t.percent_complete || 0)), placeholder: "0", hint: "Whole number from 0 to 100. Float and the critical path are computed by the engine, never typed." }],
        ["level", "Indent level", "select", { req: true, value: String(t.outline_level ?? 1), options: [["0", "Summary"], ["1", "Task"], ["2", "Subtask"]], hint: "Sets how far the task is indented on the Gantt." }],
        ["milestone", "Milestone", "select", { req: true, value: t.is_milestone ? "Yes" : "No", options: [["No", "No"], ["Yes", "Yes"]], hint: "A milestone draws as a diamond on its start date." }],
        ["pred", "Predecessor", "select", { value: primary ? primary.pred_id : "", options: [["", "None"]].concat(tasks.filter((x) => x.id !== t.id).map((x) => [x.id, (x.external_id ? x.external_id + " · " : "") + (x.name || "?")])), hint: "The task this one waits on. Moving the predecessor pushes this task with it." }],
        ["dep", "Dependency type", "select", { value: primary ? primary.link_type || "FS" : "FS", options: DEP_TYPES.map(([vv, l]) => [vv, vv + " — " + l]), hint: "FS is the usual case: this task starts after the predecessor finishes." }],
      ],
      review: editing
        ? "Changes apply to the Gantt and the register straight away, and are undoable."
        : "The task is added to the Gantt and the register. It does not write back to the customer's schedule file.",
    };
  };

  const baseSubmit = App.submitForm.bind(App);
  App.submitForm = async function () {
    const f = App.state.form;
    if (!f || f.kind !== "task") return baseSubmit();
    const spec = App.formSpec(f.kind, f.ctx);
    const errs = App.formErrors(spec, f);
    const p = parseInt(f.values.pct);
    if (f.values.start && f.values.finish && f.values.finish < f.values.start) errs.push("Finish cannot be before start.");
    if (String(f.values.pct).trim() && (isNaN(p) || p < 0 || p > 100)) errs.push("Percent complete must be a whole number between 0 and 100.");
    if (errs.length) {
      f.submitted = true;
      setState({ live: errs.length + " field" + (errs.length === 1 ? "" : "s") + " need attention." });
      return;
    }
    const job = encodeURIComponent(App.state.job);
    const editing = !!(f.ctx || {}).taskId;
    const body = { name: f.values.name, start: f.values.start, finish: f.values.finish,
      percent_complete: p || 0, outline_level: parseInt(f.values.level) || 1,
      is_milestone: f.values.milestone === "Yes" ? 1 : 0 };
    try {
      let taskId, actId, phrase;
      if (editing) {
        const out = await api(`/api/jobs/${job}/schedule/tasks/${f.ctx.taskId}`, { method: "PATCH", body: JSON.stringify(body) });
        taskId = f.ctx.taskId; actId = out.activity_id;
        const moved = (out.moved || []).length;
        phrase = "“" + f.values.name + "” updated." + (moved ? " " + moved + " dependent task" + (moved === 1 ? "" : "s") + " moved with it." : "");
      } else {
        const out = await api(`/api/jobs/${job}/schedule/tasks`, { method: "POST", body: JSON.stringify(body) });
        taskId = out.id;
        const acts = await api(`/api/jobs/${job}/activity?limit=1`);
        actId = ((acts.activity || [])[0] || {}).id;
        phrase = "“" + f.values.name + "” added to the schedule.";
      }
      // Primary predecessor: reconcile the link.
      const prevLink = App.primaryPred(taskId);
      const wantPred = f.values.pred || "";
      const wantType = f.values.dep || "FS";
      if (prevLink && (!wantPred || prevLink.pred_id !== wantPred || (prevLink.link_type || "FS") !== wantType)) {
        await api(`/api/jobs/${job}/schedule/links/${prevLink.id}`, { method: "DELETE" }).catch(() => {});
      }
      if (wantPred && (!prevLink || prevLink.pred_id !== wantPred || (prevLink.link_type || "FS") !== wantType)) {
        await api(`/api/jobs/${job}/schedule/links`, { method: "POST",
          body: JSON.stringify({ pred_id: wantPred, succ_id: taskId, link_type: wantType }) }).catch(() => {});
      }
      setState({ form: null });
      App.act(phrase, actId, ["schedule"]);
    } catch (err) {
      setState({ live: "Could not save the task: " + err.message });
    }
  };
})();

// ————— look ahead (1.x model, kept — prototype grid in front of it) —————————
Object.assign(App, {
  laPeriod() { return this.state.data.lookahead || {}; },
  laAreas() { return ((this.state.data.areas || {}).areas) || []; },

  toggleTick: (itemId, dayIndex) => async () => {
    // Optimistic: patch the cached bitmap in place (1.x behavior, kept — a
    // crew ticking across a row must not wait a round-trip per tick).
    const la = App.laPeriod();
    const item = (la.items || []).find((i) => i.id === itemId);
    if (item) {
      const days = (item.days || "").padEnd(21, "0").split("");
      days[dayIndex] = days[dayIndex] === "1" ? "0" : "1";
      item.days = days.join("");
      setState({});
    }
    try {
      await api(`/api/lookahead/items/${itemId}/day/${dayIndex}`, { method: "POST" });
    } catch (err) {
      setState({ live: "That tick did not save: " + err.message });
      App.refresh("lookahead");
    }
  },

  setLaWeeks: (weeks) => async () => {
    const la = App.laPeriod();
    try {
      await api(`/api/lookahead/${la.id}`, { method: "PATCH", body: JSON.stringify({ weeks }) });
      App.refresh("lookahead");
    } catch (err) { setState({ live: err.message }); }
  },

  async seedLook() {
    const la = App.laPeriod();
    if (!la.id) return;
    try {
      const out = await api(`/api/lookahead/${la.id}/seed`, { method: "POST" });
      setState({ live: (out.added ?? "The schedule's") + " activities seeded from the schedule. Re-seeding later adds only what is new and never disturbs hand edits." });
      App.refresh("lookahead");
    } catch (err) { setState({ live: err.message }); }
  },

  removeLaItem: (itemId) => async () => {
    const item = (App.laPeriod().items || []).find((i) => i.id === itemId) || {};
    try {
      await api(`/api/lookahead/items/${itemId}`, { method: "DELETE" });
      const acts = await api(`/api/jobs/${encodeURIComponent(App.state.job)}/activity?limit=1`);
      App.act("“" + (item.description || "the activity") + "” removed from the look ahead.",
        ((acts.activity || [])[0] || {}).id, ["lookahead"]);
    } catch (err) { setState({ live: err.message }); }
  },

  shareLook: (audience) => async () => {
    const la = App.laPeriod();
    if (!la.id) return;
    try {
      const payload = await api(`/api/lookahead/${la.id}/share?audience=${audience}&weeks=${la.weeks || 2}`);
      await companionFetch("/draft", { to: payload.to || "", subject: payload.subject,
        html: payload.html, attachments: [{ filename: payload.filename || "look-ahead.pdf", content_b64: payload.pdf_b64 }], display: true });
      setState({ live: audience === "customer"
        ? "The customer look ahead is drafted in Outlook. Tools, material and operational notes were stripped from it."
        : "The internal look ahead is drafted in Outlook with tools and material on it. Address it before sending." });
    } catch (err) {
      const eml = `/api/lookahead/${la.id}/share.eml?audience=${audience}&weeks=${la.weeks || 2}`;
      if (isNetErr(err)) {
        setState({ live: "No Outlook companion here — downloading the email file instead." });
        downloadEmlUrl(eml, "Email file downloaded. Open it in Outlook and press Send.");
      } else {
        setState({ live: "The companion refused: " + err.message + " — downloading the email file instead." });
        downloadEmlUrl(eml);
      }
    }
  },

  buildLook() {
    const s = this.state;
    if (s.page !== "look") return {};
    const la = this.laPeriod();
    const areas = this.laAreas();
    const items = la.items || [];
    const weeks = la.weeks || 2;
    const shown = weeks * 7;
    const days = (la.days || []).slice(0, shown);
    const areaOf = (id) => areas.find((a) => a.id === id);

    const lookRows = items.map((r) => {
      const bitmap = (r.days || "").padEnd(21, "0");
      const on = bitmap.slice(0, shown).split("").filter((t) => t === "1").length;
      const area = areaOf(r.work_area_id) || { name: "No area", color: "var(--nt)" };
      const notes = [];
      if (r.requirements) notes.push({ tag: "Customer", text: r.requirements, color: "var(--bp)" });
      if (r.notes) notes.push({ tag: "Ops", text: r.notes, color: "var(--nt)" });
      return {
        id: r.id, name: r.description || "?", area: area.name, areaColor: area.color || "var(--nt)",
        notes, hasNotes: notes.length > 0,
        tools: r.tools || "None",
        edit: App.openForm("look", { itemId: r.id, item: r }),
        remove: App.removeLaItem(r.id),
        count: on + (on === 1 ? " day" : " days"),
        days: days.map((d, di) => {
          const isOn = bitmap[di] === "1";
          return {
            pressed: isOn ? "true" : "false",
            label: (isOn ? "Worked" : "Not worked") + " on " + d.dow + " " + d.day + ", " + (r.description || "?") + ", " + area.name + ". Select to change.",
            mark: isOn ? "✓" : "",
            toggle: App.toggleTick(r.id, di),
            cellStyle: "padding:3px 2px;text-align:center;border-bottom:1px solid var(--ln);border-right:1px solid " +
              ((di + 1) % 7 === 0 ? "var(--ls)" : "var(--ln)") + ";background:" + (d.weekend ? "var(--p2)" : "transparent"),
            style: "width:26px;height:24px;border-radius:4px;font:700 12px var(--fd);border:1px solid " +
              (isOn ? (area.color || "var(--nt)") : "var(--ln)") + ";background:" + (isOn ? (area.color || "var(--nt)") : "var(--pn)") +
              ";color:" + (isOn ? "#FFFFFF" : "var(--ft)"),
          };
        }),
      };
    });

    const ticked = items.reduce((t, r) => t + (r.days || "").slice(0, shown).split("").filter((x) => x === "1").length, 0);
    return {
      hasLook: !!la.id,
      lookDays: days.map((d, i) => ({
        dow: d.dow, num: String(d.day),
        style: "padding:5px 2px;text-align:center;color:" + (d.weekend ? "var(--ft)" : "var(--mu)") +
          ";font:500 var(--lbl) var(--fm);letter-spacing:.03em;border-bottom:1px solid var(--ls);border-right:1px solid " +
          ((i + 1) % 7 === 0 ? "var(--ls)" : "var(--ln)") + ";background:" + (d.weekend ? "var(--p2)" : "transparent") + ";min-width:32px",
      })),
      lookRows, lookTicked: ticked,
      lookRangeLabel: la.start_date ? usDate(la.start_date) + " – " + usDate(la.end_date) + " · " + ticked + " days ticked" : "",
      lookWeeksOpts: [2, 3].map((w) => ({
        label: w + " wk", pressed: weeks === w ? "true" : "false",
        pick: App.setLaWeeks(w), style: chip(weeks === w) })),
      areaCount: areas.length + (areas.length === 1 ? " area" : " areas") + " on this job",
      areaChips: areas.map((a) => {
        const n = items.filter((r) => r.work_area_id === a.id).length;
        return { name: a.name, color: a.color || "var(--nt)", count: n + (n === 1 ? " activity" : " activities") };
      }).concat(items.some((r) => !r.work_area_id)
        ? [{ name: "No area", color: "var(--nt)", count: items.filter((r) => !r.work_area_id).length + " activities" }] : []),
      openNewArea: App.openForm("area"),
      openNewLook: App.openForm("look"),
      seedLook: () => App.seedLook(),
      shareLookCust: App.openShareWith({ "look-cust": true }),
      shareLookInt: App.openShareWith({ "look-int": true }),
      lookWeekCount: weeks === 2 ? "Two-week look ahead" : "Three-week look ahead",
    };
  },
});

// look/area form kinds
(() => {
  const baseSpec = App.formSpec.bind(App);
  App.formSpec = function (kind, ctx) {
    if (kind === "area") return {
      eyebrow: "New work area", title: "Add a work area", submit: "Add this work area",
      intro: "Work areas group the look ahead the way the site is actually divided. Each one carries a colour so the crew can read the grid at a glance.",
      fields: [
        ["name", "Area name", "text", { req: true, wide: true, placeholder: "Control building", hint: "The name the crew already uses for it on site." }],
      ],
      colors: true,
      review: "The area becomes selectable on every look-ahead activity and its colour appears on the grid straight away.",
    };
    if (kind === "look") {
      const item = (ctx || {}).item || {};
      const editing = !!(ctx || {}).itemId;
      const areas = App.laAreas();
      return {
        eyebrow: editing ? "Editing an activity" : "New activity",
        title: editing ? "Edit this look-ahead activity" : "Add an activity to the look ahead",
        submit: editing ? "Save these changes" : "Add this activity",
        intro: editing
          ? "Everything here is editable. Tools, material and operational notes stay internal; the customer copy carries the activity, the area and the days only."
          : "Activities can come from the schedule or be added by hand when the field finds work the schedule never had.",
        fields: [
          ["name", "Activity", "text", { req: true, wide: true, value: item.description || "", placeholder: "Set bus insulators, Bay 3", hint: "The words the crew would use for it." }],
          ["area", "Work area", "select", { value: item.work_area_id || "", options: [["", "No area"]].concat(areas.map((a) => [a.id, a.name])), hint: "Optional. An area sets the colour this activity carries on the grid; without one it uses the job's default colour." }],
          ["custReq", "Customer requirement", "textarea", { rows: 2, wide: true, value: item.requirements || "", placeholder: "Escort required inside the Bay 3 fence for the full outage.", hint: "Something the customer has to provide or permit. Appears on the customer copy." }],
          ["opsNote", "Operational note", "textarea", { rows: 2, wide: true, value: item.notes || "", placeholder: "Two crews, staggered start at 6 am.", hint: "Internal only. Never appears on the customer copy." }],
          ["tools", "Tools", "text", { value: item.tools || "", placeholder: "90-ton crane, torque wrenches", hint: "Internal only. Stripped from the customer copy." }],
          ["material", "Material", "text", { value: item.materials || "", placeholder: "Insulators (24), hardware kits", hint: "Internal only. Stripped from the customer copy." }],
        ],
        review: editing
          ? "Changes apply to the grid immediately. The customer copy is regenerated the next time you share it."
          : "The activity is added to the grid. Tick its days straight from the grid; nothing is sent to anyone until you share the look ahead.",
      };
    }
    return baseSpec(kind, ctx);
  };

  const baseSubmit = App.submitForm.bind(App);
  App.submitForm = async function () {
    const f = App.state.form;
    if (!f || (f.kind !== "look" && f.kind !== "area")) return baseSubmit();
    const spec = App.formSpec(f.kind, f.ctx);
    const errs = App.formErrors(spec, f);
    if (errs.length) {
      f.submitted = true;
      setState({ live: errs.length + " field" + (errs.length === 1 ? "" : "s") + " need attention." });
      return;
    }
    try {
      if (f.kind === "area") {
        await api(`/api/jobs/${encodeURIComponent(App.state.job)}/lookahead/areas`, { method: "POST",
          body: JSON.stringify({ name: f.values.name, color: (AREA_COLORS[f.color || 0] || [])[1]
            ? getComputedStyle(document.documentElement).getPropertyValue(
                (AREA_COLORS[f.color || 0][1].match(/var\((--[a-z]+)\)/) || [])[1] || "--nt").trim() || "#5C636A"
            : "#5C636A" }) });
        setState({ form: null, live: "Work area “" + f.values.name + "” added in " + AREA_COLORS[f.color || 0][0].toLowerCase() + "." });
        App.refresh("areas", "lookahead");
      } else {
        const body = { description: f.values.name, work_area_id: f.values.area || null,
          requirements: f.values.custReq || null, notes: f.values.opsNote || null,
          tools: f.values.tools || null, materials: f.values.material || null };
        const editing = !!(f.ctx || {}).itemId;
        if (editing) {
          await api(`/api/lookahead/items/${f.ctx.itemId}`, { method: "PATCH", body: JSON.stringify(body) });
          setState({ form: null, live: "“" + f.values.name + "” updated on the look ahead." });
        } else {
          const la = App.laPeriod();
          const out = await api(`/api/lookahead/${la.id}/items`, { method: "POST", body: JSON.stringify(body) });
          setState({ form: null });
          App.act("“" + f.values.name + "” added to the look ahead. Tick its days on the grid.",
            out.activity_id, ["lookahead"]);
        }
        App.refresh("lookahead");
      }
    } catch (err) {
      setState({ live: "Could not save: " + err.message });
    }
  };
})();

// ————— RFIs / submittals: detail, send ladder, thread, confirm ——————————————
Object.assign(App, {
  recById(id) {
    return (((this.state.data.records || {}).records) || []).find((r) => r.id === id);
  },

  async loadRecordExtras(recId) {
    // Draft + replies for the thread page; cached per record.
    const key = "rec:" + recId;
    if (this.state.data[key]) return;
    try {
      const [draft, replies] = await Promise.all([
        api(`/api/records/${recId}/draft`).catch(() => ({})),
        api(`/api/records/${recId}/replies`).catch(() => ({ replies: [] })),
      ]);
      this.state.data[key] = { draft, replies: replies.replies || [] };
      setState({});
    } catch (e) {}
  },

  sendRecord: (recId) => async () => {
    const rec = App.recById(recId) || {};
    try {
      // Ensure a draft exists (AI-or-template; the pipeline works without spend).
      let draft = await api(`/api/records/${recId}/draft`).catch(() => null);
      if (!draft || !draft.subject) {
        draft = await api(`/api/records/${recId}/draft`, { method: "POST", body: JSON.stringify({}) });
      }
      const pkgResp = await fetch(`/api/records/${recId}/package`, { credentials: "same-origin" });
      let attachments = [];
      if (pkgResp.ok) {
        const buf = new Uint8Array(await pkgResp.arrayBuffer());
        let bin = "";
        for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        attachments = [{ filename: (rec.number || "record") + " package.pdf", content_b64: btoa(bin) }];
      }
      const out = await companionFetch("/draft", { to: rec.to_email || "", subject: draft.subject,
        body: draft.body, attachments, display: true });
      setState({ live: (rec.number || "The record") + " is drafted in Outlook" +
        (out.unresolved && out.unresolved.length ? ", but Outlook could not resolve " + out.unresolved.join(", ") + " — pick the address before sending." : ". Press Send there; PlanWise flips it to Sent when the companion sees it leave.") });
    } catch (err) {
      const eml = `/api/records/${recId}/share.eml`;
      if (isNetErr(err)) {
        // No companion here (normal on a phone): queue for the desk AND offer
        // the email file — both 1.x rungs of the ladder, kept.
        App.queueForDesk("record", recId)();
        downloadEmlUrl(eml, "Email file downloaded. Open it in Outlook and press Send.");
      } else {
        setState({ live: "The companion answered but refused: " + err.message });
        downloadEmlUrl(eml);
      }
    }
  },

  // The natural moment to check: right after the PM alt-tabs back from
  // pressing Send in Outlook (1.x behavior, kept).
  detectSent: debounce(async () => {
    const s = App.state;
    if (s.page !== "rfis" && s.page !== "subs") return;
    const rec = s.sub ? App.recById(s.sub) : null;
    if (!rec || rec.status !== "Draft") return;
    try {
      const draft = await api(`/api/records/${rec.id}/draft`).catch(() => null);
      if (!draft || !draft.subject) return;
      const out = await companionFetch("/sent", { queries: [{ record_id: rec.id, subject: draft.subject }] });
      if ((out.sent || []).length) App.refresh("records", "attention");
    } catch (e) {}
  }, 800),

  checkReplies: (recId) => async () => {
    const rec = App.recById(recId) || {};
    try {
      const draft = await api(`/api/records/${recId}/draft`).catch(() => ({}));
      const out = await companionFetch("/scan", { queries: [{ record_id: recId,
        subject: draft.subject || rec.title, since: rec.sent_at || undefined }] });
      const replies = out.replies || [];
      let fresh = 0;
      for (const rep of replies) {
        const posted = await api(`/api/records/${recId}/replies`, { method: "POST", body: JSON.stringify(rep) });
        if (!posted.deduped) fresh++;
      }
      setState({ live: fresh ? fresh + (fresh === 1 ? " new reply filed from Outlook." : " new replies filed from Outlook.")
        : "Nothing new — the thread in Outlook holds no reply PlanWise hasn't already filed." });
      delete App.state.data["rec:" + recId];
      App.loadRecordExtras(recId);
      App.refresh("records");
    } catch (err) {
      setState({ live: isNetErr(err) ? "No Outlook companion on this machine — replies file themselves from any PC that has one." : err.message });
    }
  },

  confirmReply: (replyId, recId) => async () => {
    const bag = App.state.data["rec:" + recId] || {};
    const rep = (bag.replies || []).find((r) => r.id === replyId) || {};
    const proposed = App.state.replyEdit || {};
    try {
      await api(`/api/replies/${replyId}/confirm`, { method: "POST", body: JSON.stringify({
        status: proposed.status !== undefined ? proposed.status : rep.proposed_status,
        answer: proposed.answer !== undefined ? proposed.answer : rep.proposed_answer }) });
      setState({ replyEdit: null, live: "Confirmed. Only the confirmed answer reaches the field." });
      delete App.state.data["rec:" + recId];
      App.loadRecordExtras(recId);
      App.refresh("records");
    } catch (err) { setState({ live: err.message }); }
  },

  deleteRecord: (recId) => () => {
    const rec = App.recById(recId) || {};
    setState({
      confirm: {
        eyebrow: "Remove a record", title: (rec.number || "?") + (rec.title ? " · " + rec.title : ""),
        body: "This removes the record, its attachments and its own markup layer.",
        checks: [
          [rec.status === "Draft" ? "pass" : "warn", "Status", rec.status === "Draft" ? "It is a draft — nothing has gone out." : "It shows as " + (rec.status || "?") + ". The email that went out stays in Outlook; only PlanWise's record goes."],
          ["warn", "No undo", "Removing a record is not reversible — its replies and layer go with it."],
        ],
        blocked: false,
        verdict: "The register updates the moment you confirm.",
        label: "Remove this record",
        run: async () => {
          try {
            await api(`/api/records/${recId}`, { method: "DELETE" });
            setState({ confirm: null, detail: null, live: (rec.number || "The record") + " removed." });
            if (App.state.sub === recId) App.go(App.state.page)();
            App.refresh("records");
          } catch (err) { setState({ confirm: null, live: err.message }); }
        },
      },
    }, focusRef("confirm"));
  },

  buildThread() {
    const s = this.state;
    if ((s.page !== "rfis" && s.page !== "subs") || !s.sub) return { threadOpen: "" };
    const rec = this.recById(s.sub);
    if (!rec) return { threadOpen: "" };
    this.loadRecordExtras(rec.id);
    const bag = s.data["rec:" + rec.id] || {};
    const draft = bag.draft || {};
    const replies = bag.replies || [];
    const isR = rec.kind === "rfi";
    const unconfirmed = replies.filter((r) => !r.confirmed_at);
    const edit = s.replyEdit || {};
    const statuses = isR ? ["Answered", "Closed", "Sent"] : ["Approved", "Approved as Noted", "Revise & Resubmit", "Rejected", "Sent"];

    const messages = [];
    if (rec.sent_at || draft.subject) {
      messages.push({ from: rec.sent_by || rec.created_by || "PlanWise", to: rec.to_name || rec.to_email || "—",
        when: rec.sent_at ? usDate(rec.sent_at) : "not sent yet",
        subject: draft.subject || rec.title || "", body: draft.body || "",
        attach: (rec.attachments || []).length ? (rec.attachments || []).length + " attached drawing page" + ((rec.attachments || []).length === 1 ? "" : "s") + " · package PDF" : "",
        mine: true });
    }
    replies.forEach((r) => messages.push({
      from: r.from_name || r.from_email || "reply", to: "us",
      when: r.received_at ? usDate(r.received_at) : "", subject: "RE: " + (draft.subject || rec.title || ""),
      body: r.body || "", attach: (r.attachments || []).length ? (r.attachments || []).length + " returned file" + ((r.attachments || []).length === 1 ? "" : "s") : "",
      mine: false, replyId: r.id, confirmed: !!r.confirmed_at,
      attachments: (r.attachments || []).map((a) => ({ name: a.filename, url: `/api/replies/${r.id}/attachments/${a.id}` })),
    }));

    return {
      threadOpen: true,
      threadRec: rec,
      threadTitle: (rec.number || "?") + " · " + (rec.title || ""),
      threadStatus: rec.status || "Draft",
      threadStampStyle: stamp(STATUS_TONE[rec.status] || "nt"),
      threadFacts: [
        ["Sent", rec.sent_at ? usDate(rec.sent_at) : "not sent yet"],
        ["Sent by", rec.sent_by || "—"],
        ["Sent to", (rec.to_name || "—") + (rec.to_email ? " · " + rec.to_email : "")],
        ["Reply received", replies.length ? usDate(replies[replies.length - 1].received_at) : "no reply yet"],
        ["Due", rec.due_date || "—"],
      ].map(([label, value]) => ({ label, value })),
      threadQuestion: isR ? (rec.question || "") : (rec.spec_section ? "Spec section " + rec.spec_section : ""),
      threadPages: (rec.attachments || []).map((a) => ({
        name: (a.document_name || "Document") + ", page " + a.page,
        detail: "Original page plus this record's own layer",
        open: App.openViewer(a.document_id, a.page, "markup", { layer: (isR ? "rfi:" : "submittal:") + rec.id }),
      })),
      threadPackageUrl: `/api/records/${rec.id}/package`,
      threadCount: messages.length + (messages.length === 1 ? " message" : " messages"),
      threadMessages: messages.map((m) => ({ ...m, bg: m.mine ? "var(--pn)" : "var(--p2)", hasAttach: !!m.attach })),
      threadAnswer: rec.answer || "",
      threadHasAnswer: !!rec.answer,
      threadConfirmedBy: (replies.find((r) => r.confirmed_at) || {}).confirmed_by || rec.sent_by || "",
      threadUnconfirmed: unconfirmed.map((r) => ({
        id: r.id, from: r.from_name || r.from_email || "the reply",
        proposedStatus: edit.replyId === r.id && edit.status !== undefined ? edit.status : (r.proposed_status || rec.status),
        proposedAnswer: edit.replyId === r.id && edit.answer !== undefined ? edit.answer : (r.proposed_answer || r.body || ""),
        source: r.proposal_source || "heuristic",
        statuses: statuses.map((st) => ({ value: st, label: st })),
        setStatus: (e) => setState({ replyEdit: { ...(App.state.replyEdit || {}), replyId: r.id, status: e.target.value } }),
        setAnswer: (e) => setState({ replyEdit: { ...(App.state.replyEdit || {}), replyId: r.id, answer: e.target.value } }),
        confirm: App.confirmReply(r.id, rec.id),
      })),
      threadBack: App.go(s.page),
      threadSend: App.sendRecord(rec.id),
      threadCheckReplies: App.checkReplies(rec.id),
      threadIsDraft: rec.status === "Draft",
      threadIsRfi: isR,
      threadDraftSubject: draft.subject || "",
      threadDraftBody: draft.body || "",
      threadSetDraft: (field) => async (e) => {
        try {
          await api(`/api/records/${rec.id}/draft`, { method: "PATCH",
            body: JSON.stringify({ [field]: e.target.value }) });
          const bag2 = App.state.data["rec:" + rec.id];
          if (bag2 && bag2.draft) bag2.draft[field] = e.target.value;
        } catch (err) {}
      },
    };
  },
});

// records detail drawer branch
(() => {
  const base = App.buildDetail.bind(App);
  App.buildDetail = function () {
    const d = this.state.detail;
    if (!d || (d.kind !== "rfi" && d.kind !== "sub")) return base();
    const rec = App.recById(d.id);
    if (!rec) return { detailOpen: "" };
    const S = (id, title, rows) => ({ id: "ds-" + id, title, rows: rows.map(([label, value, note, style]) => ({ label, value, note: note || "", valueStyle: style || "" })) });
    const A = (list) => list.map(([what, who, when], i) => ({ what, who, when: when || "", color: i === list.length - 1 ? "var(--ac)" : "var(--ls)" }));
    const btn2 = (label, kind, click) => ({ label, style: btn(kind), hoverClass: kind === "primary" ? "hb-ah" : "hb-ls", click: click || (() => {}) });
    const isR = rec.kind === "rfi";
    const audit = (((this.state.data.activity || {}).activity) || []).filter((a) => a.object_id === rec.id).slice(0, 6).reverse()
      .map((a) => [a.detail || a.action, a.actor || "PlanWise", usDate(a.ts)]);
    const rows = [["Number", rec.number || "?"], ["Title", rec.title || ""], ["Status", rec.status || "Draft"]];
    if (isR) rows.push(["Question", rec.question || "not reported", "", rec.question ? "" : "color:var(--ft);font-style:italic"]);
    else rows.push(["Spec section", rec.spec_section || "not reported"]);
    rows.push([isR ? "Answer" : "Reviewer response", rec.answer || "not reported", rec.answer ? "PM confirmed" : "", rec.answer ? "" : "color:var(--ft);font-style:italic"]);
    return {
      detailOpen: true, detailHasItems: (rec.attachments || []).length > 0, detailHasNotes: "",
      detailNotes: [], detailKind: isR ? "Request for information" : "Submittal",
      detailTitle: (rec.number || "?") + " · " + (rec.title || ""),
      detailStatus: rec.status || "Draft", detailStampStyle: stamp(STATUS_TONE[rec.status] || "nt"),
      detailMeta: (rec.status === "Draft" ? "Not sent" : "Sent " + usDate(rec.sent_at)) + " · due " + (rec.due_date || "—"),
      detailSections: [
        S("rec-body", isR ? "Question and answer" : "Submittal and response", rows),
        S("rec-thread", "Thread", [["Sent to", rec.to_name || "not chosen yet", "", rec.to_name ? "" : "color:var(--ft);font-style:italic"],
          ["Recipient email", rec.to_email || "not chosen yet", "", rec.to_email ? "" : "color:var(--ft);font-style:italic"],
          ["Due date", rec.due_date || "—"],
          ["Outlook thread", rec.status === "Draft" ? "No thread yet" : "Watched by the companion"]]),
      ],
      detailItems: (rec.attachments || []).map((a) => ({ label: (a.document_name || "Document") + " · page " + a.page, value: "On this record's layer", color: "var(--mu)" })),
      detailItemsTitle: "Attached drawing pages and layers", detailItemsCol1: "Document page", detailItemsCol2: "On this record's layer",
      detailItemsTotalLabel: "Pages in the outbound package", detailItemsTotal: String((rec.attachments || []).length),
      detailAudit: A(audit.length ? audit : [["Draft created in PlanWise", rec.created_by || "—", usDate(rec.created_at)]]),
      detailFootnote: isR ? "A reply is matched from the Outlook thread. The answer reaches the field only after a project manager confirms it." : "Submittal responses are recorded exactly as the reviewer returned them.",
      detailActions: [
        btn2("Close this panel", "ghost", App.closeDetail),
        btn2("Remove " + (rec.number || "it"), "ghost", () => { App.closeDetail(); App.deleteRecord(rec.id)(); }),
        btn2("Open the full thread", "primary", () => { App.closeDetail(); App.go(this.state.page, rec.id)(); }),
      ],
    };
  };
})();

// ————— drawings: PDF.js rendering + layer-scoped marks (LOGIC-MERGE:
// prototype chrome and click-place marks; the repo's immutable originals,
// normalized coordinates and STRUCTURAL layer isolation stay) ————————————————
if (typeof pdfjsLib !== "undefined") {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.js";
}

Object.assign(App, {
  _pdfDocs: {},        // docId -> PDFDocumentProxy promise
  _thumbCache: {},     // docId|page -> dataURL
  _renderToken: {},    // canvasId -> token (serialise renders per canvas)

  docById(id) {
    return (((this.state.data.documents || {}).documents) || []).find((x) => x.id === id);
  },

  pdfDoc(docId) {
    if (!this._pdfDocs[docId]) {
      this._pdfDocs[docId] = pdfjsLib.getDocument({ url: `/api/documents/${docId}/file` }).promise;
    }
    return this._pdfDocs[docId];
  },

  async loadAnnotations(docId) {
    const key = "ann:" + docId;
    if (this.state.data[key]) return;
    try {
      const out = await api(`/api/documents/${docId}/annotations`);
      this.state.data[key] = out.annotations || [];
      setState({});
    } catch (e) { this.state.data[key] = []; }
  },

  marksFor(docId, page, layer) {
    const all = this.state.data["ann:" + docId] || [];
    return all.filter((a) => a.page === page && (a.layer || "internal") === layer);
  },

  addMark: (pane) => async (e) => {
    const s = App.state;
    const vwr = s.viewer;
    if (!vwr) return;
    const page = pane === "compare" ? vwr.compare : vwr.page;
    const box = e._el.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * 100;
    const y = ((e.clientY - box.top) / box.height) * 100;
    if (x < 0 || x > 100 || y < 0 || y > 100) return;
    const layer = (vwr.ctx || {}).layer || "internal";
    const shape = { v: 2, tool: s.tool, x, y, ink: s.ink, weight: s.weight,
      text: (s.markText || "").trim() };
    try {
      const row = await api(`/api/documents/${vwr.docId}/annotations`, { method: "POST",
        body: JSON.stringify({ page, layer, shape }) });
      const key = "ann:" + vwr.docId;
      App.state.data[key] = (App.state.data[key] || []).concat([{ ...row, shape }]);
      const list = App.marksFor(vwr.docId, page, layer);
      setState({ live: s.tool + " mark " + list.length + " added to page " + page + " on the " +
        (layer === "internal" ? "internal team" : "this record's") + " layer." });
      App.refresh("documents");
    } catch (err) { setState({ live: err.message }); }
  },

  viewerUndoMark: () => async () => {
    const vwr = App.state.viewer;
    const layer = (vwr.ctx || {}).layer || "internal";
    const list = App.marksFor(vwr.docId, vwr.page, layer);
    if (!list.length) { setState({ live: "There is nothing to remove on this page." }); return; }
    const last = list[list.length - 1];
    try {
      await api(`/api/annotations/${last.id}`, { method: "DELETE" });
      const key = "ann:" + vwr.docId;
      App.state.data[key] = (App.state.data[key] || []).filter((a) => a.id !== last.id);
      setState({ live: "Last mark removed from page " + vwr.page + "." });
      App.refresh("documents");
    } catch (err) { setState({ live: err.message }); }
  },

  viewerClearPage: () => async () => {
    const vwr = App.state.viewer;
    const layer = (vwr.ctx || {}).layer || "internal";
    const list = App.marksFor(vwr.docId, vwr.page, layer);
    if (!list.length) { setState({ live: "This page carries no marks of yours." }); return; }
    try {
      for (const a of list) await api(`/api/annotations/${a.id}`, { method: "DELETE" });
      const key = "ann:" + vwr.docId;
      App.state.data[key] = (App.state.data[key] || []).filter((a) => !list.includes(a));
      const kept = list.map((a) => ({ page: a.page, layer: a.layer, shape: a.shape }));
      const msg = "Cleared " + list.length + (list.length === 1 ? " mark" : " marks") + " from page " + vwr.page + ".";
      setState({ undo: { message: msg, revertFn: async () => {
        for (const k2 of kept) {
          const row = await api(`/api/documents/${vwr.docId}/annotations`, { method: "POST", body: JSON.stringify(k2) });
          App.state.data[key] = (App.state.data[key] || []).concat([{ ...row, shape: k2.shape }]);
        }
        App.refresh("documents");
      } }, live: msg });
      App.refresh("documents");
    } catch (err) { setState({ live: err.message }); }
  },

  viewerToggleAttach: () => async () => {
    const vwr = App.state.viewer;
    const recId = (vwr.ctx || {}).recordId;
    if (!recId) return;
    const rec = App.recById(recId) || {};
    const existing = (rec.attachments || []).find((a) => a.document_id === vwr.docId && a.page === vwr.page);
    try {
      if (existing) {
        await api(`/api/records/${recId}/attachments/${existing.id}`, { method: "DELETE" });
        setState({ live: "Page " + vwr.page + " removed from the package." });
      } else {
        await api(`/api/records/${recId}/attachments`, { method: "POST",
          body: JSON.stringify({ document_id: vwr.docId, page: vwr.page }) });
        setState({ live: "Page " + vwr.page + " attached." });
      }
      App.refresh("records");
    } catch (err) { setState({ live: err.message }); }
  },

  triggerDocUpload() {
    let input = document.getElementById("doc-upload-input");
    if (!input) {
      input = document.createElement("input");
      input.type = "file"; input.accept = ".pdf"; input.multiple = true;
      input.id = "doc-upload-input"; input.style.display = "none";
      document.body.appendChild(input);
      input.addEventListener("change", async () => {
        const files = [...(input.files || [])];
        input.value = "";
        for (const f of files) {
          try {
            const fd = new FormData();
            fd.append("file", f);
            fd.append("name", f.name.replace(/\.pdf$/i, ""));
            const r = await fetch(`/api/jobs/${encodeURIComponent(App.state.job)}/documents`,
              { method: "POST", body: fd, credentials: "same-origin" });
            const b = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(b.detail || r.status);
            setState({ live: "“" + (b.name || f.name) + "” added to the library. The original is immutable — redlines live on layers." });
          } catch (err) {
            setState({ live: f.name + ": " + err.message });
          }
        }
        App.refresh("documents");
      });
    }
    input.click();
  },

  deleteDocument: (docId) => () => {
    const doc = App.docById(docId) || {};
    setState({
      confirm: {
        eyebrow: "Remove a drawing set", title: doc.name || "?",
        body: "This removes the set and every layer of markups on it.",
        checks: [
          [doc.annotation_count ? "warn" : "pass", "Markups", doc.annotation_count ? "It carries " + doc.annotation_count + " markups across its layers — they go with it." : "It carries no markups."],
          ["warn", "Attached records", "Any RFI or submittal page attached from this set loses its page reference."],
          ["warn", "No undo", "Removing a document is not reversible — the file itself is deleted."],
        ],
        blocked: false,
        verdict: "The library updates the moment you confirm.",
        label: "Remove this set",
        run: async () => {
          try {
            await api(`/api/documents/${docId}`, { method: "DELETE" });
            setState({ confirm: null, detail: null, viewer: null, live: "“" + (doc.name || "the set") + "” removed from the library." });
            App.refresh("documents");
          } catch (err) { setState({ confirm: null, live: err.message }); }
        },
      },
    }, focusRef("confirm"));
  },

  buildViewer() {
    const s = this.state;
    const vwr = s.viewer;
    if (!vwr) return { viewerOpen: "" };
    const doc = this.docById(vwr.docId);
    if (!doc) return { viewerOpen: "" };
    this.loadAnnotations(vwr.docId);
    const layer = (vwr.ctx || {}).layer || "internal";
    const picker = vwr.mode === "picker" && (vwr.ctx || {}).recordId;
    const rec = picker ? this.recById(vwr.ctx.recordId) : null;
    const layerName = layer === "internal" ? "internal team" : "this record's";
    const all = s.data["ann:" + vwr.docId] || [];

    const renderShape = (a, i) => {
      const sh = typeof a.shape === "string" ? JSON.parse(a.shape) : a.shape;
      if (sh && sh.v === 2) {
        const m = { tool: sh.tool, x: sh.x, y: sh.y, ink: sh.ink, weight: sh.weight, text: sh.text };
        return { style: MARK_STYLE(m, i), heads: MARK_HEADS(m, i) };
      }
      // Legacy 1.x shapes (normalized 0..1 geometry) render as a simple box
      // outline at their extent — displayed, never lost, never edited here.
      const x0 = (sh.x0 ?? sh.x ?? 0) * 100, y0 = (sh.y0 ?? sh.y ?? 0) * 100;
      const x1 = (sh.x1 ?? sh.x ?? 0.05) * 100, y1 = (sh.y1 ?? sh.y ?? 0.05) * 100;
      return { style: { label: sh.text || "", style: "position:absolute;left:" + Math.min(x0, x1) + "%;top:" + Math.min(y0, y1) + "%;width:" + Math.abs(x1 - x0) + "%;height:" + Math.abs(y1 - y0) + "%;border:2px solid " + (sh.color || "#A9291D") + ";pointer-events:none" }, heads: [] };
    };

    const pane = (page, isCompare) => {
      const list = this.marksFor(vwr.docId, page, layer);
      const shapes = list.map((a, i) => renderShape(a, i));
      return {
        caption: isCompare ? "Comparing page " + page : "Page " + page + " of " + (doc.page_count || "?"),
        isCompare: !!isCompare,
        selectValue: String(page),
        onSelect: (e) => setState({ viewer: { ...App.state.viewer, compare: parseInt(e.target.value) } }),
        options: Array.from({ length: doc.page_count || 1 }, (x, i) => ({ value: String(i + 1), label: "Page " + (i + 1) })),
        canvasId: "dw-canvas-" + (isCompare ? "b" : "a"),
        pageNum: page,
        click: App.addMark(isCompare ? "compare" : "main"),
        aria: doc.name + ", page " + page + ", " + (list.length ? list.length + (list.length === 1 ? " mark" : " marks") + " on it" : "no marks") + ". Select anywhere on the sheet to place a " + s.tool.toLowerCase() + ".",
        holderStyle: "flex:1;min-height:0;display:flex;align-items:center;justify-content:center;overflow:" + (s.zoom > 1 ? "auto" : "hidden"),
        sheetStyle: "position:relative;container-type:inline-size;flex:none;margin:auto;aspect-ratio:17/11;background:#FFFFFF;border:1px solid var(--ls);box-shadow:var(--sh);cursor:crosshair;overflow:hidden;" +
          (s.zoom > 1
            ? "height:" + (s.zoom * 100) + "%;width:auto;min-width:" + (s.zoom * 100) + "%"
            : isCompare ? "width:100%;height:auto;max-height:100%" : "height:100%;width:auto;max-width:100%"),
        marks: shapes.map((x) => x.style),
        heads: shapes.reduce((out, x) => out.concat(x.heads), []),
        note: isCompare
          ? "Marks you place here land on the same layer as the left-hand sheet."
          : "The whole sheet is on screen. Marks sit on a layer above the original and never alter the file.",
      };
    };

    const panes = [pane(vwr.page, false)];
    if (vwr.compare !== null && vwr.compare !== undefined) panes.push(pane(vwr.compare, true));

    return {
      viewerOpen: true,
      viewerClose: () => setState({ viewer: null }),
      viewerEyebrow: picker ? "Choose pages for " + ((rec || {}).number || "this record") : "Drawing viewer",
      viewerTitle: doc.name,
      viewerCompareAria: vwr.compare != null ? "true" : "false",
      viewerCompareLabel: vwr.compare != null ? "Stop comparing" : "Compare two pages",
      viewerCompareStyle: "min-height:var(--tap);padding:7px 13px;border-radius:6px;font:600 12.5px var(--fd);white-space:nowrap;border:1px solid " +
        (vwr.compare != null ? "var(--ac)" : "var(--ln)") + ";background:" + (vwr.compare != null ? "var(--as)" : "var(--pn)") + ";color:" + (vwr.compare != null ? "var(--ac)" : "var(--mu)"),
      viewerToggleCompare: () => {
        const other = vwr.page < (doc.page_count || 1) ? vwr.page + 1 : Math.max(1, vwr.page - 1);
        setState({ viewer: { ...vwr, compare: vwr.compare == null ? other : null } });
      },
      viewerCols: vwr.compare != null ? "minmax(0,1fr) minmax(0,1fr)" : "minmax(0,1fr)",
      viewerPanes: panes,
      viewerTools: TOOLS.map(([label, aria, icon]) => {
        const on = s.tool === label;
        return { label, aria: aria + " tool", icon, pressed: on ? "true" : "false",
          pick: () => setState({ tool: label }),
          iconStyle: "width:15px;height:15px;flex:none;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round",
          style: "display:inline-flex;align-items:center;gap:6px;min-height:34px;padding:6px 10px;border-radius:6px;font:600 11.5px var(--fd);white-space:nowrap;border:1px solid " +
            (on ? "var(--ac)" : "var(--ln)") + ";background:" + (on ? "var(--as)" : "var(--pn)") + ";color:" + (on ? "var(--ac)" : "var(--mu)") };
      }),
      viewerInks: Object.keys(INK_NAMES).map((hex) => {
        const on = s.ink === hex;
        return { name: INK_NAMES[hex], label: INK_NAMES[hex] + " ink", pressed: on ? "true" : "false",
          pick: () => setState({ ink: hex }),
          swatch: "width:11px;height:11px;border-radius:3px;background:" + hex + ";flex:none",
          style: "display:inline-flex;align-items:center;gap:7px;min-height:34px;padding:6px 10px;border-radius:6px;font:600 11.5px var(--fd);border:1px solid " +
            (on ? "var(--ac)" : "var(--ln)") + ";background:" + (on ? "var(--as)" : "var(--pn)") + ";color:" + (on ? "var(--ac)" : "var(--mu)") };
      }),
      viewerWeights: [["Thin", 1.5], ["Medium", 2.5], ["Thick", 4]].map(([label, wt]) => {
        const on = s.weight === wt;
        return { label: label + " line weight", pressed: on ? "true" : "false",
          pick: () => setState({ weight: wt }),
          rule: "display:block;width:17px;height:0;border-top:" + wt + "px solid currentColor",
          style: "display:grid;place-content:center;min-height:34px;min-width:36px;padding:6px 8px;border-radius:6px;border:1px solid " +
            (on ? "var(--ac)" : "var(--ln)") + ";background:" + (on ? "var(--as)" : "var(--pn)") + ";color:" + (on ? "var(--ac)" : "var(--mu)") };
      }),
      viewerZooms: [["Fit page", 1], ["150%", 1.5], ["200%", 2]].map(([label, z]) => {
        const on = s.zoom === z;
        return { label, pressed: on ? "true" : "false", pick: () => setState({ zoom: z }),
          style: "min-height:34px;padding:6px 10px;border-radius:6px;font:600 11.5px var(--fd);white-space:nowrap;border:1px solid " +
            (on ? "var(--ac)" : "var(--ln)") + ";background:" + (on ? "var(--as)" : "var(--pn)") + ";color:" + (on ? "var(--ac)" : "var(--mu)") };
      }),
      viewerNeedsText: s.tool === "Text" || s.tool === "Dim",
      viewerTextLabel: s.tool === "Dim" ? "Dimension" : "Note text",
      viewerTextHint: s.tool === "Dim" ? '18"' : "Verify in field",
      viewerText: s.markText || "",
      setMarkText: (e) => setState({ markText: e.target.value }),
      viewerHint: "Places a " + s.tool.toLowerCase() + " in " + (INK_NAMES[s.ink] || "red").toLowerCase() + " on the " + layerName + " layer",
      viewerUndoMark: App.viewerUndoMark(), viewerClearPage: App.viewerClearPage(),
      viewerThumbs: Array.from({ length: doc.page_count || 1 }, (x, i) => {
        const page = i + 1;
        const on = page === vwr.page;
        const cmp = page === vwr.compare;
        const n = all.filter((a) => a.page === page && (a.layer || "internal") === layer).length;
        const att = picker && rec && (rec.attachments || []).some((a) => a.document_id === vwr.docId && a.page === page);
        return {
          num: String(page), current: on ? "true" : "false",
          go: () => setState({ viewer: { ...App.state.viewer, page } }),
          marks: n ? n + (n === 1 ? " mark" : " marks") : "", attached: !!att,
          aria: "Page " + page + (n ? ", " + n + (n === 1 ? " mark" : " marks") : ", no marks") + (att ? ", attached to this package" : "") + (on ? ", showing now" : ""),
          canvasId: "dw-thumb-" + vwr.docId + "-" + page,
          style: "width:100%;text-align:left;padding:7px;border-radius:7px;border:1px solid " + (on ? "var(--ac)" : cmp ? "var(--bp)" : "var(--ln)") +
            ";background:" + (on ? "var(--as)" : "var(--pn)"),
        };
      }),
      viewerIsPicker: !!picker, viewerIsPlain: !picker,
      viewerToggleAttach: App.viewerToggleAttach(),
      viewerAttachLabel: picker && rec && (rec.attachments || []).some((a) => a.document_id === vwr.docId && a.page === vwr.page)
        ? "Remove page " + vwr.page + " from the package" : "Attach page " + vwr.page + " to the package",
      viewerAttachStyle: "min-height:var(--tap);padding:9px 15px;border-radius:6px;font:600 13px var(--fd);border:1px solid " +
        (picker && rec && (rec.attachments || []).some((a) => a.document_id === vwr.docId && a.page === vwr.page)
          ? "var(--ok);background:var(--oks);color:var(--ok)" : "var(--ln);background:var(--pn);color:var(--ink)"),
      viewerDoneLabel: (() => {
        const n = picker && rec ? (rec.attachments || []).filter((a) => a.document_id === vwr.docId).length : 0;
        return "Done · " + n + (n === 1 ? " page attached" : " pages attached");
      })(),
      viewerFootnote: picker
        ? "Marks you place here go on this record's own layer and travel with the package. The internal team layer stays in the building."
        : layer === "internal"
          ? "Marks go on the internal team layer. They stay in the building until a page is attached to an RFI or submittal, which carries its own separate layer."
          : "You are marking this record's own layer — exactly what its outbound package carries. The internal team layer is separate and stays in the building.",
    };
  },

  // Draw the PDF pages into the viewer's canvases after each render. morphdom
  // keeps the canvas nodes, so a page draws once and survives re-renders; the
  // token serialises renders per canvas (PDF.js refuses two at once).
  async paintViewerCanvases() {
    const vwr = this.state.viewer;
    if (!vwr || typeof pdfjsLib === "undefined") return;
    const doc = this.docById(vwr.docId);
    if (!doc) return;
    const pdf = await this.pdfDoc(vwr.docId).catch(() => null);
    if (!pdf || this.state.viewer !== vwr) return;

    const paint = async (canvasId, pageNo, scaleTo) => {
      const canvas = document.getElementById(canvasId);
      if (!canvas) return;
      const want = pageNo + "@" + scaleTo;
      if (canvas.dataset.rendered === want) return;
      const token = (this._renderToken[canvasId] || 0) + 1;
      this._renderToken[canvasId] = token;
      const page = await pdf.getPage(pageNo);
      if (this._renderToken[canvasId] !== token) return;
      const vp0 = page.getViewport({ scale: 1 });
      const scale = scaleTo / vp0.width;
      const vp = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) });
      canvas.width = vp.width; canvas.height = vp.height;
      // The sheet keeps the aspect ratio of the real page, not 17/11.
      const holder = canvas.parentElement;
      if (holder && holder.style.aspectRatio !== `${vp0.width} / ${vp0.height}`) {
        holder.style.aspectRatio = `${vp0.width} / ${vp0.height}`;
      }
      // intent "print": the display intent is rAF-paced and hangs in a
      // backgrounded tab (1.x lesson, kept).
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp, intent: "print" }).promise.catch(() => {});
      canvas.dataset.rendered = want;
    };

    await paint("dw-canvas-a", vwr.page, 1400);
    if (vwr.compare != null) await paint("dw-canvas-b", vwr.compare, 1400);
    for (let p2 = 1; p2 <= (doc.page_count || 1); p2++) {
      await paint("dw-thumb-" + vwr.docId + "-" + p2, p2, 150);
      if (this.state.viewer !== vwr) return;
    }
  },
});

// docs detail drawer branch + viewer open from register
(() => {
  const base = App.buildDetail.bind(App);
  App.buildDetail = function () {
    const d = this.state.detail;
    if (!d || d.kind !== "doc") return base();
    const doc = App.docById(d.id);
    if (!doc) return { detailOpen: "" };
    const S = (id, title, rows) => ({ id: "ds-" + id, title, rows: rows.map(([label, value, note, style]) => ({ label, value, note: note || "", valueStyle: style || "" })) });
    const btn2 = (label, kind, click) => ({ label, style: btn(kind), hoverClass: kind === "primary" ? "hb-ah" : "hb-ls", click: click || (() => {}) });
    return {
      detailOpen: true, detailHasItems: "", detailHasNotes: "", detailNotes: [],
      detailKind: "Drawing set", detailTitle: doc.name,
      detailStatus: doc.annotation_count ? "Marked" : "Clean",
      detailStampStyle: stamp(doc.annotation_count ? "wn" : "ok"),
      detailMeta: (doc.page_count || 0) + " pages · uploaded " + usDate(doc.uploaded_at),
      detailSections: [
        S("doc-file", "File", [["Name", doc.name], ["Pages", String(doc.page_count || 0)],
          ["Uploaded", (doc.uploaded_by || "—") + " · " + usDate(doc.uploaded_at)],
          ["Original", "Immutable — annotations never touch the file"]]),
        S("doc-layers", "Layers", [["Internal team layer", (doc.annotation_count || 0) + " markups, stays in the building"]]),
      ],
      detailAudit: [{ what: "Uploaded, " + (doc.page_count || 0) + " pages", who: doc.uploaded_by || "—", when: usDate(doc.uploaded_at), color: "var(--ac)" }],
      detailFootnote: "Sending a page composites the original plus one record layer. Internal redlines are never in an outbound package.",
      detailActions: [
        btn2("Close this panel", "ghost", App.closeDetail),
        btn2("Remove this set", "ghost", () => { App.closeDetail(); App.deleteDocument(doc.id)(); }),
        btn2("Open and mark up this set", "primary", () => { App.closeDetail(); App.openViewer(doc.id, 1, "markup", {})(); }),
      ],
    };
  };
})();

// ————— weekly briefing (gap-build: real rows, PM-owned proposals) ———————————
Object.assign(App, {
  briefRow() { return this.state.data.briefing || {}; },

  briefPersist: debounce(async () => {
    const b = App.briefRow();
    if (!b.id) return;
    try {
      const out = await api(`/api/briefings/${b.id}`, { method: "PATCH",
        body: JSON.stringify({ blocks: b.blocks }) });
      App.state.data.briefing = out;
      setState({});
    } catch (err) { setState({ live: "Could not save the briefing: " + err.message }); }
  }, 700),

  briefSetItem: (block, i, field) => (e) => {
    const b = App.briefRow();
    b.blocks[block][i][field] = e.target.value;
    setState({});
    App.briefPersist();
  },
  briefAddItem: (block) => () => {
    const b = App.briefRow();
    b.blocks[block] = (b.blocks[block] || []).concat([{ text: "", tag: "" }]);
    setState({});
  },
  briefRemoveItem: (block, i) => () => {
    const b = App.briefRow();
    b.blocks[block] = b.blocks[block].filter((x, n) => n !== i);
    setState({});
    App.briefPersist();
  },
  briefReseed() {
    const b = App.briefRow();
    setState({
      confirm: {
        eyebrow: "Reseed the briefing", title: "Replace the blocks with fresh proposals",
        body: "PlanWise rereads the registers and writes new proposed lines for the week.",
        checks: [
          ["warn", "Your edits", "Everything typed into the blocks is replaced. The registers themselves are untouched."],
          ["pass", "The source", "Every proposed line traces to a register row — nothing is invented."],
        ],
        blocked: false,
        verdict: "Reseeding is undoable — the reversal restores the blocks as they stand now.",
        label: "Reseed from the registers",
        run: async () => {
          try {
            const out = await api(`/api/briefings/${b.id}/reseed`, { method: "POST" });
            App.state.data.briefing = out;
            setState({ confirm: null });
            App.act("The briefing was reseeded from the registers.", out.activity_id, ["briefing"]);
          } catch (err) { setState({ confirm: null, live: err.message }); }
        },
      },
    }, focusRef("confirm"));
  },

  async briefRefine() {
    const b = App.briefRow();
    if (!b.id) return;
    setState({ live: "Asking the drafting help to reword the lines…" });
    try {
      const out = await api(`/api/briefings/${b.id}/refine`, { method: "POST" });
      if (!out.changed) { setState({ live: out.detail }); return; }
      App.state.data.briefing = out;
      App.act("The briefing lines were reworded. The facts are still the registers' — read it before it goes out.", out.activity_id, ["briefing"]);
    } catch (err) { setState({ live: err.message }); }
  },

  buildBrief() {
    const s = this.state;
    if (s.page !== "brief") return {};
    const b = this.briefRow();
    if (!b.id) return { hasBrief: false };
    const jd = s.data.job || {};
    const job = jd.job || {};
    const cust = (s.briefAudience || "customer") === "customer";
    const contacts = ((jd.meta || {}).contacts || []).filter((c) => c.email);
    const meta = [
      { key: "progress", title: "Progress this week", color: "var(--ok)", soft: "var(--oks)" },
      { key: "risks", title: "What could move the finish date", color: "var(--wn)", soft: "var(--wns)" },
      { key: "asks", title: cust ? "What we need from you" : "What we need from the customer", color: "var(--ac)", soft: "var(--as)" },
    ];
    return {
      hasBrief: true,
      briefWeekTitle: "Briefing · week of " + usDate(b.week_start) + (job.job_name ? " · " + job.job_name : ""),
      briefByline: "Prepared " + usDate(b.created_at) + " by " + (b.created_by || "—") +
        (cust ? " · this is what the customer receives" : " · internal only, never sent outside the firm"),
      briefStatus: b.status || "Draft",
      briefStampStyle: stamp(STATUS_TONE[b.status] || "wn"),
      briefTabs: [["Customer copy", "customer"], ["Internal copy", "internal"]].map(([label, key]) => ({
        label, pressed: (s.briefAudience || "customer") === key ? "true" : "false",
        pick: () => setState({ briefAudience: key }), style: chip((s.briefAudience || "customer") === key) })),
      briefNotice: cust
        ? "The customer copy carries no cost, billing or margin figures. It states progress, status and what we need from them, and names an amount only where that amount has already been submitted on a change order."
        : "The internal copy carries the full financial position, including anything that would damage the firm's position if it reached the customer. Check the recipient list before this leaves your outbox.",
      briefNoticeStyle: "margin:10px 0 0;padding:10px 12px;border-radius:6px;font-size:12.5px;text-wrap:pretty;border:1px solid " +
        (cust ? "var(--ln)" : "var(--er)") + ";background:" + (cust ? "var(--p2)" : "var(--ers)") + ";color:" + (cust ? "var(--mu)" : "var(--er)"),
      briefBlocks: meta.map((m) => ({
        id: "bb-" + m.key, title: m.title, color: m.color, soft: m.soft,
        items: (b.blocks[m.key] || []).map((it, i) => ({
          text: it.text || "", tag: it.tag || "",
          setText: App.briefSetItem(m.key, i, "text"),
          setTag: App.briefSetItem(m.key, i, "tag"),
          remove: App.briefRemoveItem(m.key, i),
          textId: "bf-" + m.key + "-" + i,
        })),
        add: App.briefAddItem(m.key),
      })),
      briefSign: (b.blocks.signature || []).filter((it) => cust ? !/exposure/i.test(it.tag || "") : true)
        .map((it) => ({ what: it.text || "", state: it.tag || "", color: /exposure|open/i.test(it.tag || "") ? "var(--er)" : "var(--bp)" })),
      briefFinancials: !cust ? [
        ["Current contract", money(job.current_contract)],
        ["Billed to date", money(job.actual_billed)],
        ["Cost to date", money(job.actual_cost)],
        ["Projected at completion", money(job.projected_cost)],
      ].map(([label, value]) => ({ label, value })) : [],
      briefAtt: [
        { kind: "PDF", name: "Look ahead (" + (cust ? "customer copy" : "internal, with tools and material") + ").pdf" },
      ],
      briefRecipients: cust
        ? contacts.map((c) => ({ name: c.name || c.email, email: c.email,
            gets: "Customer copy — no cost or margin figures", color: "var(--bp)", soft: "var(--bps)" }))
        : [{ name: "Addressed in Outlook", email: "The internal copy opens unaddressed — you choose the team it goes to.",
            gets: "Internal copy — full financial position", color: "var(--ac)", soft: "var(--as)" }],
      noRecipients: cust && contacts.length === 0,
      briefReseed: () => App.briefReseed(),
      briefRefine: () => App.briefRefine(),
      briefSend: App.openShareWith(cust ? { "brief-cust": true } : { "brief-int": true }),
      briefSendLabel: "Choose recipients and send",
    };
  },
});

// ————— settings: AI, companion, users, account (1.x panes, sheet chrome) ————
Object.assign(App, {
  async loadSettingsData() {
    if (this._settingsLoading) return;
    this._settingsLoading = true;
    try { this.state.data.settings = await api("/api/settings"); } catch (e) { this.state.data.settings = {}; }
    if ((this.state.user || {}).is_admin) {
      try { this.state.data.users = await api("/api/users"); } catch (e) {}
    }
    try {
      const r = await fetch(COMPANION + "/health").then((x) => x.json());
      this.state.data.companion = r;
    } catch (e) { this.state.data.companion = { unreachable: true }; }
    this._settingsLoading = false;
    setState({});
  },

  patchSetting: (key, label) => async (e) => {
    const value = e.target ? e.target.value : e;
    try {
      const out = await api("/api/settings", { method: "PATCH", body: JSON.stringify({ [key]: value }) });
      App.state.data.settings = out;
      setState({ live: (label || key) + " saved." });
    } catch (err) { setState({ live: err.message }); }
  },

  userAction: (name, action, body, phrase) => async () => {
    try {
      if (action === "remove") await api(`/api/users/${encodeURIComponent(name)}`, { method: "DELETE" });
      else await api(`/api/users/${encodeURIComponent(name)}/${action}`, { method: "POST", body: JSON.stringify(body || {}) });
      setState({ live: phrase });
      App.loadSettingsData();
    } catch (err) { setState({ live: err.message }); }
  },

  confirmRemoveUser: (name, pending) => () => {
    setState({
      confirm: {
        eyebrow: pending ? "Deny a request" : "Remove an account",
        title: name,
        body: pending ? "The request is denied and the account removed. They can register again." : "The account and its sessions are removed. Their name stays on everything they did — attribution is history, not access.",
        checks: [
          ["pass", "Attribution", "Activity entries keep the name. Nothing they wrote is deleted."],
          [pending ? "pass" : "warn", "Access", pending ? "They never had access to job data." : "Any signed-in session ends immediately."],
        ],
        blocked: false,
        verdict: "Removing an account is not reversible from here; they can be re-invited.",
        label: pending ? "Deny and remove" : "Remove the account",
        run: async () => {
          setState({ confirm: null });
          await App.userAction(name, "remove", null, name + (pending ? "'s request denied." : " removed."))();
        },
      },
    }, focusRef("confirm"));
  },

  resetUserPassword: (name) => () => {
    // A generated temp password shown ONCE — never typed through a native
    // prompt (the 1.x unmasked-prompt hazard is retired).
    const temp = "pw-" + Math.random().toString(36).slice(2, 8) + "-" + Math.random().toString(36).slice(2, 6);
    setState({
      confirm: {
        eyebrow: "Reset a password", title: name,
        body: "PlanWise generates a temporary password. They must change it at their next sign-in.",
        checks: [
          ["pass", "The temporary password", temp + " — copy it now; it is shown only here."],
          ["pass", "First sign-in", "They are forced onto a password of their own before anything else."],
        ],
        blocked: false,
        verdict: "Their current sessions end when the reset applies.",
        label: "Reset the password",
        run: async () => {
          setState({ confirm: null });
          await App.userAction(name, "password", { password: temp },
            name + "'s password reset. The temporary password was shown in the dialog.")();
        },
      },
    }, focusRef("confirm"));
  },

  changeOwnPassword() {
    App.openForm("password")();
  },

  setUserEmail: (name, current) => () => {
    setState({ settingsOpen: false });
    App.openForm("useremail", { name, current })();
  },

  buildSettingsExtra(v) {
    const s = this.state;
    if (!s.settingsOpen) return "";
    if (!s.data.settings) this.loadSettingsData();
    const st = s.data.settings || {};
    const spend = st.spend || {};
    const comp = s.data.companion || {};
    const usersData = s.data.users || {};
    const users = usersData.users || [];
    const isAdmin = (s.user || {}).is_admin;
    const input = (id, label, key, value, hint, type) => `<div style="min-width:0">
      <label for="${id}" style="display:block;font:600 12px var(--fd);letter-spacing:.03em;margin-bottom:5px">${esc(label)}</label>
      <input id="${id}" type="${type || "text"}" value="${esc(value || "")}" data-change="${H(App.patchSetting(key, label))}" class="fi" style="width:100%;min-height:var(--tap);padding:8px 11px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)">
      ${hint ? `<p style="margin:4px 0 0;font-size:11.5px;color:var(--ft);text-wrap:pretty">${esc(hint)}</p>` : ""}
    </div>`;

    let compLine, compTone;
    if (comp.unreachable) { compLine = "Not running on this machine. Records still share by email file; replies file themselves from any PC that has the companion."; compTone = "nt"; }
    else if (!comp.paired) { compLine = "Running but not paired. Open http://127.0.0.1:8772/pair and sign in with your PlanWise email."; compTone = "wn"; }
    else if (comp.paired_user && s.user && comp.paired_user !== s.user.name) { compLine = "Paired to " + comp.paired_user + " — drafting from this PC would use their mailbox."; compTone = "er"; }
    else if (comp.outlook === false) { compLine = "Paired as " + (comp.paired_user || "you") + ", but Outlook isn't open on this PC. Open Outlook and PlanWise picks up from there."; compTone = "wn"; }
    else { compLine = "Healthy — paired as " + (comp.paired_user || "you") + (comp.watch && comp.watch.running ? ", live watch on Inbox and Sent Items" : ", backstop sweep only") + ((comp.poll || {}).interval_seconds ? " · sweep every " + comp.poll.interval_seconds + "s" : ""); compTone = "ok"; }

    return `
      <section aria-labelledby="set-ai" style="padding:16px 20px 4px;border-top:1px solid var(--ln)">
        <h3 id="set-ai" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Drafting help and spend</h3>
        <p style="margin:5px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">AI drafts emails and proposes reply dispositions — it never sends anything and never gates the pipeline. The cap is a budget backstop for the whole team, not an invoice.</p>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:13px;margin-top:13px">
          <div style="min-width:0">
            <label for="set-provider" style="display:block;font:600 12px var(--fd);letter-spacing:.03em;margin-bottom:5px">Provider</label>
            <select id="set-provider" data-change="${H(App.patchSetting("ai_provider", "Provider"))}" style="width:100%;min-height:var(--tap);padding:8px 11px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)">
              ${["anthropic", "openai"].map((p) => `<option value="${p}" ${st.ai_provider === p ? "selected" : ""}>${p === "anthropic" ? "Anthropic" : "OpenAI"}</option>`).join("")}
            </select>
          </div>
          ${input("set-akey", "Anthropic API key", "anthropic_api_key", st.anthropic_api_key, "Masked once saved; a masked value is never written back.")}
          ${input("set-okey", "OpenAI API key", "openai_api_key", st.openai_api_key, "")}
          ${input("set-cap", "Monthly spend cap, USD", "ai_spend_cap_monthly", st.ai_spend_cap_monthly, spend.month ? "Spent " + money(spend.spent) + " of " + money(spend.cap) + " this month · " + (spend.days_left ?? "—") + " days left." : "")}
        </div>
      </section>

      <section aria-labelledby="set-comp" style="padding:16px 20px 4px">
        <h3 id="set-comp" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Outlook companion</h3>
        <p style="margin:9px 0 0;padding:10px 12px;border-radius:6px;border:1px solid ${tone(compTone)};background:${toneSoft(compTone)};color:${tone(compTone)};font-size:var(--fzs);text-wrap:pretty">${esc(compLine)}</p>
        <p style="margin:8px 0 0;font-size:12px;color:var(--ft);text-wrap:pretty">The companion runs beside Outlook on each PC and drafts into that person's own mailbox — mail never leaves from a machine account. Without it, every send falls back to a downloadable email file.</p>
      </section>

      ${isAdmin ? `<section aria-labelledby="set-users" style="padding:16px 20px 4px">
        <h3 id="set-users" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">People</h3>
        <p style="margin:5px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">Sign-ups wait here for approval. Attribution is history — removing an account never removes what they did.</p>
        <ul style="list-style:none;margin:13px 0 0;padding:0;display:flex;flex-direction:column;gap:8px">
          ${users.map((u) => {
            const pending = !!u.pending;
            const self = s.user && u.name === s.user.name;
            return `<li style="display:flex;gap:11px;align-items:center;padding:11px 13px;border:1px solid ${pending ? "var(--ac)" : "var(--ln)"};border-radius:7px;background:${pending ? "var(--as)" : "var(--p3)"};flex-wrap:wrap">
              <span style="flex:1;min-width:160px">
                <span style="display:block;font:600 var(--fzs) var(--fd)">${esc(u.name)}${u.is_admin ? ` <span style="${stamp("bp")}">Admin</span>` : ""}${u.disabled ? ` <span style="${stamp("er")}">Disabled</span>` : ""}${pending ? ` <span style="${stamp("wn")}">Awaiting approval</span>` : ""}</span>
                <span style="display:block;font:11.5px var(--fm);color:var(--mu)">${esc(u.email || "no email — bootstrap account")}</span>
              </span>
              ${pending ? `<button data-click="${H(App.userAction(u.name, "approved", { approved: true }, u.name + " approved."))}" class="hb-ah" style="min-height:34px;padding:6px 12px;border:1px solid var(--ac);border-radius:6px;background:var(--ac);color:var(--acink);font:600 12px var(--fd)">Approve</button>
              <button data-click="${H(App.confirmRemoveUser(u.name, true))}" class="hb-er" style="min-height:34px;padding:6px 12px;border:1px solid var(--ln);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">Deny</button>` : self ? `
              <button data-click="${H(App.setUserEmail(u.name, u.email))}" class="hb-ac" style="min-height:34px;padding:6px 12px;border:1px solid var(--ln);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">Set email</button>` : `
              <button data-click="${H(App.setUserEmail(u.name, u.email))}" class="hb-ac" style="min-height:34px;padding:6px 12px;border:1px solid var(--ln);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">Set email</button>
              <button data-click="${H(App.userAction(u.name, "admin", { admin: !u.is_admin }, u.name + (u.is_admin ? " is no longer an administrator." : " is now an administrator.")))}" class="hb-ac" style="min-height:34px;padding:6px 12px;border:1px solid var(--ln);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">${u.is_admin ? "Revoke admin" : "Make admin"}</button>
              <button data-click="${H(App.resetUserPassword(u.name))}" class="hb-ac" style="min-height:34px;padding:6px 12px;border:1px solid var(--ln);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">Reset password</button>
              <button data-click="${H(App.userAction(u.name, "disabled", { disabled: !u.disabled }, u.name + (u.disabled ? " re-enabled." : " disabled — their sessions ended.")))}" class="hb-ac" style="min-height:34px;padding:6px 12px;border:1px solid var(--ln);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">${u.disabled ? "Enable" : "Disable"}</button>
              <button data-click="${H(App.confirmRemoveUser(u.name, false))}" class="hb-er" style="min-height:34px;padding:6px 12px;border:1px solid var(--ln);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">Remove</button>`}
            </li>`;
          }).join("")}
        </ul>
      </section>` : ""}

      <section aria-labelledby="set-account" style="padding:16px 20px 20px">
        <h3 id="set-account" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Account</h3>
        <div style="display:flex;gap:9px;margin-top:11px;flex-wrap:wrap">
          <button data-click="${H(() => { setState({ settingsOpen: false }); App.changeOwnPassword(); })}" class="hb-ls" style="${btn("ghost")}">Change my password</button>
        </div>
      </section>`;
  },
});

// password form kind
(() => {
  const baseSpec = App.formSpec.bind(App);
  App.formSpec = function (kind, ctx) {
    if (kind === "useremail") {
      return {
        eyebrow: "Sign-in address", title: (ctx || {}).name || "Set email", submit: "Set the email",
        intro: (ctx || {}).current
          ? "Currently " + ctx.current + ". The new address is what they sign in with."
          : "This account predates email sign-in. Give it the address it signs in with.",
        fields: [["email", "Work email", "text", { req: true, hint: "" }]],
        review: "Sign-in by this address works immediately. Their password does not change.",
      };
    }
    if (kind !== "password") return baseSpec(kind, ctx);
    return {
      eyebrow: "Your account", title: "Change your password", submit: "Change it",
      intro: "Changing your password signs out every other session; this one stays.",
      fields: [
        ["current", "Current password", "password", { req: true, hint: "" }],
        ["next", "New password", "password", { req: true, hint: "At least 8 characters." }],
      ],
      review: "The change applies immediately. There is no email round-trip — this instance is the authority.",
    };
  };
  const baseSubmit = App.submitForm.bind(App);
  App.submitForm = async function () {
    const f = App.state.form;
    if (f && f.kind === "useremail") {
      const spec = App.formSpec(f.kind, f.ctx);
      const errs = App.formErrors(spec, f);
      if (errs.length) { f.submitted = true; setState({ live: errs.join(" ") }); return; }
      try {
        await api(`/api/users/${encodeURIComponent(f.ctx.name)}/email`, {
          method: "POST", body: JSON.stringify({ email: f.values.email }) });
        setState({ form: null, settingsOpen: true,
          live: f.ctx.name + " signs in as " + f.values.email + " from now on." });
        App.loadSettingsData();
      } catch (err) { setState({ live: err.message }); }
      return;
    }
    if (!f || f.kind !== "password") return baseSubmit();
    const spec = App.formSpec(f.kind, f.ctx);
    const errs = App.formErrors(spec, f);
    if (errs.length) { f.submitted = true; setState({ live: errs.join(" ") }); return; }
    try {
      await api("/api/auth/password", { method: "POST", body: JSON.stringify({
        current_password: f.values.current, new_password: f.values.next }) });
      setState({ form: null, live: "Password changed. Every other session was signed out." });
    } catch (err) { setState({ live: err.message }); }
  };
})();

// password inputs need type=password in the form renderer: the generic form
// treats unknown types as text; extend the field template via type passthrough
// (uiForm already emits type="${f.type}"). formSpec used type "password" —
// the builder maps textarea/select specially and passes others through, so
// nothing more to do; this comment records the contract.

// ————— offline + outbox surfaces (1.x logic, kept; token-styled bars) ———————
Object.assign(App, {
  initOffline() {
    if (typeof OFFLINE === "undefined") return;
    OFFLINE.subscribe((st) => { App.state.net = st; setState({}); });
    OFFLINE.onFlush((out) => {
      const bits = [];
      if (out.sent) bits.push(out.sent + (out.sent === 1 ? " queued change reached the server" : " queued changes reached the server"));
      out.rejected.forEach((r) => bits.push("one was refused: " + r));
      setState({ live: "Back online. " + bits.join("; ") + "." });
      App.refresh("job", "records", "lookahead", "schedule", "documents");
    });
    this.loadOutbox();
    setInterval(() => this.loadOutbox(), 120000);
  },

  async loadOutbox() {
    try {
      const out = await api("/api/outbox");
      this.state.data.outbox = out.items || out.outbox || [];
      setState({});
    } catch (e) {}
  },

  queueForDesk: (kind, targetId, audience, weeks) => async () => {
    try {
      await api("/api/outbox", { method: "POST", body: JSON.stringify({
        job_number: App.state.job, kind, target_id: targetId,
        audience: audience || null, weeks: weeks || null }) });
      setState({ live: "Queued for your desk. It drafts from the next PC you open PlanWise on that has Outlook — what goes out reflects the sheet at drafting time, not a snapshot from the field." });
      App.loadOutbox();
      App.refresh("attention");
    } catch (err) { setState({ live: err.message }); }
  },

  async drainOutbox() {
    const items = this.state.data.outbox || [];
    if (!items.length) return;
    let drafted = 0;
    for (const item of items) {
      try {
        // Rendered at DRAIN time, not queue time — what goes out reflects the
        // current sheet rather than a snapshot from the van (1.x, kept).
        const doc = await api(`/api/outbox/${item.id}/document`);
        await companionFetch("/draft", { to: doc.to || "", subject: doc.subject,
          body: doc.body, html: doc.html,
          attachments: doc.pdf_b64 ? [{ filename: doc.filename || "planwise.pdf", content_b64: doc.pdf_b64 }] : [],
          display: false });
        await api(`/api/outbox/${item.id}/drafted`, { method: "POST" });
        drafted++;
      } catch (err) {
        // Refresh FIRST so the failure message isn't repainted away (1.x lesson).
        await this.loadOutbox();
        setState({ live: (drafted ? drafted + " drafted, then " : "") + "one failed: " + err.message +
          (isNetErr(err) ? " — no companion on this machine." : "") });
        return;
      }
    }
    try { await companionFetch("/show-drafts", {}); } catch (e) {}
    await this.loadOutbox();
    setState({ live: drafted + (drafted === 1 ? " field send drafted in your Outlook." : " field sends drafted in your Outlook.") + " They are in your Drafts folder — read and send each one." });
    App.refresh("attention");
  },

  outboxEml: (itemId) => () => {
    downloadEmlUrl(`/api/outbox/${itemId}/eml`, "Email file downloaded. Open it in Outlook and press Send.");
  },
});

// Bars rendered under the app grid: netbar (offline/stale) + outbox.
function uiBars(v) {
  let out = "";
  if (v.netBar) {
    out += `<div role="status" aria-live="polite" style="position:fixed;left:18px;bottom:18px;z-index:118;display:flex;align-items:center;gap:9px;padding:9px 13px;border-radius:8px;border:1px solid ${v.netBar.tone};background:${v.netBar.soft};color:${v.netBar.tone};font:600 12px var(--fd);box-shadow:var(--sh);max-width:min(84vw,460px)">
      <span aria-hidden="true" style="width:7px;height:7px;border-radius:50%;background:${v.netBar.tone};flex:none"></span>
      <span style="text-wrap:pretty">${esc(v.netBar.text)}</span>
      ${v.netBar.retry ? `<button data-click="${H(v.netBar.retry)}" class="ho-1" style="font:600 11.5px var(--fd);text-decoration:underline;text-underline-offset:2px;opacity:.85">Retry now</button>` : ""}
    </div>`;
  }
  if (v.outboxBar) {
    out += `<div role="status" style="position:fixed;right:18px;bottom:18px;z-index:118;display:flex;align-items:center;gap:11px;padding:10px 14px;border-radius:8px;border:1px solid var(--bp);background:var(--bps);color:var(--bp);font:600 12.5px var(--fd);box-shadow:var(--sh);max-width:min(84vw,520px);flex-wrap:wrap">
      <span style="text-wrap:pretty">${esc(v.outboxBar.text)}</span>
      <button data-click="${H(v.outboxBar.drain)}" class="hb-ah" style="min-height:34px;padding:6px 13px;border:1px solid var(--bp);border-radius:6px;background:var(--bp);color:#fff;font:600 12px var(--fd)">Draft them in Outlook</button>
      ${v.outboxBar.emlOne ? `<button data-click="${H(v.outboxBar.emlOne)}" class="ht-ac" style="font:600 11.5px var(--fm);text-decoration:underline;text-underline-offset:2px">or download the email file</button>` : ""}
    </div>`;
  }
  return out;
}

// ————— unified share sheet (prototype lines 1359–1451, wired to the real
// generators; the one rule with teeth: an internal item cannot be selected
// while a customer contact is) ————————————————————————————————————————————
Object.assign(App, {
  openShareWith: (items) => () => {
    App.state.shareItems = items;
    App.openShare();
  },
  async openShare() {
    if (!App.state.data.personnel) {
      try { App.state.data.personnel = (await api("/api/personnel")).personnel || []; } catch (e) { App.state.data.personnel = []; }
    }
    setState({ shareOpen: true }, focusRef("share"));
  },
  closeShare() { setState({ shareOpen: false }); },
  toggleRecipient: (key) => () => {
    const r = { ...App.state.recipients };
    r[key] = !r[key];
    setState({ recipients: r });
  },
  toggleShareItem: (id) => () => {
    const it = { ...App.state.shareItems };
    it[id] = !it[id];
    setState({ shareItems: it });
  },

  shareItemDefs() {
    return [
      { id: "brief-cust", label: "Weekly briefing — customer copy", aud: "customer",
        note: "Status and narrative only. Carries no cost, billing or margin figures." },
      { id: "brief-int", label: "Weekly briefing — internal copy", aud: "internal",
        note: "Full financial position, margin risk and anything damaging if it left the building." },
      { id: "look-cust", label: "Look ahead — customer copy", aud: "customer",
        note: "Activities and days. Tools, material and internal notes are stripped." },
      { id: "look-int", label: "Look ahead — internal copy", aud: "internal",
        note: "Includes tools, material and operational notes for the crew." },
    ];
  },

  async confirmShare() {
    const s = App.state;
    const people = Object.keys(s.recipients).filter((k) => s.recipients[k]);
    if (!people.length) { setState({ live: "Choose at least one recipient first." }); return; }
    const custSelected = people.some((k) => k.startsWith("cust:"));
    const picked = App.shareItemDefs().filter((d) =>
      s.shareItems[d.id] && !(d.aud === "internal" && custSelected));
    if (!picked.length) { setState({ live: "Choose at least one item to include." }); return; }

    const job = encodeURIComponent(s.job);
    const contacts = (((s.data.job || {}).meta || {}).contacts || []);
    const personnel = s.data.personnel || [];
    const emailOf = (key) => {
      const name = key.slice(key.indexOf(":") + 1);
      if (key.startsWith("cust:")) return (contacts.find((c) => c.name === name) || {}).email || "";
      return (personnel.find((p2) => p2.name === name) || {}).email || "";
    };
    const custTo = people.filter((k) => k.startsWith("cust:")).map(emailOf).filter(Boolean).join("; ");
    const intTo = people.filter((k) => k.startsWith("int:")).map(emailOf).filter(Boolean).join("; ");

    // One draft per audience: customer recipients get the customer-safe
    // items; internal recipients get everything picked. Each item is fetched
    // from ITS OWN generator, so the sheet can never fork the audience rules.
    const build = async (audience) => {
      const isInt = audience === "internal";
      const items = picked.filter((d) => isInt || d.aud === "customer");
      if (!items.length) return null;
      let subject = null, html = null;
      const attachments = [];
      for (const d of items) {
        if (d.id.startsWith("brief")) {
          const b = App.briefRow().id ? App.briefRow() : await api(`/api/jobs/${job}/briefing`);
          const payload = await api(`/api/briefings/${b.id}/share?audience=${d.aud === "internal" ? "team" : "customer"}`);
          subject = subject || payload.subject;
          html = payload.html;
        } else {
          const la = App.laPeriod().id ? App.laPeriod() : await api(`/api/jobs/${job}/lookahead`);
          const payload = await api(`/api/lookahead/${la.id}/share?audience=${d.aud === "internal" ? "team" : "customer"}&weeks=${la.weeks || 2}`);
          subject = subject || payload.subject;
          if (payload.pdf_b64) attachments.push({ filename: payload.filename || "look-ahead.pdf", content_b64: payload.pdf_b64 });
          if (!html) html = payload.html;
        }
      }
      return { subject, html, attachments, to: isInt ? intTo : custTo, audience };
    };

    try {
      const drafts = [];
      if (custTo) drafts.push(await build("customer"));
      if (intTo) drafts.push(await build("internal"));
      // Internal items with no internal recipient still go out — unaddressed,
      // for the PM to route in Outlook (the look-ahead team rule, D19).
      if (!intTo && picked.some((d) => d.aud === "internal")) drafts.push(await build("internal"));
      let n = 0;
      for (const d of drafts.filter(Boolean)) {
        await companionFetch("/draft", { to: d.to, subject: d.subject, html: d.html,
          attachments: d.attachments, display: true });
        n++;
      }
      const custCount = people.filter((k) => k.startsWith("cust:")).length;
      const msg = "Outlook drafted " + n + (n === 1 ? " email" : " emails") + ". " +
        (custCount ? custCount + " customer recipient" + (custCount === 1 ? "" : "s") + " get the customer copy only." : "All internal.") +
        " Nothing sends until you press Send in Outlook.";
      if (picked.some((d) => d.id.startsWith("brief"))) {
        // A briefing went out: mark it Sent, undoably — same bookkeeping the
        // page's old direct send did.
        const b = App.briefRow().id ? App.briefRow() : await api(`/api/jobs/${job}/briefing`);
        const upd = await api(`/api/briefings/${b.id}`, { method: "PATCH", body: JSON.stringify({ status: "Sent" }) });
        App.state.data.briefing = upd;
        setState({ shareOpen: false });
        App.act(msg, upd.activity_id, ["briefing"]);
      } else {
        setState({ shareOpen: false, live: msg });
      }
    } catch (err) {
      // Either rung below Outlook on the ladder ends the same way: the email
      // files are handed over, one per audience, recipients already inside.
      setState({ shareOpen: false, live: isNetErr(err)
        ? "No Outlook companion on this machine — downloading the email files instead."
        : "The companion refused: " + err.message + " — downloading the email files instead." });
      let b = App.briefRow();
      if (!b.id && picked.some((d) => d.id.startsWith("brief"))) {
        try { b = await api(`/api/jobs/${job}/briefing`); } catch (e2) {}
      }
      if (picked.some((d) => d.id.startsWith("brief")) && b.id) {
        if (picked.some((d) => d.id === "brief-cust")) downloadEmlUrl(`/api/briefings/${b.id}/share.eml?audience=customer`);
        if (picked.some((d) => d.id === "brief-int")) downloadEmlUrl(`/api/briefings/${b.id}/share.eml?audience=team`);
      }
      let la = App.laPeriod();
      if (!la.id && picked.some((d) => d.id.startsWith("look"))) {
        try { la = await api(`/api/jobs/${job}/lookahead`); } catch (e2) {}
      }
      if (la.id) {
        if (picked.some((d) => d.id === "look-cust")) downloadEmlUrl(`/api/lookahead/${la.id}/share.eml?audience=customer&weeks=${la.weeks || 2}`);
        if (picked.some((d) => d.id === "look-int")) downloadEmlUrl(`/api/lookahead/${la.id}/share.eml?audience=team&weeks=${la.weeks || 2}`);
      }
    }
  },

  buildShare() {
    const s = this.state;
    if (!s.shareOpen) return { shareOpen: "" };
    const contacts = (((s.data.job || {}).meta || {}).contacts || []).filter((c) => c.email);
    const personnel = (s.data.personnel || []).filter((p2) => !s.user || p2.name !== s.user.name);
    const custSelected = Object.keys(s.recipients).some((k) => s.recipients[k] && k.startsWith("cust:"));
    const people = Object.keys(s.recipients).filter((k) => s.recipients[k]);
    const items = Object.keys(s.shareItems).filter((k) => s.shareItems[k]);
    return {
      shareOpen: true,
      shareJob: s.job || "",
      closeShare: () => App.closeShare(),
      shareCustomer: contacts.map((c, i) => ({
        id: "sr-c" + i, name: c.name || c.email, role: c.role || "", email: c.email,
        on: !!s.recipients["cust:" + c.name], toggle: App.toggleRecipient("cust:" + c.name) })),
      noCustomerContacts: contacts.length === 0,
      shareInternal: personnel.map((p2, i) => ({
        id: "sr-i" + i, name: p2.name, role: p2.is_admin ? "Administrator" : "Project team", email: p2.email,
        on: !!s.recipients["int:" + p2.name], toggle: App.toggleRecipient("int:" + p2.name) })),
      noInternal: personnel.length === 0,
      shareContent: App.shareItemDefs().map((d) => {
        const blocked = d.aud === "internal" && custSelected;
        return {
          id: "si-" + d.id, label: d.label, note: d.note,
          on: s.shareItems[d.id] && !blocked,
          disabled: blocked,
          toggle: blocked ? () => {} : App.toggleShareItem(d.id),
          tag: d.aud === "customer" ? "Customer safe" : "Internal only",
          tagStyle: stamp(d.aud === "customer" ? "ok" : "er"),
          rowStyle: blocked ? "opacity:.55" : "",
          blocked,
          blockedWhy: "Cannot be sent while a customer contact is selected. Send this in a separate internal email.",
        };
      }),
      shareSummary: (() => {
        const cst = people.filter((k) => k.startsWith("cust:")).length;
        if (!people.length) return "Nobody selected yet.";
        return cst + " customer, " + (people.length - cst) + " internal · " + items.length + (items.length === 1 ? " item" : " items");
      })(),
      shareSubmitLabel: "Draft these in Outlook",
      confirmShare: () => App.confirmShare(),
    };
  },
});
