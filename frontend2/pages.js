// PlanWise 2.0 — page bodies. Markup from the prototype (lines 293–848),
// numbers from the live registers. Pages land phase by phase; a page that has
// not landed yet says so plainly rather than pretending.
"use strict";

function pageBody(page, v) {
  if (page === "dash") return pageDash(v);
  if (page === "setup") return pageSetup(v);
  if (page === "sched" && typeof pageSched === "function") return pageSched(v);
  if (page === "look" && typeof pageLook === "function") return pageLook(v);
  if (page === "brief" && typeof pageBrief === "function") return pageBrief(v);
  if (page === "docs" && typeof pageDocs === "function") return pageDocs(v);
  if (["brief", "sched", "look", "docs"].includes(page)) {
    return `<section style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh);padding:26px 20px">
      <p style="margin:0;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">This page is being rebuilt for 2.0 and lands in a later build phase. The 1.x page still works at <a href="/#/job/${esc(v.jobNumber)}">the current PlanWise</a>.</p>
    </section>`;
  }
  if (page === "pos" && typeof pagePos === "function") return pagePos(v);
  return "";   // register pages render through uiRegister
}

// ——— Dashboard (prototype lines 293–419) ————————————————————————————————
function pageDash(v) {
  return `<div style="display:flex;flex-direction:column;gap:16px">
    <section aria-labelledby="kpi-heading">
      <h2 id="kpi-heading" style="margin:0 0 10px;font:600 15px var(--fd);letter-spacing:.03em">Money at a glance</h2>
      <ul style="list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(152px,1fr));gap:10px">
        ${v.kpis.map((k) => `<li style="${k.cardStyle}">
          <span aria-hidden="true" style="${k.edge}"></span>
          <span style="display:block;font:500 var(--lbl) var(--fm);letter-spacing:.1em;text-transform:uppercase;color:var(--ft);line-height:1.3;text-wrap:balance">${esc(k.label)}</span>
          <span style="display:block;font:600 21px/1.2 var(--fd);font-variant-numeric:tabular-nums;margin-top:4px">${esc(k.value)}</span>
          <span style="flex:1"></span>
          <span role="img" aria-label="${esc(k.barAria)}" style="display:block;height:6px;border-radius:3px;background:var(--ln);margin-top:8px;overflow:hidden">
            <span style="display:flex;height:100%;width:100%">
              ${k.segments.map((sg) => `<span style="${sg.style}"></span>`).join("")}
            </span>
          </span>
          <span style="display:block;font:500 11px var(--fm);color:${k.noteColor};margin-top:6px;line-height:1.3">${esc(k.note)}</span>
          <span style="display:flex;gap:4px;flex-direction:column;margin-top:5px">
            ${k.legend.map((lg) => `<span style="display:inline-flex;align-items:center;gap:5px;font:500 9.5px var(--fm);letter-spacing:.04em;text-transform:uppercase;color:var(--ft);white-space:nowrap">
              <span aria-hidden="true" style="width:9px;height:3px;border-radius:2px;flex:none;background:${lg.color}"></span>${esc(lg.label)}
            </span>`).join("")}
          </span>
        </li>`).join("")}
      </ul>
    </section>

    <div style="display:grid;grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);gap:14px">
      <section aria-labelledby="forecast-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh)">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid var(--ln);flex-wrap:wrap">
          <h2 id="forecast-heading" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Cost forecast to completion</h2>
          <ul style="list-style:none;margin:0;padding:0;display:flex;gap:12px;font:500 10.5px var(--fm);letter-spacing:.07em;text-transform:uppercase;color:var(--mu)">
            <li style="display:inline-flex;align-items:center;gap:5px"><span aria-hidden="true" style="width:16px;height:3px;background:var(--ac);display:inline-block"></span>Actual</li>
            <li style="display:inline-flex;align-items:center;gap:5px"><span aria-hidden="true" style="width:16px;height:3px;background:var(--ac);opacity:.45;display:inline-block"></span>Forecast</li>
            <li style="display:inline-flex;align-items:center;gap:5px"><span aria-hidden="true" style="width:16px;height:3px;background:var(--ls);display:inline-block"></span>Estimate</li>
          </ul>
        </div>
        <div style="padding:16px 16px 10px">
          ${v.forecastSvg}
        </div>
        <dl style="margin:0;display:flex;border-top:1px solid var(--ln)">
          <div style="flex:1;padding:11px 16px;border-right:1px solid var(--ln)">
            <dt style="font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft)">Projected at completion</dt>
            <dd style="margin:3px 0 0;font:600 17px var(--fd);font-variant-numeric:tabular-nums">${esc(v.fcProjected)}</dd>
          </div>
          <div style="flex:1;padding:11px 16px;border-right:1px solid var(--ln)">
            <dt style="font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft)">Against estimate</dt>
            <dd style="margin:3px 0 0;font:600 17px var(--fd);font-variant-numeric:tabular-nums;color:${v.fcAgainstColor}">${esc(v.fcAgainst)}</dd>
          </div>
          <div style="flex:1;padding:11px 16px">
            <dt style="font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft)">Cost this month</dt>
            <dd style="margin:3px 0 0;font:600 17px var(--fd);font-variant-numeric:tabular-nums">${esc(v.fcBurn)}</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="health-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh)">
        <div style="padding:12px 16px;border-bottom:1px solid var(--ln)"><h2 id="health-heading" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Job health</h2></div>
        <div style="padding:14px 16px">
          <dl style="margin:0">
            ${v.health.map((h) => `<div style="display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--ln)">
              <span aria-hidden="true" style="width:8px;height:8px;border-radius:50%;background:${h.color};box-shadow:0 0 0 3px ${h.soft};flex:none"></span>
              <dt style="flex:1;font-size:var(--fz)">${esc(h.label)}</dt>
              <dd style="margin:0;font:600 11.5px var(--fm);color:${h.color};letter-spacing:.04em;text-transform:uppercase">${esc(h.state)}</dd>
            </div>`).join("")}
          </dl>
          <p style="margin:12px 0 0;padding:11px 13px;border-radius:6px;background:var(--p2);border:1px solid var(--ln);border-left:3px solid var(--ac);font-size:var(--fzs);color:var(--mu);text-wrap:pretty">Start with the items in <b style="color:var(--ink)">Needs attention</b>. Every page carries one orange action — that is the next move on it.</p>
        </div>
      </section>
    </div>

    <section aria-labelledby="cost-type-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh);overflow-x:auto">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid var(--ln);flex-wrap:wrap">
        <h2 id="cost-type-heading" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Cost by type</h2>
        <p style="margin:0;font:500 10.5px var(--fm);letter-spacing:.07em;text-transform:uppercase;color:var(--ft)">${esc(v.vistaSourceLine)}</p>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:var(--fz)">
        <caption class="sr">Estimate, actual cost to date, share of estimate spent and variance for each cost type on job ${esc(v.jobNumber)}.</caption>
        <thead><tr>
          <th scope="col" style="text-align:left;padding:10px 16px;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln)">Cost type</th>
          <th scope="col" style="text-align:right;padding:10px 16px;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln)">Estimate</th>
          <th scope="col" style="text-align:right;padding:10px 16px;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln)">Actual to date</th>
          <th scope="col" style="text-align:left;padding:10px 16px;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln);width:180px">Spent of estimate</th>
          <th scope="col" style="text-align:right;padding:10px 16px;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ln)">Variance</th>
        </tr></thead>
        <tbody>
          ${v.costRows.map((cr) => `<tr class="hr-p2">
            <th scope="row" style="text-align:left;font-weight:500;padding:var(--cellY) 16px;border-bottom:1px solid var(--ln)">${esc(cr.type)}</th>
            <td style="padding:var(--cellY) 16px;border-bottom:1px solid var(--ln);text-align:right;font-variant-numeric:tabular-nums">${esc(cr.est)}</td>
            <td style="padding:var(--cellY) 16px;border-bottom:1px solid var(--ln);text-align:right;font-variant-numeric:tabular-nums">${esc(cr.act)}</td>
            <td style="padding:var(--cellY) 16px;border-bottom:1px solid var(--ln)">
              <span style="display:flex;align-items:center;gap:9px">
                <span aria-hidden="true" style="height:6px;border-radius:3px;background:var(--ln);flex:1;overflow:hidden"><span style="display:block;height:100%;width:${cr.barW};background:${cr.barColor};border-radius:3px"></span></span>
                <span style="font:500 11.5px var(--fm);color:var(--mu);min-width:42px;text-align:right">${esc(cr.pct)}</span>
              </span>
            </td>
            <td style="padding:var(--cellY) 16px;border-bottom:1px solid var(--ln);text-align:right;font-variant-numeric:tabular-nums;color:${cr.varColor}">${esc(cr.vari)}</td>
          </tr>`).join("")}
        </tbody>
        <tfoot><tr style="background:var(--p2)">
          <th scope="row" style="text-align:left;padding:12px 16px;font:600 var(--fz) var(--fd);border-top:1px solid var(--ls)">All cost types</th>
          <td style="padding:12px 16px;text-align:right;font:600 var(--fz) var(--fd);font-variant-numeric:tabular-nums;border-top:1px solid var(--ls)">${esc(v.costTotEst)}</td>
          <td style="padding:12px 16px;text-align:right;font:600 var(--fz) var(--fd);font-variant-numeric:tabular-nums;border-top:1px solid var(--ls)">${esc(v.costTotAct)}</td>
          <td style="padding:12px 16px;border-top:1px solid var(--ls);font:500 11.5px var(--fm);color:var(--mu)">${esc(v.costTotPct)}</td>
          <td style="padding:12px 16px;text-align:right;font:600 var(--fz) var(--fd);font-variant-numeric:tabular-nums;color:${v.costTotVarColor};border-top:1px solid var(--ls)">${esc(v.costTotVar)}</td>
        </tr></tfoot>
      </table>
    </section>
  </div>`;
}

// ——— Job setup (prototype lines 763–848) ————————————————————————————————
function pageSetup(v) {
  return `<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:start">
    <section aria-labelledby="vista-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh)">
      <div style="padding:12px 16px;border-bottom:1px solid var(--ln);display:flex;align-items:center;gap:9px;flex-wrap:wrap">
        <h2 id="vista-heading" style="margin:0;font:600 15px var(--fd)">Contract facts</h2>
        <span style="font:500 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;padding:4px 9px;border-radius:4px;background:var(--nts);color:var(--nt)">Read only · from Vista</span>
      </div>
      <dl style="margin:0">
        ${v.vistaRows.map((r) => `<div style="display:flex;gap:14px;align-items:baseline;padding:10px 16px;border-bottom:1px solid var(--ln)">
          <dt style="flex:0 0 44%;font-size:var(--fzs);color:var(--mu)">${esc(r.label)}</dt>
          <dd style="margin:0;flex:1;padding:5px 9px;border:1px dashed var(--ls);border-radius:5px;background:var(--p2);font-size:var(--fzs);${r.style || ""}">${esc(r.value)}</dd>
        </div>`).join("")}
      </dl>
      <p style="margin:0;padding:11px 16px;font-size:12px;color:var(--ft);text-wrap:pretty">Dashed fields come from Vista and are corrected there. A change here would put PlanWise and Vista out of step, so PlanWise does not allow it.</p>
    </section>

    <div style="display:flex;flex-direction:column;gap:14px">
      <section aria-labelledby="pm-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh)">
        <div style="padding:12px 16px;border-bottom:1px solid var(--ln);display:flex;align-items:center;gap:9px;flex-wrap:wrap">
          <h2 id="pm-heading" style="margin:0;font:600 15px var(--fd)">Compliance and personnel</h2>
          <span style="font:500 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;padding:4px 9px;border-radius:4px;background:var(--as);color:var(--ac)">Yours to keep current</span>
        </div>
        <div style="padding:13px 16px;display:grid;grid-template-columns:1fr 1fr;gap:13px">
          ${v.pmFields.map((p) => `<div>
            <label for="${p.id}" style="display:flex;align-items:center;gap:7px;font:600 11.5px var(--fd);letter-spacing:.03em;margin-bottom:5px">${esc(p.label)}<span style="${p.savedStyle}">${esc(p.savedText)}</span></label>
            ${p.isSelect ? `<select id="${p.id}" data-change="${H(p.set)}" style="${p.control}">
              ${p.options.map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(p.value) ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
            </select>` : `<input id="${p.id}" type="text" value="${esc(p.value)}" data-change="${H(p.set)}" class="fu" style="${p.control}">`}
          </div>`).join("")}
        </div>
        <p style="margin:0;padding:0 16px 13px;font-size:12px;color:var(--ft);text-wrap:pretty">Solid underlines are yours. Each one saves the moment you change it and says so beside its label.</p>
      </section>

      <section aria-labelledby="contact-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh)">
        <div style="padding:12px 16px;border-bottom:1px solid var(--ln);display:flex;align-items:center;gap:10px">
          <h2 id="contact-heading" style="margin:0;flex:1;font:600 15px var(--fd)">Job contacts</h2>
          <p style="margin:0;font:11.5px var(--fm);color:var(--ft)">${esc(v.contactCount)}</p>
        </div>
        <ul style="list-style:none;margin:0;padding:0">
          ${v.contactRows.map((c) => `<li style="display:flex;gap:12px;align-items:flex-start;padding:13px 16px;border-bottom:1px solid var(--ln)">
            <div style="flex:1;min-width:0">
              <p style="margin:0;font:600 var(--fz) var(--fd)">${esc(c.name)}</p>
              <p style="margin:2px 0 0;font-size:12.5px;color:var(--mu)">${esc(c.role)}</p>
              <p style="margin:4px 0 0;font:11.5px var(--fm);color:var(--mu)">${esc(c.phone)}${c.email ? " · " : ""}<a href="mailto:${esc(c.email)}">${esc(c.email)}</a></p>
            </div>
            <button data-click="${H(c.remove)}" class="hb-er" style="min-height:var(--tap);padding:7px 12px;border:1px solid var(--ln);border-radius:6px;font:600 11.5px var(--fd);color:var(--mu);white-space:nowrap">Remove ${esc(c.name)}</button>
          </li>`).join("")}
        </ul>
        ${v.noContacts ? `<p style="margin:0;padding:20px 16px;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">No contacts on this job yet. Change orders, RFIs and submittals need an address to go to — add the owner's representative first.</p>` : ""}
      </section>
    </div>
  </div>`;
}

// ——— Page view models (dashboard KPIs, health, forecast, setup) ————————————
function buildPageVals(app) {
  const s = app.state;
  const d = s.data;
  const jd = d.job || {};
  const job = jd.job || {};
  const ar = jd.contract_ar || {};
  const out = {
    vistaSourceLine: jd.as_of ? "Source: Vista, as of " + usDate(jd.as_of) : "Vista extract pending",
    kpis: [], health: [], costRows: [],
    costTotEst: "", costTotAct: "", costTotPct: "", costTotVar: "", costTotVarColor: "var(--ok)",
    forecastSvg: "", fcProjected: "", fcAgainst: "", fcAgainstColor: "var(--ok)", fcBurn: "",
    vistaRows: [], pmFields: [], contactRows: [], contactCount: "", noContacts: false,
  };
  if (s.page === "dash") {
    const seg = (w, color, last) => ({ style: "display:block;height:100%;width:" + w + "%;background:" + color + (last ? "" : ";border-right:1.5px solid var(--pn)") });
    const one = (pct, color) => [seg(Math.min(100, Math.max(0, pct || 0)).toFixed(1), color, true)];
    const card = () => "background:var(--pn);border:1px solid var(--ln);border-radius:8px;padding:11px 12px 10px;position:relative;overflow:hidden;box-shadow:var(--sh);min-width:0;display:flex;flex-direction:column";
    const orig = job.original_contract, co = job.change_order_revenue, cur = job.current_contract;
    const est = job.current_estimate, act = job.actual_cost;
    const billedPct = cur ? (job.actual_billed || 0) / cur * 100 : 0;
    const spentPct = est ? (act || 0) / est * 100 : 0;
    const remaining = est !== null && est !== undefined && act !== null && act !== undefined ? est - act : null;
    out.kpis = [
      { label: "Current contract", value: money(cur), note: co ? "+" + money(co) + " in COs" : "No approved COs yet", noteColor: co ? "var(--ac)" : "var(--mu)", cardStyle: card(),
        edge: "position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--nt)",
        segments: cur ? [seg(((orig || 0) / cur * 100).toFixed(1), "var(--nt)"), seg(((co || 0) / cur * 100).toFixed(1), "var(--ac)", true)] : one(0, "var(--nt)"),
        barAria: "Original contract " + money(orig) + " plus " + money(co) + " of approved change orders.",
        legend: [{ label: "Original", color: "var(--nt)" }, { label: "Approved COs", color: "var(--ac)" }] },
      { label: "Billed to date", value: money(job.actual_billed), note: billedPct.toFixed(1) + "% billed", noteColor: "var(--mu)", cardStyle: card(),
        edge: "position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--bp)",
        segments: one(billedPct, "var(--bp)"), barAria: billedPct.toFixed(1) + " per cent billed.", legend: [] },
      { label: "Cost to date", value: money(act), note: spentPct.toFixed(1) + "% spent", noteColor: "var(--mu)", cardStyle: card(),
        edge: "position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--vi)",
        segments: one(spentPct, "var(--vi)"), barAria: spentPct.toFixed(1) + " per cent of the estimate spent.", legend: [] },
      { label: "Budget remaining", value: money(remaining), note: est ? (100 - spentPct).toFixed(1) + "% of the estimate left" : "No estimate reported", noteColor: remaining !== null && remaining < 0 ? "var(--er)" : "var(--ok)", cardStyle: card(),
        edge: "position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--ok)",
        segments: one(100 - spentPct, "var(--ok)"), barAria: (100 - spentPct).toFixed(1) + " per cent of the budget remaining.", legend: [] },
      { label: "Payables awaiting approval", value: money(job.unapproved_ap), note: "From the Vista extract", noteColor: "var(--wn)", cardStyle: card(),
        edge: "position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--wn)",
        segments: one(job.unapproved_ap && act ? job.unapproved_ap / act * 100 : 0, "var(--wn)"), barAria: money(job.unapproved_ap) + " of payables awaiting approval.", legend: [] },
    ];

    const cts = jd.cost_types || [];
    const totVar = cts.reduce((t, r) => t + (r.variance || 0), 0);
    const unc = (jd.approved_no_po || {}).cos || [];
    const attn = (d.attention || {}).items || [];
    const coOpen = attn.filter((i) => i.page === "cos").length;
    const sd = d.schedule || {};
    out.health = [
      { label: "Cost against estimate", state: totVar < 0 ? "Watch" : "Healthy", color: totVar < 0 ? "var(--wn)" : "var(--ok)", soft: totVar < 0 ? "var(--wns)" : "var(--oks)" },
      { label: "Billing against cost", state: (job.actual_billed || 0) >= (act || 0) ? "Healthy" : "Behind cost", color: (job.actual_billed || 0) >= (act || 0) ? "var(--ok)" : "var(--wn)", soft: (job.actual_billed || 0) >= (act || 0) ? "var(--oks)" : "var(--wns)" },
      { label: "Change orders", state: coOpen ? coOpen + " unsent" : "All sent", color: coOpen ? "var(--wn)" : "var(--ok)", soft: coOpen ? "var(--wns)" : "var(--oks)" },
      { label: "Commitments", state: unc.length ? unc.length + " without a PO" : "All covered", color: unc.length ? "var(--er)" : "var(--ok)", soft: unc.length ? "var(--ers)" : "var(--oks)" },
      { label: "Schedule float", state: (sd.tasks || []).length === 0 ? "No schedule yet" : (sd.critical_count || 0) + " on the critical path", color: (sd.tasks || []).length === 0 ? "var(--nt)" : sd.critical_count ? "var(--er)" : "var(--ok)", soft: (sd.tasks || []).length === 0 ? "var(--nts)" : sd.critical_count ? "var(--ers)" : "var(--oks)" },
    ];

    out.costRows = cts.map((r) => {
      const spent = r.current_estimate ? (r.actual_cost || 0) / r.current_estimate : null;
      const over = (r.variance || 0) < 0;
      return {
        type: r.cost_type, est: money(r.current_estimate), act: money(r.actual_cost),
        vari: signed(r.variance), varColor: over ? "var(--er)" : "var(--ok)",
        pct: spent === null ? "—" : (spent * 100).toFixed(1) + "%",
        barW: spent === null ? "0%" : Math.min(100, spent * 100).toFixed(0) + "%",
        barColor: spent !== null && spent > 0.95 ? "var(--er)" : over ? "var(--wn)" : "var(--bp)",
      };
    });
    const tEst = cts.reduce((t, r) => t + (r.current_estimate || 0), 0);
    const tAct = cts.reduce((t, r) => t + (r.actual_cost || 0), 0);
    out.costTotEst = money(tEst); out.costTotAct = money(tAct);
    out.costTotPct = tEst ? (tAct / tEst * 100).toFixed(1) + "% spent" : "";
    out.costTotVar = signed(tEst - tAct === 0 ? 0 : cts.reduce((t, r) => t + (r.variance || 0), 0));
    out.costTotVarColor = cts.reduce((t, r) => t + (r.variance || 0), 0) < 0 ? "var(--er)" : "var(--ok)";

    // Forecast: REAL history only (vista_history accrues per extract). Two
    // points make a line; fewer make an honest empty state, never a curve.
    const hist = ((d.history || {}).history) || [];
    out.fcProjected = money(job.projected_cost);
    const against = est !== null && est !== undefined && job.projected_cost !== null && job.projected_cost !== undefined ? est - job.projected_cost : null;
    out.fcAgainst = signed(against);
    out.fcAgainstColor = against !== null && against < 0 ? "var(--er)" : "var(--ok)";
    out.fcBurn = money(job.mtd_cost);
    if (hist.length >= 2) {
      const xs = hist.map((h) => new Date(h.as_of).getTime());
      const ys = hist.map((h) => h.actual_cost || 0);
      const x0 = Math.min(...xs), x1 = Math.max(...xs);
      const top = Math.max(job.projected_cost || 0, est || 0, ...ys) || 1;
      const px = (x) => x1 === x0 ? 0 : ((x - x0) / (x1 - x0) * 560).toFixed(1);
      const py = (yv) => (165 - yv / top * 155).toFixed(1);
      const pts = hist.map((h) => px(new Date(h.as_of).getTime()) + "," + py(h.actual_cost || 0)).join(" L");
      const lastX = px(x1), lastY = py(ys[ys.length - 1]);
      out.forecastSvg = `<svg viewBox="0 0 660 200" role="img" aria-label="Cost curve from the accrued Vista extracts. The forecast reaches ${money(job.projected_cost)} at completion." style="width:100%;height:auto;display:block;overflow:visible">
        <g stroke="var(--ln)" stroke-width="1"><line x1="0" y1="10" x2="640" y2="10"></line><line x1="0" y1="60" x2="640" y2="60"></line><line x1="0" y1="110" x2="640" y2="110"></line><line x1="0" y1="160" x2="640" y2="160"></line></g>
        ${est ? `<line x1="0" y1="165" x2="639" y2="${py(est)}" stroke="var(--ls)" stroke-width="1.5" stroke-dasharray="5 4"></line>` : ""}
        <path d="M${pts}" fill="none" stroke="var(--ac)" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"></path>
        ${job.projected_cost ? `<path d="M${lastX},${lastY} L639,${py(job.projected_cost)}" fill="none" stroke="var(--ac)" stroke-width="2.2" stroke-dasharray="4 4" opacity=".55" stroke-linecap="round"></path>` : ""}
        <circle cx="${lastX}" cy="${lastY}" r="4.5" fill="var(--pn)" stroke="var(--ac)" stroke-width="2.6"></circle>
        <line x1="${lastX}" y1="0" x2="${lastX}" y2="168" stroke="var(--ac)" stroke-width="1" opacity=".3"></line>
        <text x="${Number(lastX) + 4}" y="12" font-family="var(--fm)" font-size="10" fill="var(--ac)" letter-spacing="1">LATEST</text>
        <g font-family="var(--fm)" font-size="10" fill="var(--ft)" letter-spacing="0.8">
          <text x="0" y="182">${esc(usDate(hist[0].as_of).toUpperCase())}</text>
          <text x="500" y="182">${esc(usDate(hist[hist.length - 1].as_of).toUpperCase())}</text>
          <text x="644" y="14">${esc(money(top))}</text><text x="644" y="164">$0</text>
        </g>
      </svg>`;
    } else {
      out.forecastSvg = `<div style="min-height:180px;display:grid;place-items:center;border:1px dashed var(--ls);border-radius:6px;background:var(--p2)">
        <p style="margin:0;max-width:44ch;text-align:center;font-size:var(--fzs);color:var(--mu);text-wrap:pretty">The curve draws itself from the nightly Vista extracts. ${hist.length === 1 ? "One extract has landed — one more and the line appears." : "History starts accruing with the next extract; nothing here is invented."}</p>
      </div>`;
    }
  }

  if (s.page === "setup") {
    const meta = jd.meta || {};
    out.vistaRows = [
      { label: "Job number", value: job.job_number || s.job || "" },
      { label: "Project name", value: job.job_name || "not reported" },
      { label: "Customer status", value: job.financial_status || "not reported" },
      { label: "Job status", value: job.job_status || "not reported" },
      { label: "Contract type", value: job.contract_type || "not reported" },
      { label: "Original contract", value: money(job.original_contract), style: "font-variant-numeric:tabular-nums" },
      { label: "Change order revenue", value: money(job.change_order_revenue), style: "font-variant-numeric:tabular-nums" },
      { label: "Current contract", value: money(job.current_contract), style: "font-variant-numeric:tabular-nums;font-weight:600" },
      { label: "Billed to date", value: money(job.actual_billed), style: "font-variant-numeric:tabular-nums" },
      { label: "Collected to date", value: money(ar.collected), style: "font-variant-numeric:tabular-nums" },
      { label: "Retainage balance", value: money(ar.retainage), style: "font-variant-numeric:tabular-nums" },
      { label: "Size band", value: job.size_band || "not reported" },
    ];
    // Meta keys match 1.x exactly, so PM-entered data carries straight over.
    const pmOpt = [["", "—"], ["Yes", "Yes"], ["No", "No"], ["N/A", "Not applicable"]];
    const pmDefs = [
      ["bond_required", "Bond required", "select", pmOpt],
      ["insurance_cert", "Insurance cert", "select", pmOpt],
      ["certified_payroll", "Certified payroll", "select", pmOpt],
      ["pla_davis_bacon", "PLA / Davis-Bacon", "select", pmOpt],
      ["project_manager", "Project manager", "text"],
      ["superintendent", "Superintendent", "text"],
      ["field_leader", "Field lead", "text"],
      ["estimator", "Estimator", "text"],
    ];
    out.pmFields = pmDefs.map(([key, label, type, options]) => {
      const saved = App._savedKey === key;
      return {
        id: "pm-" + key, label, value: meta[key] || "", set: App.setMeta(key, label),
        isSelect: type === "select",
        options: (options || []).map(([value, l]) => ({ value, label: l })),
        savedText: saved ? "Saved" : "",
        savedStyle: "font:600 9.5px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:var(--ok);opacity:" + (saved ? "1" : "0"),
        control: "width:100%;min-height:var(--tap);padding:7px 10px;border:1px solid var(--ln);border-bottom:2px solid " + (saved ? "var(--ok)" : "var(--ac)") + ";border-radius:6px 6px 0 0;background:var(--p2);font-size:var(--fzs)",
      };
    });
    const contacts = meta.contacts || [];
    out.contactRows = contacts.map((c, i) => ({ name: c.name || "", role: c.role || "", phone: c.phone || "", email: c.email || "", remove: App.removeContact(i) }));
    out.contactCount = contacts.length + (contacts.length === 1 ? " contact" : " contacts");
    out.noContacts = contacts.length === 0;
  }
  return out;
}

// ——— Schedule (prototype lines 422–513; server engine behind it) ————————————
function pageSched(v) {
  if (v.staged) {
    const c = v.staged.counts || {};
    return `<section aria-labelledby="staged-heading" style="background:var(--pn);border:1px solid var(--ac);border-radius:8px;box-shadow:var(--sh);margin-bottom:14px">
      <div style="padding:12px 16px;border-bottom:1px solid var(--ln);display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <h2 id="staged-heading" style="margin:0;flex:1;font:600 15px var(--fd)">A schedule import is waiting for review</h2>
        <p style="margin:0;font:11.5px var(--fm);color:var(--ft)">${esc(String(c.tasks ?? "?"))} tasks · ${esc(String(c.links ?? 0))} proposed links · nothing lands until you commit</p>
      </div>
      ${(v.staged.warnings || []).map((w) => `<p style="margin:0;padding:9px 16px;border-bottom:1px solid var(--ln);background:var(--wns);color:var(--wn);font-size:var(--fzs);text-wrap:pretty">${esc(w)}</p>`).join("")}
      ${(v.staged.links || []).length ? `<div style="padding:12px 16px;border-bottom:1px solid var(--ln)">
        <div style="display:flex;gap:9px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
          <h3 style="margin:0;flex:1;font:600 13px var(--fd)">Inferred dependencies — tick the ones to keep</h3>
          <button data-click="${H(v.staged.tickAll(true))}" class="hb-ls" style="min-height:30px;padding:4px 10px;border:1px solid var(--ln);border-radius:5px;font:600 11.5px var(--fd)">Tick all</button>
          <button data-click="${H(v.staged.tickAll(false))}" class="hb-ls" style="min-height:30px;padding:4px 10px;border:1px solid var(--ln);border-radius:5px;font:600 11.5px var(--fd)">Untick all</button>
        </div>
        <ul style="list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:6px">
          ${v.staged.links.map((l) => `<li style="display:flex;gap:9px;align-items:center;padding:7px 9px;border:1px solid var(--ln);border-radius:6px;background:${l.on ? "var(--as)" : "var(--p3)"}">
            <input type="checkbox" ${l.on ? "checked" : ""} data-change="${H(l.toggle)}" style="width:17px;height:17px;accent-color:var(--ac);flex:none">
            <span style="flex:1;font-size:12px">${esc(l.pred_name || l.pred_id)} → ${esc(l.succ_name || l.succ_id)} <span style="font-family:var(--fm);color:var(--ft)">(${esc(l.link_type || "FS")}${l.confidence ? " · " + Math.round(l.confidence * 100) + "%" : ""})</span></span>
          </li>`).join("")}
        </ul>
      </div>` : ""}
      <div style="display:flex;gap:9px;align-items:center;padding:12px 16px;background:var(--p2);flex-wrap:wrap">
        <p style="margin:0;flex:1;font-size:12px;color:var(--mu);text-wrap:pretty">Committing replaces this job's imported tasks and keeps every task added by hand. Links land only where ticked — an inferred dependency never drives dates silently.</p>
        <button data-click="${H(v.staged.discard)}" class="hb-ls" style="min-height:var(--tap);padding:9px 15px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 13px var(--fd)">Discard the import</button>
        <button data-click="${H(v.staged.commit)}" class="hb-ah" style="min-height:var(--tap);padding:9px 17px;border:1px solid var(--ac);border-radius:6px;background:var(--ac);color:var(--acink);font:600 13px var(--fd);letter-spacing:.03em;box-shadow:0 0 0 3px var(--as)">Commit the import</button>
      </div>
    </section>`;
  }
  if (v.schedEmpty) {
    return `<section style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh);padding:34px 20px;text-align:center">
      <p style="margin:0 auto;max-width:52ch;font-size:var(--fz);color:var(--mu);text-wrap:pretty">No schedule on this job yet. Import the customer's file — .mpp, MS Project XML, a flattened PDF print, Excel or CSV — or add the first task by hand.</p>
      <div style="display:flex;gap:9px;justify-content:center;margin-top:16px;flex-wrap:wrap">
        <button data-click="${H(v.triggerSchedImport)}" class="hb-ah" style="${btn("primary")}">Import a schedule</button>
        <button data-click="${H(v.openNewTask)}" class="hb-ls" style="${btn("ghost")}">Add a task</button>
      </div>
      ${v.mppNote ? `<p style="margin:14px 0 0;font-size:12px;color:var(--ft)">${esc(v.mppNote)}</p>` : ""}
    </section>`;
  }
  return `<section aria-labelledby="gantt-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh);margin-bottom:14px">
    <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--ln);flex-wrap:wrap">
      <h2 id="gantt-heading" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Gantt chart</h2>
      <p style="margin:0;font:500 10.5px var(--fm);letter-spacing:.07em;text-transform:uppercase;color:var(--ft)">${esc(v.ganttRange)}</p>
      <span style="flex:1"></span>
      <ul style="list-style:none;margin:0;padding:0;display:flex;gap:12px;font:500 10.5px var(--fm);letter-spacing:.06em;text-transform:uppercase;color:var(--mu);flex-wrap:wrap">
        <li style="display:inline-flex;align-items:center;gap:5px"><span aria-hidden="true" style="width:14px;height:9px;border-radius:2px;border:2px solid var(--ink);display:inline-block"></span>Critical path</li>
        <li style="display:inline-flex;align-items:center;gap:5px"><span aria-hidden="true" style="width:14px;height:9px;border-radius:2px;border:1px solid var(--ls);display:inline-block"></span>Has float</li>
        <li style="display:inline-flex;align-items:center;gap:5px"><span aria-hidden="true" style="width:14px;height:9px;border-radius:2px;background:linear-gradient(90deg,var(--ls) 60%,transparent 60%);display:inline-block"></span>Filled to percent complete</li>
      </ul>
      <span role="group" aria-label="Zoom the time axis" style="display:inline-flex;gap:4px;align-items:center">
        <button data-click="${H(v.schedZoomOut)}" aria-label="Zoom out" class="hb-ac" style="min-height:30px;min-width:30px;border:1px solid var(--ln);border-radius:5px;color:var(--mu);font:600 14px var(--fm)">−</button>
        <button data-click="${H(v.schedZoomReset)}" aria-label="Reset zoom" class="hb-ac" style="min-height:30px;padding:0 8px;border:1px solid var(--ln);border-radius:5px;color:var(--mu);font:600 11px var(--fm)">${esc(v.schedZoomLabel)}</button>
        <button data-click="${H(v.schedZoomIn)}" aria-label="Zoom in" class="hb-ac" style="min-height:30px;min-width:30px;border:1px solid var(--ln);border-radius:5px;color:var(--mu);font:600 14px var(--fm)">+</button>
      </span>
      <button data-click="${H(v.triggerSchedImport)}" class="hb-ls" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12.5px var(--fd)">Import an updated schedule</button>
      <button data-click="${H(v.openNewTask)}" class="hb-fill" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ac);border-radius:6px;background:var(--as);color:var(--ac);font:600 12.5px var(--fd)">Add a task</button>
    </div>
    <div style="overflow-x:auto;padding:0 0 6px">
      <div style="min-width:${v.ganttMinWidth}px">
        <div style="display:grid;grid-template-columns:280px minmax(0,1fr);border-bottom:1px solid var(--ln);position:sticky;top:0;background:var(--pn);z-index:1">
          <p style="margin:0;padding:8px 16px;font:500 var(--lbl) var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--ft)">Task</p>
          <div style="display:flex;position:relative;padding:8px 16px 8px 0">
            ${v.ganttMonths.map((m) => `<span style="${m.style}">${esc(m.label)}</span>`).join("")}
          </div>
        </div>
        <ul style="list-style:none;margin:0;padding:0">
          ${v.ganttRows.map((g) => `<li data-sched-row="${g.idx}" style="${g.rowStyle}">
            <div class="hr-p2" style="display:grid;grid-template-columns:280px minmax(0,1fr);align-items:center">
              <div style="padding:5px 6px 5px 8px;min-width:0;display:flex;gap:6px;align-items:center">
                <span data-pointerdown="${H(g.gripDown)}" title="Drag to reorder this row" aria-hidden="true" style="flex:none;width:14px;color:var(--ls);cursor:grab;touch-action:none;font:700 11px/1 var(--fm);letter-spacing:0;text-align:center;user-select:none">⠿</span>
                <span aria-hidden="true" style="${g.indentStyle}"></span>
                ${g.caretShow ? `<button data-click="${H(g.toggleCollapse)}" aria-label="${esc(g.caretAria)}" class="hb-as" style="flex:none;width:18px;height:18px;display:grid;place-content:center;border-radius:4px;color:var(--mu);font:600 10px var(--fm)">${g.caret}</button>` : ""}
                <span style="font:500 10.5px var(--fm);color:var(--ft);flex:none">${esc(g.num)}</span>
                <span aria-hidden="true" style="${g.swatch}"></span>
                <button data-click="${H(g.edit)}" class="ht-ac" style="${g.nameStyle}">${esc(g.name)}</button>
                ${g.kidCount ? `<span style="flex:none;font:600 10px var(--fm);color:var(--ft);background:var(--p2);border:1px solid var(--ln);border-radius:999px;padding:1px 6px">${g.kidCount}</span>` : ""}
                <button data-click="${H(g.togglePeek)}" aria-expanded="${g.peekOpen ? "true" : "false"}" aria-label="${esc(g.peekAria)}" class="hb-ac" style="flex:none;width:18px;height:18px;display:grid;place-content:center;border:1px solid var(--ln);border-radius:4px;color:var(--mu);font:600 11px var(--fm)">${g.peekChevron}</button>
              </div>
              <div style="position:relative;height:26px;margin-right:16px">
                <span aria-hidden="true" style="${g.trackStyle}"></span>
                ${g.isMilestone
                  ? `<span data-pointerdown="${H(g.barDown)}" aria-hidden="true" style="${g.msStyle}"></span>`
                  : `<span data-pointerdown="${H(g.barDown)}" aria-hidden="true" style="${g.barStyle}"><span style="${g.fillStyle}"></span></span>`}
                <span aria-hidden="true" style="${g.todayStyle}"></span>
                <span class="sr">${esc(g.aria)}</span>
              </div>
            </div>
            ${g.peekOpen ? `<div style="padding:10px 16px 12px 44px;background:var(--p2);border-top:1px dashed var(--ln);animation:fadein .16s ease-out">
              ${uiPeekFields(g)}
              <p style="margin:9px 0 0;font-size:11.5px;color:var(--ft);text-wrap:pretty">Edits apply immediately, recalculate every dependent task, and are undoable. Dependency types: FS finish-to-start, SS start-to-start, FF finish-to-finish, SF start-to-finish.</p>
            </div>` : ""}
          </li>`).join("")}
        </ul>
      </div>
    </div>
    <p style="margin:0;padding:11px 16px;border-top:1px solid var(--ln);font-size:12px;color:var(--ft);text-wrap:pretty">Drag a bar to move a task, or drag the ⠿ grip to reorder the register — both ask for confirmation before anything changes. The ▾ caret collapses a summary; the + peek opens dates, predecessor, successors and dependency type as editable fields. Moving a task pushes every dependent task with it. ${esc(v.calendarNote)}</p>
  </section>`;
}

// ——— Look ahead (prototype lines 603–679; the real 21-day model behind) ————
function pageLook(v) {
  if (!v.hasLook) {
    return `<section style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh);padding:26px 20px">
      <p style="margin:0;font-size:var(--fzs);color:var(--mu)">Loading the look ahead…</p>
    </section>`;
  }
  return `<section aria-labelledby="areas-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh);margin-bottom:14px">
    <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--ln);flex-wrap:wrap">
      <h2 id="areas-heading" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">Work areas</h2>
      <p style="margin:0;font:500 10.5px var(--fm);letter-spacing:.07em;text-transform:uppercase;color:var(--ft)">${esc(v.areaCount)}</p>
      <span style="flex:1"></span>
      <button data-click="${H(v.openNewArea)}" class="hb-ac" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12.5px var(--fd)">Add a work area</button>
    </div>
    <ul style="list-style:none;margin:0;padding:12px 16px;display:flex;gap:9px;flex-wrap:wrap">
      ${v.areaChips.map((a) => `<li style="display:flex;align-items:center;gap:9px;padding:8px 13px;border:1px solid var(--ln);border-radius:999px;background:var(--p2)">
        <span aria-hidden="true" style="width:11px;height:11px;border-radius:3px;background:${a.color};flex:none"></span>
        <span style="font:600 12.5px var(--fd)">${esc(a.name)}</span>
        <span style="font:11px var(--fm);color:var(--ft)">${esc(a.count)}</span>
      </li>`).join("")}
    </ul>
  </section>

  <section aria-labelledby="look-heading" style="background:var(--pn);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--sh)">
    <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--ln);flex-wrap:wrap">
      <h2 id="look-heading" style="margin:0;font:600 15px var(--fd);letter-spacing:.02em">${esc(v.lookWeekCount)}</h2>
      <p style="margin:0;font:500 10.5px var(--fm);letter-spacing:.07em;text-transform:uppercase;color:var(--ft)">${esc(v.lookRangeLabel)}</p>
      <span role="group" aria-label="Weeks on show" style="display:inline-flex;gap:5px">
        ${v.lookWeeksOpts.map((w) => `<button data-click="${H(w.pick)}" aria-pressed="${w.pressed}" style="${w.style}">${esc(w.label)}</button>`).join("")}
      </span>
      <span style="flex:1"></span>
      <button data-click="${H(v.seedLook)}" class="hb-ls" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12.5px var(--fd)">Seed from the schedule</button>
      <button data-click="${H(v.openNewLook)}" class="hb-fill" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ac);border-radius:6px;background:var(--as);color:var(--ac);font:600 12.5px var(--fd)">Add an activity</button>
      <button data-click="${H(v.shareLookCust)}" class="hb-ls" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12.5px var(--fd)">Share with the customer</button>
      <button data-click="${H(v.shareLookInt)}" class="hb-ls" style="min-height:var(--tap);padding:7px 13px;border:1px solid var(--ln);border-radius:6px;background:var(--pn);font:600 12.5px var(--fd)">Share with the crew</button>
    </div>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:var(--fz)">
        <caption class="sr">Look-ahead activities. Each cell is a button that marks that day worked for that activity.</caption>
        <thead><tr>
          <th scope="col" style="text-align:left;padding:6px 12px;font:500 var(--lbl) var(--fm);letter-spacing:.12em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ls);border-right:1px solid var(--ln);min-width:230px">Activity</th>
          <th scope="col" style="text-align:left;padding:6px 10px;font:500 var(--lbl) var(--fm);letter-spacing:.12em;text-transform:uppercase;color:var(--ft);border-bottom:1px solid var(--ls);border-right:1px solid var(--ls);min-width:170px">Constraints &amp; notes</th>
          ${v.lookDays.map((d) => `<th scope="col" style="${d.style}"><span style="display:block;font-size:9px;opacity:.8">${esc(d.dow)}</span><span style="display:block;font:600 12px var(--fd)">${esc(d.num)}</span></th>`).join("")}
        </tr></thead>
        <tbody>
          ${v.lookRows.map((lr) => `<tr class="hr-p2">
            <th scope="row" style="text-align:left;padding:6px 12px;border-bottom:1px solid var(--ln);border-right:1px solid var(--ln);font-weight:500">
              <span style="display:flex;gap:7px;align-items:flex-start">
                <span aria-hidden="true" style="width:3px;align-self:stretch;min-height:15px;border-radius:2px;background:${lr.areaColor};flex:none"></span>
                <span style="flex:1;min-width:0">
                  <button data-click="${H(lr.edit)}" class="ht-ac" style="text-align:left;font:600 12.5px/1.3 var(--fd);color:var(--bp);text-decoration:underline;text-underline-offset:2px;min-height:20px">${esc(lr.name)}</button>
                  <span style="display:block;font:10px/1.4 var(--fm);color:var(--ft)">${esc(lr.area)} · ${esc(lr.count)} · ${esc(lr.tools)}</span>
                </span>
                <button data-click="${H(lr.remove)}" aria-label="Remove ${esc(lr.name)} from the look ahead" title="Remove" class="ht-er" style="flex:none;width:18px;height:18px;display:grid;place-content:center;border:1px solid var(--ln);border-radius:4px;color:var(--ft);font:600 12px/1 var(--fm)">×</button>
              </span>
            </th>
            <td style="padding:6px 10px;border-bottom:1px solid var(--ln);border-right:1px solid var(--ls)">
              ${lr.hasNotes ? `<ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px">
                ${lr.notes.map((n) => `<li style="display:flex;gap:6px;align-items:baseline;font:11.5px/1.4 var(--fb);color:var(--mu)">
                  <span style="font:600 8.5px var(--fm);letter-spacing:.08em;text-transform:uppercase;color:${n.color};white-space:nowrap">${esc(n.tag)}</span>
                  <span style="flex:1;text-wrap:pretty">${esc(n.text)}</span>
                </li>`).join("")}
              </ul>` : `<span style="font-size:11.5px;color:var(--ft);font-style:italic">No constraint</span>`}
            </td>
            ${lr.days.map((d) => `<td style="${d.cellStyle}">
              <button data-click="${H(d.toggle)}" aria-pressed="${d.pressed}" aria-label="${esc(d.label)}" style="${d.style}">${d.mark}</button>
            </td>`).join("")}
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <p style="margin:0;padding:11px 16px;border-top:1px solid var(--ln);font-size:12px;color:var(--ft);text-wrap:pretty">Select an activity name to edit it. Customer requirements go out on the customer copy; tools, material and operational notes never do. Dropping to two weeks hides week three rather than deleting it — the ticks keep their days.</p>
  </section>`;
}
