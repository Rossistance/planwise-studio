"""The weekly briefing — one week, two copies, no figure typed twice.

New in 2.0 (gap-build per LOGIC-MERGE): the prototype's Weekly briefing page
had no backing code. The model here is deliberately small and real:

- One row per job per week (Sun-start, same convention as the look ahead).
- `blocks` is the PM's editable content: {progress:[], risks:[], asks:[],
  signature:[]}, each entry {text, tag}. Seeded from the live registers as
  PROPOSALS — the PM edits or deletes them; nothing auto-sent is auto-written.
- Two renderings come from ONE row. The customer copy carries status and
  narrative and names an amount only where that amount is already on a
  submitted change order; the internal copy appends the financial position.
  Doctrine 5, same shape as the look ahead's audience split.

TODO(v2.x): AI-refined narrative via ai.py (draft, never gate), and PDF
attachments assembled from the other generators.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from . import db, store

BLOCK_KEYS = ("progress", "risks", "asks", "signature")


def week_start(day: date | None = None) -> str:
    """Sunday of the given (default: current) week — the look ahead's rule."""
    d = day or date.today()
    return (d - timedelta(days=(d.weekday() + 1) % 7)).isoformat()


def _blank_blocks() -> dict[str, list]:
    return {k: [] for k in BLOCK_KEYS}


def get_or_create(job_number: str, start: str | None = None,
                  actor: str | None = None) -> dict[str, Any]:
    start = start or week_start()
    conn = db.connect()
    row = conn.execute(
        "SELECT * FROM briefings WHERE job_number = ? AND week_start = ?",
        (job_number, start)).fetchone()
    if row:
        out = dict(row)
        out["blocks"] = json.loads(out["blocks"] or "{}") or _blank_blocks()
        return out
    rec = {"id": db.new_id(), "job_number": job_number, "week_start": start,
           "blocks": json.dumps(seed_blocks(job_number)), "status": "Draft",
           "created_by": actor, "created_at": db.now(),
           "updated_by": None, "updated_at": None, "sent_at": None, "sent_by": None}
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO briefings ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "briefing.create", f"week of {start}")
    rec["blocks"] = json.loads(rec["blocks"])
    return rec


def seed_blocks(job_number: str) -> dict[str, list]:
    """Proposals from the registers — what actually moved, is at risk, or is
    being waited on. Every line is traceable to a row; none is invented."""
    conn = db.connect()
    blocks = _blank_blocks()
    cutoff = (datetime.now().date() - timedelta(days=7)).isoformat()

    # Progress: what the log says happened this week (sends, confirms, commits).
    for a in conn.execute(
            "SELECT * FROM activity WHERE job_number = ? AND ts >= ? "
            "AND action IN ('rfi.sent','submittal.sent','rfi.confirm','submittal.confirm',"
            "'schedule.import.commit','co.create','po.create','invoice.create') "
            "ORDER BY ts DESC LIMIT 8", (job_number, cutoff)):
        blocks["progress"].append({"text": (a["detail"] or a["action"]),
                                   "tag": a["action"].split(".")[0].upper()})

    # Risks: draft records past or near due; critical schedule state is the
    # schedule engine's to state, so only what the registers show directly.
    for rec in conn.execute(
            "SELECT * FROM pipeline_records WHERE job_number = ? AND status = 'Draft' "
            "ORDER BY due_date", (job_number,)):
        due = f" — needed by {rec['due_date']}" if rec["due_date"] else ""
        blocks["risks"].append({
            "text": f"{rec['number'] or rec['kind'].upper()} ({rec['title'] or 'untitled'}) "
                    f"has not gone out{due}.",
            "tag": "Draft"})

    # Asks: sent-and-unanswered records, and submitted COs awaiting a decision.
    for rec in conn.execute(
            "SELECT * FROM pipeline_records WHERE job_number = ? AND status = 'Sent' "
            "ORDER BY due_date", (job_number,)):
        due = f" by {rec['due_date']}" if rec["due_date"] else ""
        blocks["asks"].append({
            "text": f"An answer to {rec['number'] or rec['kind'].upper()}, "
                    f"{rec['title'] or 'untitled'},{due}.".replace(",,", ","),
            "tag": f"Due {rec['due_date']}" if rec["due_date"] else "Awaiting reply"})
    for co in conn.execute(
            "SELECT * FROM change_orders WHERE job_number = ? AND kind = 'customer' "
            "AND amount_submitted IS NOT NULL AND amount_submitted > 0 "
            "AND (amount_approved IS NULL OR amount_approved = 0) "
            "ORDER BY date_submitted DESC", (job_number,)):
        n = co["co_number"] or "(unnumbered)"
        blocks["asks"].append({
            "text": f"A decision on CO-{n}"
                    + (f", {co['description']}" if co["description"] else "")
                    + f" — ${(co['amount_submitted'] or 0):,.0f} submitted.",
            "tag": co["status"] or "Submitted"})
        blocks["signature"].append({
            "text": f"CO-{n}" + (f" · {co['description']}" if co["description"] else ""),
            "tag": co["status"] or "Submitted"})

    # Exposure is a signature-level internal item too.
    unc = store.approved_no_po(job_number)
    if unc["cos"]:
        blocks["signature"].append({
            "text": f"{len(unc['cos'])} subcontractor commitment{'s' if len(unc['cos']) != 1 else ''} "
                    f"· ${unc['total']:,.0f} approved with no purchase order",
            "tag": "Open exposure"})
    return blocks


def patch(briefing_id: str, fields: dict[str, Any],
          actor: str | None = None) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM briefings WHERE id = ?", (briefing_id,)).fetchone()
    if row is None:
        return None
    updates: dict[str, Any] = {}
    if "blocks" in fields and isinstance(fields["blocks"], dict):
        clean = {k: fields["blocks"].get(k) or [] for k in BLOCK_KEYS}
        updates["blocks"] = json.dumps(clean)
    if "status" in fields and fields["status"] in ("Draft", "Sent"):
        updates["status"] = fields["status"]
        if fields["status"] == "Sent":
            updates["sent_at"] = db.now()
            updates["sent_by"] = actor
    if not updates:
        out = dict(row)
        out["blocks"] = json.loads(out["blocks"] or "{}") or _blank_blocks()
        return out
    updates["updated_by"] = actor
    updates["updated_at"] = db.now()
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE briefings SET {sets} WHERE id = ?",  # noqa: S608
                 (*updates.values(), briefing_id))
    conn.commit()
    old_status = row["status"]
    activity_id = db.log_activity(
        actor, row["job_number"], "briefing.update",
        f"week of {row['week_start']}: {', '.join(updates)}",
        object_kind="briefing", object_id=briefing_id,
        revert={"op": "briefing.patch", "id": briefing_id,
                "fields": {"blocks": row["blocks"], "status": old_status,
                           "sent_at": row["sent_at"], "sent_by": row["sent_by"]}}
        if "status" in updates or "blocks" in updates else None)
    out = dict(conn.execute("SELECT * FROM briefings WHERE id = ?", (briefing_id,)).fetchone())
    out["blocks"] = json.loads(out["blocks"] or "{}") or _blank_blocks()
    out["activity_id"] = activity_id
    return out


def render_html(briefing: dict[str, Any], job: dict[str, Any] | None,
                audience: str) -> str:
    """One inline-styled HTML body per audience, same technique as the look
    ahead's share_html. The internal copy APPENDS the financial position; the
    customer copy structurally never receives it (doctrine 5)."""
    internal = audience == "team"
    esc = _esc
    name = (job or {}).get("job_name") or briefing["job_number"]
    parts = [
        f"<h2 style='font-family:Segoe UI,Arial,sans-serif'>Weekly briefing — {esc(name)} "
        f"(week of {esc(briefing['week_start'])})</h2>",
        "<p style='color:#555'>"
        + ("Internal copy — carries the financial position. Check recipients before sending."
           if internal else
           "Customer copy — status and narrative only.")
        + "</p>",
    ]
    titles = {"progress": "Progress this week",
              "risks": "What could move the finish date",
              "asks": "What we need from you" if not internal else "At risk / needs a push",
              "signature": "Needs a signature"}
    for key in BLOCK_KEYS:
        rows = briefing["blocks"].get(key) or []
        if not rows:
            continue
        if key == "signature" and not internal:
            rows = [r for r in rows if "exposure" not in (r.get("tag") or "").lower()]
            if not rows:
                continue
        parts.append(f"<h3 style='font-family:Segoe UI,Arial,sans-serif'>{esc(titles[key])}</h3><ul>")
        for r in rows:
            tag = f" <i style='color:#888'>({esc(r.get('tag') or '')})</i>" if r.get("tag") else ""
            parts.append(f"<li>{esc(r.get('text') or '')}{tag}</li>")
        parts.append("</ul>")
    if internal and job:
        parts.append("<h3 style='font-family:Segoe UI,Arial,sans-serif'>Financial position</h3>")
        parts.append("<table style='border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:13px'>")
        for label, key in (("Current contract", "current_contract"),
                           ("Billed to date", "actual_billed"),
                           ("Cost to date", "actual_cost"),
                           ("Projected at completion", "projected_cost"),
                           ("Current estimate", "current_estimate")):
            v = job.get(key)
            if v is None:
                continue
            parts.append(f"<tr><td style='padding:3px 14px 3px 0;color:#555'>{esc(label)}</td>"
                         f"<td style='padding:3px 0;text-align:right'>${v:,.0f}</td></tr>")
        parts.append("</table>")
    parts.append("<p style='color:#888;font-size:12px'>Every figure is read from the "
                 "Vista extract or the PlanWise registers. Nothing is typed twice.</p>")
    return "".join(parts)


def _esc(t: str) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
