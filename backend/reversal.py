"""The reversal engine — "anything you send can be undone", made structural.

Every 2.0 mutation that knows its own inverse stores it on its activity entry
as a `revert` JSON payload when it logs (db.log_activity). This module is the
other half: given an activity id, decide whether the reversal is allowed —
with the same pass/warn/fail checks the confirm dialog shows the user — and
apply the stored inverse in one transaction, appending a reversal entry that
points back at the original. The log is append-only throughout: a reversal is
a new fact on the record, never an erasure of the old one.

What this deliberately is NOT: a time machine. An entry written before 2.0
carries no payload and refuses honestly. An email that left the building
cannot be recalled — reversing a send restores the RECORD's state, and says
so. Reversing an entry whose object has since been deleted fails its
downstream check rather than resurrecting half a world.

TODO(v2.x): widen the reversible set further (documents and work areas are
still undo-bar-only via client inverses) and chain-detection (reversing a
create whose object has since been edited should warn with the edit list).
Look-ahead rows joined the covered set 2026-08-19.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db

# Reversals stay offered for this long. Past it, the books have moved on:
# Vista extracts, billings and downstream registers have all seen the state,
# and a silent flip would put PlanWise at odds with everything reconciled
# against it. Matches the confirm-dialog copy ("reversible for thirty days").
WINDOW_DAYS = 30


def get_entry(activity_id: int) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM activity WHERE id = ?", (activity_id,)).fetchone()
    return dict(row) if row else None


def _already_reversed(activity_id: int) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM activity WHERE reversal_of = ?",
                       (activity_id,)).fetchone()
    return dict(row) if row else None


def checks_for(entry: dict[str, Any], actor: str, is_admin: bool) -> dict[str, Any]:
    """The pass/warn/fail list the confirm dialog renders, computed for real.

    Shapes match the prototype's confirm spec: checks = [[kind, label, note]],
    plus blocked + verdict. The dialog's heading — "What PlanWise checked
    before offering this" — is only honest if these ARE the checks the apply
    path enforces, so apply() calls this same function and refuses on blocked.
    """
    checks: list[list[str]] = []
    blocked = False

    revert = json.loads(entry["revert"]) if entry.get("revert") else None
    if revert is None:
        checks.append(["fail", "Source of record",
                       "This entry does not carry its own inverse — it was recorded "
                       "before reversal support, or it states a fact (a Vista extract, "
                       "a sign-in) that PlanWise does not own. Reversing it here would "
                       "change nothing or put two systems out of step."])
        blocked = True
    else:
        checks.append(["pass", "Source of record",
                       "This entry was made in PlanWise and carries its own inverse, "
                       "so it can be reversed here."])

    prior = _already_reversed(entry["id"])
    if prior:
        checks.append(["fail", "Already reversed",
                       f"This entry was reversed on {prior['ts']} by {prior['actor']}. "
                       "A reversal is not itself reversible — redo the action instead."])
        blocked = True

    # Age: entries stay reversible for WINDOW_DAYS.
    try:
        ts = datetime.fromisoformat(entry["ts"])
        age = datetime.now(timezone.utc) - ts
    except ValueError:
        age = timedelta(0)
    if age > timedelta(days=WINDOW_DAYS):
        checks.append(["fail", "Age",
                       f"Recorded {entry['ts']}. Entries stay reversible for thirty "
                       "days; past that the books have moved on around them."])
        blocked = True
    else:
        checks.append(["pass", "Age",
                       f"Recorded {entry['ts']}. Entries stay reversible for thirty days."])

    # Permission: yours, or an admin's.
    if entry.get("actor") and entry["actor"] != actor and not is_admin:
        checks.append(["fail", "Permission",
                       f"This entry was made by {entry['actor']}. Only they or an "
                       "administrator can reverse it."])
        blocked = True
    else:
        checks.append(["pass", "Permission",
                       "You made this entry — it is yours to reverse."
                       if entry.get("actor") == actor else
                       "You are an administrator, so this is yours to reverse."])

    # Downstream: the object the inverse touches must still be addressable.
    if revert and not blocked:
        problem = _downstream_problem(revert)
        if problem:
            checks.append(["fail", "Downstream conflict", problem])
            blocked = True
        else:
            checks.append(["pass", "Downstream conflict",
                           "The object this touches is still where the reversal expects it."])

    verdict = ("This entry cannot be reversed from here. Clear the failed check above first."
               if blocked else
               "Nothing blocks this. The reversal is written to the log beneath the "
               "original entry; the original is never deleted.")
    return {"checks": checks, "blocked": blocked, "verdict": verdict}


def _downstream_problem(revert: dict[str, Any]) -> str | None:
    """Does the world still hold what the inverse needs? One query per op."""
    conn = db.connect()
    op = revert.get("op", "")

    def exists(table: str, rec_id: str) -> bool:
        return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?",  # noqa: S608 — table is a code constant
                            (rec_id,)).fetchone() is not None

    if op in ("po.delete", "po.patch") and not exists("purchase_orders", revert["id"]):
        return "The purchase order this entry created or edited has since been deleted."
    if op in ("co.delete", "co.patch") and not exists("change_orders", revert["id"]):
        return "The change order this entry created or edited has since been deleted."
    if op == "invoice.delete" and not exists("invoices", revert["id"]):
        return "The invoice this entry recorded has since been removed."
    if op == "invoice.recreate" and not exists("purchase_orders", revert["row"]["po_id"]):
        return "The purchase order this invoice belonged to has since been deleted."
    if op == "record.patch" and not exists("pipeline_records", revert["id"]):
        return "The record this entry touched has since been deleted."
    if op == "laitem.recreate" and not exists("lookahead_periods", revert["row"]["period_id"]):
        return "The look-ahead period this row belonged to has since been deleted."
    if op == "task.patch" and not exists("schedule_tasks", revert["id"]):
        return "The schedule task this entry edited has since been deleted — possibly by a re-import."
    if op == "schedule.recreate":
        row = conn.execute("SELECT COUNT(*) c FROM schedule_tasks WHERE job_number = ?",
                           (revert["tasks"][0]["job_number"],)).fetchone() if revert.get("tasks") else None
        if row and row["c"]:
            return ("A schedule exists again on this job — undoing the wipe would "
                    "collide with it. Clear the current schedule first if you mean it.")
    if op == "task.recreate" and exists("schedule_tasks", revert["row"]["id"]):
        return "The deleted task appears to exist again already."
    if op in ("po.recreate", "co.recreate"):
        if exists(op.split(".")[0] == "po" and "purchase_orders" or "change_orders",
                  revert["row"]["id"]):
            return "The deleted row appears to exist again already."
    return None


def apply(activity_id: int, actor: str, is_admin: bool) -> dict[str, Any]:
    """Reverse one entry. Returns {ok, reversal_id?, detail?, checks, verdict}."""
    entry = get_entry(activity_id)
    if entry is None:
        return {"ok": False, "detail": "No such activity entry.", "checks": [],
                "blocked": True, "verdict": "No such activity entry."}

    gate = checks_for(entry, actor, is_admin)
    if gate["blocked"]:
        return {"ok": False, **gate}

    revert = json.loads(entry["revert"])
    conn = db.connect()
    op = revert["op"]
    try:
        if op == "po.delete":
            conn.execute("DELETE FROM purchase_orders WHERE id = ?", (revert["id"],))
        elif op == "po.patch":
            _patch(conn, "purchase_orders", revert["id"], revert["fields"])
        elif op == "po.recreate":
            _insert(conn, "purchase_orders", revert["row"])
            for inv in revert.get("invoices", []):
                _insert(conn, "invoices", inv)
        elif op == "invoice.delete":
            conn.execute("DELETE FROM invoices WHERE id = ?", (revert["id"],))
        elif op == "invoice.recreate":
            _insert(conn, "invoices", revert["row"])
        elif op == "co.delete":
            conn.execute("DELETE FROM change_orders WHERE id = ?", (revert["id"],))
        elif op == "co.patch":
            _patch(conn, "change_orders", revert["id"], revert["fields"])
        elif op == "co.recreate":
            _insert(conn, "change_orders", revert["row"])
            for it in revert.get("items", []):
                _insert(conn, "change_order_items", it)
            for cl in revert.get("clars", []):
                _insert(conn, "change_order_clarifications", cl)
        elif op == "record.patch":
            _patch(conn, "pipeline_records", revert["id"], revert["fields"])
        elif op == "task.patch":
            _patch(conn, "schedule_tasks", revert["id"], revert["fields"])
        elif op == "schedule.recreate":
            for t in revert.get("tasks", []):
                _insert(conn, "schedule_tasks", t)
            for ln in revert.get("links", []):
                _insert(conn, "schedule_links", ln)
        elif op == "task.recreate":
            _insert(conn, "schedule_tasks", revert["row"])
            for ln in revert.get("links", []):
                # A link whose other end has since been deleted stays gone —
                # resurrecting half a dependency helps nobody.
                other = ln["pred_id"] if ln["succ_id"] == revert["row"]["id"] else ln["succ_id"]
                if conn.execute("SELECT 1 FROM schedule_tasks WHERE id = ?",
                                (other,)).fetchone():
                    _insert(conn, "schedule_links", ln)
        elif op == "briefing.patch":
            _patch(conn, "briefings", revert["id"], revert["fields"])
        elif op == "laitem.delete":
            conn.execute("DELETE FROM lookahead_items WHERE id = ?", (revert["id"],))
        elif op == "laitem.recreate":
            _insert(conn, "lookahead_items", revert["row"])
        elif op == "meta.patch":
            # Route through the meta helper so clears behave identically —
            # but without logging a second revert for the reversal itself.
            from . import store
            data = store.get_meta(entry["job_number"])
            for k, v in revert["fields"].items():
                if v in (None, ""):
                    data.pop(k, None)
                else:
                    data[k] = v
            conn.execute(
                "INSERT INTO project_meta (job_number, data, updated_by, updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT(job_number) DO UPDATE SET "
                "data = excluded.data, updated_by = excluded.updated_by, "
                "updated_at = excluded.updated_at",
                (entry["job_number"], json.dumps(data), actor, db.now()))
        else:
            return {"ok": False, "detail": f"Unknown reversal op {op}.",
                    "checks": gate["checks"], "blocked": True,
                    "verdict": f"Unknown reversal op {op}."}
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    reversal_id = db.log_activity(
        actor, entry["job_number"], "reversed",
        f"Reversed: {entry['action']} — {entry['detail'] or ''}".strip(" —"),
        object_kind=entry.get("object_kind"), object_id=entry.get("object_id"),
        reversal_of=activity_id)
    return {"ok": True, "reversal_id": reversal_id, **gate}


def _patch(conn, table: str, rec_id: str, fields: dict[str, Any]) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?",  # noqa: S608 — table is a code constant
                 (*fields.values(), rec_id))


def _insert(conn, table: str, row: dict[str, Any]) -> None:
    row = {k: v for k, v in row.items() if not k.startswith("_")}
    cols = ", ".join(row)
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({','.join('?' * len(row))})",  # noqa: S608
                 tuple(row.values()))
