"""The sample project — one seeded job where every surface has something real to show.

The guided tour is only honest if the person can actually DO things: open a
change order that has items and a narrative, issue a PO against real exposure,
tick a look-ahead day, confirm a reply that genuinely arrived with a returned
file. So the sample is not a screenshot — it is a fully populated job
(``25-DEMO``) built through the same store functions the app uses, which means
the activity log, attention panel, exposure math and reversal engine all light
up for free.

Two rules:

* **Nothing here touches Vista.** The job number cannot exist in the extract,
  and its financials come from :func:`vista_snapshot` — a synthetic snapshot
  the API substitutes only for this one job, so every derivation (cost-type
  rollup, variance, exposure) runs through the SAME code paths as a real job.
* **Reset means reset.** ``ensure(reset=True)`` wipes the job and reseeds the
  canonical state, so a tour always starts from the same picture no matter
  what the last person clicked. Activity for the sample job is deleted on
  reset — append-only history is a promise made about real jobs, not about
  demo scaffolding.
"""
from __future__ import annotations

import base64
import zlib
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from . import briefing, changeorder, db, documents, lookahead, records, schedule, store

JOB = "25-DEMO"
LABEL = "25-DEMO Meadowlark Substation & Solar Yard"
ACTOR = "PlanWise Guide"


def exists() -> bool:
    return bool(store.get_meta(JOB).get("sample"))


# --- the synthetic Vista view -----------------------------------------------
# Shaped exactly like vista.py's parsed rows so cost_types_for/phases_for and
# get_job's own rollup run unchanged. Numbers are internally consistent: the
# phase lines sum (near enough) to the job row, the approved customer CO is
# the change-order revenue, and billed/collected/retainage reconcile.

def _phase_rows() -> list[dict[str, Any]]:
    def p(phase, ct, actual, est, proj, hours=None, mtd=None):
        return {"job_label": LABEL, "phase": phase, "cost_type": ct,
                "actual_cost": actual, "current_estimate": est,
                "projected_cost": proj, "hours_units": hours,
                "remaining_cost": (proj - actual) if proj and actual else None,
                "mtd_cost": mtd}
    return [
        p("26-050 Mobilization", "Labor", 148_200, 155_000, 152_000, 1_890, 0),
        p("26-100 Duct Bank & Trenching", "Labor", 612_400, 640_000, 668_000, 8_120, 58_400),
        p("26-200 Switchgear & Terminations", "Labor", 341_700, 705_000, 712_000, 4_880, 61_020),
        p("26-100 Duct Bank & Trenching", "Material", 498_300, 560_000, 571_000, None, 12_600),
        p("26-200 Switchgear & Terminations", "Material", 802_150, 1_390_000, 1_402_000, None, 9_800),
        p("26-300 Site Lighting", "Material", 96_400, 214_000, 219_000, None, 0),
        p("26-150 Directional Boring", "Subcontract", 219_800, 268_000, 271_500, None, 6_400),
        p("26-400 Testing & Commissioning", "Subcontract", 41_500, 214_000, 216_300, None, 0),
        p("26-100 Duct Bank & Trenching", "Equipment", 172_600, 158_000, 181_000, None, 0),
        p("26-050 Mobilization", "Equipment", 96_400, 214_000, 219_000, None, 0),  # rentals run long
        p("26-900 General Conditions", "Other", 82_100, 108_000, 111_000, None, 0),
    ]


def _job_row() -> dict[str, Any]:
    return {
        "job_label": LABEL, "job_number": JOB,
        "job_name": "Meadowlark Substation & Solar Yard",
        "original_contract": 4_825_000.0, "change_order_revenue": 128_700.0,
        "current_contract": 4_953_700.0, "actual_billed": 3_215_900.0,
        "actual_cost": 2_988_450.0, "projected_cost": 4_455_800.0,
        "current_estimate": 4_391_200.0, "earned_revenue": 3_180_000.0,
        "labor_cost": 1_102_300.0, "labor_hours": 14_890.0,
        "pct_complete": 0.67, "financial_status": "Active",
        "size_band": "$1M - $10M", "job_status": "In Progress",
        "contract_type": "Lump Sum",
        "mtd_cost": 148_220.0, "mtd_hours": 1_460.0, "mtd_billed": 186_300.0,
        "unapproved_ap": 21_480.0,
    }


def vista_snapshot() -> Any | None:
    """A snapshot-shaped stand-in covering ONLY the sample job, or None when
    the sample has not been seeded. Substituted by the API layer, never by
    vista.py itself — the real extract stays the only source for real jobs."""
    if not exists():
        return None
    now = datetime.now()
    return SimpleNamespace(
        jobs={JOB: _job_row()},
        phases={LABEL: _phase_rows()},
        contract_ar={JOB: {"contract": 4_953_700.0, "contract_status": "Open",
                           "billed": 3_215_900.0, "collected": 2_894_310.0,
                           "retainage": 321_590.0}},
        as_of=now, age_hours=0.0, is_stale=False, schema_version=2,
    )


def search_hit(q: str | None) -> dict[str, Any] | None:
    """The sample job's row for the type-ahead, when it matches. The real
    registry never contains it, so the search endpoint asks here too."""
    if not exists():
        return None
    needle = (q or "").strip().lower()
    hay = (JOB + " " + _job_row()["job_name"]).lower()
    if needle and needle not in hay and not JOB.lower().startswith(needle):
        return None
    return {"job_number": JOB, "job_name": _job_row()["job_name"],
            "financial_status": "Active", "sample": True}


# --- seeding -----------------------------------------------------------------

def _wipe() -> None:
    conn = db.connect()
    for doc in documents.list_documents(JOB):
        documents.delete_document(doc["id"], actor=ACTOR)
    po_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM purchase_orders WHERE job_number = ?", (JOB,))]
    if po_ids:
        conn.execute(f"DELETE FROM invoices WHERE po_id IN ({','.join('?' * len(po_ids))})",  # noqa: S608
                     tuple(po_ids))
    co_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM change_orders WHERE job_number = ?", (JOB,))]
    if co_ids:
        marks = ",".join("?" * len(co_ids))
        conn.execute(f"DELETE FROM change_order_items WHERE co_id IN ({marks})", tuple(co_ids))  # noqa: S608
        conn.execute(f"DELETE FROM change_order_clarifications WHERE co_id IN ({marks})", tuple(co_ids))  # noqa: S608
    rec_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM pipeline_records WHERE job_number = ?", (JOB,))]
    if rec_ids:
        marks = ",".join("?" * len(rec_ids))
        reply_ids = [r["id"] for r in conn.execute(
            f"SELECT id FROM record_replies WHERE record_id IN ({marks})", tuple(rec_ids))]  # noqa: S608
        if reply_ids:
            rmarks = ",".join("?" * len(reply_ids))
            conn.execute(f"DELETE FROM reply_attachments WHERE reply_id IN ({rmarks})", tuple(reply_ids))  # noqa: S608
        conn.execute(f"DELETE FROM record_replies WHERE record_id IN ({marks})", tuple(rec_ids))  # noqa: S608
        conn.execute(f"DELETE FROM record_drafts WHERE record_id IN ({marks})", tuple(rec_ids))  # noqa: S608
        conn.execute(f"DELETE FROM record_attachments WHERE record_id IN ({marks})", tuple(rec_ids))  # noqa: S608
    period_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM lookahead_periods WHERE job_number = ?", (JOB,))]
    if period_ids:
        conn.execute(f"DELETE FROM lookahead_items WHERE period_id IN ({','.join('?' * len(period_ids))})",  # noqa: S608
                     tuple(period_ids))
    for table in ("purchase_orders", "change_orders", "pipeline_records",
                  "schedule_tasks", "schedule_links", "schedule_imports",
                  "lookahead_periods", "lookahead_areas", "briefings",
                  "vista_history", "vista_monthly", "outbox", "activity",
                  "project_meta"):
        col = "job_number"
        conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (JOB,))  # noqa: S608
    conn.commit()


def ensure(actor: str = ACTOR, reset: bool = False) -> dict[str, Any]:
    if exists() and not reset:
        return {"job_number": JOB, "seeded": False}
    if exists():
        _wipe()

    today = date.today()
    d = lambda days: (today + timedelta(days=days)).isoformat()  # noqa: E731

    # -- job setup: every field filled, contacts that feed every dropdown ----
    store.patch_meta(JOB, {
        "sample": True,
        "project_manager": "Jordan Avery", "estimator": "Sam Whitcomb",
        "superintendent": "Marcus Boyd",
        "superintendent_email": "sample.super@planwise.demo",
        "field_leader": "Rita Calloway",
        "field_leader_email": "sample.lead@planwise.demo",
        "bond_required": "Yes", "insurance_cert": "Yes",
        "certified_payroll": "No", "pla_davis_bacon": "N/A",
        "contacts": [
            {"name": "Dana Whitfield", "role": "Owner's representative · Meadowlark Energy",
             "email": "dana.whitfield@meadowlark.example", "phone": "806-555-0142"},
            {"name": "Priya Natarajan", "role": "Engineer of record · Caldwell & Frost",
             "email": "pnatarajan@caldwellfrost.example", "phone": "512-555-0187"},
        ],
    }, actor=actor)

    # -- history: monthly cost postings + this month's extract points --------
    conn = db.connect()
    months, cum = [], 0.0
    monthly_costs = [96_000, 214_000, 386_000, 611_000, 742_000, 939_450]
    monthly_billed = [0, 168_000, 402_000, 655_000, 886_000, 1_104_900]
    first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    for i in range(len(monthly_costs) - 1, -1, -1):
        m = first
        for _ in range(i):
            m = (m.replace(day=1) - timedelta(days=1)).replace(day=1)
        months.append(m.strftime("%Y-%m"))
    months.sort()
    for m, cost, billed in zip(months, monthly_costs, monthly_billed):
        conn.execute("INSERT OR REPLACE INTO vista_monthly (job_number, month, cost, billed, hours, captured_at)"
                     " VALUES (?,?,?,?,?,?)", (JOB, m, cost, billed, cost / 74.0, db.now()))
        cum += cost
    for offset, frac in ((-9, 0.955), (-4, 0.978), (0, 1.0)):
        conn.execute("INSERT OR REPLACE INTO vista_history (as_of, job_number, actual_cost,"
                     " projected_cost, current_estimate, actual_billed, pct_complete, captured_at)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     (d(offset), JOB, round(cum + (2_988_450 - cum) * frac, 2),
                      4_455_800, 4_391_200,
                      round(3_215_900 * (0.94 + 0.06 * frac), 2), 0.67, db.now()))
    conn.commit()

    # -- change orders: one of every posture the tour talks about ------------
    co1 = store.add_co(JOB, {
        "kind": "customer", "co_number": "001", "cust_co_number": "OCO-14",
        "date_submitted": d(-41), "description": "Relocate transformer pad — owner directed",
        "amount_submitted": 128_700, "amount_approved": 128_700,
        "approved_by": "Dana Whitfield", "status": "Approved",
        "narrative": ("During the 60% site walk Meadowlark Energy directed the pad for "
                      "transformer T-2 to move 40 feet north, clear of the future battery "
                      "yard. This order covers demolition of the placed formwork, the new "
                      "excavation and reinforced pad, and rerouted secondary conduit."),
    }, actor=actor)
    changeorder.set_items(co1["id"], [
        {"description": "Demolish placed formwork and re-excavate", "amount": 18_400},
        {"description": "New reinforced pad, 40 ft north", "amount": 64_800},
        {"description": "Reroute secondary duct bank and conductors", "amount": 45_500},
    ])
    lib = changeorder.list_clarifications()
    if lib:
        changeorder.set_selected(co1["id"], [row["text"] for row in lib[:2]], actor=actor)

    store.add_co(JOB, {
        "kind": "customer", "co_number": "002",
        "date_submitted": d(-6), "description": "Added lighting circuits — Building B",
        "amount_submitted": 57_700, "status": "Draft",
        "narrative": ("Owner requested two additional exterior lighting circuits on the "
                      "Building B elevation. Pricing carries panel schedule revisions and "
                      "trenching shared with the signal duct."),
    }, actor=actor)

    sub1 = store.add_co(JOB, {
        "kind": "subcontractor", "co_number": "S-001", "subcontractor": "Caprock Boring",
        "date_submitted": d(-13), "description": "Rock clause — duct bank run 4",
        "amount_approved": 48_200, "status": "Approved",
    }, actor=actor)
    store.add_co(JOB, {
        "kind": "subcontractor", "co_number": "S-002", "subcontractor": "Tejas Electric Testing",
        "date_submitted": d(-2), "description": "Added relay set — feeder 3",
        "status": "Draft",
    }, actor=actor)

    # -- purchase orders + invoices. S-001 stays UNCOVERED so the exposure
    #    panel has something true to say. -----------------------------------
    po1 = store.add_po(JOB, {"po_number": "PO-4501", "vendor": "Wesco Distribution",
                             "description": "Switchgear line-up and breakers",
                             "order_date": d(-96), "ordered_by": "Jordan Avery",
                             "original_amount": 1_180_000, "cost_type": "Material",
                             "status": "Open"}, actor=actor)
    store.add_invoice(JOB, po1["id"], {"invoice_number": "INV-88121", "date": d(-34),
                                       "amount": 412_000}, actor=actor)
    store.add_invoice(JOB, po1["id"], {"invoice_number": "INV-88549", "date": d(-8),
                                       "amount": 390_150}, actor=actor)
    po2 = store.add_po(JOB, {"po_number": "PO-4502", "vendor": "Sunbelt Rentals",
                             "description": "Excavator + trench boxes, monthly",
                             "order_date": d(-118), "ordered_by": "Marcus Boyd",
                             "original_amount": 88_500, "cost_type": "Equipment",
                             "status": "Open"}, actor=actor)
    store.add_invoice(JOB, po2["id"], {"invoice_number": "R-20441", "date": d(-19),
                                       "amount": 61_200}, actor=actor)
    store.add_po(JOB, {"po_number": "PO-4503", "vendor": "Caprock Boring",
                       "description": "Directional bores, runs 1–4 (base contract)",
                       "order_date": d(-101), "ordered_by": "Jordan Avery",
                       "original_amount": 265_000, "cost_type": "Subcontract",
                       "status": "Open"}, actor=actor)
    store.add_po(JOB, {"po_number": "PO-4488", "vendor": "Hays Site Services",
                       "description": "Temporary facilities, mobilization month",
                       "order_date": d(-140), "ordered_by": "Marcus Boyd",
                       "original_amount": 9_600, "adjusted_amount": 9_600,
                       "cost_type": "Other", "status": "Closed"}, actor=actor)

    # -- schedule: three phases, real links (lags, SS), a critical chain -----
    def t(eid, name, start, dur, pct=0, level=2, summary=False, milestone=False, preds=""):
        fin = (date.fromisoformat(start) + timedelta(days=max(0, dur - 1))).isoformat()
        return {"external_id": str(eid), "name": name, "start": start, "finish": fin,
                "duration_days": dur, "percent_complete": pct, "outline_level": level,
                "is_summary": 1 if summary else 0, "is_milestone": 1 if milestone else 0,
                "predecessors": preds, "sort_order": eid}
    s0 = d(-118)
    tasks = [
        t(1, "Mobilization", s0, 18, 100, level=1, summary=True),
        t(2, "Notice to proceed", s0, 0, 100, milestone=True),
        t(3, "Site mobilization & laydown yard", d(-117), 10, 100, preds="2"),
        t(4, "SWPPP & erosion controls", d(-114), 6, 100, preds="3SS+3d"),
        t(5, "Underground & duct bank", d(-104), 68, 78, level=1, summary=True),
        t(6, "Trench & install duct bank — run 1", d(-104), 15, 100, preds="3"),
        t(7, "Trench & install duct bank — run 2", d(-88), 15, 100, preds="6"),
        t(8, "Rock excavation — run 4 chase", d(-74), 12, 85, preds="7SS+5d"),
        t(9, "Manholes & pull boxes", d(-80), 18, 70, preds="6"),
        t(10, "Backfill, compaction & surface repair", d(-58), 20, 55, preds="8"),
        t(11, "Switchgear & commissioning", d(-30), 96, 12, level=1, summary=True),
        t(12, "Switchgear pads & containment", d(-30), 14, 40, preds="10"),
        t(13, "Set switchgear & connect grounds", d(-9), 10, 0, preds="12"),
        t(14, "Cable pull & terminations", d(-2), 24, 0, preds="13SS+5d"),
        t(15, "Grounding grid test", d(6), 4, 0, preds="10"),
        t(16, "Energization", d(38), 0, 0, milestone=True, preds="14,15"),
        t(17, "Punch list & demobilize", d(39), 12, 0, preds="16"),
    ]
    schedule.import_tasks(JOB, tasks, source="mspdi", mode="replace", actor=actor)
    schedule.sync_links_from_text(JOB, source="mspdi", actor=actor)

    # -- look ahead: seeded from the schedule, then dressed ------------------
    period = lookahead.get_or_create_period(JOB, actor=actor)
    lookahead.seed_from_schedule(period["id"], actor=actor)
    a1 = lookahead.add_area(JOB, "Substation yard", "#C7420A", actor=actor)
    a2 = lookahead.add_area(JOB, "Duct bank alley", "#1F5F97", actor=actor)
    lookahead.add_area(JOB, "Control house", "#1B6B3D", actor=actor)
    items = lookahead.list_items(period["id"])
    for i, item in enumerate(items[:4]):
        lookahead.update_item(item["id"], {
            "crew": ["Boyd + 4", "Calloway + 3", "Caprock crew", "Boyd + 2"][i],
            "work_area_id": (a1 if i % 2 == 0 else a2)["id"],
        }, actor=actor)
        for day in range(i, i + 4):
            lookahead.toggle_day(item["id"], day, True, actor=actor)
    if items:
        lookahead.update_item(items[0]["id"], {
            "requirements": "Outage window confirmed with Meadowlark dispatch",
            "tools": "Cable tugger, 4k reel stands", "materials": "600A terminations x6",
        }, actor=actor)

    # -- drawings: a real 2-page set with marks on the internal layer --------
    doc = documents.add_document(JOB, "E-101 — Single Line & Site Plan.pdf",
                                 _drawing_pdf(), actor=actor)
    for shape in ({"v": 2, "tool": "Cloud", "x": 34.0, "y": 42.0, "ink": "#A9291D",
                   "weight": 2, "text": "Pad moves 40 ft north — CO-001"},
                  {"v": 2, "tool": "Pin", "x": 62.0, "y": 30.0, "ink": "#1F5F97",
                   "weight": 2, "text": "Verify conduit stub-up count"},
                  {"v": 2, "tool": "Text", "x": 18.0, "y": 74.0, "ink": "#1B6B3D",
                   "weight": 1, "text": "Laydown moves here after backfill"}):
        documents.add_annotation(doc["id"], 1, "internal", shape, actor=actor)

    # -- records: an answered RFI with a returned file, a draft RFI, and a
    #    submittal sent back for another pass --------------------------------
    rfi1 = records.add_record(JOB, "rfi", {
        "number": "RFI-001", "title": "Duct bank routing at north gate",
        "question": ("Sheet E-101 shows duct bank run 4 crossing the drilled pier at "
                     "grid C-4. Please confirm routing or issue a revised alignment."),
        "spec_section": "26 05 43", "status": "Draft",
        "to_name": "Priya Natarajan", "to_email": "pnatarajan@caldwellfrost.example",
        "due_date": d(-18)}, actor=actor)
    records.attach_page(rfi1["id"], doc["id"], 1, actor=actor)
    records.save_draft(rfi1["id"], "RFI-001 — Duct bank routing at north gate",
                       "Priya,\n\nSee the attached plan page. Run 4 as drawn crosses the "
                       "drilled pier at C-4; we need a confirmed alignment before the "
                       "crew reaches that station.\n\nJordan Avery",
                       "manual", actor=actor)
    records.mark_sent(rfi1["id"], actor=actor)
    reply = records.add_reply(rfi1["id"], {
        "from_name": "Priya Natarajan", "from_email": "pnatarajan@caldwellfrost.example",
        "received_at": d(-21) + "T14:22:05", "message_id": "<sample-rfi1-r1@planwise.demo>",
        "body": ("Jordan — shift run 4 two feet south of the pier cage and hold 18\" "
                 "clearance. Revised alignment clouded on the attached. Elevation is "
                 "unchanged."),
    }, attachments=[{"filename": "E-101 response — clouded.pdf",
                     "content_b64": base64.b64encode(_returned_pdf()).decode()}],
        actor=actor)
    records.confirm_reply(reply["id"], {
        "status": "Answered",
        "answer": "Shift run 4 two feet south of the pier cage; hold 18\" clearance. "
                  "Elevation unchanged — see clouded response sheet."}, actor=actor)

    rfi2 = records.add_record(JOB, "rfi", {
        "number": "RFI-002", "title": "Meter section landing lugs",
        "question": "Utility metering section arrived with 350MCM lugs; feeder schedule "
                    "calls 500MCM. Confirm replacement lug kit or approved reducer.",
        "spec_section": "26 27 13", "status": "Draft",
        "to_name": "Priya Natarajan", "to_email": "pnatarajan@caldwellfrost.example",
        "due_date": d(9)}, actor=actor)
    records.save_draft(rfi2["id"], "RFI-002 — Meter section landing lugs",
                       "Priya,\n\nThe metering section landed with 350MCM lugs against a "
                       "500MCM feeder schedule. Which way do you want to go?\n\nJordan",
                       "manual", actor=actor)

    sub = records.add_record(JOB, "submittal", {
        "number": "SUB-003", "title": "Switchgear shop drawings — line-up B",
        "spec_section": "26 23 00", "status": "Draft",
        "to_name": "Priya Natarajan", "to_email": "pnatarajan@caldwellfrost.example",
        "due_date": d(-4)}, actor=actor)
    records.attach_page(sub["id"], doc["id"], 2, actor=actor)
    records.save_draft(sub["id"], "SUB-003 — Switchgear shop drawings",
                       "Attached for review — line-up B shop drawings.", "manual",
                       actor=actor)
    records.mark_sent(sub["id"], actor=actor)
    sreply = records.add_reply(sub["id"], {
        "from_name": "Priya Natarajan", "from_email": "pnatarajan@caldwellfrost.example",
        "received_at": d(-7) + "T09:03:41", "message_id": "<sample-sub3-r1@planwise.demo>",
        "body": "Returning line-up B marked Revise & Resubmit — breaker AIC ratings on "
                "sheets 4 and 6 don't match the coordination study.",
    }, attachments=[{"filename": "SUB-003 returned.pdf",
                     "content_b64": base64.b64encode(_returned_pdf()).decode()}],
        actor=actor)
    records.confirm_reply(sreply["id"], {"status": "Revise & Resubmit"}, actor=actor)

    # -- the weekly briefing seeds itself from everything above --------------
    briefing.get_or_create(JOB, actor=actor)

    db.log_activity(actor, JOB, "sample.seed", "sample project seeded")
    return {"job_number": JOB, "seeded": True}


# --- a real (tiny) drawing set ----------------------------------------------
# Hand-authored PDF, two landscape pages: enough line work to be worth marking
# up, small enough to live in code. Same spirit as changeorder.py's builder.

def _pdf_pages(page_streams: list[bytes]) -> bytes:
    objs: list[bytes] = []
    n_pages = len(page_streams)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, stream in enumerate(page_streams):
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] "
                     f"/Resources << /Font << /F1 {3 + 2 * n_pages} 0 R >> >> "
                     f"/Contents {4 + 2 * i} 0 R >>").encode())
        comp = zlib.compress(stream)
        objs.append(b"<< /Length " + str(len(comp)).encode()
                    + b" /Filter /FlateDecode >>\nstream\n" + comp + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


def _title_block(sheet: str, title: str) -> bytes:
    return (
        b"1 w 0 0 0 RG 24 24 744 564 re S "
        b"0.6 w 552 24 m 552 96 l S 24 96 m 768 96 l S "
        + f"BT /F1 22 Tf 566 66 Td ({sheet}) Tj ET ".encode()
        + f"BT /F1 9 Tf 566 46 Td ({title}) Tj ET ".encode()
        + b"BT /F1 8 Tf 566 34 Td (Meadowlark Substation & Solar Yard \\(sample\\)) Tj ET "
        + b"BT /F1 8 Tf 36 78 Td (WHITE ELECTRIC CO. \\(SAMPLE SET\\) - NOT FOR CONSTRUCTION) Tj ET "
    )


def _drawing_pdf() -> bytes:
    p1 = (
        _title_block("E-101", "SINGLE LINE & SITE PLAN")
        # site outline + pads
        + b"0.8 w 80 160 m 700 160 l 700 540 l 80 540 l h S "
        + b"1.2 w 150 400 60 60 re S 320 400 60 60 re S 490 400 90 60 re S "
        + b"BT /F1 8 Tf 152 388 Td (XFMR T-1) Tj ET BT /F1 8 Tf 322 388 Td (XFMR T-2) Tj ET "
        + b"BT /F1 8 Tf 492 388 Td (SWGR LINE-UP B) Tj ET "
        # duct bank runs
        + b"0.9 w [6 4] 0 d 180 400 m 180 240 l 620 240 l S 350 400 m 350 240 l S "
        + b"535 400 m 535 240 l S [] 0 d "
        + b"BT /F1 8 Tf 240 226 Td (DUCT BANK - RUNS 1-4) Tj ET "
        # fence + gate
        + b"0.5 w 80 160 m 700 160 l S BT /F1 7 Tf 84 148 Td (NORTH GATE) Tj ET "
        + b"BT /F1 10 Tf 84 520 Td (SITE PLAN - 1\\\" = 40'-0\\\") Tj ET "
    )
    p2 = (
        _title_block("E-102", "DUCT BANK SECTIONS & DETAILS")
        + b"0.9 w 120 300 160 140 re S 360 300 160 140 re S 600 300 100 140 re S "
        + b"BT /F1 8 Tf 124 288 Td (SECTION A - 4W CONCRETE ENCASED) Tj ET "
        + b"BT /F1 8 Tf 364 288 Td (SECTION B - ROCK CHASE, RUN 4) Tj ET "
        + b"BT /F1 8 Tf 604 288 Td (MANHOLE MH-2) Tj ET "
        + b"0.6 w 150 330 m 150 420 l S 190 330 m 190 420 l S 230 330 m 230 420 l S "
        + b"390 330 m 390 420 l S 430 330 m 430 420 l S "
        + b"BT /F1 10 Tf 84 500 Td (TYPICAL SECTIONS) Tj ET "
    )
    return _pdf_pages([p1, p2])


def _returned_pdf() -> bytes:
    p1 = (
        _title_block("E-101R", "RESPONSE - CLOUDED")
        + b"0.8 w 80 160 m 700 160 l 700 540 l 80 540 l h S "
        + b"1.2 w 150 400 60 60 re S 320 400 60 60 re S "
        + b"0.9 w [6 4] 0 d 180 400 m 180 250 l 620 250 l S [] 0 d "
        # the engineer's cloud + note
        + b"1.4 w 0.66 0.16 0.11 RG 430 220 150 70 re S 0 0 0 RG "
        + b"BT /F1 9 Tf 434 200 Td (SHIFT RUN 4 2'-0\\\" SOUTH OF PIER CAGE - HOLD 18\\\" CLR) Tj ET "
    )
    return _pdf_pages([p1])
