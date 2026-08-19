// PlanWise 2.0 — shared component templates, translated 1:1 from the
// prototype's markup (PlanWise Redesign v3.dc.html lines 74–1889). The
// translation is mechanical and deliberately unimaginative:
//   {{ x }}            → ${esc(v.x)}   (or ${v.x} for our own style strings)
//   <sc-if value>      → ternary
//   <sc-for list as>   → .map(...).join("")
//   onClick={{fn}}     → data-click="${H(fn)}"   (handler-table token)
//   onChange           → data-input (text/textarea) / data-change (select, date, checkbox)
//   style-hover/focus  → the matching class in app.css
//   ref={{xRef}}       → data-ref="x"
// Copy is verbatim; structure is verbatim; only the binding syntax changed.
"use strict";

function uiSkipLinks() {
  return `<div style="display:flex;gap:8px;padding:0;position:absolute;left:8px;top:8px;z-index:200">
  <a href="#main-content" class="skip">Skip to main content</a>
  <a href="#attention-panel" class="skip">Skip to items needing attention</a>
</div>`;
}

// ——— Splash (lines 6–49; letter-by-letter slogan per CHANGELOG change 5) ———
function uiSplash(v) {
  if (!v.splashOn) return "";
  const letters = [["T",2.45],["r",2.5],["u",2.55],["e",2.6],[null,0],["t",2.68],["o",2.73],[null,0],["t",2.81],["h",2.86],["e",2.91],[null,0],["f",2.99],["i",3.04],["e",3.09],["l",3.14],["d",3.19]]
    .map(([ch, at]) => ch === null
      ? '<span aria-hidden="true" style="display:inline-block;width:.6em"></span>'
      : `<span aria-hidden="true" style="display:inline-block;animation:letterset .5s cubic-bezier(.3,1.2,.4,1) ${at}s both">${ch}</span>`)
    .join("");
  return `<div role="img" aria-label="PlanWise is starting" style="position:fixed;inset:0;z-index:420;background:var(--pn);display:grid;place-items:center;overflow:hidden;animation:splashout .45s ease-in 4.05s both">
    <div style="display:flex;flex-direction:column;align-items:center;gap:26px">
      <svg viewBox="0 0 170 210" aria-hidden="true" style="width:150px;height:auto;overflow:visible">
        <g stroke="var(--ln)" stroke-width="1.2" fill="none" stroke-dasharray="200" style="animation:gridin 1s ease-out both">
          <path d="M30 8v194M140 8v194M8 62h154M8 158h154"></path>
        </g>
        <g style="animation:plumbdrop .7s cubic-bezier(.2,.7,.3,1) .15s both">
          <path d="M52 20h66" stroke="var(--ink)" stroke-width="3.5" stroke-linecap="round"></path>
          <g style="transform-origin:85px 20px;animation:plumbswing 2s cubic-bezier(.36,0,.22,1) .5s both">
            <path d="M85 20v82" stroke="var(--ink)" stroke-width="2"></path>
            <path d="M67 102h36l-18 62z" fill="var(--ac)"></path>
            <path d="M67 102h36" stroke="var(--ink)" stroke-width="3" stroke-linecap="round"></path>
          </g>
        </g>
        <path d="M18 186h134" stroke="var(--ink)" stroke-width="3" stroke-linecap="round" style="animation:risein .5s ease-out 1.5s both"></path>
      </svg>
      <div style="text-align:center">
        <svg viewBox="0 0 208 44" role="img" aria-label="PlanWise" style="height:52px;width:auto;display:block;margin:0 auto;overflow:visible;animation:risein .6s ease-out 1.75s both">${WORDMARK_INNER}</svg>
        <div style="position:relative;height:11px;margin:12px auto 0;width:214px;border:1.5px solid var(--ls);border-radius:6px;background:var(--p2);overflow:hidden;transform-origin:left center;animation:vialdraw .55s cubic-bezier(.3,0,.2,1) 2.1s both">
          <span aria-hidden="true" style="position:absolute;top:1.5px;width:12px;height:6px;border-radius:4px;background:var(--ac);animation:bubbleset .9s cubic-bezier(.36,0,.22,1) 2.35s both"></span>
        </div>
        <p aria-label="True to the field" style="margin:14px 0 0;font:500 11.5px var(--fm);letter-spacing:.26em;text-transform:uppercase;color:var(--ft)">${letters}</p>
        <span aria-hidden="true" style="display:block;height:2px;width:130px;margin:7px auto 0;background:var(--ac);transform-origin:left center;animation:sloganrule .5s cubic-bezier(.3,0,.2,1) 3.35s both"></span>
      </div>
    </div>
  </div>`;
}

// ——— Login (lines 51–96) — the prototype's card carrying the REAL auth ———
// The prototype accepted anything; the repo's auth is the more developed side
// (LOGIC-MERGE), so this one card renders all five real states: login,
// register, pending approval, must-change-password, and first-run bootstrap.
function uiLogin(v) {
  if (!v.loginOn) return "";
  const f = (id, label, type, value, oninput, auto, hint) => `<div>
      <label for="${id}" style="display:block;font:600 12px var(--fd);letter-spacing:.03em;margin-bottom:5px">${label}</label>
      <input id="${id}" type="${type}" ${id === "login-email" ? 'data-ref="login"' : ""} value="${esc(value)}" data-input="${oninput}" ${auto ? `autocomplete="${auto}"` : ""} class="fi" style="width:100%;min-height:var(--tap);padding:9px 11px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)">
      ${hint ? `<p style="margin:4px 0 0;font-size:11.5px;color:var(--ft)">${hint}</p>` : ""}
    </div>`;
  let title = "Sign in", blurb = "Use your White Electrical account. Jobs, cost and drawings follow your Vista permissions.",
      fields = "", submitLabel = "Sign in", foot = "";
  const a = v.auth;
  if (a.mode === "pending") {
    title = "Waiting for approval";
    blurb = "Your account is created and an administrator has been asked to approve it. This page checks by itself — leave it open.";
    fields = `<p style="margin:0;padding:12px 14px;border:1px solid var(--wn);border-radius:6px;background:var(--wns);color:var(--wn);font-size:var(--fzs)">Signed in as ${esc(a.userName || "")} — pending approval.</p>`;
    submitLabel = "";
  } else if (a.mode === "must_change") {
    title = "Set a new password";
    blurb = "Your password was reset by an administrator. Choose your own before continuing.";
    fields = f("login-newpass", "New password", "password", a.newPass || "", H(v.setAuthField("newPass")), "new-password", "At least 8 characters.");
    submitLabel = "Set password and continue";
  } else if (a.mode === "bootstrap") {
    title = "Set up PlanWise";
    blurb = "This is a fresh instance. Create the first administrator account with the setup token from the server's data directory.";
    fields = f("login-token", "Setup token", "text", a.token || "", H(v.setAuthField("token")), "", "From setup_token.txt beside the database.")
      + f("login-name", "Your name", "text", a.name || "", H(v.setAuthField("name")), "name", "The attribution string on everything you do.")
      + f("login-pass", "Password", "password", a.pass || "", H(v.setAuthField("pass")), "new-password", "");
    submitLabel = "Create the administrator account";
  } else if (a.mode === "register") {
    title = "Create your account";
    blurb = "Sign-ups wait for an administrator's approval before they can see job data.";
    fields = f("login-email", "Work email", "email", a.email || "", H(v.setAuthField("email")), "username", "")
      + `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          ${f("login-first", "First name", "text", a.first || "", H(v.setAuthField("first")), "given-name", "")}
          ${f("login-last", "Last name", "text", a.last || "", H(v.setAuthField("last")), "family-name", "")}
         </div>`
      + f("login-pass", "Set a password", "password", a.pass || "", H(v.setAuthField("pass")), "new-password", "");
    submitLabel = "Create account";
    foot = `<p style="margin:15px 0 0;font-size:12px;color:var(--ft)">Already have an account? <button type="button" data-click="${H(v.switchAuthMode("login"))}" style="font:inherit;color:var(--bp);text-decoration:underline;text-underline-offset:2px">Sign in</button></p>`;
  } else {
    fields = f("login-email", "Work email", "email", a.email || "", H(v.setAuthField("email")), "username", "")
      + f("login-pass", "Password", "password", a.pass || "", H(v.setAuthField("pass")), "current-password", "");
    foot = `<p style="margin:15px 0 0;font-size:12px;color:var(--ft)">New here? <button type="button" data-click="${H(v.switchAuthMode("register"))}" style="font:inherit;color:var(--bp);text-decoration:underline;text-underline-offset:2px">Create your account</button></p>`;
  }
  return `<div role="dialog" aria-modal="true" aria-labelledby="login-title" style="position:fixed;inset:0;z-index:410;background:var(--bg);display:grid;place-items:center;padding:24px;overflow-y:auto">
    <div style="width:min(400px,100%);animation:risein .4s ease-out both">
      <div style="display:flex;align-items:center;gap:11px;margin-bottom:24px">
        ${logoSvg(40)}
        ${wordmark(27)}
      </div>
      <form data-submit="${H(v.signIn)}" style="background:var(--pn);border:1px solid var(--ln);border-radius:10px;box-shadow:var(--sh);padding:22px 24px 24px">
        <h1 id="login-title" style="margin:0;font:600 21px/1.2 var(--fd);letter-spacing:.01em">${title}</h1>
        <p style="margin:7px 0 20px;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${blurb}</p>
        ${a.error ? `<p role="alert" style="margin:0 0 14px;padding:10px 12px;border:1px solid var(--er);border-radius:6px;background:var(--ers);color:var(--er);font-size:var(--fzs)">${esc(a.error)}</p>` : ""}
        <div style="display:flex;flex-direction:column;gap:14px">${fields}</div>
        ${submitLabel ? `<button type="submit" class="hb-ah" style="width:100%;margin-top:20px;min-height:var(--tap);padding:11px;border:1px solid var(--ac);border-radius:6px;background:var(--ac);color:var(--acink);font:600 14.5px var(--fd);letter-spacing:.03em;box-shadow:0 0 0 3px var(--as)">${submitLabel}</button>` : ""}
        ${foot}
      </form>
    </div>
  </div>`;
}

// ——— Rail (lines 100–223) ————————————————————————————————————————————————
function uiRail(v) {
  return `<div id="pw-rail" style="${v.railStyle}">
    <div style="${v.brandRowStyle}">
      ${logoSvg(26)}
      ${v.railWide ? wordmark(19) : ""}
      ${v.railWide ? `<button data-click="${H(v.toggleRail)}" aria-pressed="${v.railPinnedAria}" aria-label="${esc(v.railPinAria)}" title="${esc(v.railPinAria)}" class="ht-ac" style="${v.railPinStyle}">
          <svg aria-hidden="true" viewBox="0 0 24 24" style="${v.railPinIconStyle}">
            <path d="M9.5 3.5h5l-1 5.5 3.2 3.2H6.3L9.5 9z" fill="${v.railPinFill}"></path>
            <path d="M12 12.2V20.5" fill="none"></path>
            <path d="${v.railPinSlash}" fill="none" stroke-width="2.1"></path>
          </svg>
        </button>` : ""}
    </div>

    <div style="${v.jobCardWrap}">
      ${v.railWide ? `<div style="${v.jobCardStyle}">
          <label for="job-picker" style="display:block;font:500 var(--lbl) var(--fm);letter-spacing:.16em;text-transform:uppercase;color:var(--ft);padding:9px 11px 0">Current job</label>
          <p style="margin:0;padding:3px 11px 0;font:500 11px var(--fm);letter-spacing:.04em;color:var(--ac)">${esc(v.jobCurrentNum)}</p>
          <p style="margin:0;padding:1px 11px 8px;font:600 13.5px/1.3 var(--fd);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(v.jobCurrentName)}</p>
          <div style="position:relative;border-top:1px solid var(--ln)">
            <input id="job-picker" type="text" data-ref="job" value="${esc(v.jobQuery)}" data-input="${H(v.onJobQuery)}" data-focus="${H(v.openJobs)}" aria-expanded="${v.jobsExpanded}" aria-controls="job-list" aria-describedby="job-picker-hint" autocomplete="off" placeholder="${esc(v.jobPlaceholder)}" class="fj" style="${v.jobInputStyle}">
            <span id="job-picker-hint" class="sr">Type a job number or name to search your recent jobs, or leave it empty to see them all.</span>
          </div>
        </div>` : `<button data-click="${H(v.toggleRail)}" aria-label="Current job ${esc(v.jobCurrentNum)}, ${esc(v.jobCurrentName)}. Expand the rail to switch jobs." title="Job ${esc(v.jobCurrentNum)} · ${esc(v.jobCurrentName)}" class="hb-as" style="width:100%;min-height:38px;border:1px solid var(--ln);border-radius:7px;background:var(--p2);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;padding:4px 0">
          <span aria-hidden="true" style="font:500 8px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:var(--ft);white-space:nowrap">Job</span>
          <span aria-hidden="true" style="font:700 11px var(--fm);letter-spacing:0;color:var(--ac);white-space:nowrap">${esc(v.jobCurrentNum.split(" ")[0])}</span>
        </button>`}
    </div>

    ${v.jobsOpen ? `<div id="job-list" style="margin:0 12px 6px;border:1px solid var(--ls);border-top:none;border-radius:0 0 7px 7px;background:var(--p3);box-shadow:var(--sh);overflow:hidden;animation:fadein .16s ease-out">
        <h2 style="margin:0;padding:8px 11px 6px;font:500 var(--lbl) var(--fm);letter-spacing:.16em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln)">${esc(v.jobListHeading)}</h2>
        <ul style="list-style:none;margin:0;padding:0">
          ${v.jobList.map((j) => `<li>
            <button data-click="${H(j.pick)}" class="hr-as" style="width:100%;min-height:var(--tap);display:flex;gap:8px;align-items:baseline;padding:9px 11px;border-bottom:1px solid var(--ln);text-align:left">
              <span style="font:500 11px var(--fm);color:var(--ac)">${esc(j.num)}</span>
              <span style="flex:1;min-width:0">
                <span style="display:block;font-size:var(--fzs);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(j.name)}</span>
                <span style="display:block;font:10.5px var(--fm);color:var(--ft)">${esc(j.seen)}</span>
              </span>
              <span style="font:10px var(--fm);letter-spacing:.06em;text-transform:uppercase;color:var(--ft);white-space:nowrap">${esc(j.status)}</span>
            </button>
          </li>`).join("")}
        </ul>
        ${v.jobsEmpty ? `<p style="margin:0;padding:14px 11px;font-size:12.5px;color:var(--mu);text-wrap:pretty">No job matches that. Try a number like 24-003 or part of a name.</p>` : ""}
      </div>` : ""}

    <nav aria-label="Job sections" style="${v.navStyle}">
      ${v.navGroups.map((g) => `<div role="group" aria-labelledby="${g.id}" style="${g.groupStyle}">
        <h2 id="${g.id}" style="${g.headStyle}">${esc(g.label)}</h2>
        <ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px">
          ${g.items.map((it) => `<li>
            <button data-click="${H(it.go)}" aria-current="${it.current}" aria-label="${esc(it.aria)}" title="${esc(it.label)}" class="hp2-ink" style="${it.style}">
              <span aria-hidden="true" style="${it.edge}"></span>
              ${it.showIcon ? `<svg aria-hidden="true" viewBox="0 0 24 24" style="${it.iconStyle}"><path d="${it.icon}"></path></svg>` : ""}
              ${it.showLabel ? `<span style="flex:1;text-align:left">${esc(it.label)}</span>` : ""}
              ${it.badge ? `<span style="${it.badgeStyle}">${esc(it.badge)}</span>` : ""}
            </button>
          </li>`).join("")}
        </ul>
      </div>`).join("")}
    </nav>

    <div style="${v.userRowStyle}">
      <div style="display:flex;align-items:center;gap:9px;justify-content:${v.userJustify}">
        <span aria-hidden="true" style="width:27px;height:27px;border-radius:50%;background:var(--as);color:var(--ac);font:700 10.5px var(--fd);display:grid;place-content:center;letter-spacing:.04em;flex:none">${esc(v.userInitials)}</span>
        ${v.railWide ? `<span style="flex:1;min-width:0"><span style="display:block;font-size:var(--fzs);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(v.userName)}</span><span style="display:block;font:10px var(--fm);letter-spacing:.05em;text-transform:uppercase;color:var(--ft);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(v.userRole)}</span></span>
          <button data-click="${H(v.openSettings)}" aria-label="Settings" title="Settings" class="hb-ac" style="flex:none;min-height:32px;min-width:32px;display:grid;place-content:center;border:1px solid var(--ln);border-radius:6px;color:var(--mu)">
            <svg aria-hidden="true" viewBox="0 0 24 24" style="width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3q0-.6-.1-1.2l2-1.6-2-3.4-2.4 1a7.4 7.4 0 0 0-2-1.2L14.5 2h-4l-.4 2.6a7.4 7.4 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.4 7.4 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7.4 7.4 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6q.1-.6.1-1.2Z"></path></svg>
          </button>` : ""}
      </div>
      ${v.railWide ? `<button data-click="${H(v.toggleVista)}" aria-expanded="${v.vistaExpandedAria}" aria-label="${esc(v.vistaFull)}" title="${esc(v.vistaFull)}" class="hb-ls" style="${v.vistaStyle}">
          <span aria-hidden="true" style="${v.vistaDotStyle}"></span>
          <span aria-hidden="true" style="${v.vistaTextStyle}">${esc(v.vistaText)}</span>
        </button>` : ""}
    </div>
  </div>`;
}

// ——— Header + search results (lines 227–254) ————————————————————————————
function uiHeader(v) {
  return `<header style="height:50px;display:flex;align-items:center;gap:12px;padding:7px 18px;border-bottom:1px solid var(--ln);background:var(--pn);position:sticky;top:0;z-index:30;flex-wrap:nowrap">
      <search style="position:relative;flex:1 1 180px;min-width:150px;max-width:400px">
        <label for="job-search" class="sr">Search job ${esc(v.jobNumber)} for change orders, purchase orders, RFIs, submittals, drawings and tasks</label>
        <input id="job-search" type="search" data-ref="search" value="${esc(v.query)}" data-input="${H(v.onQuery)}" data-focus="${H(v.onSearchFocus)}" autocomplete="off" aria-describedby="search-hint" placeholder="Search this job — press / to jump here" class="fi" style="width:100%;min-height:var(--tap);padding:7px 11px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)">
        <span id="search-hint" class="sr">Results appear below as you type. Press Escape to close them.</span>
      </search>
      <span style="flex:1"></span>
      ${v.attnHasAny ? `<button data-click="${H(v.toggleAttn)}" aria-expanded="${v.attnExpanded}" aria-controls="${v.attnControls}" class="hb-ls" style="${v.attnBtnStyle}">Needs attention<span style="${v.attnCountStyle}">${v.attnCount}</span></button>` : ""}
    </header>

    ${v.searchOpen ? `<section aria-label="Search results" style="border-bottom:1px solid var(--ln);background:var(--p2);padding:12px 18px;animation:fadein .14s ease-out">
      <p role="status" style="margin:0 0 8px;font:500 11px var(--fm);letter-spacing:.06em;text-transform:uppercase;color:var(--mu)">${esc(v.resultSummary)}</p>
      <ul style="list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:7px">
        ${v.results.map((r) => `<li>
          <button data-click="${H(r.go)}" class="hb-acp3" style="width:100%;min-height:var(--tap);text-align:left;display:flex;gap:10px;align-items:baseline;padding:9px 12px;border:1px solid var(--ln);border-radius:6px;background:var(--pn)">
            <span style="font:500 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:var(--ac);white-space:nowrap">${esc(r.kind)}</span>
            <span style="flex:1;min-width:0"><span style="display:block;font-weight:500;font-size:var(--fzs)">${esc(r.label)}</span><span style="display:block;font-size:11.5px;color:var(--mu);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.sub)}</span></span>
          </button>
        </li>`).join("")}
      </ul>
      <button data-click="${H(v.clearSearch)}" class="hb-ls" style="margin-top:10px;min-height:var(--tap);padding:6px 12px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12px var(--fd)">Clear search</button>
    </section>` : ""}`;
}

// ——— Page scaffold: crumbs, title, purpose, next step (lines 260–289) ————
function uiScaffold(v) {
  return `<div style="padding:10px 20px 12px;border-bottom:1px solid var(--ln);background:var(--pn)">
      <nav aria-label="Breadcrumb" style="margin-bottom:5px">
        <ol style="list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:7px;align-items:center;font:500 10.5px var(--fm);letter-spacing:.05em;color:var(--ft)">
          ${v.crumbs.map((c) => `<li style="display:flex;gap:7px;align-items:center">
            ${c.isLast ? `<span aria-current="page" style="color:var(--ink)">${esc(c.label)}</span>` : ""}
            ${c.isLink ? `<button data-click="${H(c.go)}" style="font:inherit;color:var(--bp);text-decoration:underline;text-underline-offset:2px">${esc(c.label)}</button>` : ""}
            ${c.sep ? `<span aria-hidden="true">/</span>` : ""}
          </li>`).join("")}
        </ol>
      </nav>
      <div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap">
        <div style="flex:1;min-width:240px">
          <div style="display:flex;align-items:baseline;gap:11px;flex-wrap:wrap">
            <h1 style="margin:0;font:600 var(--h1)/1.15 var(--fd);letter-spacing:.005em">${esc(v.pageTitle)}</h1>
            <p style="margin:0;font:500 10px var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft)">${esc(v.pageEyebrow)}</p>
          </div>
          <p style="margin:3px 0 0;font-size:var(--fzs);color:var(--mu);max-width:78ch;text-wrap:pretty">${esc(v.pagePurpose)}</p>
        </div>
        <div role="group" aria-label="Actions for this page" style="display:flex;gap:9px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
          ${v.nextStepLabel ? `<p style="margin:0;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ac);white-space:nowrap">${esc(v.nextStepLabel)}</p>` : ""}
          ${v.pageActions.map((a) => `<button data-click="${H(a.click)}" class="${a.hoverClass}" style="${a.style}">${esc(a.label)}</button>`).join("")}
        </div>
      </div>
    </div>
    <p role="status" aria-live="polite" class="sr">${esc(v.liveMessage)}</p>`;
}

// ——— Attention panel (lines 970–1010) ————————————————————————————————————
function uiAttention(v) {
  if (!v.attnOpen) return "";
  return `<aside id="attention-panel" aria-labelledby="attn-heading" style="width:308px;border-left:1px solid var(--ln);background:var(--pn);position:sticky;top:50px;height:calc(100vh - 50px);overflow-y:auto;animation:fadein .18s ease-out">
    <div style="padding:14px 16px 11px;border-bottom:1px solid var(--ln);display:flex;align-items:center;gap:8px">
      <h2 id="attn-heading" style="margin:0;font:600 14px var(--fd);letter-spacing:.04em;text-transform:uppercase">Needs attention</h2>
      <span style="flex:1"></span>
      <button data-click="${H(v.toggleAttn)}" class="hb-ls-ink" style="min-height:28px;padding:4px 9px;border:1px solid var(--ln);border-radius:5px;font:600 11px var(--fd);color:var(--mu)">Hide</button>
    </div>
    ${v.attnEmpty ? `<p style="margin:0;padding:22px 16px;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">Nothing is waiting on you. Everything that was open has been handled.</p>` : ""}
    <ul style="list-style:none;margin:0;padding:0">
      ${v.attnItems.map((a) => `<li>
        <button data-click="${H(a.go)}" class="hr-p2" style="width:100%;text-align:left;padding:14px 16px;border-bottom:1px solid var(--ln);display:block">
          <span style="display:flex;align-items:center;gap:7px">
            <span aria-hidden="true" style="width:7px;height:7px;border-radius:50%;background:${a.color};box-shadow:0 0 0 3px ${a.soft};flex:none"></span>
            <span style="font:500 var(--lbl) var(--fm);letter-spacing:.13em;text-transform:uppercase;color:${a.color}">${esc(a.kind)}</span>
            <span style="flex:1"></span>
            <span style="font:11px var(--fm);color:var(--ft)">${esc(a.age)}</span>
          </span>
          <span style="display:block;font-size:var(--fz);line-height:1.45;margin-top:6px;text-wrap:pretty">${esc(a.text)}</span>
          <span style="display:block;margin-top:8px;font:600 11.5px var(--fm);color:var(--bp);text-decoration:underline;text-underline-offset:2px">${esc(a.cta)}</span>
        </button>
      </li>`).join("")}
    </ul>
    <section aria-labelledby="recent-heading" style="padding:14px 16px">
      <h3 id="recent-heading" style="margin:0 0 9px;font:500 var(--lbl) var(--fm);letter-spacing:.13em;text-transform:uppercase;color:var(--ft)">Recent activity</h3>
      <ul style="list-style:none;margin:0;padding:0">
        ${v.attnActivity.map((a) => `<li style="display:flex;gap:9px;padding:7px 0;font-size:var(--fzs);color:var(--mu);align-items:baseline">
          <span aria-hidden="true" style="width:5px;height:5px;border-radius:50%;background:var(--ls);flex:none"></span>
          <span style="flex:1;text-wrap:pretty">${esc(a.text)}</span>
          <span style="font:11px var(--fm);color:var(--ft);white-space:nowrap">${esc(a.when)}</span>
        </li>`).join("")}
      </ul>
      <button data-click="${H(v.goActivity)}" style="margin-top:11px;min-height:var(--tap);font:600 12px var(--fm);color:var(--bp);text-decoration:underline;text-underline-offset:2px">See the full activity log</button>
    </section>
  </aside>`;
}

// ——— Undo bar (lines 1460–1466) ——————————————————————————————————————————
function uiUndo(v) {
  if (!v.undoOpen) return "";
  return `<div role="status" aria-live="polite" style="position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:120;display:flex;align-items:center;gap:14px;padding:12px 14px 12px 18px;border-radius:8px;border:1px solid var(--ls);background:var(--ink);color:var(--bg);box-shadow:var(--shp);animation:riseup .18s ease-out;max-width:min(92vw,640px)">
    <span style="font-size:var(--fzs);text-wrap:pretty">${esc(v.undoMessage)}</span>
    <button data-click="${H(v.doUndo)}" class="hu" style="min-height:var(--tap);padding:7px 14px;border-radius:6px;border:1px solid var(--bg);background:transparent;color:var(--bg);font:600 12.5px var(--fd);letter-spacing:.03em;white-space:nowrap">Undo this</button>
    <button data-click="${H(v.dismissUndo)}" class="ho-1" style="min-height:var(--tap);padding:7px 10px;font:600 12px var(--fd);color:var(--bg);opacity:.75;white-space:nowrap">Dismiss</button>
  </div>`;
}

// ——— Confirm dialog (lines 1152–1182) ————————————————————————————————————
function uiConfirm(v) {
  if (!v.confirmOpen) return "";
  return `<div style="position:fixed;inset:0;z-index:145;background:rgba(24,27,30,.5);display:grid;place-items:center;padding:24px">
    <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-body" style="width:min(600px,100%);max-height:86vh;overflow-y:auto;background:var(--pn);border:1px solid var(--ls);border-radius:10px;box-shadow:var(--shp);animation:fadein .16s ease-out">
      <div style="padding:16px 20px;border-bottom:1px solid var(--ln)">
        <p style="margin:0 0 4px;font:500 10px var(--fm);letter-spacing:.16em;text-transform:uppercase;color:var(--ac)">${esc(v.confirmEyebrow)}</p>
        <h2 id="confirm-title" style="margin:0;font:600 19px/1.25 var(--fd)">${esc(v.confirmTitle)}</h2>
        <p id="confirm-body" style="margin:8px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(v.confirmBody)}</p>
      </div>
      <section aria-labelledby="confirm-checks" style="padding:14px 20px">
        <h3 id="confirm-checks" style="margin:0 0 9px;font:500 var(--lbl) var(--fm);letter-spacing:.15em;text-transform:uppercase;color:var(--ft)">What PlanWise checked before offering this</h3>
        <ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px">
          ${v.confirmChecks.map((c) => `<li style="display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border:1px solid var(--ln);border-left:3px solid ${c.color};border-radius:0 6px 6px 0;background:var(--p3)">
            <span aria-hidden="true" style="font:700 12px var(--fm);color:${c.color};flex:none;margin-top:1px">${c.mark}</span>
            <span style="flex:1;min-width:0">
              <span style="display:block;font:600 var(--fzs) var(--fd)">${esc(c.label)}</span>
              <span style="display:block;font-size:12.5px;color:var(--mu);margin-top:2px;text-wrap:pretty">${esc(c.note)}</span>
            </span>
          </li>`).join("")}
        </ul>
        <p style="${v.confirmVerdictStyle}">${esc(v.confirmVerdict)}</p>
      </section>
      <div style="padding:14px 20px;border-top:1px solid var(--ln);background:var(--p2);display:flex;gap:9px;align-items:center;flex-wrap:wrap;border-radius:0 0 10px 10px">
        <span style="flex:1"></span>
        <button data-click="${H(v.closeConfirm)}" data-ref="confirm" class="hb-ls" style="min-height:var(--tap);padding:9px 15px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 13px var(--fd)">Leave it as it is</button>
        <button data-click="${H(v.runConfirm)}" ${v.confirmBlocked ? "disabled" : ""} class="${v.confirmBlocked ? "" : "hb-ah2"}" style="${v.confirmBtnStyle}">${esc(v.confirmLabel)}</button>
      </div>
    </div>
  </div>`;
}

// ——— Keyboard shortcut sheet (lines 1521–1538) ———————————————————————————
function uiKeys(v) {
  if (!v.keysOpen) return "";
  return `<div style="position:fixed;inset:0;z-index:140;background:rgba(24,27,30,.45);display:grid;place-items:center;padding:24px">
    <div role="dialog" aria-modal="true" aria-labelledby="keys-title" style="width:min(620px,100%);max-height:82vh;overflow-y:auto;background:var(--pn);border:1px solid var(--ls);border-radius:10px;box-shadow:var(--shp);animation:fadein .16s ease-out">
      <div style="display:flex;align-items:center;gap:12px;padding:15px 20px;border-bottom:1px solid var(--ln)">
        <h2 id="keys-title" style="margin:0;font:600 18px var(--fd);letter-spacing:.02em">Keyboard shortcuts</h2>
        <span style="flex:1"></span>
        <button data-click="${H(v.closeKeys)}" data-ref="keys" class="hb-ls-ink" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;font:600 12.5px var(--fd);color:var(--mu)">Close</button>
      </div>
      <p style="margin:0;padding:13px 20px 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">Every shortcut has a visible control as well — nothing here is the only way to do something. Tab moves through the rail, the header, the page and then the attention panel, in that order.</p>
      <dl style="margin:0;padding:14px 20px 20px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px 16px;align-items:baseline">
        ${SHORTCUTS.map((k) => `<dt style="font:600 12px var(--fm);letter-spacing:.04em;padding:4px 8px;border:1px solid var(--ls);border-radius:5px;background:var(--p2);white-space:nowrap;justify-self:start">${esc(k.key)}</dt>
          <dd style="margin:0;font-size:var(--fzs);color:var(--mu)">${esc(k.what)}</dd>`).join("")}
      </dl>
    </div>
  </div>`;
}

// ——— Tour (lines 1540–1562) ———————————————————————————————————————————————
function uiTour(v) {
  if (!v.tourOpen) return "";
  return `<div style="position:fixed;inset:0;z-index:150;background:rgba(24,27,30,.5);display:grid;place-items:center;padding:24px">
    <div role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" style="width:min(520px,100%);background:var(--pn);border:1px solid var(--ls);border-radius:10px;box-shadow:var(--shp);animation:fadein .16s ease-out">
      <div style="padding:18px 22px 0;display:flex;align-items:baseline;gap:10px">
        <p style="margin:0;font:500 10.5px var(--fm);letter-spacing:.16em;text-transform:uppercase;color:var(--ac)">${esc(v.tourStepLabel)}</p>
        <span style="flex:1"></span>
        <ul aria-hidden="true" style="list-style:none;margin:0;padding:0;display:flex;gap:5px">
          ${v.tourDots.map((d) => `<li style="${d.style}"></li>`).join("")}
        </ul>
      </div>
      <h2 id="tour-title" style="margin:9px 22px 0;font:600 20px var(--fd);letter-spacing:.01em">${esc(v.tourTitle)}</h2>
      <p id="tour-body" style="margin:8px 22px 0;font-size:var(--fz);color:var(--mu);line-height:1.6;text-wrap:pretty">${esc(v.tourBody)}</p>
      <div style="display:flex;gap:9px;align-items:center;padding:18px 22px;margin-top:14px;border-top:1px solid var(--ln);background:var(--p2);border-radius:0 0 10px 10px;flex-wrap:wrap">
        <button data-click="${H(v.endTour)}" class="ht-ink" style="min-height:var(--tap);padding:8px 13px;font:600 12.5px var(--fd);color:var(--mu);text-decoration:underline;text-underline-offset:2px">Skip the tour</button>
        <span style="flex:1"></span>
        ${v.tourHasBack ? `<button data-click="${H(v.tourBack)}" class="hb-ls" style="min-height:var(--tap);padding:8px 15px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12.5px var(--fd)">Back</button>` : ""}
        <button data-click="${H(v.tourNext)}" data-ref="tour" class="hb-ah" style="min-height:var(--tap);padding:8px 17px;border:1px solid var(--ac);border-radius:6px;background:var(--ac);color:var(--acink);font:600 12.5px var(--fd);letter-spacing:.03em">${esc(v.tourNextLabel)}</button>
      </div>
    </div>
  </div>`;
}

// ——— Schedule peek editor (shared partial; lines 470–506 / 910–948) ———————
// One partial serves both the Gantt row and the register's full-width row —
// the prototype binds identical fields in both places via schedRowProps.
function uiPeekFields(g) {
  return `<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end">
      <label style="display:flex;flex-direction:column;gap:3px;font:500 var(--lbl) var(--fm);letter-spacing:.13em;text-transform:uppercase;color:var(--ft)">Start
        <input type="date" value="${esc(g.peekStart)}" data-change="${H(g.setStart)}" ${g.datesDisabled ? "disabled" : ""} style="min-height:30px;padding:4px 8px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:500 12px var(--fm);color:var(--ink)${g.datesDisabled ? ";opacity:.55" : ""}">
      </label>
      <label style="display:flex;flex-direction:column;gap:3px;font:500 var(--lbl) var(--fm);letter-spacing:.13em;text-transform:uppercase;color:var(--ft)">Finish
        <input type="date" value="${esc(g.peekFinish)}" data-change="${H(g.setFinish)}" ${g.datesDisabled ? "disabled" : ""} style="min-height:30px;padding:4px 8px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:500 12px var(--fm);color:var(--ink)${g.datesDisabled ? ";opacity:.55" : ""}">
      </label>
      <label style="display:flex;flex-direction:column;gap:3px;font:500 var(--lbl) var(--fm);letter-spacing:.13em;text-transform:uppercase;color:var(--ft)">Predecessor
        <select data-change="${H(g.setPred)}" style="min-height:30px;padding:4px 8px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font-size:12px;max-width:240px">
          ${g.predOpts.map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(g.predValue) ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
        </select>
      </label>
      ${g.depShow ? `<label style="display:flex;flex-direction:column;gap:3px;font:500 var(--lbl) var(--fm);letter-spacing:.13em;text-transform:uppercase;color:var(--ft)">Dependency type
        <select data-change="${H(g.setDep)}" style="min-height:30px;padding:4px 8px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font-size:12px">
          ${g.depOpts.map((o) => `<option value="${esc(o.value)}" ${o.value === g.depValue ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
        </select>
      </label>` : ""}
      ${g.morePreds ? `<span style="font:11.5px var(--fm);color:var(--ft);align-self:center">also after ${esc(g.morePreds)}</span>` : ""}
    </div>
    <div style="margin-top:9px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span style="font:500 var(--lbl) var(--fm);letter-spacing:.13em;text-transform:uppercase;color:var(--ft)">Successors</span>
      ${g.succChips.map((sx) => `<span style="display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border:1px solid var(--ln);border-radius:999px;background:var(--pn);font:500 11px var(--fm);color:var(--mu)">${esc(sx.label)}
        <button data-click="${H(sx.drop)}" aria-label="${esc(sx.dropAria)}" class="ht-er" style="color:var(--ft);font:600 12px/1 var(--fm);padding:0 1px">×</button>
      </span>`).join("")}
      ${g.succNone ? `<span style="font:11.5px var(--fm);color:var(--ft)">none</span>` : ""}
      <select data-change="${H(g.addSucc)}" aria-label="Add a successor to this task" style="min-height:28px;padding:3px 8px;border:1px dashed var(--ls);border-radius:999px;background:transparent;font-size:11.5px;color:var(--mu);max-width:220px">
        ${g.succOpts.map((o) => `<option value="${esc(o.value)}" ${o.value === "" ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
      </select>
    </div>`;
}

// ——— Generic register (lines 850–965) ————————————————————————————————————
function uiRegister(v) {
  if (!v.hasRegister) return "";
  return `<section aria-labelledby="register-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh)">
    <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--ln);flex-wrap:wrap">
      <h2 id="register-heading" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">${esc(v.regTitle)}</h2>
      <p style="margin:0;font:500 10.5px var(--fm);letter-spacing:.07em;text-transform:uppercase;color:var(--ft)">${esc(v.regSource)}</p>
      <span style="flex:1"></span>
      ${(v.regExtras || []).map((x) => `<button data-click="${H(x.click)}" class="${x.hoverClass || "hb-ls"}" style="${x.style}">${esc(x.label)}</button>`).join("")}
    </div>
    ${v.regHasFilters ? `<div role="group" aria-label="Filter this register by status" style="display:flex;gap:7px;padding:11px 16px;border-bottom:1px solid var(--ln);flex-wrap:wrap;background:var(--p2)">
      ${v.regFilters.map((f) => `<button data-click="${H(f.pick)}" aria-pressed="${f.pressed}" class="hb-ls" style="${f.style}">${esc(f.label)}<span style="${f.countStyle}">${f.count}</span></button>`).join("")}
    </div>` : ""}
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:var(--fz)">
        <caption class="sr">${esc(v.regCaption)}</caption>
        <thead><tr>
          ${v.regColumns.map((c) => `<th scope="col" aria-sort="${c.sort}" style="${c.style}">
            ${c.sortable ? `<button data-click="${H(c.click)}" class="ht-ac" style="font:inherit;color:inherit;letter-spacing:inherit;text-transform:inherit;display:inline-flex;gap:5px;align-items:center;min-height:24px">${esc(c.label)}<span aria-hidden="true" style="color:var(--ac)">${c.arrow}</span></button>` : esc(c.label)}
          </th>`).join("")}
        </tr></thead>
        <tbody>
          ${v.regRows.map((r) => `<tr ${r.hasSched ? `data-sched-row="${r.schedIdx}"` : ""} class="hr-p2" style="${r.rowStyle}">
            <th scope="row" style="${r.headStyle}">
              <span style="display:flex;align-items:center;gap:6px">
                ${r.hasSched ? `<span data-pointerdown="${H(r.gripDown)}" title="Drag to reorder this row" aria-hidden="true" style="flex:none;width:14px;color:var(--ls);cursor:grab;touch-action:none;font:700 11px/1 var(--fm);text-align:center;user-select:none">⠿</span>` : ""}
                <button data-click="${H(r.open)}" class="ht-ac" style="text-align:left;font:inherit;color:var(--bp);text-decoration:underline;text-underline-offset:3px;min-height:var(--tap);display:block;flex:1;min-width:0">
                  <span style="display:block">${esc(r.key)}</span>
                  <span style="display:block;font:400 12px var(--fb);color:var(--mu);text-decoration:none">${esc(r.keySub)}</span>
                </button>
                ${r.hasSched ? `<button data-click="${H(r.togglePeek)}" aria-expanded="${r.peekOpen ? "true" : "false"}" aria-label="${esc(r.peekAria)}" class="hb-ac" style="flex:none;width:18px;height:18px;display:grid;place-content:center;border:1px solid var(--ln);border-radius:4px;color:var(--mu);font:600 11px var(--fm)">${r.peekChevron}</button>` : ""}
              </span>
            </th>
            ${r.cells.map((c) => `<td style="${c.style}">
              ${c.isStamp ? `<span style="${c.stampStyle}">${esc(c.text)}</span>` : ""}
              ${c.isBar ? `<span style="display:flex;align-items:center;gap:9px">
                <span aria-hidden="true" style="height:6px;border-radius:3px;background:var(--ln);flex:1;min-width:54px;overflow:hidden"><span style="display:block;height:100%;width:${c.barW};background:${c.barColor};border-radius:3px"></span></span>
                <span style="font:500 11.5px var(--fm);color:var(--mu);min-width:40px;text-align:right">${esc(c.text)}</span>
              </span>` : ""}
              ${c.isPlain ? esc(c.text) : ""}
            </td>`).join("")}
          </tr>
          ${r.peekOpen ? `<tr>
            <td colspan="9" style="padding:0;border-bottom:1px solid var(--ln)">
              <div style="padding:10px 16px 12px 36px;background:var(--p2);animation:fadein .16s ease-out">
                ${uiPeekFields(r)}
              </div>
            </td>
          </tr>` : ""}`).join("")}
        </tbody>
        ${v.regHasTotal ? `<tfoot><tr style="background:var(--p2)">
          <th scope="row" style="text-align:left;padding:12px 16px;font:600 var(--fz) var(--fd);border-top:1px solid var(--ls)">${esc(v.regTotalLabel)}</th>
          ${v.regTotalCells.map((c) => `<td style="${c.style}">${esc(c.text)}</td>`).join("")}
        </tr></tfoot>` : ""}
      </table>
    </div>
    ${v.regEmpty ? `<p style="margin:0;padding:26px 16px;font-size:var(--fzs);color:var(--mu);text-align:center;text-wrap:pretty">${esc(v.regEmptyText)}</p>` : ""}
    <p style="margin:0;padding:11px 16px;border-top:1px solid var(--ln);font-size:12px;color:var(--ft);text-wrap:pretty">${esc(v.regFootnote)}</p>
  </section>`;
}

// ——— Detail drawer (lines 1565–1653) ————————————————————————————————————
function uiDetail(v) {
  if (!v.detailOpen) return "";
  return `<div style="position:fixed;inset:0;z-index:130;background:rgba(24,27,30,.42);display:flex;justify-content:flex-end">
    <div role="dialog" aria-modal="true" aria-labelledby="detail-title" style="width:min(660px,100%);height:100%;background:var(--pn);border-left:1px solid var(--ls);box-shadow:var(--shp);display:flex;flex-direction:column;animation:fadein .16s ease-out">
      <div style="padding:15px 20px;border-bottom:1px solid var(--ln);display:flex;align-items:flex-start;gap:12px;flex:none">
        <div style="flex:1;min-width:0">
          <p style="margin:0 0 4px;font:500 10px var(--fm);letter-spacing:.16em;text-transform:uppercase;color:var(--ac)">${esc(v.detailKind)}</p>
          <h2 id="detail-title" style="margin:0;font:600 19px/1.25 var(--fd);letter-spacing:.01em">${esc(v.detailTitle)}</h2>
          <p style="margin:5px 0 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <span style="${v.detailStampStyle}">${esc(v.detailStatus)}</span>
            <span style="font:11.5px var(--fm);color:var(--mu)">${esc(v.detailMeta)}</span>
          </p>
        </div>
        <button data-click="${H(v.closeDetail)}" data-ref="detail" class="hb-ls-ink" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;font:600 12.5px var(--fd);color:var(--mu);white-space:nowrap">Close this panel</button>
      </div>
      <div style="flex:1;overflow-y:auto;padding:4px 20px 20px">
        ${v.detailSections.map((s) => `<section aria-labelledby="${s.id}" style="margin-top:18px">
          <h3 id="${s.id}" style="margin:0 0 8px;font:500 var(--lbl) var(--fm);letter-spacing:.15em;text-transform:uppercase;color:var(--ft)">${esc(s.title)}</h3>
          <dl style="margin:0;border:1px solid var(--ln);border-radius:7px;overflow:hidden;background:var(--p3)">
            ${s.rows.map((r) => `<div style="display:flex;gap:14px;align-items:baseline;padding:10px 13px;border-bottom:1px solid var(--ln)">
              <dt style="flex:0 0 38%;font-size:var(--fzs);color:var(--mu)">${esc(r.label)}</dt>
              <dd style="margin:0;flex:1;min-width:0;font-size:var(--fz);${r.valueStyle}">${esc(r.value)}</dd>
              ${r.note ? `<span style="font:500 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:var(--ft);white-space:nowrap">${esc(r.note)}</span>` : ""}
            </div>`).join("")}
          </dl>
        </section>`).join("")}

        ${v.detailHasItems ? `<section aria-labelledby="detail-items" style="margin-top:18px">
          <h3 id="detail-items" style="margin:0 0 8px;font:500 var(--lbl) var(--fm);letter-spacing:.15em;text-transform:uppercase;color:var(--ft)">${esc(v.detailItemsTitle)}</h3>
          <table style="width:100%;border-collapse:collapse;border:1px solid var(--ln);border-radius:7px;font-size:var(--fzs);background:var(--p3)">
            <thead><tr>
              <th scope="col" style="text-align:left;padding:9px 13px;font:500 9.5px var(--fm);letter-spacing:.13em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln)">${esc(v.detailItemsCol1)}</th>
              <th scope="col" style="text-align:right;padding:9px 13px;font:500 9.5px var(--fm);letter-spacing:.13em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln)">${esc(v.detailItemsCol2)}</th>
            </tr></thead>
            <tbody>
              ${v.detailItems.map((i) => `<tr>
                <td style="padding:9px 13px;border-bottom:1px solid var(--ln)">${esc(i.label)}</td>
                <td style="padding:9px 13px;border-bottom:1px solid var(--ln);text-align:right;font-variant-numeric:tabular-nums;color:${i.color}">${esc(i.value)}</td>
              </tr>`).join("")}
            </tbody>
            <tfoot><tr style="background:var(--p2)">
              <th scope="row" style="text-align:left;padding:10px 13px;font:600 var(--fzs) var(--fd)">${esc(v.detailItemsTotalLabel)}</th>
              <td style="padding:10px 13px;text-align:right;font:600 var(--fzs) var(--fd);font-variant-numeric:tabular-nums">${esc(v.detailItemsTotal)}</td>
            </tr></tfoot>
          </table>
        </section>` : ""}

        ${v.detailHasNotes ? `<section aria-labelledby="detail-notes" style="margin-top:18px">
          <h3 id="detail-notes" style="margin:0 0 8px;font:500 var(--lbl) var(--fm);letter-spacing:.15em;text-transform:uppercase;color:var(--ft)">${esc(v.detailNotesTitle)}</h3>
          <ul style="margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:7px">
            ${v.detailNotes.map((n) => `<li style="padding:10px 13px;border:1px solid var(--ln);border-left:3px solid var(--ls);border-radius:0 6px 6px 0;background:var(--p3);font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(n.text)}</li>`).join("")}
          </ul>
        </section>` : ""}

        <section aria-labelledby="detail-audit" style="margin-top:18px">
          <h3 id="detail-audit" style="margin:0 0 8px;font:500 var(--lbl) var(--fm);letter-spacing:.15em;text-transform:uppercase;color:var(--ft)">Audit trail</h3>
          <ol style="margin:0;padding:0;list-style:none;border-left:2px solid var(--ln);margin-left:5px">
            ${v.detailAudit.map((a) => `<li style="position:relative;padding:0 0 14px 16px">
              <span aria-hidden="true" style="position:absolute;left:-5px;top:5px;width:8px;height:8px;border-radius:50%;background:${a.color};border:2px solid var(--pn)"></span>
              <span style="display:block;font-size:var(--fzs)">${esc(a.what)}</span>
              <span style="display:block;font:11px var(--fm);color:var(--ft);margin-top:2px">${esc(a.who)}${a.when ? " · " + esc(a.when) : ""}</span>
            </li>`).join("")}
          </ol>
        </section>
      </div>
      <div style="flex:none;padding:14px 20px;border-top:1px solid var(--ln);background:var(--p2);display:flex;gap:9px;align-items:center;flex-wrap:wrap">
        <p style="margin:0;flex:1;min-width:180px;font-size:12px;color:var(--mu);text-wrap:pretty">${esc(v.detailFootnote)}</p>
        ${v.detailActions.map((a) => `<button data-click="${H(a.click)}" class="${a.hoverClass}" style="${a.style}">${esc(a.label)}</button>`).join("")}
      </div>
    </div>
  </div>`;
}

// ——— Generic form drawer (lines 1655–1816) ————————————————————————————————
function uiForm(v) {
  if (!v.formOpen) return "";
  return `<div style="position:fixed;inset:0;z-index:135;background:rgba(24,27,30,.42);display:flex;justify-content:flex-end">
    <form role="dialog" aria-modal="true" aria-labelledby="form-title" aria-describedby="form-intro" data-submit="${H(v.submitForm)}" style="width:min(660px,100%);height:100%;background:var(--pn);border-left:1px solid var(--ls);box-shadow:var(--shp);display:flex;flex-direction:column;animation:fadein .16s ease-out">
      <div style="padding:15px 20px;border-bottom:1px solid var(--ln);display:flex;align-items:flex-start;gap:12px;flex:none">
        <div style="flex:1;min-width:0">
          <p style="margin:0 0 4px;font:500 10px var(--fm);letter-spacing:.16em;text-transform:uppercase;color:var(--ac)">${esc(v.formEyebrow)}</p>
          <h2 id="form-title" style="margin:0;font:600 19px/1.25 var(--fd);letter-spacing:.01em">${esc(v.formTitle)}</h2>
        </div>
        <button type="button" data-click="${H(v.closeForm)}" class="hb-ls-ink" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;font:600 12.5px var(--fd);color:var(--mu);white-space:nowrap">Cancel and close</button>
      </div>
      <div style="flex:1;overflow-y:auto;padding:16px 20px 20px">
        <p id="form-intro" style="margin:0 0 16px;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(v.formIntro)}</p>

        ${v.formShowErrors ? `<div role="alert" style="margin:0 0 16px;padding:12px 14px;border:1px solid var(--er);border-radius:7px;background:var(--ers)">
          <p style="margin:0 0 6px;font:600 13px var(--fd);color:var(--er)">${esc(v.formErrorHeading)}</p>
          <ul style="margin:0;padding-left:18px;font-size:var(--fzs);color:var(--er)">
            ${v.formErrors.map((e2) => `<li>${esc(e2.text)}</li>`).join("")}
          </ul>
        </div>` : ""}

        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px 16px">
          ${v.formFields.map((f) => `<div style="${f.wrap}">
            <label for="${f.id}" style="display:block;font:600 12px var(--fd);letter-spacing:.03em;margin-bottom:5px">${esc(f.label)}<span style="${f.reqStyle}">${esc(f.reqText)}</span></label>
            ${f.isInput ? `<input id="${f.id}" type="${f.type}" value="${esc(f.value)}" ${f.type === "date" ? `data-change="${H(f.set)}"` : `data-input="${H(f.set)}"`} aria-describedby="${f.hintId}" aria-invalid="${f.invalid}" placeholder="${esc(f.placeholder)}" class="fi" style="${f.control}">` : ""}
            ${f.isArea ? `<textarea id="${f.id}" rows="${f.rows}" data-input="${H(f.set)}" aria-describedby="${f.hintId}" aria-invalid="${f.invalid}" placeholder="${esc(f.placeholder)}" class="fi" style="${f.control}">${esc(f.value)}</textarea>` : ""}
            ${f.isSelect ? `<select id="${f.id}" data-change="${H(f.set)}" aria-describedby="${f.hintId}" style="${f.control}">
              ${f.options.map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(f.value) ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
            </select>` : ""}
            <p id="${f.hintId}" style="margin:5px 0 0;font-size:11.5px;color:${f.hintColor};text-wrap:pretty">${esc(f.hint)}</p>
          </div>`).join("")}
        </div>

        ${v.formHasItems ? `<section aria-labelledby="form-items" style="margin-top:20px;border:1px solid var(--ln);border-radius:7px;overflow:hidden">
          <div style="padding:11px 14px;background:var(--p2);border-bottom:1px solid var(--ln)">
            <h3 id="form-items" style="margin:0;font:600 13px var(--fd);letter-spacing:.03em">${esc(v.formItemsTitle)}</h3>
            <p style="margin:4px 0 0;font-size:11.5px;color:var(--mu);text-wrap:pretty">${esc(v.formItemsHint)}</p>
          </div>
          <ul style="list-style:none;margin:0;padding:0">
            ${v.formItems.map((i) => `<li style="display:flex;gap:9px;align-items:flex-end;padding:11px 14px;border-bottom:1px solid var(--ln)">
              <div style="flex:1;min-width:0">
                <label for="${i.descId}" style="display:block;font:600 11px var(--fd);letter-spacing:.03em;margin-bottom:4px;color:var(--mu)">Line ${i.n} description</label>
                <input id="${i.descId}" type="text" value="${esc(i.desc)}" data-input="${H(i.setDesc)}" placeholder="${esc(i.placeholder)}" class="fi2" style="width:100%;min-height:var(--tap);padding:7px 10px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)">
              </div>
              <div style="width:150px;flex:none">
                <label for="${i.amtId}" style="display:block;font:600 11px var(--fd);letter-spacing:.03em;margin-bottom:4px;color:var(--mu)">Amount, US dollars</label>
                <input id="${i.amtId}" type="text" inputmode="decimal" value="${esc(i.amt)}" data-input="${H(i.setAmt)}" placeholder="0.00" class="fi2" style="width:100%;min-height:var(--tap);padding:7px 10px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font:var(--fzs) var(--fm);text-align:right">
              </div>
              <button type="button" data-click="${H(i.remove)}" class="hb-er" style="min-height:var(--tap);padding:7px 11px;border:1px solid var(--ln);border-radius:6px;font:600 11.5px var(--fd);color:var(--mu);white-space:nowrap">Remove line ${i.n}</button>
            </li>`).join("")}
          </ul>
          <div style="display:flex;gap:12px;align-items:center;padding:11px 14px;background:var(--p2);flex-wrap:wrap">
            <button type="button" data-click="${H(v.addItem)}" class="hb-ac" style="min-height:var(--tap);padding:7px 13px;border:1px dashed var(--ls);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">${esc(v.addItemLabel)}</button>
            <span style="flex:1"></span>
            <p style="margin:0;font:600 13px var(--fd)" aria-live="polite">${esc(v.formItemsTotalLabel)} <span style="font-variant-numeric:tabular-nums;font-family:var(--fm)">${esc(v.formItemsTotal)}</span></p>
          </div>
        </section>` : ""}

        ${v.formHasDays ? `<fieldset style="margin:20px 0 0;padding:0;border:1px solid var(--ln);border-radius:7px;overflow:hidden">
          <legend style="float:left;width:100%;margin:0;padding:11px 14px;background:var(--p2);border-bottom:1px solid var(--ln);font:600 13px var(--fd);letter-spacing:.03em">Days this activity is worked</legend>
          <p style="margin:0;padding:9px 14px 0;clear:both;font-size:11.5px;color:var(--mu);text-wrap:pretty">Select the days the crew is on this. You can change them later straight from the look-ahead grid.</p>
          <div style="display:grid;grid-template-columns:repeat(14,1fr);gap:5px;padding:11px 14px 14px">
            ${v.formDays.map((d) => `<button type="button" data-click="${H(d.toggle)}" aria-pressed="${d.pressed}" aria-label="${esc(d.label)}" style="${d.style}">
              <span aria-hidden="true" style="display:block;font:500 9px var(--fm);opacity:.8">${d.dow}</span>
              <span aria-hidden="true" style="display:block;font:600 13px var(--fd)">${d.num}</span>
            </button>`).join("")}
          </div>
        </fieldset>` : ""}

        ${v.formHasColors ? `<fieldset style="margin:20px 0 0;padding:0;border:1px solid var(--ln);border-radius:7px;overflow:hidden">
          <legend style="float:left;width:100%;margin:0;padding:11px 14px;background:var(--p2);border-bottom:1px solid var(--ln);font:600 13px var(--fd);letter-spacing:.03em">Colour on the grid</legend>
          <p style="margin:0;padding:9px 14px 0;clear:both;font-size:11.5px;color:var(--mu);text-wrap:pretty">Each work area carries a colour so the crew can read the grid at a glance. Every colour here holds its contrast in field mode and in bright sun.</p>
          <div style="display:flex;gap:9px;padding:11px 14px 14px;flex-wrap:wrap">
            ${v.formColors.map((c) => `<button type="button" data-click="${H(c.pick)}" aria-pressed="${c.pressed}" aria-label="${esc(c.label)}" style="${c.style}">
              <span aria-hidden="true" style="${c.swatch}"></span>${esc(c.name)}
            </button>`).join("")}
          </div>
        </fieldset>` : ""}

        ${v.formHasClar ? `<fieldset style="margin:20px 0 0;padding:0;border:1px solid var(--ln);border-radius:7px;overflow:hidden">
          <legend style="float:left;width:100%;margin:0;padding:11px 14px;background:var(--p2);border-bottom:1px solid var(--ln);font:600 13px var(--fd);letter-spacing:.03em">Clarifications and exceptions to include</legend>
          <p style="margin:0;padding:9px 14px 0;clear:both;font-size:11.5px;color:var(--mu);text-wrap:pretty">These are the firm's standing positions. Ticked lines print on the change order letter in this order.</p>
          <ul style="list-style:none;margin:0;padding:9px 14px 13px">
            ${v.formClar.map((c) => `<li style="display:flex;gap:10px;align-items:flex-start;padding:7px 0">
              <input id="${c.id}" type="checkbox" ${c.on ? "checked" : ""} data-change="${H(c.toggle)}" style="width:19px;height:19px;margin:1px 0 0;accent-color:var(--ac);flex:none">
              <label for="${c.id}" style="font-size:var(--fzs);color:var(--mu);text-wrap:pretty;cursor:pointer">${esc(c.text)}</label>
            </li>`).join("")}
          </ul>
        </fieldset>` : ""}

        ${v.formHasPages ? `<section aria-labelledby="form-pages" style="margin:20px 0 0;border:1px solid var(--ln);border-radius:7px;overflow:hidden">
          <div style="padding:11px 14px;background:var(--p2);border-bottom:1px solid var(--ln)">
            <h3 id="form-pages" style="margin:0;font:600 13px var(--fd);letter-spacing:.03em">Drawing pages to attach</h3>
            <p style="margin:4px 0 0;font-size:11.5px;color:var(--mu);text-wrap:pretty">Open a set to find the page visually, then attach it and mark it up. The package sends the original page plus this record's own redlines; internal team markups never go out.</p>
          </div>
          <ul style="list-style:none;margin:0;padding:0">
            ${v.formDocs.map((d) => `<li style="display:flex;gap:11px;align-items:center;padding:11px 14px;border-bottom:1px solid var(--ln)">
              <span aria-hidden="true" style="${d.thumbStyle}"><span style="${d.thumbBlock}"></span></span>
              <span style="flex:1;min-width:0">
                <span style="display:block;font:600 var(--fzs) var(--fd)">${esc(d.name)}</span>
                <span style="display:block;font:11.5px var(--fm);color:var(--ft);margin-top:2px">${esc(d.sub)}</span>
              </span>
              <button type="button" data-click="${H(d.browse)}" class="hb-ac" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12px var(--fd);white-space:nowrap">${esc(d.browseLabel)}</button>
            </li>`).join("")}
          </ul>
          ${v.formHasAttached ? `<div style="padding:11px 14px;background:var(--oks);border-top:1px solid var(--ln)">
            <p style="margin:0 0 6px;font:600 12px var(--fd);color:var(--ok)">In the package</p>
            <ul style="list-style:none;margin:0;padding:0;display:flex;gap:7px;flex-wrap:wrap">
              ${v.formAttached.map((a) => `<li><button type="button" data-click="${H(a.remove)}" class="hb-er" style="display:inline-flex;align-items:center;gap:8px;min-height:34px;padding:5px 11px;border:1px solid var(--ok);border-radius:999px;background:var(--pn);font:600 11.5px var(--fd);color:var(--ok)">${esc(a.label)}<span aria-hidden="true">×</span><span class="sr">Remove ${esc(a.label)} from the package</span></button></li>`).join("")}
            </ul>
          </div>` : ""}
          ${v.formNoAttached ? `<p style="margin:0;padding:13px 14px;font-size:12.5px;color:var(--mu);background:var(--p2);border-top:1px solid var(--ln);text-wrap:pretty">Nothing attached yet. Open a set above to find the page you mean.</p>` : ""}
        </section>` : ""}

        <section aria-labelledby="form-review" style="margin-top:20px;padding:13px 15px;border:1px solid var(--ls);border-left:3px solid var(--ac);border-radius:0 7px 7px 0;background:var(--p2)">
          <h3 id="form-review" style="margin:0 0 6px;font:600 13px var(--fd);letter-spacing:.03em">Before you create this</h3>
          <p style="margin:0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(v.formReview)}</p>
        </section>
      </div>
      <div style="flex:none;padding:14px 20px;border-top:1px solid var(--ln);background:var(--p2);display:flex;gap:9px;align-items:center;flex-wrap:wrap">
        <p style="margin:0;flex:1;min-width:170px;font-size:12px;color:var(--mu)" aria-live="polite">${esc(v.formStatus)}</p>
        <button type="button" data-click="${H(v.closeForm)}" class="hb-ls" style="min-height:var(--tap);padding:9px 15px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 13px var(--fd)">Discard this draft</button>
        <button type="submit" class="hb-ah" style="min-height:var(--tap);padding:9px 17px;border:1px solid var(--ac);border-radius:6px;background:var(--ac);color:var(--acink);font:600 13px var(--fd);letter-spacing:.03em;box-shadow:0 0 0 3px var(--as)">${esc(v.formSubmitLabel)}</button>
      </div>
    </form>
  </div>`;
}

// ——— Settings sheet (lines 1468–1519) — prototype visuals; the 1.x panes
// (AI, spend cap, companion, users, push, account) mount beneath the
// appearance rows in plan Phase 8. ————————————————————————————————————————
function uiSettings(v) {
  if (!v.settingsOpen) return "";
  return `<div style="position:fixed;inset:0;z-index:142;background:rgba(24,27,30,.45);display:grid;place-items:center;padding:24px">
    <div role="dialog" aria-modal="true" aria-labelledby="settings-title" style="width:min(640px,100%);max-height:84vh;overflow-y:auto;background:var(--pn);border:1px solid var(--ls);border-radius:10px;box-shadow:var(--shp);animation:fadein .16s ease-out">
      <div style="display:flex;align-items:center;gap:12px;padding:15px 20px;border-bottom:1px solid var(--ln)">
        <h2 id="settings-title" style="margin:0;flex:1;font:600 19px var(--fd);letter-spacing:.02em">Settings</h2>
        <button data-click="${H(v.closeSettings)}" data-ref="settings" class="hb-ls-ink" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;font:600 12.5px var(--fd);color:var(--mu)">Close</button>
      </div>

      <section aria-labelledby="set-display" style="padding:16px 20px 4px">
        <h3 id="set-display" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Display</h3>
        <p style="margin:5px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">Every choice here is remembered on this device, so the way you left PlanWise is the way you find it.</p>

        <fieldset style="margin:14px 0 0;padding:0;border:1px solid var(--ln);border-radius:8px;overflow:hidden">
          <legend style="float:left;width:100%;margin:0;padding:10px 13px;background:var(--p2);border-bottom:1px solid var(--ln);font:600 13px var(--fd)">Appearance</legend>
          <div style="clear:both">
            ${v.appearanceRows.map((a) => `<div style="display:flex;align-items:center;gap:14px;padding:12px 13px;border-bottom:1px solid var(--ln);flex-wrap:wrap">
              <span style="flex:1;min-width:180px">
                <span style="display:block;font:600 var(--fzs) var(--fd)">${esc(a.label)}</span>
                <span style="display:block;font-size:12.5px;color:var(--mu);margin-top:2px;text-wrap:pretty">${esc(a.note)}</span>
              </span>
              <span role="group" aria-label="${esc(a.label)}" style="display:flex;gap:7px;flex-wrap:wrap">
                ${a.options.map((o) => `<button data-click="${H(o.pick)}" aria-pressed="${o.pressed}" style="${o.style}">${o.swatch ? `<span aria-hidden="true" style="${o.swatch}"></span>` : ""}${esc(o.label)}</button>`).join("")}
              </span>
            </div>`).join("")}
          </div>
        </fieldset>
      </section>

      <section aria-labelledby="set-help" style="padding:16px 20px ${v.settingsExtra ? "4px" : "20px"}">
        <h3 id="set-help" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Help</h3>
        <p style="margin:5px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">Nothing in PlanWise can only be done by shortcut. These are here to make the work quicker, never to hide it.</p>
        <ul style="list-style:none;margin:13px 0 0;padding:0;display:flex;flex-direction:column;gap:9px">
          ${v.helpRows.map((h) => `<li>
            <button data-click="${H(h.click)}" class="hb-ac" style="width:100%;text-align:left;display:flex;align-items:center;gap:13px;padding:13px;border:1px solid var(--ln);border-radius:8px;background:var(--p3)">
              <svg aria-hidden="true" viewBox="0 0 24 24" style="width:20px;height:20px;flex:none;stroke:var(--ac);fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round"><path d="${h.icon}"></path></svg>
              <span style="flex:1;min-width:0">
                <span style="display:block;font:600 var(--fzs) var(--fd)">${esc(h.label)}</span>
                <span style="display:block;font-size:12.5px;color:var(--mu);margin-top:2px;text-wrap:pretty">${esc(h.note)}</span>
              </span>
            </button>
          </li>`).join("")}
        </ul>
      </section>
      ${v.settingsExtra || ""}
    </div>
  </div>`;
}

// ——— Change order composer (lines 1184–1357) ————————————————————————————
// The prototype's preview pane simulated the letter in HTML; the production
// pane shows the ACTUAL letter PDF the customer receives — same pane, honest
// content (LOGIC-MERGE: real generator wins over simulation).
function uiCO(v) {
  if (!v.coOpen) return "";
  return `<div style="position:fixed;inset:0;z-index:136;background:rgba(24,27,30,.45);display:flex;justify-content:center;align-items:stretch;padding:22px">
    <form role="dialog" aria-modal="true" aria-labelledby="co-title" data-submit="${H(v.coSubmit)}" style="width:min(1220px,100%);background:var(--pn);border:1px solid var(--ls);border-radius:10px;box-shadow:var(--shp);display:flex;flex-direction:column;overflow:hidden;animation:fadein .16s ease-out">
      <div style="flex:none;padding:14px 20px;border-bottom:1px solid var(--ln);display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <div style="flex:1;min-width:220px">
          <p style="margin:0 0 3px;font:500 10px var(--fm);letter-spacing:.16em;text-transform:uppercase;color:var(--ac)">${esc(v.coEyebrow)}</p>
          <h2 id="co-title" style="margin:0;font:600 19px/1.2 var(--fd)">${esc(v.coTitle)}</h2>
        </div>
        <span style="${v.coStateStyle}">${esc(v.coStateLabel)}</span>
        <button type="button" data-click="${H(v.coTogglePreview)}" aria-pressed="${v.coPreviewAria}" class="hb-ls" style="${v.coPreviewBtnStyle}">${esc(v.coPreviewLabel)}</button>
        <button type="button" data-click="${H(v.coClose)}" data-ref="co" class="hb-ls-ink" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;font:600 12.5px var(--fd);color:var(--mu);white-space:nowrap">Close</button>
      </div>

      <div style="flex:1;min-height:0;display:grid;grid-template-columns:${v.coCols}">
        <div style="overflow-y:auto;padding:16px 20px 20px;border-right:1px solid var(--ln)">
          ${v.coShowErrors ? `<div role="alert" style="margin:0 0 15px;padding:12px 14px;border:1px solid var(--er);border-radius:7px;background:var(--ers)">
            <p style="margin:0 0 6px;font:600 13px var(--fd);color:var(--er)">${esc(v.coErrorHeading)}</p>
            <ul style="margin:0;padding-left:18px;font-size:var(--fzs);color:var(--er)">
              ${v.coErrors.map((e2) => `<li>${esc(e2.text)}</li>`).join("")}
            </ul>
          </div>` : ""}

          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px 16px">
            ${v.coFields.map((f) => `<div style="${f.wrap}">
              <label for="${f.id}" style="display:block;font:600 12px var(--fd);letter-spacing:.03em;margin-bottom:5px">${esc(f.label)}<span style="${f.reqStyle}">${esc(f.reqText)}</span></label>
              ${f.isInput ? `<input id="${f.id}" type="${f.type}" value="${esc(f.value)}" ${f.type === "date" ? `data-change="${H(f.set)}"` : `data-input="${H(f.set)}"`} placeholder="${esc(f.placeholder)}" aria-describedby="${f.hintId}" aria-invalid="${f.invalid}" class="fi2" style="${f.control}">` : ""}
              ${f.isArea ? `<textarea id="${f.id}" rows="${f.rows}" data-input="${H(f.set)}" placeholder="${esc(f.placeholder)}" aria-describedby="${f.hintId}" aria-invalid="${f.invalid}" class="fi2" style="${f.control}">${esc(f.value)}</textarea>` : ""}
              ${f.isSelect ? `<select id="${f.id}" data-change="${H(f.set)}" aria-describedby="${f.hintId}" style="${f.control}">
                ${f.options.map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(f.value) ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
              </select>` : ""}
              <p id="${f.hintId}" style="margin:5px 0 0;font-size:11.5px;color:${f.hintColor};text-wrap:pretty">${esc(f.hint)}</p>
            </div>`).join("")}
          </div>

          <section aria-labelledby="co-lines" style="margin-top:18px;border:1px solid var(--ln);border-radius:7px;overflow:hidden">
            <div style="padding:11px 14px;background:var(--p2);border-bottom:1px solid var(--ln)">
              <h3 id="co-lines" style="margin:0;font:600 13px var(--fd)">Breakout pricing</h3>
              <p style="margin:3px 0 0;font-size:11.5px;color:var(--mu);text-wrap:pretty">Price each cause on its own line. A credit is a negative amount.</p>
            </div>
            <ul style="list-style:none;margin:0;padding:0">
              ${v.coItems.map((i) => `<li style="display:flex;gap:9px;align-items:flex-end;padding:11px 14px;border-bottom:1px solid var(--ln)">
                <div style="flex:1;min-width:0">
                  <label for="${i.descId}" style="display:block;font:600 11px var(--fd);margin-bottom:4px;color:var(--mu)">Line ${i.n} description</label>
                  <input id="${i.descId}" type="text" value="${esc(i.desc)}" data-input="${H(i.setDesc)}" placeholder="Replacement anchor bolt assemblies" class="fi2" style="width:100%;min-height:var(--tap);padding:7px 10px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)">
                </div>
                <div style="width:140px;flex:none">
                  <label for="${i.amtId}" style="display:block;font:600 11px var(--fd);margin-bottom:4px;color:var(--mu)">Amount, USD</label>
                  <input id="${i.amtId}" type="text" inputmode="decimal" value="${esc(i.amt)}" data-input="${H(i.setAmt)}" placeholder="0.00" class="fi2" style="width:100%;min-height:var(--tap);padding:7px 10px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font:var(--fzs) var(--fm);text-align:right">
                </div>
                <button type="button" data-click="${H(i.remove)}" class="hb-er" style="min-height:var(--tap);padding:7px 11px;border:1px solid var(--ln);border-radius:6px;font:600 11.5px var(--fd);color:var(--mu);white-space:nowrap">Remove line ${i.n}</button>
              </li>`).join("")}
            </ul>
            <div style="display:flex;gap:12px;align-items:center;padding:11px 14px;background:var(--p2);flex-wrap:wrap">
              <button type="button" data-click="${H(v.coAddItem)}" class="hb-ac" style="min-height:var(--tap);padding:7px 13px;border:1px dashed var(--ls);border-radius:6px;font:600 12px var(--fd);color:var(--mu)">Add another line</button>
              <span style="flex:1"></span>
              <p style="margin:0;font:600 13px var(--fd)" aria-live="polite">Total submitted <span style="font-family:var(--fm);font-variant-numeric:tabular-nums">${esc(v.coTotal)}</span></p>
            </div>
          </section>

          ${v.coIsCustomer ? `<fieldset style="margin:18px 0 0;padding:0;border:1px solid var(--ln);border-radius:7px;overflow:hidden">
            <legend style="float:left;width:100%;margin:0;padding:11px 14px;background:var(--p2);border-bottom:1px solid var(--ln);font:600 13px var(--fd)">Clarifications and exceptions</legend>
            <p style="margin:0;padding:9px 14px 0;clear:both;font-size:11.5px;color:var(--mu);text-wrap:pretty">Ticked lines print on the letter in this order. Anything you add here is saved to the firm's library for the next change order.</p>
            <ul style="list-style:none;margin:0;padding:9px 14px 4px">
              ${v.coClar.map((c) => `<li style="display:flex;gap:10px;align-items:flex-start;padding:7px 0">
                <input id="${c.id}" type="checkbox" ${c.on ? "checked" : ""} data-change="${H(c.toggle)}" style="width:19px;height:19px;margin:1px 0 0;accent-color:var(--ac);flex:none">
                <label for="${c.id}" style="flex:1;font-size:var(--fzs);color:var(--mu);cursor:pointer;text-wrap:pretty">${esc(c.text)}</label>
                ${c.isNew ? `<span style="font:500 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:var(--ok);white-space:nowrap">Added by the team</span>` : ""}
              </li>`).join("")}
            </ul>
            <div style="display:flex;gap:9px;align-items:flex-end;padding:6px 14px 13px">
              <div style="flex:1;min-width:0">
                <label for="co-new-clar" style="display:block;font:600 11px var(--fd);margin-bottom:4px;color:var(--mu)">Write a new clarification</label>
                <input id="co-new-clar" type="text" value="${esc(v.coNewClar)}" data-input="${H(v.coSetNewClar)}" placeholder="Pricing excludes work outside the fenced substation yard." class="fi2" style="width:100%;min-height:var(--tap);padding:7px 10px;border:1px solid var(--ln);border-radius:6px;background:var(--p2);font-size:var(--fzs)">
              </div>
              <button type="button" data-click="${H(v.coAddClar)}" class="hb-ac" style="min-height:var(--tap);padding:8px 13px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12px var(--fd);white-space:nowrap">Add to the library</button>
            </div>
          </fieldset>` : ""}
        </div>

        ${v.coPreviewOn ? `<div style="overflow-y:auto;background:var(--p2);padding:18px;display:flex;flex-direction:column">
          <p style="margin:0 0 10px;font:500 10px var(--fm);letter-spacing:.15em;text-transform:uppercase;color:var(--ft)">${esc(v.coPreviewNote)}</p>
          <iframe title="Live preview of the change order letter" src="${v.coPreviewUrl}" style="flex:1;min-height:520px;width:100%;background:#FFFFFF;border:1px solid var(--ls);border-radius:4px;box-shadow:var(--sh)"></iframe>
        </div>` : ""}
      </div>

      <div style="flex:none;padding:13px 20px;border-top:1px solid var(--ln);background:var(--p2);display:flex;gap:9px;align-items:center;flex-wrap:wrap">
        <p style="margin:0;flex:1;min-width:220px;font-size:12px;color:var(--mu);text-wrap:pretty" aria-live="polite">${esc(v.coFootnote)}</p>
        <button type="submit" class="hb-ls" style="min-height:var(--tap);padding:9px 16px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 13px var(--fd)">${esc(v.coSaveLabel)}</button>
        <button type="button" data-click="${H(v.coSaveAndSend)}" class="hb-ah" style="min-height:var(--tap);padding:9px 17px;border:1px solid var(--ac);border-radius:6px;background:var(--ac);color:var(--acink);font:600 13px var(--fd);letter-spacing:.03em;box-shadow:0 0 0 3px var(--as)">${esc(v.coSendLabel)}</button>
      </div>
    </form>
  </div>`;
}
