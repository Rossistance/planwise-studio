# LOGIC-MERGE — PlanWise 2.0.0

The element-by-element comparison the 2.0 release was built from, per the governing rule:
**UI copied exactly from the prototype; logic kept from whichever side is more developed; gaps
behind new UI get real backing code.** One row per element. "Existing" = PlanWise 1.x
(`backend/` + `frontend/` as of commit `3cb6bb4`); "Handoff" = the design package at
`C:\Users\rhixon\planwise claude design migration\` (prototype `PlanWise Redesign v3.dc.html`
+ DESIGN-SPEC / FEATURE-LOGIC / IMPLEMENTATION-NOTES).

Verdict vocabulary:
- **EXISTING** — repo logic kept untouched, wired behind the new UI.
- **HANDOFF** — handoff version implemented; weaker existing version retired (data migrated).
- **RESKIN** — comparable; existing implementation kept, presented in the new UI.
- **BUILD** — new UI had no real backing code; real service/model/handler built
  (honest-minimal where flagged `TODO(v2.x)`).

## Architecture

| Element | Existing | Handoff | Verdict | Why |
|---|---|---|---|---|
| Frontend runtime | No-build vanilla JS, innerHTML rebuild, 31 delegated listeners | React-under-canvas prototype (support.js harness) | **EXISTING approach, rebuilt** | No-build is load-bearing (corporate TLS, pip-only Render build, frozen exes). support.js is an editor harness (CDN React, eval, postMessage bridge) — discarded. New runtime keeps the prototype's `state → flat view-model → template` shape with vendored morphdom for focus-preserving re-render. |
| Rendering/focus | Full innerHTML swap; caret fought in 4 documented places | React reconciliation (in-place patch) | **HANDOFF semantics** via morphdom | The prototype's controlled-input model requires in-place patching; morphdom (vendored, single file) reproduces it without a build step. |
| Styling | styles.css component classes, 2 themes, system fonts | 57-line token block + 936 inline styles + 4 theme axes + 3 webfont families | **HANDOFF** | Tokens/themes/typography are the design. Hybrid: token block verbatim, 8 repeated style factories promoted to classes, one-off layout inline. Fonts self-hosted woff2 (vendoring policy, same as pdf.js). |
| Event model | 31 listeners, registration-order coupling (documented regression) | React synthetic handlers | **HANDOFF semantics** via one `data-act` dispatch registry | Kills the ordering hazard; one listener per event type. |
| Section names | Tabs, no groups | Job / Money / Time / Field & docs → proposals | **Option A** (Job overview / Cost & contracts / Schedule & planning / Field records) | User instruction adopted Option A — that is the sign-off IMPLEMENTATION-NOTES #11 awaited. |

## Cross-cutting doctrine

| Element | Existing | Handoff | Verdict | Why |
|---|---|---|---|---|
| One orange action/page | No equivalent | PAGE_META next-step block | **HANDOFF** | Pure presentation doctrine; PAGE_META ported verbatim. |
| Undo everywhere | None | Undo bar + revert on every outbound/destructive verb | **BUILD** | Client-orchestrated inverse API operations + append-only reversal activity entries. `TODO(v2.x)`: server-side operation log. |
| Confirm dialog | `armed()` two-step, native `prompt()`/`confirm()` (incl. an unmasked password prompt) | Checked confirm (pass/warn/fail, blocked verdict) | **HANDOFF** | Richer, and eliminates native prompts entirely. |
| Registers never disagree | Real: D8 open-committed derived from PO register; CO register reconciled against Vista | Same doctrine, derived in view code | **EXISTING** | The repo already computes, never stores; footnote copy from the prototype. |
| Vista read-only | Real: ingest push, snapshot cache, provenance tags | "Source: Vista, as of <date>" + stale pill | **EXISTING** logic, **HANDOFF** presentation | Rail pill + as-of footnotes from `/api/health` freshness the repo already reports. |
| Customer vs internal copy | Real: look-ahead audience layouts (internal columns structurally absent from customer PDF), record packages carry only own layer | Same doctrine + share-sheet blocking rule | **EXISTING** enforcement, **BUILD** share-sheet UI | Blocking rule (internal item + customer recipient → disabled with reason) implemented in the sheet; server audiences already enforce the output side. |
| Append-only history | Real: `activity` table, every mutation logged | Activity register + reversal entries | **EXISTING** log, **BUILD** reversal | `POST /api/activity/{id}/reverse` for the reversible action set; reversal appends beneath the original, never deletes. |
| Keyboard map / tour / shortcut sheet | ~none (Enter/Esc in markup editor only) | Full map (`/ ? Esc Alt+A/F/D/Z Alt+[ ]`), 4-step tour, sheet | **HANDOFF** | Ported as designed. |
| Accessibility | Thin (2 live regions, no dialog semantics, no Esc) | Skip links, aria-sort, aria-current, sr-only captions, focus doctrine, live region | **HANDOFF** | Ported as designed; existing card-reflow `data-label` pass kept. |
| Responsive/mobile | 5 breakpoints, table→card reflow, coarse-pointer, safe-area | field mode (48px tap), compact density | **BOTH merged** | Density axes from handoff; breakpoints + card reflow from 1.x (the prototype was desktop-preview only). |

## Shell

| Element | Existing | Handoff | Verdict | Why |
|---|---|---|---|---|
| Navigation shell | Topbar + tab row | Rail (226/56px, pin tack right-edge open-only, hover-open 260/380ms, overshoot-open easing, groups + badges, collapsed = nav + initials only) | **HANDOFF** | The redesign's centerpiece; all 7 CHANGELOG refinements included. |
| Job switcher | Topbar search box → `GET /api/jobs?q` over the full Vista registry | Type-ahead card in rail, one job openable | **EXISTING** logic behind **HANDOFF** UI | Repo is multi-job for real (9,345 jobs); prototype's display-only limitation is a fake to discard. |
| Auth | Real: PBKDF2, sessions, self-service register, pending approval, must-change, bootstrap | Accept-anything login card | **EXISTING** | All five auth states re-skinned into the prototype's login-card visuals. |
| Splash | None | Plumb-bob construction, letter-by-letter slogan, 4.4s, no skip button | **HANDOFF** | Pure presentation; runs before login/app per real session state. |
| Vista status | Companion/health chip in topbar & settings | Rail pill (Data connected / Connection stale amber) | **HANDOFF placement** | Data from existing `/api/health` freshness. |
| Attention panel | None | 308px right panel, genuinely-waiting items, deep links, recent activity | **BUILD** | `GET /api/jobs/{job}/attention` composed from real sources: drafted-unsent COs, draft records, unconfirmed replies, approved sub COs without a PO, staged schedule imports, stale Vista, pending outbox. |
| Cross-entity search | Job search only | `/`-focused index across COs/POs/records/docs/tasks/nav/personnel | **BUILD** | Client-side index over registers already loaded per job. |

## Pages

| Element | Existing | Handoff | Verdict | Why |
|---|---|---|---|---|
| Dashboard KPIs | 13 real tiles from Vista + registers | KPI grid (`auto-fit minmax(152px,1fr)`), health strip | **RESKIN** | Real numbers into prototype grid; widest-value fit checked. |
| Forecast chart | None | SVG cost curve | **BUILD** | `vista_history` table appended on each workbook push; renders accrued real history, honest empty state until ≥2 points. Inventing a curve would violate the app's own doctrine. |
| Job setup | Real: Vista facts read-only w/ provenance, compliance/personnel/contacts editable, save-as-you-type | Same structure | **RESKIN** | Existing `PATCH /meta`; contacts feed all recipient dropdowns (both sides agree). |
| Cost breakdown | Real: dynamic cost types, phase codes, D8 open-committed, po_only rows, D5 variance | Adds approved-with-no-PO exposure column + committed-% bar | **EXISTING + HANDOFF column** | Approved-no-PO is derivable today: approved sub COs not referenced by any PO's `source_co_id`, rolled by cost type server-side (the prototype's `uncoveredByCostType` semantic, done for real). |
| Change orders | Real: composer (items PUT w/ total write-back, narrative, clarifications library seeded/archived/text-copied, live PDF iframe, needs_contact 409), DOCX+PDF hand-authored, sub-CO **log** PDF, share w/ both attachments | HTML letter simulation, same concepts, audit trail | **EXISTING** logic in **HANDOFF** composer chrome | The real PDF preview replaces the prototype's HTML simulation inside the same pane — the honest version of the same design. Audit trail = real activity entries per CO. |
| Invoices & POs | Real: register + nested invoices, PO-PDF import (SSRS-tuned, evidence, dedupe, wrong-job warning), sub-CO awaiting-PO panel, source_co_id link | Simpler register, faked import ("seven orders matched") | **EXISTING** | Import-review and awaiting-PO panels restyled as prototype registers/forms; `prompt()`-based issue-PO replaced by FormModal. |
| Schedule engine | Real server CPM: 4 link types both passes, real job calendar + holidays + elapsed durations, stored-start floor (push-only), both floats, computed critical path, cycle-tolerant, links table, staged imports | Client 8-pass relaxation, single predecessor, 5/7 approximation, asserted critical flag | **EXISTING** | Handoff's own resolved decisions #5/#6 ask for exactly what the repo has. Prototype engine retired on arrival. Push-only semantics identical (floor rule). |
| Schedule interactions | Zoom stops + Ctrl-wheel, column drag w/ persisted widths, collapse, import review, typed-DELETE clear | Bar-drag→confirm, row-reorder→confirm, peek editing (dates/pred/dep-type/successors), collapse w/ +N chip, announcements | **BOTH** | Handoff interactions implemented against the server engine (PATCH gains `moved` delta so "N dependent tasks moved" is the engine's truth); 1.x zoom/columns/import-review kept — richer than the prototype's fixed frame. |
| Predecessors UI | Multi-predecessor links table + text-input parsing (`12FS+2d`) | Single predecessor + dep type + successor chips | **HANDOFF UI, EXISTING model** | Per handoff resolved #2: primary predecessor editable, additional predecessors listed read-only in the peek. Text column stays an input format. |
| Summary dates | Derived by engine (summaries excluded from network) | Peek allows editing but recalc overwrites; production should disable | **EXISTING + handoff #4** | Date inputs disabled on rows with children. |
| Reorder vs reschedule | sort_order column | Reorder is presentation-only, numbers are identities | **Agreement** (handoff #3) | Row drag PATCHes sort_order only; confirm copy states dates/dependencies untouched. |
| Look ahead | Real: 21-day storage (2/3-week views hide, never delete), Sun–Sat weeks, areas owned by job w/ 8-color palette, idempotent schedule seeding (weekdays, status from %), audience-split HTML+PDF, share-week clamp | 14-day grid, 6 colors, constraint/requirement/ops/tools/material, seed, customer vs internal sheet | **EXISTING** | Strictly richer; re-skinned into the prototype grid. Internal columns already structurally absent from customer output. |
| Drawings storage | Real: immutable originals, sha256, normalized-coordinate shapes, **structural layer isolation** (`layer_for(rec)`), package flattening w/ rotation handling | Marks as % positioned spans; layers cosmetic (a string; nothing filters) — "internal never leaves" told through copy only | **EXISTING** | The prototype's layer story is fake; the repo's is the shape of the code. Kept wholesale. |
| Drawings viewer UI | 6 tools, 5 inks, DPR canvas, serialised renders | 8 tools (pin/box/cloud/line/arrow/text/highlight/dim), 4 inks, 3 weights, zoom presets, thumbnail rail w/ per-page counts, page-compare, picker mode | **HANDOFF UI** on existing pipeline | New shape kinds added to the annotation JSON vocabulary; existing shapes render unchanged. Picker mode wires the real attach endpoints. |
| RFIs/Submittals | Real: per-kind statuses, thread capture (companion match, idempotent dedupe, adopt-message-id), staged AI/heuristic proposals, PM confirm gate, packages w/ only own layer, sent-vs-returned compare (PDF & image) | Detail layout (what went out / thread / confirmed answer), doctrine copy, numbers in sequence | **EXISTING** logic in **HANDOFF** detail UI | The prototype's THREADS are seed data standing in for the repo's real reply pipeline. Compare view kept (no prototype counterpart). |
| Weekly briefing | None | Full page: customer/internal tabs, progress/risks/asks/signature blocks, attachments, recipient routing | **BUILD** | `briefings` table + CRUD + seeding from real registers (schedule deltas, attention items, CO/PO status) as PM-editable proposals; share via existing companion/eml paths. `TODO(v2.x)`: AI-refined narrative via ai.py. |
| Activity page | Table + endpoints, no page | Register, reversible rows → checked confirm (30-day, permission), reversal beneath original | **BOTH** | Page over existing data; reversal endpoint new (see Undo). Non-reversible rows get a blocked verdict naming why. |
| Settings | Real: AI provider/keys (masked round-trip), spend cap + live readout, poll config, users admin, push devices, account | Settings sheet visuals (theme/density/accent/field) | **EXISTING** panes in **HANDOFF** sheet + **HANDOFF** appearance controls | Accent selection (4 options) is new and persists with prefs. |
| Share sheet | Per-feature share endpoints (audience=team/customer), contacts from meta, `.eml` fallback | Unified sheet: recipients, items w/ internal blocking, when-options | **Handoff UI wired to existing generators** (shipped 2026-08-19, un-deferring the earlier verdict) | The sheet is the prototype's recipients/items/blocking layout over the real share endpoints: customer contacts from job meta, internal personnel from `GET /api/personnel` (approved accounts with an email), items fetched from each feature's OWN generator so the audience rules cannot fork client-side. The one rule with teeth is live: an internal item cannot be selected while a customer contact is (`disabled` + "Cannot be sent while a customer contact is selected"). One draft per audience; a briefing item marks the row Sent, undoably. Ladder preserved: companion draft → refusal or no-companion hands over per-audience `.eml` files (recipients in the file are the server's suggestion — edit in Outlook; the sheet's exact selection binds only the companion path, noted as a v2.x refinement). When-options (send-later) remain TODO(v2.x). |

## Existing features with no prototype counterpart — all kept (governing rule §2 bullet 1)

| Feature | Home in 2.0 |
|---|---|
| PWA offline (Cache API + write queue, stale labeling) | Netbar restyled on tokens; behavior untouched |
| Outbox (field→desk handoff, drain-at-desk re-render) | Outbox bar restyled; attention panel lists pending items |
| Web push (VAPID, per-device) | Settings sheet pane |
| `.eml` ladder (X-Unsent compose fallback) | Every share path, unchanged |
| Companion (draft/sent/scan, 5-state chip, D45/D46) | Status in Settings sheet; drives record/CO/look-ahead sends |
| PO-PDF import review (evidence, dedupe, wrong-job) | Prototype-styled review register on the POs page |
| Schedule import staging + link-confidence review | Prototype-styled review screen on the Schedule page |
| Sent-vs-returned compare (PDF + image replies) | Record detail thread |
| Sub-CO → PO issuance (`source_co_id`) | Awaiting-PO block + FormModal on POs page |
| Users admin (approve/deny/disable/reset) | Settings sheet, FormModal + ConfirmDialog (native prompts gone) |
| Vista workbook push + validate-then-swap | Unchanged; now also appends `vista_history` |
| Getting-started PDF generator, installers, desktop shell | Regenerated/wording at cutover; no code change |

## Prototype details deliberately not ported

- support.js runtime, `data-dc-tpl` annotations, streaming scaffolding, canvas editor bridge.
- Dead prototype code: `regHasNew`/`openNew`, unused `isCosts…isActivity` flags, duplicate `zoom`
  state, `helpControls` view-model remnants, `weeks/recStatus/coSel` dead state keys.
- Seed/fake data (R. Hall, job 24-003 Sage Draw, THREADS, faked "seven orders matched" import).
- `startStage`/`startPage` preview knobs (replaced by real session + hash routing).
- The prototype's totals-row off-by-one alignment (fixed in the Register port).
- Cosmetic layer badge (`seededMarks`) — replaced by real layer-scoped counts.

## Resolved decisions honored (IMPLEMENTATION-NOTES §4)

1 push-never-pull ✓ (engine floor rule) · 2 single predecessor in UI ✓ · 3 reorder ≠ reschedule ✓ ·
4 summary dates derived, inputs disabled ✓ · 5 real job calendar ✓ · 6 computed critical path ✓ ·
7 confirm-for-gestures / immediate-undoable-for-typed-edits ✓ · 8 collapsed rail navigation-only ✓ ·
9 pin tack placement/behavior ✓ · 10 splash ~4.4s, no skip button ✓ · 11 section names = Option A
(signed off in the 2.0 task) ✓ · 12 undo/confirm on every outbound or destructive verb ✓.

## Verdicts discovered during the build (appended per phase, as the plan required)

| Element | Verdict | Why |
|---|---|---|
| Splash frequency | Once per browser SESSION, not per page load | The prototype models app launch; resolved decision #10 says the login screen is the skip. A working tool cannot cost 4.4s per F5. `sessionStorage["pw.splashed"]`. |
| Composer creation | "Compose a change order" CREATES the row first, then opens the composer | A real id from the first keystroke is what lets the preview pane show the actual letter PDF. A CO abandoned untouched is deleted quietly on close. |
| CO letter preview | Real PDF iframe inside the prototype's preview pane | The prototype simulated the letter in HTML; the generator that produces what the customer receives wins (debounced save → cache-busted reload). |
| CO send status | "Awaiting Outlook" is set on drafting and stays until the PM advances it | The companion's send-detection watches pipeline records, not COs. `TODO(v2.x)`: companion CO-thread watch. |
| PO invoices | Detail-drawer list + Record-an-invoice form (prototype interaction model) replaces 1.x inline sub-rows | Same data, prototype presentation; the sort-grouping hack dies with the sub-rows. |
| Gantt bar geometry | Bars draw from the ENGINE's early dates, stored dates stay floors | Stored dates are push-only floors (D43); the bar the field sees must be where the network actually puts the work. Verified: an edit answered "4 dependent tasks moved with it" while stored starts held. |
| Gantt zoom | Kept (a 1.x feature Ross asked for by name); per-column drag dropped | The prototype's fixed 280px task column wins; the register carries the data columns, so column widths lost their purpose. |
| Clear schedule | Checked confirm replaces 1.x's typed-DELETE native prompt | Same stakes, the 2.0 confirm idiom; still explicitly not undoable. |
| Native prompts | ALL eliminated (`prompt()`/`confirm()` zero uses — pinned by test) | Includes 1.x's unmasked admin password prompt; resets now generate a temp password shown once in the checked confirm. |
| Annotation marks | v2 dialect ({v:2, tool, x%, y%}) joins the 1.x shapes on the same layer-scoped rows | Old shapes render forever (read-only box extent); new marks are the prototype's click-placed vocabulary. Server validates both; junk still refused. |
| Viewer layer display | The viewer shows the ACTIVE layer only, named in the footnote | The prototype drew all layers and told the isolation story through copy; production scopes the display to match the structural isolation that already governs packages. |
| Briefing attachments | The matching-audience look-ahead PDF rides along | One email instead of two, real generator, audience-correct. `TODO(v2.x)`: register PDFs as selectable attachments + a briefing .eml route. |
| Record send fallback | No companion → queue to outbox AND download the .eml | Both 1.x rungs kept; the outbox bar drains at a desk, rendering at DRAIN time (1.x lesson: never a snapshot from the van). |
| Service worker | Registers only when 2.0 is the root app | At /v2 (the dev mount) a root-scoped worker would hijack the 1.x shell. |
| Job switcher landing | No job in the hash → last job, else the first the registry offers | A dashboard about nothing helps nobody. |
| Legacy hash keys | 1.x page keys (dashboard/overview/changeorders/…) resolve to 2.0 pages | Old deep links and bookmarks keep working. |

### Appended after release feedback (2026-08-19)

| Element | Existing (2.0.0 as tagged) | Owner feedback / gap | Verdict | Why |
|---|---|---|---|---|
| Typography | Vendored woff2 of the spec families (Barlow Semi Condensed / Archivo / JetBrains Mono) | "The font isnt the same… looks like old typewriter print." Canvas metrics proved the design canvas never loaded its Google Fonts — the prototype the owner approved rendered the FALLBACK stack. | **Owner verdict over spec text**: system stack shipped (`Segoe UI Semibold` / `Segoe UI` / `Cascadia Mono`), fonts.css link and SW precaches removed (v6); the woff2 files stay in `frontend/fonts/` unused should the verdict flip. | The governing rule copies the design the owner signed off, and what they signed off was measurably the system stack (identical measureText in both tabs). |
| Login identity field | `type="email"` (browser blocks a bare name) | Server auth has always accepted name OR email; the field's type forbade what the API allows. | **Existing server logic wins; UI corrected**: `type="text"`, label "Work email or name". | The browser was enforcing a rule the product does not have. |
| Briefing `.eml` escape hatch | Companion-only ("lands in v2.x") | Honest-edge list item | **Built**: `GET /api/briefings/{id}/share.eml?audience=…` via the same `_lookahead_doc` assembler (matching sheet rides along); ASCII filename (headers are latin-1 — regression test). | Same D41 ladder every other share already had. |
| Briefing AI reword | — | Honest-edge list item | **Built**: `POST /api/briefings/{id}/refine` → `briefing.refine_blocks()` — whitelist-validated block keys, unchanged-on-any-failure, undoable via returned `activity_id`; UI button "Reword with drafting help". No key → "Nothing was reworded… The blocks are untouched." | Reword is presentation; the facts stay the registers'. |
| Look-ahead rows in the reversal set | Undo bar offered a client inverse only | Honest-edge list item | **Built**: `lookahead.add_item/delete_item` log `revert` payloads (`laitem.delete`/`laitem.recreate`); server reversal + downstream check (period must still exist). | "Anything you send can be undone" now includes the crew sheet's rows. |

### Owner round two (2026-08-20)

| Element | Was | Owner verdict | Now |
|---|---|---|---|
| Typeface | System stack (Segoe UI Semibold / Segoe UI / Cascadia Mono) | "Too thin, techy like code; smooth, not pixelated. Create a custom font." | **PlanWise Sans** — the product's own face, instanced from Rubik (OFL, fonts/OFL.txt) with every CSS weight cut ~50 units heavier (400→470 … 700→770), renamed per the OFL, digits remapped to the tabular glyphs AT BUILD (the templates' `font:` shorthand resets any CSS feature toggle, so the font itself carries alignment). One family fills all three token roles — the mono face is gone deliberately; it was the "code" look. |
| Rail pinning | Pin-open only; tack rendered only while wide, so the pinned-closed state existing in code was unreachable | "Pin it closed too. Icons missing when expanded. Doesn't fit without scrolling." | Three reachable states — auto / open / closed — with the tack in BOTH widths (wide tack: open↔closed; narrow tack: closed↔auto); pin persisted in `pw.railPin` (restore was missing entirely); icons render in both widths; metrics tightened (collapsed list 479px). Collapsed job button expands without pinning. |
| Forecast chart | Honest empty state until 2 extracts landed | "Populate it from past data." | The extract's own month-to-date columns make month-start derivable: JTD − MTD, stored against the 1st with projected/estimate NULL (the derived-point marker), so one extract already draws a real line and every month boundary accrues another. Chart footnotes the derivation. Doctrine holds: Vista's arithmetic, never a guess. |
| Cost register | 10 columns, 16px cell padding, long headers → horizontal scroll | "Column spacing very large; doesn't fit." | Cell padding 16→10px across all registers, header tracking .14em→.09em, cost headers shortened (This month / Actual / Open PO / No PO / Committed / Of estimate); natural width ~1005px. |

### Appended 2026-08-20 (owner's mobile round)

| Element | Verdict | Why |
|---|---|---|
| Splash frequency | **Owner override of resolved decision #10**: the splash runs on EVERY fresh page load, signed in or not. | "The splash screen needs to appear every time the page loads fresh." Hash navigation never reloads the document, so in-app movement stays free. |
| Phone layout | **Root cause fixed**: on phones the rail is position:fixed and therefore out of grid flow — its 0px track captured the first in-flow child, so the whole page laid out zero-wide and painted by overflow. The mobile grid is now single-column; two-column page layouts stack; fact lists stack; buttons wrap; the dash cost table reflows; body overflow-x capped. Measured clean (0 uncontained leaks, scrollWidth = viewport) across all 12 pages, the settings sheet, share sheet, and CO composer at 375px. | The v11 "mobile shell" shipped over a broken foundation; the audit found it. |
| Projected at completion | **Gap-build, no AI**: `backend/projection.py` — the larger of the committed floor (actual cost + open PO value not yet invoiced + approved sub-COs without a PO) and the burn reading (actual / percent complete, abstaining below 5%). The chart's dashed tail lands on it; the panel shows Vista's figure beneath and a plain-English ledger of the components. | The owner's ask: an internal calculation from contract, open COs, and open POs. Every term is a register total; the basis is named. |

### PlanWise Field (2026-08-20, owner's role rule)

| Element | Verdict | Why |
|---|---|---|
| Field version | **Handoff's second prototype shipped** (`PlanWise Field.dc.html` → `frontend/field.js` + field tokens): five bottom tabs — Today on site (blockers from the attention feed + today's activities with big ticks), Look ahead (area chips, week grids, crew share), Drawings (sets → the real viewer), Questions and submittals (rows, read-only thread with the confirmed answer, raise-a-draft FAB), Job numbers (read-only money cards). Glove and sun modes verbatim. One PWA, one origin: the shell is chosen at sign-in by role, not by a second install. | The owner's rule: the email on a job's Superintendent or Field leader line IS the role. |
| Role source | Job setup gains `superintendent_email` / `field_leader_email`; `backend/field.py` matches the signed-in email case-insensitively, per job. Admins are never field-limited. | "the email that is added to the Field Leader or Superintendent section in each job setup" |
| Enforcement | SERVER-side: office writes (POs, COs, invoices, meta, schedule, briefings, record send/confirm, reversals) refuse with a sentence naming where the work lives; the field's own writes (day ticks, activities, areas, drawing marks, draft RFIs) keep working. UI limiting alone would not have satisfied the doctrine. | Registers never disagree; a hidden button is not a limit. |
