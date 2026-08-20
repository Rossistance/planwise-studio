# PlanWise 2.0.0 — release verification

Executed 19 Aug 2026 against the isolated dev instance (`scripts/seed-dev.py`
data, synthetic job 26-101 Northwind) with the prototype servable beside it
(`python -m http.server 8741 --directory "…/design"`). Every check below was
run in the live browser pane; the test suite (`pytest -q`, 326 tests) was
green before and after. Re-run this list for any release that touches the
frontend; the per-item mechanics live in the referenced code.

## Foundation (must pass before anything else matters)

- [x] **Focus survives full re-renders.** Typed 9 characters into the job
  search — 9 complete morphdom re-renders — focus held, caret at end, live
  results updated. Repeated in the CO composer narrative through a debounced
  save→refresh cycle.
- [x] **Fonts are self-hosted and load.** `document.fonts` lists Barlow Semi
  Condensed, Archivo, JetBrains Mono — zero network font requests beyond our
  own origin.
- [x] **Tokens are the prototype's.** Body `#EFEDE6`, accent `#C7420A`, dark
  `#14171A`/`#F97435`, h1 21px Barlow, rail 226px with overshoot easing
  `cubic-bezier(.3,1.36,.4,1)` (computed, not asserted).
- [x] **KPI widest-value test:** `$6,482,910` fits its card at the grid's
  minimum column width.

## Doctrine

- [x] **One orange action per page.** Counted computed backgrounds across all
  12 pages: exactly one accent button each (Activity: zero, by design).
- [x] **Undo everywhere → reversal engine.** Contact removal → undo bar →
  `POST /api/activity/{id}/reverse` → contact restored → log holds original
  AND reversal (`reversal_of` set). Same path verified for a schedule edit.
- [x] **Registers never disagree.** Cost page open-committed equals the PO
  register's remaining-on-open-orders; issuing the PO for sub CO S-02 cleared
  the exposure column and the attention item in the same refresh.
- [x] **Customer vs internal copy.** Briefing customer tab carries no
  financial panel (checked in the DOM); internal tab shows it with a red
  internal-only stamp. Look-ahead customer share strips tools/material
  structurally (server layout, D-series).
- [x] **Confirm-for-gestures.** Bar drag and row reorder open the checked
  confirm before anything changes; typed edits apply immediately and announce.
- [x] **Append-only log.** Every check above left both the act and, where
  undone, the reversal on the Activity register.

## Pages (each opened, populated, exercised)

- [x] Dashboard — live KPIs, health strip, cost table, forecast drawn from
  two real `vista_history` points (empty-state wording verified with <2).
- [x] Weekly briefing — seeded proposals traced to rows (CO-04 in asks),
  inline edits persisted through the debounced PATCH, reseed confirm.
- [x] Job setup — Vista facts read-only, compliance/personnel saved on
  change with the "Saved" flash, contacts add (form) / remove (undoable).
- [x] Cost breakdown — 7 cost types, approved-no-PO column, committed bar.
- [x] Change orders — composer opens on a real row, real PDF letter preview
  refreshed while typing, items total written back ($186,400), clarification
  library ticks, delete via checked confirm.
- [x] Invoices & POs — register + detail invoices, exposure panel with
  prefilled issue-PO (verified cleared server-side), PDF import review
  (editable rows, evidence, duplicate flags).
- [x] Schedule — Gantt with engine early dates, peek edit announced
  "4 dependent tasks moved with it" from the engine's own delta, undo
  restored, collapse persists, drag confirms, staged-import review.
- [x] Look ahead — seeded 2 genuinely-overlapping tasks, day tick optimistic
  and persisted, 2/3-week switch, areas with counts.
- [x] Drawings — upload, real PDF painted in the viewer, marks stored on the
  internal layer (Pin/Cloud/Highlight/Dim verified), undo-last removed the
  row, thumbnails carry counts.
- [x] RFIs — thread page with the real reply, PM-confirm gate applied the
  proposal (status → Answered, answer released), draft subject/body edits.
- [x] Submittals — register with per-kind statuses, Revise & Resubmit stamp.
- [x] Activity — register over the live log, reversal confirm shows the
  SERVER's checks, blocked verdicts for entries without an inverse.

## Shell & chrome

- [x] Splash plays once per session (letter-by-letter slogan), login carries
  the real auth states (register → pending → approve → in, verified earlier
  with the second seeded account path).
- [x] Rail: pin tack right-edge/open-only, hover-open/close, collapsed =
  icons + initials, badges from the attention derivation, Option A names.
- [x] Attention panel auto-tucks at 10s untouched; items deep-link and
  disappear when their cause resolves.
- [x] Search `/` across COs/POs/records/docs/tasks/contacts ("grounding" →
  1 real match).
- [x] Dark theme toggle (both palettes), density, field mode, accent picker —
  all persisted in `pw.prefs` and re-applied before first paint.
- [x] Keyboard: `?` sheet, Esc stack, Alt+A/F/D/Z, Alt+[ ] section hop.
  Focus trap cycles inside the topmost dialog.
- [x] Offline netbar + queued-writes flush (offline.js carried from 1.x,
  same localStorage keys — queued 1.x writes survive the cutover).
- [x] Outbox bar drains at a desk, rendering at drain time; no-companion
  record sends queue for the desk AND download the .eml.

## Companion (requires a paired Windows PC — verified against the code path,
not this dev box)

- [ ] Draft-in-Outlook from CO / record / look-ahead / briefing.
- [ ] Send detection flips Draft → Sent on window focus.
- [ ] Check-for-replies files and dedupes.
These three re-run on Ross's PC after deploy — the ladder's fallback rungs
(.eml, outbox) were verified here in their place.

## Cutover checks

- [x] 326-test suite green.
- [x] `sw.js` precache list matches files on disk (pinned by test).
- [x] Verbatim microcopy pinned by test (confirm heading, RFI hint, slogan…).
- [x] No native `prompt()`/`confirm()` (pinned by test).
- [x] 1.x deep links resolve (legacy page keys mapped).
- [x] A 1.x database opens under 2.0 unchanged (additive migrations only;
  `test_migrations` extended).
