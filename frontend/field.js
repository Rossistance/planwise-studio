// PlanWise Field — the shell a Superintendent or Field-leader account gets,
// ported from the handoff's PlanWise Field.dc.html. Five bottom tabs over
// the same state, api and morphdom loop as the office app; the office
// dialogs (form, viewer, confirm, share, undo) are reused as-is — they were
// audited clean at phone width. The server refuses office writes for this
// role regardless of anything this file renders (backend/field.py).

function uiFieldApp(v) {
  const f = v.field;
  if (!f) return "";
  return `<div style="min-height:100vh;display:flex;flex-direction:column;background:var(--bg);max-width:520px;margin:0 auto">
    <header style="position:sticky;top:0;z-index:20;background:var(--pn);border-bottom:1px solid var(--ln);padding:calc(env(safe-area-inset-top,0px) + 10px) var(--pad) 9px">
      <div style="display:flex;align-items:center;gap:10px">
        <span aria-hidden="true" style="width:8px;height:20px;background:var(--ac);border-radius:1px;display:inline-block;flex:none"></span>
        <div style="flex:1;min-width:0">
          <p style="margin:0;font:500 11px var(--fm);letter-spacing:.1em;color:var(--ac)">JOB ${esc(f.jobNumber)} · FIELD</p>
          <p style="margin:1px 0 0;font:600 16px/1.25 var(--fd);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(f.jobName)}</p>
        </div>
        <button data-click="${H(f.openMore)}" aria-expanded="${f.moreOpen ? "true" : "false"}" class="hb-ls" style="min-height:var(--tap);padding:8px 13px;border:1px solid var(--ln);border-radius:8px;font:600 13px var(--fd);color:var(--mu);background:var(--p2)">Settings</button>
      </div>
      <p role="status" style="margin:7px 0 0;display:flex;align-items:center;gap:7px;font:12.5px var(--fm);color:${f.connColor}">
        <span aria-hidden="true" style="width:8px;height:8px;border-radius:50%;flex:none;background:${f.connColor}"></span>${esc(f.connText)}</p>
    </header>

    <main id="field-main" style="flex:1;padding:0 var(--pad) 190px">
      ${f.tab === "today" ? uiFieldToday(f) : ""}
      ${f.tab === "look" ? uiFieldLook(f) : ""}
      ${f.tab === "docs" ? uiFieldDocs(f) : ""}
      ${f.tab === "recs" ? uiFieldRecs(f) : ""}
      ${f.tab === "money" ? uiFieldMoney(f) : ""}
    </main>

    <div style="position:fixed;left:0;right:0;bottom:0;z-index:30;max-width:520px;margin:0 auto;background:var(--pn);border-top:1px solid var(--ln);box-shadow:var(--shp);padding:8px var(--pad) calc(env(safe-area-inset-bottom,0px) + 8px)">
      ${f.fab ? `<button data-click="${H(f.fab.go)}" class="hb-ah" style="width:100%;min-height:var(--tap);margin-bottom:8px;padding:12px;border-radius:10px;border:1px solid var(--ac);background:var(--ac);color:var(--acink);font:600 16px var(--fd);letter-spacing:.03em;box-shadow:0 0 0 3px var(--as)">${esc(f.fab.label)}</button>` : ""}
      <nav aria-label="Field sections">
        <ul style="list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(5,1fr);gap:4px">
          ${f.tabs.map((t) => `<li style="position:relative">
            <button data-click="${H(t.go)}" aria-current="${t.current}" style="width:100%;min-height:var(--tap);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border-radius:9px;padding:6px 2px;${t.on ? "background:var(--as);color:var(--ac)" : "color:var(--mu)"}">
              <span aria-hidden="true" style="width:6px;height:6px;border-radius:50%;background:${t.on ? "var(--ac)" : "var(--ls)"}"></span>
              <span style="font:600 12px var(--fd);letter-spacing:.01em">${esc(t.label)}</span>
            </button>
            ${t.badge ? `<span style="position:absolute;top:2px;right:4px;min-width:18px;padding:2px 5px;border-radius:999px;background:var(--er);color:#fff;font:700 10px var(--fm);text-align:center">${t.badge}</span>` : ""}
          </li>`).join("")}
        </ul>
      </nav>
    </div>

    ${uiFieldThread(f)}
    ${uiFieldMore(f)}
  </div>`;
}

function uiFieldToday(f) {
  return `<section aria-labelledby="today-heading" style="padding:16px 0 0">
      <p style="margin:0;font:500 var(--lbl) var(--fm);letter-spacing:.15em;text-transform:uppercase;color:var(--ft)">${esc(f.todayDate)}</p>
      <h1 id="today-heading" style="margin:4px 0 0;font:600 var(--h1)/1.2 var(--fd)">Today on site</h1>
      <p style="margin:7px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(FIELD_COPY.todayIntro)}</p>
    </section>
    <section aria-labelledby="blocking-heading" style="margin-top:20px">
      <h2 id="blocking-heading" style="margin:0 0 9px;font:600 17px var(--fd)">${esc(FIELD_COPY.blockingHeading)}</h2>
      ${f.blockers.length ? `<ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px">
        ${f.blockers.map((b) => `<li>
          <button data-click="${H(b.go)}" style="width:100%;text-align:left;padding:14px;border:1px solid var(--ln);border-left:4px solid ${b.color};border-radius:0 10px 10px 0;background:var(--pn);box-shadow:var(--sh);min-height:var(--tap)">
            <span style="display:flex;align-items:center;gap:8px">
              <span style="font:600 var(--lbl) var(--fm);letter-spacing:.12em;text-transform:uppercase;color:${b.color}">${esc(b.kind)}</span>
              <span style="flex:1"></span>
              <span style="font:12px var(--fm);color:var(--ft)">${esc(b.age)}</span>
            </span>
            <span style="display:block;font-size:var(--fz);line-height:1.4;margin-top:6px;text-wrap:pretty">${esc(b.text)}</span>
            ${b.cta ? `<span style="display:block;margin-top:8px;font:600 14px var(--fd);color:var(--bp);text-decoration:underline;text-underline-offset:3px">${esc(b.cta)}</span>` : ""}
          </button>
        </li>`).join("")}
      </ul>` : `<p style="margin:0;padding:18px 14px;border:1px solid var(--ln);border-radius:10px;background:var(--pn);font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(FIELD_COPY.noBlockers)}</p>`}
    </section>
    <section aria-labelledby="crew-heading" style="margin-top:22px">
      <h2 id="crew-heading" style="margin:0 0 3px;font:600 17px var(--fd)">${esc(FIELD_COPY.crewHeading)}</h2>
      <p style="margin:0 0 10px;font-size:13.5px;color:var(--ft)">${esc(f.todayDoneText)}</p>
      <ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px">
        ${f.todayItems.map((t) => `<li style="border:1px solid var(--ln);border-radius:10px;background:var(--pn);box-shadow:var(--sh);overflow:hidden;display:flex">
          <button data-click="${H(t.toggle)}" aria-pressed="${t.on ? "true" : "false"}" aria-label="${esc(t.aria)}" style="flex:none;width:74px;display:flex;flex-direction:column;align-items:center;justify-content:center;border-right:1px solid var(--ln);${t.on ? `background:${t.soft};color:${t.color}` : "background:var(--p2);color:var(--ft)"}">
            <span aria-hidden="true" style="font:700 20px var(--fd);line-height:1">${t.on ? "✓" : "○"}</span>
            <span style="font:600 10px var(--fd);letter-spacing:.05em;margin-top:2px">${t.on ? "Worked" : "Tick"}</span>
          </button>
          <button data-click="${H(t.open)}" class="hr-p2" style="flex:1;min-width:0;text-align:left;padding:13px 14px;min-height:var(--tap)">
            <span style="display:flex;gap:8px;align-items:center">
              <span style="${t.areaStyle}">${esc(t.area)}</span>
              <span style="flex:1"></span>
              <span style="font:12px var(--fm);color:var(--ft)">${esc(t.days)}</span>
            </span>
            <span style="display:block;font:600 var(--fz)/1.35 var(--fd);margin-top:5px;text-wrap:pretty">${esc(t.name)}</span>
            ${t.note ? `<span style="display:block;font-size:13.5px;color:var(--mu);margin-top:3px;text-wrap:pretty">${esc(t.note)}</span>` : ""}
          </button>
        </li>`).join("")}
      </ul>
      ${f.todayItems.length ? "" : `<p style="margin:0;padding:16px 14px;border:1px dashed var(--ls);border-radius:10px;background:var(--p2);font-size:var(--fzs);color:var(--mu);text-wrap:pretty">Nothing is planned for today on the look ahead.</p>`}
    </section>`;
}

function uiFieldLook(f) {
  return `<section aria-labelledby="look-heading" style="padding:16px 0 0">
      <h1 id="look-heading" style="margin:0;font:600 var(--h1)/1.2 var(--fd)">Look ahead</h1>
      <p style="margin:7px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(f.lookRange)}. ${esc(FIELD_COPY.lookIntro)}</p>
    </section>
    <section aria-labelledby="areas-heading" style="margin-top:14px;border:1px solid var(--ln);border-radius:10px;background:var(--pn);box-shadow:var(--sh);padding:12px 14px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <h2 id="areas-heading" style="margin:0;flex:1;font:600 var(--fz) var(--fd)">Work areas</h2>
        <button data-click="${H(f.openNewArea)}" class="hb-fill" style="min-height:var(--tap);padding:8px 13px;border:1px solid var(--ln);border-radius:9px;background:var(--pn);font:600 13px var(--fd);white-space:nowrap">Add an area</button>
      </div>
      <ul style="list-style:none;margin:10px 0 0;padding:0;display:flex;gap:8px;flex-wrap:wrap">
        ${f.areaChips.map((a) => `<li style="display:flex;align-items:center;gap:8px;padding:7px 12px;border:1px solid var(--ln);border-radius:999px;background:var(--p2)">
          <span aria-hidden="true" style="width:11px;height:11px;border-radius:3px;flex:none;background:${a.color}"></span>
          <span style="font:600 13px var(--fd)">${esc(a.name)}</span>
          <span style="font:11.5px var(--fm);color:var(--ft)">${a.count}</span>
        </li>`).join("")}
      </ul>
      <button data-click="${H(f.openShare)}" class="hb-fill" style="width:100%;margin-top:11px;min-height:var(--tap);padding:11px;border:1px solid var(--ac);border-radius:9px;background:var(--as);color:var(--ac);font:600 14px var(--fd)">Share this look ahead</button>
    </section>
    <ul style="list-style:none;margin:14px 0 0;padding:0;display:flex;flex-direction:column;gap:12px">
      ${f.lookRows.map((r) => `<li style="border:1px solid var(--ln);border-radius:10px;background:var(--pn);box-shadow:var(--sh);padding:13px 14px">
        <p style="margin:0;display:flex;gap:8px;align-items:center">
          <span style="${r.areaStyle}">${esc(r.area)}</span>
          <span style="flex:1"></span>
          <span style="font:12px var(--fm);color:var(--ft)">${esc(r.count)}</span>
        </p>
        <h2 style="margin:6px 0 0;font:600 var(--fz)/1.35 var(--fd);text-wrap:pretty">${esc(r.name)}</h2>
        ${r.notes.length ? `<ul style="list-style:none;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:4px">
          ${r.notes.map((n) => `<li style="display:flex;gap:8px;align-items:baseline;font-size:13.5px;color:var(--mu)">
            <span style="font:600 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:${n.color};white-space:nowrap">${esc(n.tag)}</span>
            <span style="flex:1;text-wrap:pretty">${esc(n.text)}</span>
          </li>`).join("")}
        </ul>` : ""}
        <button data-click="${H(r.edit)}" class="hb-fill" style="margin-top:8px;min-height:38px;padding:6px 12px;border:1px solid var(--ln);border-radius:8px;background:var(--p2);font:600 12.5px var(--fd);color:var(--mu)">Edit this activity</button>
        <div role="group" aria-label="${esc(r.groupLabel)}" style="display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin-top:11px">
          ${r.days.map((d) => `<button data-click="${H(d.toggle)}" aria-pressed="${d.on ? "true" : "false"}" aria-label="${esc(d.label)}" style="min-height:var(--tap);border-radius:9px;border:1px solid ${d.on ? d.color : "var(--ln)"};${d.on ? `background:${d.soft};color:${d.color}` : "background:var(--pn);color:var(--mu)"}">
            <span aria-hidden="true" style="display:block;font:500 10px var(--fm);letter-spacing:.05em;opacity:.8">${esc(d.dow)}</span>
            <span aria-hidden="true" style="display:block;font:600 15px var(--fd);margin-top:1px">${esc(d.num)}</span>
          </button>`).join("")}
        </div>
      </li>`).join("")}
    </ul>`;
}

function uiFieldDocs(f) {
  return `<section aria-labelledby="docs-heading" style="padding:16px 0 0">
      <h1 id="docs-heading" style="margin:0;font:600 var(--h1)/1.2 var(--fd)">Drawings</h1>
      <p style="margin:7px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(FIELD_COPY.docsIntro)}</p>
    </section>
    <ul style="list-style:none;margin:16px 0 0;padding:0;display:flex;flex-direction:column;gap:10px">
      ${f.docRows.map((d) => `<li>
        <button data-click="${H(d.open)}" class="hr-p2" style="width:100%;text-align:left;padding:14px;border:1px solid var(--ln);border-radius:10px;background:var(--pn);box-shadow:var(--sh);min-height:var(--tap)">
          <span style="display:flex;gap:9px;align-items:center">
            <span style="${d.stampStyle}">${esc(d.stamp)}</span>
            <span style="flex:1"></span>
            <span style="font:12px var(--fm);color:var(--ft)">${esc(d.pages)}</span>
          </span>
          <span style="display:block;font:600 var(--fz)/1.35 var(--fd);margin-top:7px;text-wrap:pretty">${esc(d.name)}</span>
          <span style="display:block;font-size:13.5px;color:var(--mu);margin-top:3px">${esc(d.sub)}</span>
        </button>
      </li>`).join("")}
    </ul>
    ${f.docRows.length ? "" : `<p style="margin:16px 0 0;padding:16px 14px;border:1px dashed var(--ls);border-radius:10px;background:var(--p2);font-size:var(--fzs);color:var(--mu)">No drawing sets on this job yet.</p>`}`;
}

function uiFieldRecs(f) {
  return `<section aria-labelledby="recs-heading" style="padding:16px 0 0">
      <h1 id="recs-heading" style="margin:0;font:600 var(--h1)/1.2 var(--fd)">Questions and submittals</h1>
      <p style="margin:7px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(FIELD_COPY.recsIntro)}</p>
    </section>
    <div role="group" aria-label="Choose which register to show" style="display:flex;gap:8px;margin-top:14px">
      ${f.recTabs.map((t) => `<button data-click="${H(t.pick)}" aria-pressed="${t.on ? "true" : "false"}" style="flex:1;min-height:var(--tap);border-radius:10px;border:1px solid ${t.on ? "var(--ac)" : "var(--ln)"};${t.on ? "background:var(--as);color:var(--ac)" : "background:var(--pn);color:var(--mu)"};font:600 14px var(--fd)">${esc(t.label)}<span style="margin-left:7px;font:600 11.5px var(--fm)">${t.count}</span></button>`).join("")}
    </div>
    <ul style="list-style:none;margin:14px 0 0;padding:0;display:flex;flex-direction:column;gap:10px">
      ${f.recRows.map((r) => `<li>
        <button data-click="${H(r.open)}" class="hr-p2" style="width:100%;text-align:left;padding:14px;border:1px solid var(--ln);border-radius:10px;background:var(--pn);box-shadow:var(--sh);min-height:var(--tap)">
          <span style="display:flex;gap:9px;align-items:center;flex-wrap:wrap">
            <span style="font:600 13px var(--fm);letter-spacing:.04em;color:var(--ac)">${esc(r.num)}</span>
            <span style="${r.stampStyle}">${esc(r.status)}</span>
            <span style="flex:1"></span>
            <span style="font:12px var(--fm);color:var(--ft)">${esc(r.due)}</span>
          </span>
          <span style="display:block;font:600 var(--fz)/1.35 var(--fd);margin-top:7px;text-wrap:pretty">${esc(r.title)}</span>
          ${r.sub ? `<span style="display:block;font-size:13.5px;color:var(--mu);margin-top:3px;text-wrap:pretty">${esc(r.sub)}</span>` : ""}
        </button>
      </li>`).join("")}
    </ul>`;
}

function uiFieldMoney(f) {
  return `<section aria-labelledby="money-heading" style="padding:16px 0 0">
      <h1 id="money-heading" style="margin:0;font:600 var(--h1)/1.2 var(--fd)">Job numbers</h1>
      <p style="margin:7px 0 0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">${esc(FIELD_COPY.moneyIntro)} ${esc(f.moneyAsOf)}</p>
    </section>
    <ul style="list-style:none;margin:16px 0 0;padding:0;display:flex;flex-direction:column;gap:10px">
      ${f.moneyRows.map((m) => `<li style="border:1px solid var(--ln);border-left:4px solid ${m.color};border-radius:0 10px 10px 0;background:var(--pn);box-shadow:var(--sh);padding:13px 14px">
        <p style="margin:0;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft)">${esc(m.label)}</p>
        <p style="margin:4px 0 0;font:600 24px var(--fd);font-variant-numeric:tabular-nums">${esc(m.value)}</p>
        <p style="margin:3px 0 0;font-size:13.5px;color:var(--mu)">${esc(m.note)}</p>
      </li>`).join("")}
    </ul>
    <p style="margin:14px 0 0;padding:13px 14px;border:1px solid var(--ln);border-radius:10px;background:var(--p2);font-size:13.5px;color:var(--mu);text-wrap:pretty">${esc(FIELD_COPY.moneyFoot)}</p>`;
}

function uiFieldThread(f) {
  if (!f.thread) return "";
  const t = f.thread;
  return `<div role="dialog" aria-modal="true" aria-labelledby="ft-title" style="position:fixed;inset:0;z-index:158;background:var(--bg);display:flex;flex-direction:column">
    <div style="flex:none;padding:12px 14px;border-bottom:1px solid var(--ln);background:var(--pn);display:flex;align-items:center;gap:10px">
      <div style="flex:1;min-width:0">
        <p style="margin:0 0 2px;font:600 10px var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ac)">${esc(t.eyebrow)}</p>
        <h2 id="ft-title" style="margin:0;font:600 15px/1.25 var(--fd);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.title)}</h2>
      </div>
      <button data-click="${H(t.close)}" data-ref="fthread" class="hb-ls" style="min-height:var(--tap);padding:9px 14px;border:1px solid var(--ln);border-radius:9px;font:600 13px var(--fd);color:var(--mu)">Close</button>
    </div>
    <div style="flex:1;min-height:0;overflow-y:auto;padding:14px">
      ${t.question ? `<p style="margin:0 0 12px;padding:13px 14px;border:1px solid var(--ln);border-radius:10px;background:var(--pn);font-size:var(--fzs);line-height:1.55;text-wrap:pretty">${esc(t.question)}</p>` : ""}
      <ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:12px">
        ${t.messages.map((m) => `<li style="border:1px solid ${m.mine ? "var(--ln)" : "var(--bp)"};border-radius:10px;background:${m.mine ? "var(--pn)" : "var(--bps)"};padding:12px 14px">
          <p style="margin:0;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap">
            <span style="font:600 13px var(--fd)">${esc(m.from)}</span>
            <span style="flex:1"></span>
            <span style="font:11.5px var(--fm);color:var(--ft)">${esc(m.when)}</span>
          </p>
          <p style="margin:7px 0 0;font-size:var(--fzs);line-height:1.55;text-wrap:pretty">${esc(m.body)}</p>
        </li>`).join("")}
      </ul>
      ${t.messages.length ? "" : `<p style="margin:0;padding:14px;border:1px dashed var(--ls);border-radius:10px;background:var(--p2);font-size:var(--fzs);color:var(--mu)">No replies yet.</p>`}
      ${t.answer ? `<div style="margin-top:14px;border:1px solid var(--ok);border-radius:10px;background:var(--oks);padding:13px 14px">
        <p style="margin:0 0 5px;font:600 11px var(--fm);letter-spacing:.12em;text-transform:uppercase;color:var(--ok)">The answer</p>
        <p style="margin:0;font-size:var(--fzs);line-height:1.55;text-wrap:pretty">${esc(t.answer)}</p>
      </div>` : ""}
    </div>
  </div>`;
}

function uiFieldMore(f) {
  if (!f.moreOpen) return "";
  return `<div style="position:fixed;inset:0;z-index:70;background:rgba(24,27,30,.5);display:flex;align-items:flex-end;justify-content:center">
    <div role="dialog" aria-modal="true" aria-labelledby="more-title" style="width:100%;max-width:520px;background:var(--pn);border-radius:14px 14px 0 0;box-shadow:var(--shp);animation:sheetup .18s ease-out;padding:14px var(--pad) calc(env(safe-area-inset-bottom,0px) + 16px)">
      <div style="display:flex;align-items:center;gap:10px">
        <h2 id="more-title" style="margin:0;flex:1;font:600 20px var(--fd)">Settings for this phone</h2>
        <button data-click="${H(f.closeMore)}" data-ref="fmore" class="hb-ls" style="min-height:var(--tap);padding:9px 13px;border:1px solid var(--ln);border-radius:8px;font:600 13px var(--fd);color:var(--mu)">Close</button>
      </div>
      <ul style="list-style:none;margin:14px 0 0;padding:0;display:flex;flex-direction:column;gap:10px">
        ${f.moreToggles.map((t) => `<li>
          <button data-click="${H(t.toggle)}" aria-pressed="${t.on ? "true" : "false"}" style="width:100%;display:flex;align-items:center;gap:12px;padding:13px 14px;border:1px solid ${t.on ? "var(--ac)" : "var(--ln)"};border-radius:10px;background:${t.on ? "var(--as)" : "var(--pn)"};text-align:left;min-height:var(--tap)">
            <span style="flex:1">
              <span style="display:block;font:600 var(--fz) var(--fd)">${esc(t.label)}</span>
              <span style="display:block;font-size:13.5px;color:var(--mu);margin-top:2px;text-wrap:pretty">${esc(t.hint)}</span>
            </span>
            <span style="font:600 11px var(--fm);letter-spacing:.08em;text-transform:uppercase;padding:5px 10px;border-radius:999px;${t.on ? "background:var(--ac);color:var(--acink)" : "background:var(--p2);color:var(--ft)"}">${t.on ? "On" : "Off"}</span>
          </button>
        </li>`).join("")}
        ${f.moreJobs.length > 1 ? `<li style="border:1px solid var(--ln);border-radius:10px;overflow:hidden">
          <p style="margin:0;padding:10px 14px;background:var(--p2);border-bottom:1px solid var(--ln);font:600 13px var(--fd)">Your jobs</p>
          ${f.moreJobs.map((j) => `<button data-click="${H(j.pick)}" aria-current="${j.on ? "true" : "false"}" class="hr-p2" style="width:100%;text-align:left;padding:11px 14px;border-bottom:1px solid var(--ln);font:600 14px var(--fd);${j.on ? "color:var(--ac)" : ""}">${esc(j.label)}</button>`).join("")}
        </li>` : ""}
        <li><button data-click="${H(f.signOut)}" class="hb-ls" style="width:100%;min-height:var(--tap);padding:12px;border:1px solid var(--ln);border-radius:10px;background:var(--pn);font:600 14px var(--fd);color:var(--mu)">Sign out</button></li>
      </ul>
      <p style="margin:14px 0 0;padding:12px 13px;border:1px solid var(--ln);border-radius:9px;background:var(--p2);font-size:13.5px;color:var(--mu);text-wrap:pretty">${esc(FIELD_COPY.install)}</p>
    </div>
  </div>`;
}

// ————— the field shell's state, handlers and view model —————————————————
Object.assign(App, {
  enterFieldShell() {
    const s = this.state;
    document.documentElement.dataset.shell = "field";
    try {
      const p = JSON.parse(localStorage.getItem("pwfield.prefs") || "{}");
      if (p.glove) document.documentElement.dataset.glove = "on";
      if (p.sun) document.documentElement.dataset.sun = "on";
    } catch (e) {}
    s.shell = "field";
    s.fieldTab = "today";
    s.recTab = "rfi";
    const jobs = (this._status || {}).field_jobs || [];
    let last = null;
    try { last = localStorage.getItem("pw.lastFieldJob"); } catch (e) {}
    s.job = jobs.includes(last) ? last : jobs[0];
    this.refresh("job", "lookahead", "documents", "records", "attention");
    setState({});
  },

  fieldGo: (tab) => () => setState({ fieldTab: tab, fieldThread: null }),
  fieldPickJob: (job) => () => {
    try { localStorage.setItem("pw.lastFieldJob", job); } catch (e) {}
    App.state.job = job;
    App.state.fieldMore = false;
    App.refresh("job", "lookahead", "documents", "records", "attention");
    setState({});
  },
  fieldToggle: (key) => () => {
    const el = document.documentElement;
    const on = el.dataset[key] === "on";
    if (on) delete el.dataset[key]; else el.dataset[key] = "on";
    try {
      const p = JSON.parse(localStorage.getItem("pwfield.prefs") || "{}");
      p[key] = !on;
      localStorage.setItem("pwfield.prefs", JSON.stringify(p));
    } catch (e) {}
    setState({});
  },

  async fieldOpenThread(recId) {
    setState({ fieldThread: { id: recId, loading: true } });
    try {
      const out = await api(`/api/records/${recId}`);
      setState({ fieldThread: { id: recId, data: out } }, focusRef("fthread"));
    } catch (err) {
      setState({ fieldThread: null, live: err.message });
    }
  },

  buildField() {
    const s = this.state;
    if (s.shell !== "field") return {};
    const d = s.data;
    const jd = d.job || {};
    const job = jd.job || {};
    const la = d.lookahead || {};
    const items = la.items || [];
    const areas = ((d.areas || {}).areas) || [];
    const areaOf = (id) => areas.find((a) => a.id === id) || { name: "No area", color: "var(--nt)", soft: "var(--nts)" };
    const softOf = (a) => a.soft || "var(--nts)";

    const today = new Date();
    const iso = today.getFullYear() + "-" + String(today.getMonth() + 1).padStart(2, "0") + "-" + String(today.getDate()).padStart(2, "0");
    const dayList = la.days || [];
    const todayIdx = dayList.indexOf(iso);

    // Blockers: the attention list, mapped onto the tabs this shell has.
    const attn = ((d.attention || {}).items) || [];
    const tabFor = { look: "look", docs: "docs", rfis: "recs", subs: "recs" };
    const blockers = attn.filter((a) => tabFor[a.page]).slice(0, 5).map((a) => ({
      kind: a.kind || a.tag || "Waiting", color: a.tone === "er" ? "var(--er)" : a.tone === "wn" ? "var(--wn)" : "var(--bp)",
      age: a.when || "", text: a.text || a.title || "", cta: a.cta || "Open it",
      go: () => setState({ fieldTab: tabFor[a.page], recTab: a.page === "subs" ? "submittal" : "rfi" }),
    }));

    const weekAria = (name) => "Days this week for " + name + ". Each day is a button; select it to mark it worked.";
    const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const weekStart = todayIdx >= 0 ? todayIdx - ((new Date(dayList[todayIdx] + "T12:00:00").getDay() + 6) % 7) : 0;
    const weekIdx = [];
    for (let i = 0; i < 7; i++) {
      const di = weekStart + i;
      if (di >= 0 && di < dayList.length) weekIdx.push(di);
    }

    const rowFor = (r) => {
      const bits = (r.days || "").padEnd(21, "0");
      const area = areaOf(r.work_area_id);
      const on = bits.split("").filter((x) => x === "1").length;
      const notes = [];
      if (r.requirements) notes.push({ tag: "Customer", text: r.requirements, color: "var(--bp)" });
      if (r.tools) notes.push({ tag: "Tools", text: r.tools, color: "var(--nt)" });
      if (r.material) notes.push({ tag: "Material", text: r.material, color: "var(--nt)" });
      if (r.notes) notes.push({ tag: "Ops", text: r.notes, color: "var(--nt)" });
      return { r, bits, area, on, notes };
    };

    const lookRows = items.map((raw) => {
      const { r, bits, area, on, notes } = rowFor(raw);
      return {
        name: r.description || "?", area: area.name,
        areaStyle: "font:600 11px var(--fm);letter-spacing:.07em;text-transform:uppercase;padding:4px 8px;border-radius:4px;white-space:nowrap;background:" + softOf(area) + ";color:" + (area.color || "var(--nt)"),
        count: on + (on === 1 ? " day" : " days"), notes,
        edit: App.openForm("look", { itemId: r.id, item: r }),
        groupLabel: weekAria(r.description || "this activity"),
        days: weekIdx.map((di) => {
          const dt = new Date(dayList[di] + "T12:00:00");
          return {
            dow: DOW[dt.getDay()], num: String(dt.getDate()),
            on: bits[di] === "1", color: area.color || "var(--ac)", soft: softOf(area),
            label: (bits[di] === "1" ? "Worked: " : "Not worked: ") + dayList[di],
            toggle: App.toggleTick(r.id, di),
          };
        }),
      };
    });

    const todayItems = todayIdx < 0 ? [] : items.map(rowFor)
      .filter(({ bits }) => bits[todayIdx] === "1" || false)
      .map(({ r, bits, area, on, notes }) => ({
        name: r.description || "?", area: area.name,
        areaStyle: "font:600 11px var(--fm);letter-spacing:.07em;text-transform:uppercase;padding:4px 8px;border-radius:4px;white-space:nowrap;background:" + softOf(area) + ";color:" + (area.color || "var(--nt)"),
        days: on + (on === 1 ? " day" : " days"),
        note: (notes[0] || {}).text || "",
        on: bits[todayIdx] === "1", color: area.color || "var(--ac)", soft: softOf(area),
        aria: "Mark " + (r.description || "this activity") + " worked today",
        toggle: App.toggleTick(r.id, todayIdx),
        open: App.openForm("look", { itemId: r.id, item: r }),
      }));

    const recs = ((d.records || {}).records) || [];
    const recKind = s.recTab || "rfi";
    const recRows = recs.filter((r) => r.kind === recKind).map((r) => ({
      num: r.number || "—", status: r.status || "Draft",
      stampStyle: stamp(STATUS_TONE[r.status] || "nt"),
      due: r.due_date ? "due " + usDate(r.due_date) : "",
      title: r.title || "?", sub: r.spec_section || "",
      open: () => App.fieldOpenThread(r.id),
    }));

    const docs = ((d.documents || {}).documents) || [];
    const docRows = docs.map((doc) => ({
      name: doc.name || "?",
      stamp: (doc.annotation_count || 0) > 0 ? (doc.annotation_count + " marked") : "Clean",
      stampStyle: stamp((doc.annotation_count || 0) > 0 ? "wn" : "ok"),
      pages: (doc.page_count || "?") + " pages",
      sub: (doc.uploaded_at ? usDate(doc.uploaded_at) : "") + (doc.uploaded_by ? " · " + doc.uploaded_by : ""),
      open: App.openViewer(doc.id, 1, "markup", {}),
    }));

    const est = job.current_estimate;
    const committed = ((jd.cost_types || []).reduce((t, r) => t + (r.open_committed || 0), 0)) + (jd.approved_no_po ? (jd.approved_no_po.total || 0) : 0);
    const moneyRows = [
      { label: "Current contract", value: money(job.current_contract), color: "var(--ls)",
        note: job.change_order_revenue ? "Includes " + money(job.change_order_revenue) + " of approved change orders" : "From the Vista extract" },
      { label: "Cost to date", value: money(job.actual_cost), color: "var(--ac)",
        note: est ? ((job.actual_cost || 0) / est * 100).toFixed(1) + " per cent of the " + money(est) + " estimate" : "" },
      { label: "Committed and open", value: money(committed), color: "var(--bp)",
        note: "Open purchase orders and approved subcontractor change orders" },
      { label: "Budget remaining", value: money(est !== null && est !== undefined ? est - (job.actual_cost || 0) : null), color: "var(--ok)",
        note: est ? (100 - (job.actual_cost || 0) / est * 100).toFixed(1) + " per cent left to spend" : "" },
    ];

    const net = s.net || {};
    const online = net.online !== undefined ? !!net.online : navigator.onLine !== false;
    const queued = (d.outbox || []).length;

    const thread = s.fieldThread ? (() => {
      const t = s.fieldThread;
      const rec = (t.data || {}).record || t.data || {};
      const replies = (t.data || {}).replies || rec.replies || [];
      const confirmed = replies.find((m) => m.confirmed);
      return {
        eyebrow: (rec.kind === "submittal" ? "Submittal " : "RFI ") + (rec.number || ""),
        title: rec.title || (t.loading ? "Loading…" : "?"),
        question: rec.question || rec.description || "",
        close: () => setState({ fieldThread: null }),
        messages: replies.map((m) => ({
          from: m.from_name || m.from_email || "?", when: m.received_at ? usDate(m.received_at) : "",
          body: m.body_text || m.body || "", mine: false,
        })),
        answer: confirmed ? (confirmed.body_text || confirmed.body || "") : "",
      };
    })() : null;

    const fieldJobs = (this._status || {}).field_jobs || [];
    const fabs = {
      today: { label: FIELD_COPY.fabQuestion, go: App.openForm("rfi") },
      recs: { label: FIELD_COPY.fabQuestion, go: App.openForm("rfi") },
      look: { label: FIELD_COPY.fabActivity, go: App.openForm("look") },
    };

    return { field: {
      jobNumber: s.job || "", jobName: job.job_name || (jd.meta || {}).job_name || "",
      tab: s.fieldTab || "today",
      connColor: online ? "var(--ok)" : "var(--wn)",
      connText: online ? FIELD_COPY.online : FIELD_COPY.offline + (queued ? " (" + queued + " waiting)" : ""),
      openMore: () => setState({ fieldMore: true }, focusRef("fmore")),
      closeMore: () => setState({ fieldMore: false }),
      moreOpen: !!s.fieldMore,
      moreToggles: [
        { label: FIELD_COPY.glove[0], hint: FIELD_COPY.glove[1], on: document.documentElement.dataset.glove === "on", toggle: App.fieldToggle("glove") },
        { label: FIELD_COPY.sun[0], hint: FIELD_COPY.sun[1], on: document.documentElement.dataset.sun === "on", toggle: App.fieldToggle("sun") },
      ],
      moreJobs: fieldJobs.map((j) => ({ label: "Job " + j, on: j === s.job, pick: App.fieldPickJob(j) })),
      signOut: () => App.signOut(),
      todayDate: today.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" }),
      todayDoneText: todayItems.filter((t) => t.on).length + " of " + todayItems.length + " ticked for today",
      blockers, todayItems,
      lookRange: dayList.length ? usDate(dayList[0]) + " – " + usDate(dayList[Math.min(dayList.length, (la.weeks || 2) * 7) - 1]) : "This period",
      openNewArea: App.openForm("area"),
      openShare: App.openShareWith({ "look-int": true }),
      areaChips: areas.map((a) => ({ name: a.name, color: a.color || "var(--nt)",
        count: items.filter((i) => i.work_area_id === a.id).length })),
      lookRows,
      docRows,
      recTabs: [
        { label: "RFIs", count: recs.filter((r) => r.kind === "rfi").length, on: recKind === "rfi", pick: () => setState({ recTab: "rfi" }) },
        { label: "Submittals", count: recs.filter((r) => r.kind === "submittal").length, on: recKind === "submittal", pick: () => setState({ recTab: "submittal" }) },
      ],
      recRows,
      moneyAsOf: jd.as_of ? "Figures come from the Vista extract of " + usDate(jd.as_of) + "." : "",
      moneyRows,
      thread,
      fab: fabs[s.fieldTab || "today"] || null,
      tabs: FIELD_TABS.map(([key, label]) => ({
        key, label, on: (s.fieldTab || "today") === key,
        current: (s.fieldTab || "today") === key ? "page" : "false",
        go: App.fieldGo(key),
        badge: key === "recs" ? (recs.filter((r) => r.status === "Draft").length || "") : "",
      })),
    } };
  },
});
