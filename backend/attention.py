"""Needs attention — the morning list, computed from the real registers.

The doctrine (FEATURE-LOGIC §0/§2): the panel holds ONLY items genuinely
waiting on the user, newest cause first; each deep-links to the page where it
can be finished and disappears the moment it is done. So nothing here is
stored — every item is derived from the same rows the pages themselves show,
and "disappears when done" falls out of the derivation instead of needing a
dismissal table.

Item shape mirrors the prototype's attentionItems(): kind (the rail-group
word), tone (er/wn/bp — the panel colors from it), age (humanised from the
cause row's own timestamp), text, cta, page (+ sub for deep links).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import db, store


def _age(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        then = datetime.fromisoformat(ts)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    days = max(0, (datetime.now(timezone.utc) - then).days)
    if days == 0:
        return "today"
    return f"{days} day{'s' if days != 1 else ''} open"


def _money(n: float) -> str:
    return "$" + f"{n:,.0f}"


def items_for(job_number: str, vista_stale: bool = False,
              vista_as_of: str | None = None) -> list[dict[str, Any]]:
    conn = db.connect()
    out: list[dict[str, Any]] = []

    # Drafted-but-unsent change orders: money written down that has not gone
    # to the customer. Any CO with a submitted amount and no sent marker in
    # its status counts; sub COs wait on approval, not sending, so customer
    # kind only.
    for co in conn.execute(
            "SELECT * FROM change_orders WHERE job_number = ? AND kind = 'customer' "
            "AND (status IS NULL OR status IN ('Draft','Unsent','Pending')) "
            "AND amount_submitted IS NOT NULL AND amount_submitted > 0 "
            "ORDER BY created_at DESC", (job_number,)):
        n = co["co_number"] or "(unnumbered)"
        out.append({
            "kind": "Money", "tone": "wn", "age": _age(co["created_at"]),
            "text": f"CO-{n} for {_money(co['amount_submitted'])} is drafted "
                    "but has not gone to the customer.",
            "cta": "Go to change orders", "page": "cos", "sub": co["id"],
            "ts": co["created_at"],
        })

    # Approved subcontractor work with no purchase order — exposure, the
    # red item. One line for the lot, matching the cost page's column.
    unc = store.approved_no_po(job_number)
    if unc["cos"]:
        n = len(unc["cos"])
        oldest = min(c["created_at"] for c in unc["cos"])
        out.append({
            "kind": "Commitment", "tone": "er", "age": _age(oldest),
            "text": f"{n} approved subcontractor change order{'s' if n != 1 else ''} "
                    f"worth {_money(unc['total'])} ha{'ve' if n != 1 else 's'} no purchase order.",
            "cta": "Go to the purchase order register", "page": "pos", "sub": None,
            "ts": oldest,
        })

    # Draft RFIs / submittals: written but never sent.
    for rec in conn.execute(
            "SELECT * FROM pipeline_records WHERE job_number = ? AND status = 'Draft' "
            "ORDER BY created_at DESC", (job_number,)):
        kind_word = "RFI" if rec["kind"] == "rfi" else "Submittal"
        due = f" It is due {rec['due_date']}." if rec["due_date"] else ""
        out.append({
            "kind": "Field", "tone": "bp", "age": _age(rec["created_at"]),
            "text": f"{rec['number'] or kind_word} is still a draft.{due}",
            "cta": f"Go to {'RFIs' if rec['kind'] == 'rfi' else 'submittals'}",
            "page": "rfis" if rec["kind"] == "rfi" else "subs", "sub": rec["id"],
            "ts": rec["created_at"],
        })

    # Replies captured but not confirmed: the customer answered and a PM has
    # not yet released the answer to the field.
    for row in conn.execute(
            "SELECT r.*, p.number AS rec_number, p.kind AS rec_kind, p.id AS rec_id "
            "FROM record_replies r JOIN pipeline_records p ON p.id = r.record_id "
            "WHERE p.job_number = ? AND r.confirmed_at IS NULL "
            "ORDER BY r.created_at DESC", (job_number,)):
        out.append({
            "kind": "Field", "tone": "wn", "age": _age(row["created_at"]),
            "text": f"{row['rec_number'] or 'A record'} has a reply from "
                    f"{row['from_name'] or row['from_email'] or 'the customer'} "
                    "waiting for a project manager to confirm it.",
            "cta": "Read and confirm the reply",
            "page": "rfis" if row["rec_kind"] == "rfi" else "subs", "sub": row["rec_id"],
            "ts": row["created_at"],
        })

    # A staged schedule import awaiting review.
    staged = conn.execute(
        "SELECT * FROM schedule_imports WHERE job_number = ? AND status = 'staged' "
        "ORDER BY created_at DESC LIMIT 1", (job_number,)).fetchone()
    if staged:
        out.append({
            "kind": "Time", "tone": "bp", "age": _age(staged["created_at"]),
            "text": f"A schedule import from {staged['filename'] or 'a file'} is "
                    "staged and waiting for review. Nothing lands until it is committed.",
            "cta": "Review the import", "page": "sched", "sub": None,
            "ts": staged["created_at"],
        })

    # Outbox items queued in the field, waiting for a desk with Outlook.
    for ob in conn.execute(
            "SELECT * FROM outbox WHERE job_number = ? AND drafted_at IS NULL "
            "ORDER BY queued_at DESC", (job_number,)):
        out.append({
            "kind": "Field", "tone": "bp", "age": _age(ob["queued_at"]),
            "text": f"A {'look ahead' if ob['kind'] == 'lookahead' else 'record'} share "
                    f"queued by {ob['queued_by'] or 'someone'} in the field is waiting "
                    "to be drafted from a desk with Outlook.",
            "cta": "Open the outbox", "page": "dash", "sub": None,
            "ts": ob["queued_at"],
        })

    # Stale Vista: the ground truth is old. Job-independent but shown per job
    # because every number on the job is only as fresh as the extract.
    if vista_stale:
        out.append({
            "kind": "Data", "tone": "wn", "age": "",
            "text": "The Vista extract is stale"
                    + (f" — last landed {vista_as_of}." if vista_as_of else ".")
                    + " Every cost figure on this job is only as fresh as the extract.",
            "cta": "Check the connection in Settings", "page": "dash", "sub": None,
            "ts": None,
        })

    # Newest cause first — the doctrine's ordering.
    out.sort(key=lambda i: i.get("ts") or "", reverse=True)
    for i in out:
        i.pop("ts", None)
    return out
