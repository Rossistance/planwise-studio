"""The mobile → desk handoff for Outlook drafting (Phase 5g).

The one thing iOS genuinely cannot do. D10 puts mail through each person's own
**desktop** Outlook over COM, which is what avoids Graph, tenant approval and
stored credentials entirely. There is no COM on a phone and no equivalent, so
"draft this into my Outlook" cannot be satisfied from an iPhone at all.

Rather than pretend, the send is *prepared* in the field and *drafted* at a
desk: the phone queues the intent here, and the next time its author opens
PlanWise on a machine with a companion, the app offers to draft everything
waiting. Mail still leaves from the account of the person who asked for it —
only the moment moves.

Two consequences worth stating plainly.

**Intent, not a rendered document.** A queued look ahead is re-rendered when
it's actually drafted, so what reaches the customer reflects the sheet at that
moment rather than a snapshot from the van. That is usually what's wanted; it
does mean the sheet can change between queuing and sending, which is why the
desk-side prompt shows what it's about to draft rather than sending blind.

**Only its author can draft it.** A queued item is claimable by the person who
queued it and nobody else — otherwise the whole point of D10 (mine through my
email, someone else's through theirs) would quietly break the first time two
people were signed in on the same machine.
"""
from __future__ import annotations

from typing import Any

from . import db

KINDS = ("lookahead", "record")


class OutboxError(ValueError):
    pass


def queue(job_number: str, kind: str, target_id: str, *, audience: str | None = None,
          weeks: int | None = None, note: str | None = None,
          actor: str | None = None) -> dict[str, Any]:
    if kind not in KINDS:
        raise OutboxError(f"Don't know how to send a '{kind}'.")
    if not target_id:
        raise OutboxError("Nothing to send.")

    rec = {"id": db.new_id(), "job_number": job_number, "kind": kind,
           "target_id": target_id, "audience": audience, "weeks": weeks,
           "note": (note or "").strip() or None,
           "queued_by": actor, "queued_at": db.now(),
           "drafted_at": None, "drafted_by": None}
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO outbox ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "outbox.queue", f"{kind} {target_id}")
    return rec


def pending(actor: str | None = None, job_number: str | None = None) -> list[dict[str, Any]]:
    """What's still waiting to be drafted. Scoped to one person by default —
    you are only ever offered your own."""
    q = "SELECT * FROM outbox WHERE drafted_at IS NULL"
    args: list[Any] = []
    if actor:
        q += " AND queued_by = ?"
        args.append(actor)
    if job_number:
        q += " AND job_number = ?"
        args.append(job_number)
    conn = db.connect()
    return [dict(r) for r in conn.execute(q + " ORDER BY queued_at", tuple(args))]


def get(item_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM outbox WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def claim(item_id: str, actor: str | None) -> dict[str, Any]:
    """Check an item out for drafting. Refuses anyone but its author, so a
    shared machine can't send someone else's mail from the wrong mailbox."""
    item = get(item_id)
    if item is None:
        raise OutboxError("That item is no longer queued.")
    if item["drafted_at"]:
        raise OutboxError("That one has already been drafted.")
    if item["queued_by"] and actor and item["queued_by"] != actor:
        raise OutboxError(f"Only {item['queued_by']} can draft that — it has to go "
                          "out from their own Outlook.")
    return item


def mark_drafted(item_id: str, actor: str | None = None) -> dict[str, Any] | None:
    conn = db.connect()
    cur = conn.execute(
        "UPDATE outbox SET drafted_at = ?, drafted_by = ? WHERE id = ? AND drafted_at IS NULL",
        (db.now(), actor, item_id))
    conn.commit()
    if cur.rowcount == 0:
        return None
    item = get(item_id)
    db.log_activity(actor, item["job_number"] if item else None, "outbox.drafted",
                    f"{item['kind']} {item['target_id']}" if item else item_id)
    return item


def cancel(item_id: str, actor: str | None = None) -> bool:
    item = get(item_id)
    if item is None or item["drafted_at"]:
        return False
    if item["queued_by"] and actor and item["queued_by"] != actor:
        raise OutboxError("That isn't yours to cancel.")
    conn = db.connect()
    conn.execute("DELETE FROM outbox WHERE id = ?", (item_id,))
    conn.commit()
    db.log_activity(actor, item["job_number"], "outbox.cancel",
                    f"{item['kind']} {item['target_id']}")
    return True
