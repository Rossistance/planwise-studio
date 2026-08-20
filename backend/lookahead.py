"""Two-week look ahead (Phase 4, reworked to the field format 2026-08-09).

The sheet the field actually uses is a **day grid**: one row per activity,
fourteen day columns you tick, then per-row requirements, operation notes,
tools and materials. Start/finish dates were the wrong shape; crews plan in
"which days are we on this", and an activity is often on-and-off across the
window rather than one contiguous span.

Tools and materials are ours, not the customer's, so the audience decides the
column list rather than filtering a shared one — the customer sheet is built
from a layout that has no such columns to leak. Work areas are optional
colour coding owned by the job; rows carry an area or don't.

Seeds from the schedule where it can, then gets out of the way: the master
schedule doesn't reach daily granularity and construction changes, so every
line is hand-editable and lines can be added that exist nowhere else. Seeding
is idempotent — re-seeding pulls in newly-overlapping schedule tasks without
touching or duplicating what the PM has already written.

Sharing reuses the RFI/submittal path: an HTML table plus a printable PDF,
drafted into the sender's own Outlook (D10), never sent by the app.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import db, schedule

# Two or three weeks, the PM's choice. Ticks are ALWAYS stored 21 days wide,
# whatever the sheet is currently showing — switching a 3-week look ahead back
# to 2 weeks hides week three, it doesn't throw it away, so the PM can run a
# rolling three-week plan and still send the customer two.
WEEK_DAYS = 7
MIN_WEEKS, MAX_WEEKS = 2, 3
MAX_DAYS = MAX_WEEKS * WEEK_DAYS
DEFAULT_WEEKS = 2
DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# Row columns follow the AEFORM sheet: a customer-facing requirement, an
# internal operation note, and internal tools/materials — per row, not per
# sheet, because they differ by activity.
ITEM_FIELDS = {"description", "crew", "days", "status", "notes",
               "requirements", "tools", "materials", "work_area_id", "sort_order"}
PERIOD_FIELDS = {"notes", "prepared_by", "weeks"}

# Columns stripped from anything the customer receives.
INTERNAL_COLUMNS = ("tools", "materials")

# Distinct enough to tell apart at a glance, legible tinted over both themes.
AREA_COLORS = ["#2F74B8", "#1E7A46", "#B8860B", "#8E44AD",
               "#C23A2E", "#0E7490", "#A0522D", "#4A5568"]
STATUSES = ["Planned", "In Progress", "Complete", "Blocked", "Deferred"]

BLANK_DAYS = "0" * MAX_DAYS


class LookaheadError(ValueError):
    pass


def _week_start(d: date) -> date:
    """The Sunday that begins d's week — the field sheet runs Sun→Sat."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def clamp_weeks(value: Any, upper: int = MAX_WEEKS) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = DEFAULT_WEEKS
    return max(MIN_WEEKS, min(upper, n))


def normalize_days(value: Any) -> str:
    """Coerce anything the UI might send into a 21-day 0/1 string. Always the
    full three weeks, whatever the sheet is showing."""
    if isinstance(value, (list, tuple)):
        bits = "".join("1" if v else "0" for v in value)
    else:
        bits = "".join("1" if c in "1tTyY" else "0" for c in str(value or ""))
    return (bits + BLANK_DAYS)[:MAX_DAYS]


def day_headers(start_date: str, weeks: int = DEFAULT_WEEKS) -> list[dict[str, Any]]:
    start = date.fromisoformat(start_date)
    out = []
    for i in range(clamp_weeks(weeks) * WEEK_DAYS):
        d = start + timedelta(days=i)
        out.append({"index": i, "date": d.isoformat(), "dow": DAY_NAMES[(d.weekday() + 1) % 7],
                    "day": d.day, "weekend": d.weekday() >= 5})
    return out


# --- work areas (optional) ---------------------------------------------------

def list_areas(job_number: str, active_only: bool = False) -> list[dict[str, Any]]:
    conn = db.connect()
    q = "SELECT * FROM lookahead_areas WHERE job_number = ?"
    if active_only:
        q += " AND active = 1"
    return [dict(r) for r in conn.execute(q + " ORDER BY sort_order, rowid", (job_number,))]


def add_area(job_number: str, name: str, color: str | None = None,
             actor: str | None = None) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise LookaheadError("A work area needs a name.")
    existing = list_areas(job_number)
    rec = {"id": db.new_id(), "job_number": job_number, "name": name,
           "color": color or AREA_COLORS[len(existing) % len(AREA_COLORS)],
           "active": 1, "sort_order": len(existing) + 1,
           "created_by": actor, "created_at": db.now()}
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO lookahead_areas ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "lookahead.area.add", name)
    return rec


def update_area(area_id: str, fields: dict[str, Any],
                actor: str | None = None) -> dict[str, Any] | None:
    """Un-ticking "in use" releases the rows that were on that area — they go
    back to no area (and to the default tick colour) immediately. Keeping them
    assigned to something no longer in use just leaves the sheet lying."""
    clean = {k: v for k, v in fields.items() if k in {"name", "color", "active", "sort_order"}}
    if "active" in clean:
        clean["active"] = 1 if clean["active"] in (1, True, "1", "true", "on") else 0
    if not clean:
        return None
    conn = db.connect()
    sets = ", ".join(f"{k} = ?" for k in clean)
    cur = conn.execute(f"UPDATE lookahead_areas SET {sets} WHERE id = ?",  # noqa: S608
                       (*clean.values(), area_id))
    if clean.get("active") == 0:
        conn.execute("UPDATE lookahead_items SET work_area_id = NULL WHERE work_area_id = ?",
                     (area_id,))
    conn.commit()
    if cur.rowcount == 0:
        return None
    return dict(conn.execute("SELECT * FROM lookahead_areas WHERE id = ?", (area_id,)).fetchone())


def delete_area(area_id: str, actor: str | None = None) -> bool:
    """Removing an area unassigns its rows rather than deleting them — the
    work is still planned, it just loses its colour."""
    conn = db.connect()
    row = conn.execute("SELECT * FROM lookahead_areas WHERE id = ?", (area_id,)).fetchone()
    if row is None:
        return False
    conn.execute("UPDATE lookahead_items SET work_area_id = NULL WHERE work_area_id = ?", (area_id,))
    conn.execute("DELETE FROM lookahead_areas WHERE id = ?", (area_id,))
    conn.commit()
    db.log_activity(actor, row["job_number"], "lookahead.area.delete", row["name"])
    return True


# --- periods ----------------------------------------------------------------

def get_or_create_period(job_number: str, start_date: str | None = None,
                         actor: str | None = None) -> dict[str, Any]:
    start = (date.fromisoformat(start_date) if start_date else _week_start(date.today()))
    iso = start.isoformat()
    conn = db.connect()
    row = conn.execute("SELECT * FROM lookahead_periods WHERE job_number = ? AND start_date = ?",
                       (job_number, iso)).fetchone()
    if row:
        return dict(row)
    rec = {"id": db.new_id(), "job_number": job_number, "start_date": iso,
           "notes": None, "prepared_by": actor,
           "created_by": actor, "created_at": db.now()}
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO lookahead_periods ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "lookahead.period", iso)
    return rec


def list_periods(job_number: str) -> list[dict[str, Any]]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM lookahead_periods WHERE job_number = ? ORDER BY start_date DESC",
        (job_number,))]


def update_period(period_id: str, fields: dict[str, Any],
                  actor: str | None = None) -> dict[str, Any] | None:
    clean = {k: v for k, v in fields.items() if k in PERIOD_FIELDS}
    if "weeks" in clean:
        clean["weeks"] = clamp_weeks(clean["weeks"])
    if not clean:
        return None
    conn = db.connect()
    sets = ", ".join(f"{k} = ?" for k in clean)
    cur = conn.execute(f"UPDATE lookahead_periods SET {sets} WHERE id = ?",  # noqa: S608
                       (*clean.values(), period_id))
    conn.commit()
    return get_period(period_id) if cur.rowcount else None


def get_period(period_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM lookahead_periods WHERE id = ?", (period_id,)).fetchone()
    if not row:
        return None
    p = dict(row)
    p["weeks"] = clamp_weeks(p.get("weeks") or DEFAULT_WEEKS)
    p["items"] = list_items(period_id)
    p["areas"] = list_areas(p["job_number"])
    p["max_weeks"] = MAX_WEEKS
    p["end_date"] = (date.fromisoformat(p["start_date"])
                     + timedelta(days=p["weeks"] * WEEK_DAYS - 1)).isoformat()
    p["days"] = day_headers(p["start_date"], p["weeks"])
    return p


# --- items ------------------------------------------------------------------

def list_items(period_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    out = []
    for r in conn.execute("SELECT * FROM lookahead_items WHERE period_id = ? "
                          "ORDER BY sort_order, rowid", (period_id,)):
        item = dict(r)
        item["days"] = normalize_days(item.get("days"))
        out.append(item)
    return out


def add_item(period_id: str, fields: dict[str, Any], task_id: str | None = None,
             actor: str | None = None, at_top: bool = False) -> dict[str, Any]:
    """`at_top` is what the PM typing a new line gets — the newest work is the
    work you're thinking about. Seeding leaves it off so schedule rows keep
    their schedule order."""
    conn = db.connect()
    agg = "MIN(sort_order), 0) - 1" if at_top else "MAX(sort_order), 0) + 1"
    nxt = conn.execute(f"SELECT COALESCE({agg} n FROM lookahead_items "  # noqa: S608
                       "WHERE period_id = ?", (period_id,)).fetchone()["n"]
    rec = {k: None for k in ITEM_FIELDS}
    rec.update({"status": "Planned", "sort_order": nxt, "days": BLANK_DAYS})
    rec.update({k: v for k, v in fields.items() if k in ITEM_FIELDS})
    rec["days"] = normalize_days(rec["days"])
    rec.update({"id": db.new_id(), "period_id": period_id, "task_id": task_id,
                "created_by": actor, "created_at": db.now()})
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO lookahead_items ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    out = dict(conn.execute("SELECT * FROM lookahead_items WHERE id = ?",
                            (rec["id"],)).fetchone())
    period = get_period(period_id) or {}
    out["activity_id"] = db.log_activity(
        actor, period.get("job_number"), "lookahead.item.add",
        rec.get("description") or "(untitled)",
        object_kind="laitem", object_id=rec["id"],
        revert={"op": "laitem.delete", "id": rec["id"]})
    return out


def update_item(item_id: str, fields: dict[str, Any],
                actor: str | None = None) -> dict[str, Any] | None:
    clean = {k: v for k, v in fields.items() if k in ITEM_FIELDS}
    if "days" in clean:
        clean["days"] = normalize_days(clean["days"])
    if not clean:
        return None
    conn = db.connect()
    sets = ", ".join(f"{k} = ?" for k in clean)
    cur = conn.execute(f"UPDATE lookahead_items SET {sets} WHERE id = ?",  # noqa: S608
                       (*clean.values(), item_id))
    conn.commit()
    if cur.rowcount == 0:
        return None
    row = dict(conn.execute("SELECT * FROM lookahead_items WHERE id = ?", (item_id,)).fetchone())
    row["days"] = normalize_days(row.get("days"))
    return row


def toggle_day(item_id: str, index: int, on: bool | None = None,
               actor: str | None = None) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT days FROM lookahead_items WHERE id = ?", (item_id,)).fetchone()
    if row is None or not (0 <= int(index) < MAX_DAYS):
        return None
    bits = list(normalize_days(row["days"]))
    i = int(index)
    bits[i] = ("1" if on else "0") if on is not None else ("0" if bits[i] == "1" else "1")
    return update_item(item_id, {"days": "".join(bits)}, actor=actor)


def delete_item(item_id: str, actor: str | None = None) -> bool:
    conn = db.connect()
    row = conn.execute(
        "SELECT i.*, p.job_number FROM lookahead_items i "
        "JOIN lookahead_periods p ON p.id = i.period_id WHERE i.id = ?",
        (item_id,)).fetchone()
    cur = conn.execute("DELETE FROM lookahead_items WHERE id = ?", (item_id,))
    conn.commit()
    if cur.rowcount == 0:
        return False
    snap = {k: row[k] for k in row.keys() if k != "job_number"}
    db.log_activity(actor, row["job_number"], "lookahead.item.delete",
                    row["description"] or "(untitled)",
                    object_kind="laitem", object_id=item_id,
                    revert={"op": "laitem.recreate", "row": snap})
    return True


def seed_from_schedule(period_id: str, actor: str | None = None) -> dict[str, Any]:
    """Pull schedule tasks overlapping the window in, ticking the days each
    one actually spans.

    Skips tasks already represented (by task_id), so re-seeding after the
    schedule changes adds only what's new and never disturbs hand-written
    lines or edits made to previously seeded ones.
    """
    period = get_period(period_id)
    if period is None:
        raise LookaheadError("No such look-ahead period.")
    # Seeding always fills the full three weeks, not just the weeks on show,
    # so switching a 2-week sheet to 3 reveals real data rather than blanks.
    start = date.fromisoformat(period["start_date"])
    end = start + timedelta(days=MAX_DAYS - 1)
    already = {i["task_id"] for i in period["items"] if i["task_id"]}

    seeded = 0
    for t in schedule.list_tasks(period["job_number"]):
        if t["is_summary"] or t["id"] in already:
            continue
        t_start = date.fromisoformat(t["start"]) if t["start"] else None
        if not t_start:
            continue
        t_end = date.fromisoformat(t["finish"]) if t["finish"] else t_start
        if t_start > end or t_end < start:                 # no overlap
            continue
        bits = ["0"] * MAX_DAYS
        for i in range(MAX_DAYS):
            d = start + timedelta(days=i)
            if t_start <= d <= t_end and d.weekday() < 5:  # work days only
                bits[i] = "1"
        pct = t["percent_complete"] or 0
        add_item(period_id, {
            "description": t["name"],
            "days": "".join(bits),
            "status": "Complete" if pct >= 100 else "In Progress" if pct > 0 else "Planned",
        }, task_id=t["id"], actor=actor)
        seeded += 1

    db.log_activity(actor, period["job_number"], "lookahead.seed",
                    f"{period['start_date']} · {seeded} task(s) from schedule")
    return {"seeded": seeded, "skipped": len(already)}


# --- sharing ----------------------------------------------------------------

def _esc(s: Any) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _load_shareable(period_id: str) -> dict[str, Any]:
    period = get_period(period_id)
    if period is None:
        raise LookaheadError("No such look-ahead period.")
    if not period["items"]:
        raise LookaheadError("This look ahead has no line items yet.")
    return period


def is_internal(audience: str) -> bool:
    """`team` gets the whole sheet; anything else is treated as customer-facing
    and never carries the internal columns."""
    return audience == "team"


def share_weeks(period: dict[str, Any], weeks: int | None) -> int:
    """How many weeks actually go out. Never more than the sheet holds, so a
    two-week look ahead can't be shared as three empty-tailed weeks."""
    held = clamp_weeks(period.get("weeks") or DEFAULT_WEEKS)
    return held if weeks is None else clamp_weeks(weeks, upper=held)


def _span(period: dict[str, Any], weeks: int) -> str:
    end = date.fromisoformat(period["start_date"]) + timedelta(days=weeks * WEEK_DAYS - 1)
    return end.isoformat()


def _areas_in_use(period: dict[str, Any]) -> list[dict[str, Any]]:
    """Only the areas rows actually reference — an unused area is noise on a
    sheet the customer reads."""
    used = {i.get("work_area_id") for i in period["items"]}
    return [a for a in period.get("areas") or [] if a["id"] in used]


def share_html(period_id: str, job_name: str, job_number: str,
               audience: str = "customer", weeks: int | None = None) -> dict[str, str]:
    """Subject + HTML body mirroring the on-screen day grid."""
    period = _load_shareable(period_id)
    internal = is_internal(audience)
    weeks = share_weeks(period, weeks)
    items = period["items"]
    days = day_headers(period["start_date"], weeks)
    areas = {a["id"]: a for a in period.get("areas") or []}
    colors = {k: a["color"] for k, a in areas.items()}
    with_area = bool(_areas_in_use(period))

    cell = "padding:5px 6px;border:1px solid #ddd"

    def tick(color: str) -> str:
        return (f"<span style='display:inline-block;width:16px;height:16px;line-height:16px;"
                f"border-radius:3px;background:{color};color:#fff;font-size:11px'>&#10003;</span>")
    tail = [("requirements", "Requirements for Customer"), ("notes", "Operation Notes")]
    if internal:
        tail += [("tools", "Tools Needed"), ("materials", "Material Needed")]

    area_head = (f"<th style='{cell};background:#f2f1ec;text-align:left'>Work Area</th>"
                 if with_area else "")
    head = "".join(
        f"<th style='{cell};background:{'#f6efe9' if d['weekend'] else '#f2f1ec'};"
        f"text-align:center;font-size:11px;white-space:nowrap'>"
        f"{d['dow']}<br>{d['day']}</th>" for d in days)
    head += "".join(f"<th style='{cell};background:#f2f1ec;text-align:left'>{label}</th>"
                    for _, label in tail)

    rows = ""
    for i in items:
        area = areas.get(i.get("work_area_id"))
        band = area["color"] if area else None
        mark = tick(band or ACCENT)
        marks = "".join(
            f"<td style='{cell};text-align:center;"
            f"background:{'#faf6f2' if d['weekend'] else '#fff'}'>"
            f"{mark if i['days'][d['index']] == '1' else '&nbsp;'}</td>"
            for d in days)
        task = (f"<td style='{cell}"
                + (f";border-left:5px solid {band}" if band else "")
                + f"'>{_esc(i['description'])}</td>")
        area_cell = ""
        if with_area:
            chip = (f"<span style='display:inline-block;width:10px;height:10px;background:{band};"
                    f"border-radius:2px;vertical-align:-1px'></span> " if area else "")
            area_cell = (f"<td style='{cell};font-size:11px'>"
                         f"{chip}{_esc(area['name']) if area else '&nbsp;'}</td>")
        rest = "".join(f"<td style='{cell}'>{_esc(i.get(key)) or '&nbsp;'}</td>"
                       for key, _ in tail)
        rows += f"<tr>{task}{area_cell}{marks}{rest}</tr>"

    label = f"{'Two' if weeks == 2 else 'Three'}-Week"
    body = f"""<p>{label.lower()} look ahead for <strong>{_esc(job_name)}</strong> (job {_esc(job_number)}),
covering {_esc(period['start_date'])} through {_esc(_span(period, weeks))}.
{f"Prepared by {_esc(period['prepared_by'])}." if period.get('prepared_by') else ""}</p>
{f"<p>{_esc(period['notes'])}</p>" if period.get('notes') else ""}
<table style="border-collapse:collapse;font-family:Segoe UI,sans-serif;font-size:12px">
<thead><tr><th style="{cell};background:#f2f1ec;text-align:left">Task Name &amp; Description</th>
{area_head}{head}</tr></thead>
<tbody>{rows}</tbody></table>
<p>This look ahead reflects current planning and is subject to field conditions.</p>"""

    subject = f"{label} Look Ahead — {job_name} ({period['start_date']})"
    return {
        "subject": f"[Internal] {subject}" if internal else subject,
        "html": body,
    }


# --- printable attachment ----------------------------------------------------

_PW, _PH = 792.0, 612.0          # US Letter, landscape
_MARGIN = 40.0

# The WECC letterhead, shared with the change order documents so every page
# that leaves this app carries the same mark. Read once; absent is survivable,
# because a sheet without a logo still tells the field what to do.
_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "wecc-letterhead.jpg"
_LOGO_W = 168.0
_LOGO_H = _LOGO_W * 372.0 / 2550.0        # the banner's own aspect ratio


def _logo_bytes() -> bytes | None:
    try:
        return _LOGO_PATH.read_bytes()
    except OSError:
        return None


def _logo_ops(x: float, y: float, w: float, h: float) -> str:
    return (f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {y:.2f} cm /Im0 Do Q"
            if _logo_bytes() else "")
_BODY_W = _PW - _MARGIN * 2

# The tail columns, in order. Only the widths vary between layouts.
_TAIL_TEAM = [("requirements", "Requirements for Customer"), ("notes", "Operation Notes"),
              ("tools", "Tools Needed"), ("materials", "Material Needed")]
_TAIL_CUSTOMER = _TAIL_TEAM[:2]

# (weeks, internal, with_area) -> (day width, tick box, work-area width, tail widths).
# Three things vary: the customer sheet has no tools/materials, the Work Area
# column only exists when a row uses one, and a third week costs seven more day
# columns. Every row leaves the task column what's left of the 712pt body, and
# each set is sized so that remainder stays readable rather than collapsing.
_LAYOUTS = {
    (2, True,  False): (19.0, 12.0,  0.0, [82.0, 82.0, 75.0, 75.0]),
    (2, True,  True):  (17.5, 12.0, 80.0, [70.0, 70.0, 68.0, 67.0]),
    (2, False, False): (21.0, 12.0,  0.0, [129.0, 129.0]),
    (2, False, True):  (20.0, 12.0, 96.0, [98.0, 98.0]),
    (3, True,  False): (12.5,  9.0,  0.0, [80.0, 80.0, 80.0, 79.5]),
    (3, True,  True):  (12.5,  9.0, 74.0, [68.0, 68.0, 67.0, 67.0]),
    (3, False, False): (13.0,  9.5,  0.0, [139.5, 139.5]),
    (3, False, True):  (13.0,  9.5, 90.0, [109.5, 109.5]),
}

# Table geometry, measured from the top edge down — borders fall out of it.
_TOP = _PH - 84.0
_HEAD_H = 24.0            # minimum; grows if a heading wraps
_MIN_ROW_H = 24.0         # minimum; each row grows to its tallest cell
_PAGE_BOTTOM = 46.0       # keep clear of the footer line


def _layout(internal: bool, with_area: bool, weeks: int) -> tuple[
        float, float, float, float, list[tuple[str, str, float]]]:
    """(task width, work-area width, day width, tick box, tail columns).
    A 0-width work area means no such column at all."""
    weeks = clamp_weeks(weeks)
    day_w, box, area_w, widths = _LAYOUTS[(weeks, internal, with_area)]
    tail = _TAIL_TEAM if internal else _TAIL_CUSTOMER
    cols = [(k, h, w) for (k, h), w in zip(tail, widths)]
    task_w = _BODY_W - area_w - day_w * weeks * WEEK_DAYS - sum(widths)
    return task_w, area_w, day_w, box, cols


# Helvetica advance widths, per 1000 units of point size. Character counts
# were never good enough: "Wed" and "III" are the same length and nowhere near
# the same width, which is what crushed the date headers into their borders and
# ran the task heading through the Work Area rule.
_W: dict[str, int] = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015, "[": 278,
    "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333, "{": 334, "|": 260, "}": 334,
    "~": 584,
}
_W.update(dict.fromkeys("0123456789", 556))
_W.update(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
              [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
               722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611]))
_W.update(zip("abcdefghijklmnopqrstuvwxyz",
              [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
               556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500]))
_BOLD_FACTOR = 1.06          # Helvetica-Bold runs a few percent wider


def text_width(s: Any, size: float, bold: bool = False) -> float:
    total = sum(_W.get(ch, 500) for ch in str(s))
    return total / 1000.0 * size * (_BOLD_FACTOR if bold else 1.0)


def _latin1(s: Any) -> str:
    """Helvetica is latin-1; real typing isn't."""
    t = (str(s or "").replace("—", "-").replace("–", "-")
         .replace("’", "'").replace("“", '"').replace("”", '"'))
    return t.encode("latin-1", "replace").decode("latin-1")


def _esc_pdf(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _pdf_text(s: Any, limit: int) -> str:
    """One line, clipped by character count. Only for the title and strap
    line, which have a whole page width to play with."""
    t = _latin1(s)
    if len(t) > limit:
        t = t[: max(1, limit - 1)] + "."
    return _esc_pdf(t)


def _fit(s: Any, width: float, size: float, bold: bool = False) -> str:
    """One line, shrunk to the column by dropping characters — for the few
    places that genuinely cannot wrap."""
    t = _latin1(s)
    while t and text_width(t, size, bold) > width:
        t = t[:-1]
    return _esc_pdf(t)


def _wrap(s: Any, width: float, size: float, bold: bool = False,
          max_lines: int = 12) -> list[str]:
    """Word wrap on real metrics. Cells wrap and their row grows to fit —
    a requirement the customer can't read is not a requirement."""
    words = _latin1(s).replace("\n", " ").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and text_width(trial, size, bold) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
        # a single word wider than the column has to be broken somewhere
        while text_width(cur, size, bold) > width and len(cur) > 1:
            cut = len(cur)
            while cut > 1 and text_width(cur[:cut], size, bold) > width:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return [_esc_pdf(ln) for ln in lines[:max_lines]]


def _centered(s: Any, x: float, col_w: float, size: float, bold: bool = False) -> float:
    """Left edge that centres `s` in a column starting at x."""
    return x + max(0.0, (col_w - text_width(_latin1(s), size, bold)) / 2)


# The light-theme accent, so a ticked day is the same orange box on paper
# that it is on screen.
ACCENT = "#C7420A"
_BOX = 12.0


def _rule(x1: float, y1: float, x2: float, y2: float, weight: float) -> str:
    """One grid line. Heavier lines are darker — section edges and the table
    border have to read as structure, inner cell lines as separation."""
    grey = 0.42 if weight >= 0.75 else 0.70
    return ("%.2f %.2f %.2f RG %.2f w %.1f %.1f m %.1f %.1f l S"
            % (grey, grey, grey, weight, x1, y1, x2, y2))


def _tick_ops(x: float, by: float, day_w: float, color: str = ACCENT,
              box: float = _BOX) -> list[str]:
    """A ticked day, drawn to match the on-screen checkbox: filled square in
    the row's work-area colour (accent when the row has no area), white check.
    `by` is the box's bottom edge, `box` its size — a three-week sheet has
    narrower day columns and so a smaller box. Helvetica has no check glyph,
    so it's vector."""
    bx = x + (day_w - box) / 2
    k = box / _BOX                                  # scale the check with the box
    return [
        "%.3f %.3f %.3f rg %.1f %.1f %.1f %.1f re f" % (*_hex_rgb(color), bx, by, box, box),
        "1 1 1 RG %.2f w 1 J 1 j %.1f %.1f m %.1f %.1f l %.1f %.1f l S"
        % (1.5 * k, bx + 2.6 * k, by + 6.4 * k, bx + 5.0 * k, by + 3.6 * k,
           bx + 9.4 * k, by + 8.8 * k),
    ]


def _hex_rgb(color: str) -> tuple[float, float, float]:
    c = (color or "").lstrip("#")
    if len(c) != 6:
        return (0.5, 0.5, 0.5)
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def share_pdf(period_id: str, job_name: str, job_number: str,
              audience: str = "customer", weeks: int | None = None) -> bytes:
    """The printable day-grid sheet.

    Hand-authored like the RFI package renderer: content-stream drawing, no
    dependency, and identical in every viewer. The customer sheet is built
    from a column list that simply doesn't contain tools or materials, so
    there is no filter to forget — the data never reaches the page.

    `weeks` lets a three-week sheet go out as two — the PM can plan three
    weeks and still send the customer the near-term two.
    """
    period = _load_shareable(period_id)
    internal = is_internal(audience)
    weeks = share_weeks(period, weeks)
    items = period["items"]
    days = day_headers(period["start_date"], weeks)
    areas = {a["id"]: a for a in period.get("areas") or []}
    colors = {k: a["color"] for k, a in areas.items()}
    with_area = bool(_areas_in_use(period))
    task_w, area_w, day_w, box, cols = _layout(internal, with_area, weeks)

    left = _MARGIN
    grid_w = task_w + area_w + day_w * len(days) + sum(c[2] for c in cols)

    # Every vertical rule, with the weight it's drawn at. The table border and
    # the section edges — task | work area | the weeks | customer text |
    # internal text — read heavier than the cell lines inside them.
    verticals: list[tuple[float, float]] = [(left, 1.0), (left + task_w, 0.8)]
    x = left + task_w
    if with_area:
        x += area_w
        verticals.append((x, 0.8))
    for n in range(len(days)):
        x += day_w
        # a heavier rule at each week boundary, so the weeks read as blocks
        verticals.append((x, 0.8 if n == len(days) - 1 else
                          0.6 if (n + 1) % WEEK_DAYS == 0 else 0.35))
    for n, (_key, _h, width) in enumerate(cols):
        x += width
        last = n == len(cols) - 1
        section = internal and n == 1        # customer-facing | internal divide
        verticals.append((x, 1.0 if last else 0.8 if section else 0.35))

    # --- measure before drawing -------------------------------------------
    # Every text cell wraps, and its row grows to the tallest cell in it, so
    # nothing is ever clipped.
    TASK_F, TASK_L = 8.5, 10.0
    AREA_F, AREA_L = 7.0, 8.5
    TAIL_F, TAIL_L = 7.5, 9.0
    PAD = 9.0

    def measure(item):
        """Wrapped lines per column, plus the height the row needs."""
        area = areas.get(item.get("work_area_id"))
        m = {
            "task": _wrap(item["description"], task_w - 16, TASK_F),
            "area": _wrap(area["name"], area_w - 22, AREA_F) if (with_area and area) else [],
            "tail": [_wrap(item.get(k), w - 10, TAIL_F) for k, _h, w in cols],
            "area_obj": area,
        }
        need = [len(m["task"]) * TASK_L, len(m["area"]) * AREA_L]
        need += [len(c) * TAIL_L for c in m["tail"]]
        m["h"] = max(_MIN_ROW_H, max(need) + PAD)
        return m

    measured = [measure(i) for i in items]

    # Headings wrap too, and the header band grows with them.
    head_task = _wrap("Task Name & Description", task_w - 12, TASK_F, bold=True)
    head_area = _wrap("Work Area", area_w - 10, TAIL_F, bold=True) if with_area else []
    head_cols = [_wrap(h, w - 10, TAIL_F, bold=True) for _k, h, w in cols]
    head_h = max(_HEAD_H,
                 len(head_task) * TASK_L + PAD,
                 len(head_area) * TAIL_L + PAD,
                 max((len(c) * TAIL_L for c in head_cols), default=0) + PAD)

    # Day headers use the longest abbreviation that actually fits the column —
    # "Wed", else "We", else "W". This is what stops the dates running through
    # their own borders on a three-week sheet; two letters are the floor worth
    # aiming for, because "T" alone can't tell Tuesday from Thursday.
    dow_f, dow_len = 6.5, 1
    for n in (3, 2, 1):
        if max(text_width(d["dow"][:n], dow_f, True) for d in days) <= day_w - 2:
            dow_len = n
            break
    num_f = 8.0
    while num_f > 5.5 and text_width("29", num_f, True) > day_w - 2:
        num_f -= 0.25

    # --- paginate on measured heights -------------------------------------
    pages, cur, used = [], [], 0.0
    room = _TOP - head_h - _PAGE_BOTTOM
    for item, m in zip(items, measured):
        if cur and used + m["h"] > room:
            pages.append(cur)
            cur, used = [], 0.0
        cur.append((item, m))
        used += m["h"]
    pages.append(cur)

    streams = []
    for pno, chunk in enumerate(pages, start=1):
        title = (f"{'Two' if weeks == 2 else 'Three'}-Week Look Ahead - " + job_name
                 + (" (Internal)" if internal else ""))
        ops = [
            # WECC's mark, top right, clear of the title. The sheet goes to a
            # customer, so it should look like it came from the company rather
            # than from a piece of software.
            _logo_ops(_PW - 40 - _LOGO_W, _PH - 30 - _LOGO_H, _LOGO_W, _LOGO_H),
            "BT /F2 15 Tf 40 %.1f Td (%s) Tj ET"
            % (_PH - 46, _fit(title, _BODY_W, 15, True)),
            "BT /F1 9.5 Tf 40 %.1f Td (%s) Tj ET"
            % (_PH - 61, _fit(
                f"Job {job_number}   |   {period['start_date']} through {_span(period, weeks)}"
                + (f"   |   Prepared by {period['prepared_by']}" if period.get("prepared_by") else "")
                + f"   |   page {pno} of {len(pages)}", _BODY_W, 9.5)),
            _rule(40, _PH - 68, _PW - 40, _PH - 68, 0.8),
        ]
        head_bottom = _TOP - head_h
        heights = [m["h"] for _i, m in chunk]
        tops, y = [], head_bottom
        for h in heights:
            tops.append(y)
            y -= h
        bottom = y

        # --- fills, bottom layer up ------------------------------------------
        for idx, h in enumerate(heights):
            if idx % 2 == 1:
                ops.append("0.972 0.970 0.960 rg %.1f %.1f %.1f %.1f re f"
                           % (left, tops[idx] - h, grid_w, h))
        x = left + task_w + area_w
        for d in days:                       # weekend columns band the full table
            if d["weekend"]:
                ops.append("0.960 0.930 0.900 rg %.1f %.1f %.1f %.1f re f"
                           % (x, bottom, day_w, head_bottom - bottom))
            x += day_w
        ops.append("0.930 0.930 0.910 rg %.1f %.1f %.1f %.1f re f"
                   % (left, head_bottom, grid_w, head_h))
        x = left + task_w + area_w
        for d in days:
            if d["weekend"]:
                ops.append("0.895 0.855 0.815 rg %.1f %.1f %.1f %.1f re f"
                           % (x, head_bottom, day_w, head_h))
            x += day_w

        # --- header text ------------------------------------------------------
        for n, line in enumerate(head_task):
            ops.append("0 0 0 rg BT /F2 %.1f Tf %.1f %.1f Td (%s) Tj ET"
                       % (TASK_F, left + 6, _TOP - 12 - n * TASK_L, line))
        x = left + task_w
        if with_area:
            for n, line in enumerate(head_area):
                ops.append("0 0 0 rg BT /F2 %.1f Tf %.1f %.1f Td (%s) Tj ET"
                           % (TAIL_F, x + 5, _TOP - 11 - n * TAIL_L, line))
            x += area_w
        for d in days:
            dow = d["dow"][:dow_len]
            ops.append("0 0 0 rg BT /F2 %.1f Tf %.1f %.1f Td (%s) Tj ET"
                       % (dow_f, _centered(dow, x, day_w, dow_f, True), _TOP - 10,
                          _esc_pdf(_latin1(dow))))
            ops.append("0 0 0 rg BT /F2 %.1f Tf %.1f %.1f Td (%s) Tj ET"
                       % (num_f, _centered(d["day"], x, day_w, num_f, True), _TOP - 20,
                          str(d["day"])))
            x += day_w
        for lines, (_k, _h, width) in zip(head_cols, cols):
            for n, line in enumerate(lines):
                ops.append("0 0 0 rg BT /F2 %.1f Tf %.1f %.1f Td (%s) Tj ET"
                           % (TAIL_F, x + 5, _TOP - 11 - n * TAIL_L, line))
            x += width

        # --- row content ------------------------------------------------------
        for idx, (item, m) in enumerate(chunk):
            band_top, h = tops[idx], heights[idx]
            area = m["area_obj"]
            color = area["color"] if area else None
            if color:
                ops.append("%.3f %.3f %.3f rg %.1f %.1f 4 %.1f re f"
                           % (*_hex_rgb(color), left, band_top - h, h))
            for n, line in enumerate(m["task"]):
                ops.append("0 0 0 rg BT /F1 %.1f Tf %.1f %.1f Td (%s) Tj ET"
                           % (TASK_F, left + 9, band_top - 12 - n * TASK_L, line))
            x = left + task_w
            if with_area:
                if area:
                    ops.append("%.3f %.3f %.3f rg %.1f %.1f 7 7 re f"
                               % (*_hex_rgb(color), x + 5, band_top - 16))
                    for n, line in enumerate(m["area"]):
                        ops.append("0 0 0 rg BT /F1 %.1f Tf %.1f %.1f Td (%s) Tj ET"
                                   % (AREA_F, x + 16, band_top - 11 - n * AREA_L, line))
                x += area_w
            # Ticks sit against the top of the band, level with the first line
            # of text, so a tall row doesn't leave them floating in the middle.
            for d in days:
                if item["days"][d["index"]] == "1":
                    ops.extend(_tick_ops(x, band_top - 6 - box, day_w, color or ACCENT, box))
                x += day_w
            for lines, (_k, _h, width) in zip(m["tail"], cols):
                for n, line in enumerate(lines):
                    ops.append("0 0 0 rg BT /F1 %.1f Tf %.1f %.1f Td (%s) Tj ET"
                               % (TAIL_F, x + 5, band_top - 11 - n * TAIL_L, line))
                x += width

        # --- grid, drawn last so nothing paints over it ------------------------
        for xx, weight in verticals:
            ops.append(_rule(xx, _TOP, xx, bottom, weight))
        ops.append(_rule(left, _TOP, left + grid_w, _TOP, 1.0))
        ops.append(_rule(left, head_bottom, left + grid_w, head_bottom, 1.0))
        for yy in tops[1:]:
            ops.append(_rule(left, yy, left + grid_w, yy, 0.35))
        ops.append(_rule(left, bottom, left + grid_w, bottom, 1.0))

        # No legend: the Work Area column names the area on every row it
        # applies to, which a footer key would only repeat.
        ops.append("0.45 0.45 0.45 rg BT /F1 8 Tf 40 26 Td (%s) Tj ET"
                   % _fit("Reflects current planning and is subject to field conditions.",
                          _BODY_W, 8))
        streams.append("\n".join(ops).encode("latin-1", "replace"))

    return _write_pdf(streams)


def _write_pdf(streams: list[bytes]) -> bytes:
    import io

    n_pages = len(streams)
    first_content = 3 + n_pages
    font_regular = first_content + n_pages
    font_bold = font_regular + 1
    logo = _logo_bytes()
    logo_obj = font_bold + 1 if logo else None

    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [%s] /Count %d >>"
         % (" ".join(f"{3 + i} 0 R" for i in range(n_pages)), n_pages)).encode(),
    ]
    xobj = f" /XObject << /Im0 {logo_obj} 0 R >>" if logo else ""
    for i in range(n_pages):
        objs.append((
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PW:.0f} {_PH:.0f}] "
            f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >>{xobj} >> "
            f"/Contents {first_content + i} 0 R >>").encode())
    for s in streams:
        objs.append(b"<< /Length " + str(len(s)).encode() + b" >>\nstream\n" + s + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    if logo:
        objs.append((b"<< /Type /XObject /Subtype /Image /Width 2550 /Height 372 "
                     b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                     b"/Length " + str(len(logo)).encode() + b" >>\nstream\n")
                    + logo + b"\nendstream")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
              f"startxref\n{xref}\n%%EOF".encode())
    return out.getvalue()
