// PlanWise 2.0 — design constants and microcopy, ported VERBATIM from the
// prototype (PlanWise Redesign v3.dc.html, constants block lines 1892–2309).
// "Copywriting is part of the design" (IMPLEMENTATION-NOTES §2) — every
// purpose sentence, hint, footnote and aria phrase an implementer might be
// tempted to paraphrase lives here, in one auditable place.
//
// Deliberate departures, each recorded in LOGIC-MERGE.md:
//  - NAV group names are Option A (Job overview / Cost & contracts /
//    Schedule & planning / Field records) — the sign-off the proposals
//    document was waiting for. TOUR step 1 names the new groups.
//  - Seed data (JOBS, TASKS, POS, COS, RECORDS, THREADS…) is NOT ported:
//    real registers replace it. What remains here is design, not data.
"use strict";

const ICONS = {
  dash: "M3 11h6V3H3v8Zm0 10h6v-6H3v6Zm8 0h10v-8H11v8Zm0-18v6h10V3H11Z",
  brief: "M5 3h11l4 4v14H5V3Zm10 1v4h4M8 12h8M8 16h8",
  // The clipboard, deliberately NOT a gear — the gear is reserved for Settings
  // (CHANGELOG change 2).
  setup: "M9 3h6v3.5H9V3Zm6 1.5h4V21H5V4.5h4M8.5 11l1.5 1.5L12.5 10M14.5 11H16M8.5 16l1.5 1.5L12.5 15M14.5 16H16",
  costs: "M4 20h16M7 20V9m5 11V4m5 16v-7",
  cos: "M4 5h16M4 12h10M4 19h7M17 15l3 3-3 3M20 18h-6",
  pos: "M6 2h9l4 4v16H6V2Zm9 1v4h4M9 12h7M9 16h7M9 8h3",
  sched: "M3 5h18v16H3V5Zm0 5h18M8 3v4m8-4v4M7 14h4m2 0h4M7 18h3",
  // Binoculars — deliberately distinct from sched's calendar (CHANGELOG change 2).
  look: "M3.2 15.5a3.4 3.4 0 1 0 6.8 0 3.4 3.4 0 1 0-6.8 0Zm10.8 0a3.4 3.4 0 1 0 6.8 0 3.4 3.4 0 1 0-6.8 0ZM4.4 13.2 6.4 6h2.4v6.2M19.6 13.2 17.6 6h-2.4v6.2M10 11.5h4M12 8.5v3",
  docs: "M4 3h11l5 5v13H4V3Zm11 1v4h4M8 13h8M8 17h5",
  rfis: "M12 18h.01M9.1 9a3 3 0 1 1 4.4 3c-.9.6-1.5 1.2-1.5 2.2M4 3h16v18H4V3Z",
  subs: "M9 12l2 2 4-4M4 3h16v18H4V3Zm4 0v3h8V3",
  activity: "M3 12h4l2.5-7 3.5 14 2.5-7H21",
};

// Rail groups — Option A names (decision E), members unchanged.
const NAV = [
  ["Job overview", "JOB", [["dash", "Dashboard", ""], ["brief", "Weekly briefing", ""], ["setup", "Job setup", ""]]],
  ["Cost & contracts", "COST", [["costs", "Cost breakdown", ""], ["cos", "Change orders", "co"], ["pos", "Invoices & POs", "po"]]],
  ["Schedule & planning", "PLAN", [["sched", "Schedule", ""], ["look", "Look ahead", ""]]],
  ["Field records", "FIELD", [["docs", "Drawings", ""], ["rfis", "RFIs", "rfi"], ["subs", "Submittals", "sub"], ["activity", "Activity", ""]]],
];

const GROUP_OF = {};
NAV.forEach(([g, ab, items]) => items.forEach(([k]) => { GROUP_OF[k] = g; }));

// Page scaffolding: [eyebrow, title, purpose, next-step label, actions].
// Eyebrows and dynamic phrases are recomputed from live data at render time
// (the {tokens} below); the purpose sentences are the prototype's, verbatim.
const PAGE_META = {
  dash:  ["{jobline}", "Dashboard", "Where the job stands this morning: money, forecast, and the items waiting on you.", "Start here"],
  brief: ["{week}", "Weekly briefing", "Two copies of the same week. The customer copy carries status and narrative; the internal copy carries the money.", "Next step"],
  setup: ["{job}", "Job setup", "Contract facts come from Vista and cannot be edited here. Compliance, personnel and contacts are yours.", "Next step"],
  costs: ["{vista}", "Cost breakdown", "{costcount}, exactly what this job carries. Open and committed comes from the purchase order register; every other column comes from Vista.", "Next step"],
  cos:   ["{cocounts}", "Change orders", "{cosummary} Select any change order number to audit its breakout pricing, narrative and clarifications.", "Next step"],
  pos:   ["{pocounts}", "Invoices & POs", "Purchase orders are raised in Vista; PlanWise logs them so the register can feed open committed cost. Select a purchase order to audit its invoices.", "Next step"],
  sched: ["{schedcounts}", "Schedule", "A working schedule, not a frozen import. Add tasks, edit dates and progress, and watch the Gantt move with them.", "Next step"],
  look:  ["{lookrange}", "Look ahead", "Tick the days each activity is worked. Tools and material stay internal; the customer sheet strips them out.", "Next step"],
  docs:  ["{doccounts}", "Drawings", "One library feeds every package. Select a set to open it, turn pages and mark them up. Originals never change — redlines live on layers.", "Next step"],
  rfis:  ["{rficounts}", "RFIs", "{rfisummary} Select a number to audit the question, answer and attached pages.", "Next step"],
  subs:  ["{subcounts}", "Submittals", "{subsummary} Open a returned or approved submittal to read the review thread beside the marked pages.", "Next step"],
  activity: ["{job}", "Activity", "Every edit, share and reply on this job, newest first.", ""],
};

const DEP_TYPES = [["FS", "Finish to Start"], ["SS", "Start to Start"], ["FF", "Finish to Finish"], ["SF", "Start to Finish"]];
const DEP_NAME = { FS: "Finish to Start", SS: "Start to Start", FF: "Finish to Finish", SF: "Start to Finish" };

// Deterministic task colors (OKLCH hue rotation) — the Gantt's per-task hue.
const taskHue = (n) => {
  const i = (parseInt(n) || 1) - 1;
  return 26 + ((i * 47) % 300);
};
const taskColor = (n) => "oklch(0.55 0.13 " + taskHue(n) + ")";
const taskSoft = (n) => "oklch(0.94 0.035 " + taskHue(n) + ")";

const TOOLS = [
  ["Pin", "Numbered pin", "M12 21s7-6.4 7-11.4A7 7 0 0 0 5 9.6C5 14.6 12 21 12 21Zm0-8.6a2.4 2.4 0 1 0 0-4.8 2.4 2.4 0 0 0 0 4.8Z"],
  ["Box", "Rectangle", "M4 5h16v14H4z"],
  ["Cloud", "Revision cloud", "M6 15a3 3 0 0 1 .3-6 3.4 3.4 0 0 1 6-1.6A3 3 0 0 1 18 9a3 3 0 0 1 0 6Z"],
  ["Line", "Straight line", "M4 18 20 6"],
  ["Arrow", "Arrow", "M4 18 19 7m0 0h-6m6 0v6"],
  ["Text", "Text note", "M5 5h14M12 5v14M9 19h6"],
  ["Highlight", "Highlight block", "M5 14h14v5H5zM8 5h8v6H8z"],
  ["Dim", "Dimension", "M4 12h16M4 8v8M20 8v8"],
];

const INK_NAMES = { "#A9291D": "Red", "#1F5F97": "Blue", "#1B6B3D": "Green", "#7A5100": "Bronze" };

const MARK_STYLE = (m, i) => {
  const w = m.weight || 2.5;
  const pos = (l, t) => "position:absolute;left:" + l.toFixed(2) + "%;top:" + t.toFixed(2) + "%;";
  const nope = "pointer-events:none;";
  if (m.tool === "Box") return { label: "", style: pos(m.x - 7, m.y - 6) + "width:14%;height:12%;border:" + w + "px solid " + m.ink + ";border-radius:2px;" + nope };
  if (m.tool === "Cloud") return { label: "", style: pos(m.x - 8, m.y - 7) + "width:16%;height:14%;border:" + (w + 0.5) + "px dashed " + m.ink + ";border-radius:14px;" + nope };
  if (m.tool === "Line") return { label: "", style: pos(m.x - 8, m.y) + "width:16%;height:0;border-top:" + w + "px solid " + m.ink + ";" + nope };
  if (m.tool === "Arrow") return { label: "", style: pos(m.x - 16, m.y) + "width:16%;height:0;border-top:" + w + "px solid " + m.ink + ";" + nope };
  if (m.tool === "Highlight") return { label: "", style: pos(m.x - 9, m.y - 4) + "width:18%;height:8%;background:" + m.ink + "3D;border-top:1px solid " + m.ink + "66;border-bottom:1px solid " + m.ink + "66;" + nope };
  if (m.tool === "Text") return { label: m.text || "Note", style: pos(m.x, m.y - 2) + "max-width:34%;padding:3px 7px;background:rgba(255,255,255,.94);border:" + w + "px solid " + m.ink + ";border-radius:3px;color:" + m.ink + ";font:600 1.15cqw var(--fb);line-height:1.35;" + nope };
  if (m.tool === "Dim") return { label: m.text || "0'-0\"", style: pos(m.x - 11, m.y) + "width:22%;border-top:" + w + "px solid " + m.ink + ";color:" + m.ink + ";font:600 1.05cqw var(--fm);text-align:center;padding-bottom:2px;transform:translateY(-100%);" + nope };
  return { label: String(i + 1), style: pos(m.x - 1.5, m.y - 2.3) + "width:3%;aspect-ratio:1;border-radius:50%;background:" + m.ink + ";color:#fff;font:700 1.1cqw var(--fm);display:grid;place-content:center;" + nope };
};

const MARK_HEADS = (m, i) => {
  const w = m.weight || 2.5;
  const h = Math.round(w * 2.4);
  if (m.tool === "Arrow") return [{ style: "position:absolute;left:" + m.x.toFixed(2) + "%;top:" + m.y.toFixed(2) + "%;width:0;height:0;border-left:" + (h + 3) + "px solid " + m.ink + ";border-top:" + h + "px solid transparent;border-bottom:" + h + "px solid transparent;transform:translate(-100%,-50%);pointer-events:none" }];
  if (m.tool === "Dim") return [-11, 11].map((off) => ({
    style: "position:absolute;left:" + (m.x + off).toFixed(2) + "%;top:" + m.y.toFixed(2) + "%;width:0;height:14px;border-left:" + w + "px solid " + m.ink + ";transform:translateY(-50%);pointer-events:none",
  }));
  return [];
};

const RAIL_W = 226;
const RAIL_N = 56;

const AREA_COLORS = [
  ["Blue", "var(--bp)"], ["Green", "var(--ok)"], ["Amber", "var(--wn)"],
  ["Red", "var(--er)"], ["Slate", "var(--nt)"], ["Orange", "var(--ac)"],
];

const STATUS_TONE = {
  "Answered": "ok", "Approved": "ok", "Approved as Noted": "ok", "Closed": "ok",
  "Sent": "bp", "Draft": "wn", "Revise & Resubmit": "er", "Rejected": "er",
  "Pending": "bp", "Unsent": "er", "Resubmitted": "bp", "Awaiting Outlook": "bp",
  "Open": "er", "Marked": "wn", "Clean": "ok",
  // 1.x statuses the prototype's map never met — same tone vocabulary.
  "Critical": "er", "Has float": "ok", "Committed": "bp", "Staged": "wn",
};

const SHORTCUTS = [
  { key: "/", what: "Move focus to the job search box" },
  { key: "?", what: "Open and close this shortcut list" },
  { key: "Esc", what: "Close search results, this list, or the tour" },
  { key: "Alt + A", what: "Show or hide the Needs attention panel" },
  { key: "Alt + F", what: "Turn Field mode on or off (bigger targets, higher contrast)" },
  { key: "Alt + D", what: "Switch row density between comfortable and compact" },
  { key: "Alt + [", what: "Go to the previous section in the rail" },
  { key: "Alt + ]", what: "Go to the next section in the rail" },
  { key: "Alt + Z", what: "Undo the last thing you sent or removed" },
  { key: "Tab", what: "Rail, then header, then page, then attention panel" },
];

// TOUR step 1 names the Option-A groups (the proposals doc's "How to apply").
const TOUR = [
  { title: "Everything on this job lives in the left rail", body: "The rail is grouped the way the work is grouped: Cost and contracts, Schedule and planning, then Field records. The group you are in stays highlighted, so you always know where you are. A red count means that section has something open." },
  { title: "One orange action per page is the next move", body: "Each page has exactly one orange button, always in the same place — top right, under the words Next step. If you only do one thing on a page, do that. Everything else is grey." },
  { title: "Needs attention is the morning list", body: "The panel on the right holds only items that are genuinely waiting on you, newest cause first. Selecting one takes you to the page where you can finish it, and the item disappears once it is done." },
  { title: "Anything you send can be undone", body: "Sending a change order, issuing a purchase order or removing a contact all show a bar at the bottom of the screen with an Undo. Nothing leaves the building on a single click without a way back. Press ? at any time for the full shortcut list." },
];

const money = (n) => n === null || n === undefined ? "not reported"
  : (n < 0 ? "−" : "") + "$" + Math.abs(Math.round(n)).toLocaleString("en-US");
const signed = (n) => n === null || n === undefined ? "not reported"
  : n < 0 ? "$" + Math.abs(Math.round(n)).toLocaleString("en-US") + " over"
  : "$" + Math.round(n).toLocaleString("en-US") + " under";

const tone = (t) => ({ ok: "var(--ok)", er: "var(--er)", wn: "var(--wn)", bp: "var(--bp)", nt: "var(--nt)", vi: "var(--vi)" }[t] || "var(--nt)");
const toneSoft = (t) => ({ ok: "var(--oks)", er: "var(--ers)", wn: "var(--wns)", bp: "var(--bps)", nt: "var(--nts)", vi: "var(--vis)" }[t] || "var(--nts)");
const stamp = (t) => "display:inline-flex;align-items:center;gap:5px;font:600 10.5px var(--fm);letter-spacing:.08em;text-transform:uppercase;padding:4px 9px;border-radius:4px;white-space:nowrap;background:" + toneSoft(t) + ";color:" + tone(t);
const chip = (on) => "display:inline-flex;align-items:center;gap:7px;min-height:var(--tap);padding:6px 13px;border-radius:999px;font:600 12px var(--fd);letter-spacing:.04em;white-space:nowrap;border:1px solid " +
  (on ? "var(--ac)" : "var(--ln)") + ";background:" + (on ? "var(--as)" : "var(--pn)") + ";color:" + (on ? "var(--ac)" : "var(--mu)");
const btn = (kind) => "white-space:nowrap;min-height:var(--tap);" + (kind === "primary"
  ? "padding:9px 16px;border-radius:6px;border:1px solid var(--ac);background:var(--ac);color:var(--acink);font:600 13.5px var(--fd);letter-spacing:.03em;box-shadow:0 0 0 3px var(--as)"
  : "padding:9px 15px;border-radius:6px;border:1px solid var(--ln);background:var(--pn);color:var(--ink);font:600 13.5px var(--fd);letter-spacing:.03em");

// The wordmark and logo SVGs — used at three scales (rail 19px, login 27px,
// splash 52px). The "I" of WISE runs full cap height with the plumb-bob cone
// tucked inside the baseline: a weighted foot on the letter.
const WORDMARK_INNER =
  '<g fill="none" stroke="var(--ink)" stroke-width="4.6" stroke-linecap="butt">' +
  '<path d="M2 36V8h11a7.5 7.5 0 0 1 0 15H2"></path>' +
  '<path d="M29 8v28h17"></path>' +
  '<path d="M52 36 63 8l11 28M56.5 27.5h13"></path>' +
  '<path d="M81 36V8l19 28V8"></path></g>' +
  '<g fill="none" stroke="var(--ac)" stroke-width="4.6" stroke-linecap="butt">' +
  '<path d="M107 8l6 28 8-19 8 19 6-28"></path>' +
  '<path d="M149 8v20"></path>' +
  '<path d="M177 13c0-4.5-14-5.5-14 2 0 6.5 14 5.5 14 13.5 0 8-13.5 7-14.5 2.5"></path>' +
  '<path d="M203 8h-18v28h18M185 22h13"></path></g>' +
  '<path d="M144.6 28h8.8L149 36z" fill="var(--ac)"></path>';
const wordmark = (h) => '<svg viewBox="0 0 208 44" role="img" aria-label="PlanWise" style="height:' + h + 'px;width:auto;flex:none;overflow:visible">' + WORDMARK_INNER + "</svg>";
const LOGO_INNER =
  '<rect x="0" y="0" width="32" height="32" rx="7.5" fill="var(--ac)"></rect>' +
  '<g stroke="rgba(255,255,255,.3)" stroke-width="1" fill="none"><path d="M8.5 3v26M23.5 3v26M3 21.5h26"></path></g>' +
  '<path d="M16 4.5v6.5" stroke="#fff" stroke-width="1.7" stroke-linecap="round"></path>' +
  '<path d="M12.2 11h7.6L16 26.2z" fill="#fff"></path>' +
  '<path d="M5.5 28.8h21" stroke="#fff" stroke-width="1.9" stroke-linecap="round"></path>';
const logoSvg = (px) => '<svg viewBox="0 0 32 32" aria-hidden="true" style="width:' + px + "px;height:" + px + 'px;flex:none">' + LOGO_INNER + "</svg>";
