"""PlanWise-owned data — the PM-entered side of the app, on SQLite (D9).

Vista is read-only truth; this store holds what Vista cannot: the PO register,
change orders (customer + subcontractor), Overview supplements, users, and the
activity trail. Every mutation takes an `actor` and logs it.

Purchase orders carry a cost type so Open/Committed on the Cost Breakdown can
be DERIVED from the register (decision D8): committed for a cost type is the
sum of open POs' remaining value (adjusted amount minus invoiced). One entry
point, no second copy of the number to drift.
"""
from __future__ import annotations

import json
from typing import Any

from . import db

# --- users ------------------------------------------------------------------


def list_users() -> list[dict[str, Any]]:
    conn = db.connect()
    return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY name")]


def ensure_user(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("A user needs a name.")
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
    if row:
        return dict(row)
    rec = {"id": db.new_id(), "name": name, "created_at": db.now()}
    conn.execute("INSERT INTO users (id, name, created_at) VALUES (?,?,?)",
                 (rec["id"], rec["name"], rec["created_at"]))
    conn.commit()
    return rec


# --- helpers ----------------------------------------------------------------

PO_FIELDS = {"po_number", "vendor", "description", "order_date", "ordered_by",
             "original_amount", "adjusted_amount", "cost_type", "status"}
CO_FIELDS = {"kind", "co_number", "cust_co_number", "date_submitted",
             "description", "amount_submitted", "amount_pending",
             "amount_approved", "approved_by", "subcontractor", "status"}
INVOICE_FIELDS = {"invoice_number", "date", "amount"}
_NUMERIC = {"original_amount", "adjusted_amount", "amount",
            "amount_submitted", "amount_pending", "amount_approved"}


def _clean(fields: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in _NUMERIC:
            out[k] = None if v in (None, "") else float(v)
        else:
            out[k] = v if v is None else str(v)
    return out


def _update(table: str, rec_id: str, fields: dict[str, Any]) -> bool:
    if not fields:
        return True
    conn = db.connect()
    sets = ", ".join(f"{k} = ?" for k in fields)
    cur = conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?",  # noqa: S608 — table/keys are code constants
                       (*fields.values(), rec_id))
    conn.commit()
    return cur.rowcount > 0


# --- purchase orders --------------------------------------------------------


def list_pos(job_number: str) -> list[dict[str, Any]]:
    conn = db.connect()
    # Newest first: the add form sits at the top of the card, so a just-added
    # row appears directly beneath it instead of scrolling off the bottom.
    pos = [dict(r) for r in conn.execute(
        "SELECT * FROM purchase_orders WHERE job_number = ? ORDER BY created_at DESC, rowid DESC",
        (job_number,))]
    for po in pos:
        po["invoices"] = [dict(r) for r in conn.execute(
            "SELECT * FROM invoices WHERE po_id = ? ORDER BY created_at", (po["id"],))]
    return pos


def add_po(job_number: str, fields: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
    rec = {"po_number": None, "vendor": None, "description": None,
           "order_date": None, "ordered_by": None, "original_amount": None,
           "adjusted_amount": None, "cost_type": None, "status": "Open"}
    rec.update(_clean(fields, PO_FIELDS))
    rec.update({"id": db.new_id(), "job_number": job_number,
                "created_by": actor, "created_at": db.now()})
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO purchase_orders ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "po.create",
                    f"PO {rec['po_number'] or '(unnumbered)'} · {rec['vendor'] or ''}")
    rec["invoices"] = []
    return rec


def update_po(job_number: str, po_id: str, fields: dict[str, Any],
              actor: str | None = None) -> dict[str, Any] | None:
    clean = _clean(fields, PO_FIELDS)
    if not _update("purchase_orders", po_id, clean):
        return None
    db.log_activity(actor, job_number, "po.update", f"{po_id}: {', '.join(clean)}")
    conn = db.connect()
    po = dict(conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone())
    po["invoices"] = [dict(r) for r in conn.execute(
        "SELECT * FROM invoices WHERE po_id = ? ORDER BY created_at", (po_id,))]
    return po


def delete_po(job_number: str, po_id: str, actor: str | None = None) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM purchase_orders WHERE id = ?", (po_id,))
    conn.commit()
    if cur.rowcount == 0:
        return False
    db.log_activity(actor, job_number, "po.delete", po_id)
    return True


def add_invoice(job_number: str, po_id: str, fields: dict[str, Any],
                actor: str | None = None) -> dict[str, Any] | None:
    conn = db.connect()
    if conn.execute("SELECT 1 FROM purchase_orders WHERE id = ?", (po_id,)).fetchone() is None:
        return None
    rec = {"invoice_number": None, "date": None, "amount": None}
    rec.update(_clean(fields, INVOICE_FIELDS))
    rec.update({"id": db.new_id(), "po_id": po_id,
                "created_by": actor, "created_at": db.now()})
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO invoices ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "invoice.create",
                    f"{rec['invoice_number'] or '(unnumbered)'} on PO {po_id}")
    return rec


def delete_invoice(job_number: str, po_id: str, invoice_id: str,
                   actor: str | None = None) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM invoices WHERE id = ? AND po_id = ?",
                       (invoice_id, po_id))
    conn.commit()
    if cur.rowcount == 0:
        return False
    db.log_activity(actor, job_number, "invoice.delete", invoice_id)
    return True


# --- change orders ----------------------------------------------------------


def list_cos(job_number: str) -> list[dict[str, Any]]:
    conn = db.connect()
    # Newest first — see list_pos.
    return [dict(r) for r in conn.execute(
        "SELECT * FROM change_orders WHERE job_number = ? ORDER BY created_at DESC, rowid DESC",
        (job_number,))]


def add_co(job_number: str, fields: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
    rec = {"kind": "customer", "co_number": None, "cust_co_number": None,
           "date_submitted": None, "description": None, "amount_submitted": None,
           "amount_pending": None, "amount_approved": None, "approved_by": None,
           "subcontractor": None, "status": None}
    rec.update(_clean(fields, CO_FIELDS))
    if rec["kind"] not in ("customer", "subcontractor"):
        rec["kind"] = "customer"
    rec.update({"id": db.new_id(), "job_number": job_number,
                "created_by": actor, "created_at": db.now()})
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO change_orders ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "co.create",
                    f"{rec['kind']} CO {rec['co_number'] or '(unnumbered)'}")
    return rec


def update_co(job_number: str, co_id: str, fields: dict[str, Any],
              actor: str | None = None) -> dict[str, Any] | None:
    clean = _clean(fields, CO_FIELDS)
    clean.pop("kind", None)  # a CO does not change sides after creation
    if not _update("change_orders", co_id, clean):
        return None
    db.log_activity(actor, job_number, "co.update", f"{co_id}: {', '.join(clean)}")
    conn = db.connect()
    return dict(conn.execute("SELECT * FROM change_orders WHERE id = ?", (co_id,)).fetchone())


def delete_co(job_number: str, co_id: str, actor: str | None = None) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM change_orders WHERE id = ?", (co_id,))
    conn.commit()
    if cur.rowcount == 0:
        return False
    db.log_activity(actor, job_number, "co.delete", co_id)
    return True


# --- project meta (PM-entered Overview supplements) -------------------------


def get_meta(job_number: str) -> dict[str, Any]:
    conn = db.connect()
    row = conn.execute("SELECT data FROM project_meta WHERE job_number = ?",
                       (job_number,)).fetchone()
    return json.loads(row["data"]) if row else {}


def patch_meta(job_number: str, fields: dict[str, Any],
               actor: str | None = None) -> dict[str, Any]:
    data = get_meta(job_number)
    for k, v in fields.items():
        if v in (None, ""):
            data.pop(k, None)
        else:
            data[k] = v
    conn = db.connect()
    conn.execute(
        "INSERT INTO project_meta (job_number, data, updated_by, updated_at) "
        "VALUES (?,?,?,?) ON CONFLICT(job_number) DO UPDATE SET "
        "data = excluded.data, updated_by = excluded.updated_by, "
        "updated_at = excluded.updated_at",
        (job_number, json.dumps(data), actor, db.now()))
    conn.commit()
    db.log_activity(actor, job_number, "meta.update", ", ".join(fields))
    return data


# --- activity ---------------------------------------------------------------


def list_activity(job_number: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    conn = db.connect()
    if job_number:
        rows = conn.execute(
            "SELECT * FROM activity WHERE job_number = ? ORDER BY id DESC LIMIT ?",
            (job_number, limit))
    else:
        rows = conn.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


# --- derivations ------------------------------------------------------------


def po_invoiced(po: dict[str, Any]) -> float:
    return sum(i["amount"] or 0 for i in po.get("invoices", []))


def po_remaining(po: dict[str, Any]) -> float | None:
    """Adjusted (falling back to original) minus invoiced. None when the PO
    has no amount yet — an unpriced PO is not a $0 commitment."""
    amt = po.get("adjusted_amount")
    if amt is None:
        amt = po.get("original_amount")
    if amt is None:
        return None
    return amt - po_invoiced(po)


def open_committed_by_cost_type(job_number: str) -> dict[str, float]:
    """Decision D8: committed = Σ remaining value of OPEN POs, per cost type.

    POs without a cost type roll into "Unassigned" so the money stays visible
    instead of vanishing from the breakdown.
    """
    out: dict[str, float] = {}
    for po in list_pos(job_number):
        if (po.get("status") or "Open") != "Open":
            continue
        rem = po_remaining(po)
        if rem is None:
            continue
        key = po.get("cost_type") or "Unassigned"
        out[key] = out.get(key, 0.0) + rem
    return out
