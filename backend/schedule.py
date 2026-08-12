"""Schedule: import, storage, and critical-path analysis (Phase 4).

Three ways in, per the walkthrough: a customer's (or our own) **MPP**, an
**MSPDI XML** export, and **manual entry**.

On MPP: MPXJ ships the Java libraries that can read the binary format, but
reading one needs a JVM. This machine has none (probed 2026-08-08), so
``parse_mpp`` raises with install guidance rather than pretending. MSPDI XML
is pure Python and always works — which is also the fallback we tell people
about. The 2.0 line could never read .mpp at all; that was a browser limit,
not a format one, so the capability is real as soon as a JRE exists.
"""
from __future__ import annotations

import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Any

from . import db

MSPDI_NS = {"m": "http://schemas.microsoft.com/project"}
HOURS_PER_DAY = 8.0

FIELDS = {"name", "start", "finish", "duration_days", "percent_complete",
          "outline_level", "is_milestone", "is_summary", "predecessors", "sort_order",
          # Added with the typed-link rebuild. `wbs` is what every real source
          # carries and the old schema dropped; the constraint/actual/deadline
          # fields are what an MS Project or Smartsheet export holds.
          "wbs", "notes", "duration_unit", "constraint_type", "constraint_date",
          "actual_start", "actual_finish", "deadline", "collapsed"}

# Constraints an imported schedule can carry. Deliberately a short list: these
# are the ones that change a date, and the ones every source expresses.
CONSTRAINTS = ("ASAP", "ALAP", "SNET", "SNLT", "FNET", "FNLT", "MSO", "MFO")


class ScheduleError(ValueError):
    pass


# --- parsing ----------------------------------------------------------------

def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(v[:19] if "T" in v else v, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _duration_days(value: str | None) -> float | None:
    """MSPDI durations are ISO-8601 like 'PT40H0M0S' or 'P5D'.

    Zero is a real duration, not a missing one: a milestone is exactly 'PT0H'.
    This used to end in `or None`, which turned every milestone's duration into
    NULL and sent it down the start/finish fallback in analyze() — where
    `_weekdays_between(start, finish) + 1` gives a milestone a length of one
    day and pushes everything downstream of it a day late.
    """
    if not value:
        return None
    m = re.match(r"^P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?"
                 r"(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$", value.strip())
    if not m:
        return None
    days, hours, minutes, seconds = (float(g or 0) for g in m.groups())
    total_hours = days * HOURS_PER_DAY + hours + minutes / 60 + seconds / 3600
    return round(total_hours / HOURS_PER_DAY, 3)


def parse_mspdi(data: bytes) -> list[dict[str, Any]]:
    """Microsoft Project XML (MSPDI) -> task dicts. Pure stdlib."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ScheduleError(f"Not valid XML: {exc}") from exc

    tasks_el = root.find("m:Tasks", MSPDI_NS)
    if tasks_el is None:
        raise ScheduleError(
            "This XML has no <Tasks> section — it does not look like a "
            "Microsoft Project (MSPDI) export.")

    def text(el, tag):
        found = el.find(f"m:{tag}", MSPDI_NS)
        return found.text if found is not None else None

    out: list[dict[str, Any]] = []
    for i, t in enumerate(tasks_el.findall("m:Task", MSPDI_NS)):
        uid = (text(t, "UID") or "").strip()
        name = (text(t, "Name") or "").strip()
        # UID 0 is Project Summary; unnamed rows are structural filler
        if not uid or uid == "0" or not name:
            continue
        preds = []
        for link in t.findall("m:PredecessorLink", MSPDI_NS):
            puid = text(link, "PredecessorUID")
            if not puid:
                continue
            lag_raw = text(link, "LinkLag")
            lag_days = 0.0
            try:
                # LinkLag is in tenths of a minute
                lag_days = round(float(lag_raw or 0) / 10 / 60 / HOURS_PER_DAY, 2)
            except (TypeError, ValueError):
                pass
            # Type 0=FF 1=FS 2=SF 3=SS. This was read and thrown away, so every
            # dependency in every imported schedule became finish-to-start —
            # a start-to-start pair silently gained its predecessor's whole
            # duration.
            ltype = _MSPDI_LINK_TYPES.get((text(link, "Type") or "1").strip(), "FS")
            preds.append({"pred_external_id": puid, "link_type": ltype,
                          "lag_days": lag_days})

        out.append({
            "external_id": uid,
            "name": name,
            "start": _iso_date(text(t, "Start")),
            "finish": _iso_date(text(t, "Finish")),
            "duration_days": _duration_days(text(t, "Duration")),
            "percent_complete": float(text(t, "PercentComplete") or 0),
            "outline_level": int(text(t, "OutlineLevel") or 1),
            "is_milestone": 1 if (text(t, "Milestone") or "0") == "1" else 0,
            "is_summary": 1 if (text(t, "Summary") or "0") == "1" else 0,
            "wbs": (text(t, "WBS") or None),
            "predecessors": _preds_to_text(preds) or None,
            "links": preds,
            "sort_order": i,
        })
    if not out:
        raise ScheduleError("The XML parsed but contained no schedule tasks.")
    return out


# MSPDI's PredecessorLink/Type codes.
_MSPDI_LINK_TYPES = {"0": "FF", "1": "FS", "2": "SF", "3": "SS"}


# --- human-written durations and dates ----------------------------------------
# What appears in a printed schedule, an xlsx export, or a typed cell.

_DURATION_RE = re.compile(
    r"^\s*(?P<qty>-?\d+(?:[.,]\d+)?)\s*(?P<unit>[A-Za-z]*)\s*\??\s*$")

# Elapsed units run through weekends; working units don't. Keeping them apart
# matters: a 60-eday delivery lead converted to 60 working days lands twelve
# weeks late.
_DURATION_UNITS = {
    "": ("d", 1.0), "d": ("d", 1.0), "day": ("d", 1.0), "days": ("d", 1.0),
    "w": ("w", 5.0), "wk": ("w", 5.0), "wks": ("w", 5.0),
    "week": ("w", 5.0), "weeks": ("w", 5.0),
    "mon": ("mo", 20.0), "mons": ("mo", 20.0),
    "month": ("mo", 20.0), "months": ("mo", 20.0),
    "h": ("h", 1.0 / HOURS_PER_DAY), "hr": ("h", 1.0 / HOURS_PER_DAY),
    "hrs": ("h", 1.0 / HOURS_PER_DAY), "hour": ("h", 1.0 / HOURS_PER_DAY),
    "hours": ("h", 1.0 / HOURS_PER_DAY),
    "ed": ("ed", 1.0), "eday": ("ed", 1.0), "edays": ("ed", 1.0),
    "ewk": ("ew", 7.0), "ewks": ("ew", 7.0), "eweek": ("ew", 7.0),
    "eweeks": ("ew", 7.0), "emon": ("emo", 30.0), "emons": ("emo", 30.0),
}


def parse_duration_text(raw: Any) -> tuple[float | None, str | None]:
    """'5 days' / '20 wks' / '60 edays' / '0 days' -> (working days, unit).

    Returns the duration expressed in working days plus the unit it was
    written in, so an elapsed duration can be recognised later rather than
    silently becoming a working one. `None` for anything unreadable — a
    duration we can't parse is missing, not zero.
    """
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return float(raw), "d"
    m = _DURATION_RE.match(str(raw))
    if not m:
        return None, None
    unit_raw = m.group("unit").lower()
    if unit_raw not in _DURATION_UNITS:
        return None, None
    unit, factor = _DURATION_UNITS[unit_raw]
    try:
        qty = float(m.group("qty").replace(",", "."))
    except ValueError:
        return None, None
    return round(qty * factor, 3), unit


# "Tue 12/6/22", "12/6/22", "2024-12-06", "6 Dec 24", and the ISO datetimes an
# xlsx cell hands over.
_DATE_FORMATS = ("%a %m/%d/%y", "%a %m/%d/%Y", "%m/%d/%y", "%m/%d/%Y",
                 "%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y", "%d %b %y", "%d %b %Y",
                 "%a %d/%m/%y", "%m-%d-%y", "%m-%d-%Y")


def parse_date_text(raw: Any) -> tuple[str | None, bool]:
    """Parse a printed date. Returns (ISO date, weekday_matched).

    A printed MS Project date carries its own checksum: "Tue 12/6/22" states
    the weekday, so if the parsed date isn't a Tuesday something upstream went
    wrong — a mis-clustered row, a column read from the wrong band. The caller
    turns a False into a warning rather than guessing, because a date that is
    wrong but plausible is the worst thing a schedule importer can produce.
    """
    if raw is None:
        return None, True
    if isinstance(raw, datetime):
        return raw.date().isoformat(), True
    if isinstance(raw, date):
        return raw.isoformat(), True

    s = str(raw).strip().replace(" ", " ")
    if not s:
        return None, True
    s = re.sub(r"\s+", " ", s)
    stated_dow = None
    m = re.match(r"^(?P<dow>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", s, re.I)
    if m:
        stated_dow = m.group("dow").lower()

    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if stated_dow:
            actual = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[d.weekday()]
            return d.isoformat(), actual == stated_dow
        return d.isoformat(), True

    # Last resort: a bare ISO datetime from a spreadsheet cell.
    iso = _iso_date(s)
    return iso, True


def _preds_to_text(links: list[dict[str, Any]]) -> str:
    """Render typed links back into the text the grid shows and accepts.

    Round-trips with `_parse_preds`, so what somebody sees in the Predecessors
    column is exactly what they could have typed.
    """
    parts = []
    for lk in links:
        s = str(lk["pred_external_id"])
        if lk.get("link_type") and lk["link_type"] != "FS":
            s += lk["link_type"]
        lag = float(lk.get("lag_days") or 0)
        if lag:
            s += f"{'+' if lag > 0 else '-'}{abs(lag):g}d"
        parts.append(s)
    return ",".join(parts)


def mpp_available() -> tuple[bool, str]:
    """Can this machine read a binary .mpp? (MPXJ needs a JVM.)"""
    global _MPP_STATE
    if _MPP_STATE is not None:
        return _MPP_STATE
    try:
        import jpype  # noqa: F401
        import mpxj  # noqa: F401
    except ImportError:
        _MPP_STATE = (False, "MPXJ is not installed (pip install mpxj JPype1).")
        return _MPP_STATE
    try:
        import jpype
        if not jpype.isJVMStarted():
            jpype.getDefaultJVMPath()
        _MPP_STATE = (True, "ready")
    except Exception as exc:  # noqa: BLE001
        _MPP_STATE = (False, (
            "No Java runtime found. Reading binary .mpp needs a JRE — install "
            "one (e.g. Temurin 17) and restart PlanWise. Until then, export "
            "the schedule from Microsoft Project as XML (File > Save As > "
            f"XML) and import that. [{type(exc).__name__}]"))
    return _MPP_STATE


# Cached: whether a JVM exists cannot change without restarting the process,
# and this is now on the health endpoint, which Render polls constantly.
_MPP_STATE: tuple[bool, str] | None = None


def parse_mpp(data: bytes) -> list[dict[str, Any]]:
    """Binary .mpp via MPXJ. Honest failure when no JVM is present."""
    ok, detail = mpp_available()
    if not ok:
        raise ScheduleError(detail)

    import pathlib
    import shutil
    import tempfile

    import jpype
    import mpxj

    if not jpype.isJVMStarted():
        jars = [str(p) for p in pathlib.Path(mpxj.__file__).parent.rglob("*.jar")]
        jpype.startJVM(classpath=jars)

    from net.sf.mpxj.reader import UniversalProjectReader  # type: ignore

    # MPXJ reads from a path, not a stream, so the upload has to touch disk.
    # The directory is removed afterwards — it used to be left behind on every
    # import, quietly filling the temp folder with copies of the schedule.
    workdir = tempfile.mkdtemp(prefix="planwise_mpp_")
    try:
        tmp = pathlib.Path(workdir) / "schedule.mpp"
        tmp.write_bytes(data)
        project = UniversalProjectReader().read(str(tmp))

        def as_date(v):
            return _iso_date(str(v)[:10]) if v is not None else None

        out = []
        for i, t in enumerate(project.getTasks()):
            name = t.getName()
            if not name or t.getUniqueID() is None:
                continue
            dur = t.getDuration()
            preds = []
            for rel in (t.getPredecessors() or []):
                tgt = rel.getTargetTask()
                if tgt is not None:
                    preds.append(str(tgt.getUniqueID()))
            out.append({
                "external_id": str(t.getUniqueID()),
                "name": str(name),
                "start": as_date(t.getStart()),
                "finish": as_date(t.getFinish()),
                "duration_days": round(dur.getDuration(), 3) if dur is not None else None,
                "percent_complete": float(t.getPercentageComplete() or 0),
                "outline_level": int(t.getOutlineLevel() or 1),
                "is_milestone": 1 if t.getMilestone() else 0,
                "is_summary": 1 if t.getSummary() else 0,
                "predecessors": ",".join(preds) or None,
                "sort_order": i,
            })
    finally:
        # Windows can still hold the file open through the JVM; a leftover
        # temp directory is not worth failing an otherwise good import over.
        shutil.rmtree(workdir, ignore_errors=True)
    if not out:
        raise ScheduleError("The .mpp parsed but contained no tasks.")
    return out


def parse_schedule(filename: str, data: bytes) -> tuple[list[dict[str, Any]], str]:
    """Legacy shape: (tasks, source). Kept for callers that predate links."""
    parsed = parse_any(filename, data)
    return parsed["tasks"], parsed["source"]


def parse_any(filename: str, data: bytes) -> dict[str, Any]:
    """Read any supported schedule file -> {tasks, links, warnings, source}.

    Extension first, then a content sniff, so a file renamed on its way through
    email still imports. Every branch returns the same shape, which is what
    lets one staging path serve five different formats.
    """
    name = (filename or "").lower()

    def wrap(result: dict[str, Any], source: str) -> dict[str, Any]:
        return {"tasks": result["tasks"], "links": result.get("links") or [],
                "warnings": result.get("warnings") or [], "source": source}

    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        from . import schedule_pdf
        return wrap(schedule_pdf.parse_pdf(data), "pdf")
    if name.endswith(".mpp") or data[:4] == b"\xd0\xcf\x11\xe0":
        return wrap({"tasks": parse_mpp(data)}, "mpp")
    if name.endswith((".xlsx", ".xlsm")) or data[:4] == b"PK\x03\x04":
        from . import schedule_tab
        return wrap(schedule_tab.parse_table(data, name or "schedule.xlsx"), "xlsx")
    if name.endswith(".csv"):
        from . import schedule_tab
        return wrap(schedule_tab.parse_table(data, name), "csv")
    if name.endswith((".xml", ".mspdi")) or data.lstrip()[:1] == b"<":
        return wrap({"tasks": parse_mspdi(data)}, "mspdi")
    # A CSV with an odd extension is still a CSV; try it before refusing.
    if b"," in data[:2048] or b";" in data[:2048]:
        from . import schedule_tab
        return wrap(schedule_tab.parse_table(data, "schedule.csv"), "csv")
    raise ScheduleError(
        "Unsupported schedule file. PlanWise reads Microsoft Project (.mpp), "
        "an MSPDI .xml export, a printed schedule PDF, or a spreadsheet "
        "(.xlsx/.csv) such as a Smartsheet export.")


# --- storage ----------------------------------------------------------------

def list_tasks(job_number: str) -> list[dict[str, Any]]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM schedule_tasks WHERE job_number = ? "
        "ORDER BY sort_order, rowid", (job_number,))]


def import_tasks(job_number: str, tasks: list[dict[str, Any]], source: str,
                 mode: str = "replace", actor: str | None = None,
                 commit: bool = True) -> dict[str, Any]:
    """Replace the schedule, or merge onto it by external_id.

    Merge updates authoritative fields on tasks the source still knows about
    and leaves locally-added ones alone — re-importing a revised schedule
    must not orphan work the PM added by hand.

    **Replace no longer means delete-everything.** It used to, and the row ids
    it threw away were the ids the look ahead points at (`lookahead_items
    .task_id`) and, now, the ids dependencies hang off. A re-import silently
    orphaned every seeded look-ahead item and would have taken every link with
    it. Replace now reconciles instead: tasks the file still knows about are
    updated *in place* so their ids survive, genuinely new ones are inserted,
    and only previously-IMPORTED rows the file has dropped are deleted. Rows
    somebody added by hand always survive both modes — that promise is the
    whole point of having two modes at all.

    `commit=False` lets a caller wrap this in a larger transaction, which the
    staged-import commit needs: tasks and their links have to land together or
    a crash leaves a schedule whose dependencies quietly went missing.
    """
    if mode not in ("replace", "merge"):
        raise ScheduleError("mode must be 'replace' or 'merge'.")
    conn = db.connect()
    existing = {t["external_id"]: t for t in list_tasks(job_number) if t["external_id"]}

    added = updated = 0
    seen: set[str] = set()
    for t in tasks:
        ext = t.get("external_id")
        prior = existing.get(ext) if ext else None
        if ext:
            seen.add(str(ext))
        if prior:
            sets = ", ".join(f"{k} = ?" for k in FIELDS if k in t)
            if sets:
                conn.execute(f"UPDATE schedule_tasks SET {sets} WHERE id = ?",  # noqa: S608
                             (*[t[k] for k in FIELDS if k in t], prior["id"]))
            updated += 1
        else:
            rec = {k: t.get(k) for k in FIELDS}
            rec.update({"id": t.get("id") or db.new_id(), "job_number": job_number,
                        "external_id": ext, "source": source,
                        "created_by": actor, "created_at": db.now()})
            cols = ", ".join(rec)
            conn.execute(
                f"INSERT INTO schedule_tasks ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                tuple(rec.values()))
            added += 1

    removed = 0
    if mode == "replace":
        # Only rows that came from a file and are no longer in it. Hand-added
        # rows have source='manual' and are never swept.
        for ext, row in existing.items():
            if str(ext) in seen or (row["source"] or "manual") == "manual":
                continue
            conn.execute("DELETE FROM schedule_tasks WHERE id = ?", (row["id"],))
            removed += 1

    # Drop the dependencies this file supplied last time before re-deriving
    # them, or a link the revised schedule REMOVED would survive forever (and,
    # worse, an edited lag would lose to the old row on the unique index).
    # Hand-drawn links and accepted inferred ones are somebody's decision, not
    # this file's, so they stay.
    conn.execute(
        "DELETE FROM schedule_links WHERE job_number = ? AND inferred = 0 "
        "AND COALESCE(source, 'manual') NOT IN ('manual')", (job_number,))

    # Whatever arrived as predecessor TEXT becomes real link rows here — the
    # engine reads nothing else. Typed links supplied alongside the tasks are
    # inserted separately by the caller (see commit_import).
    made = sync_links_from_text(job_number, source=source, actor=actor, commit=False)

    if commit:
        conn.commit()
    db.log_activity(actor, job_number, "schedule.import",
                    f"{source} · {added} added, {updated} updated, "
                    f"{removed} removed ({mode})")
    return {"added": added, "updated": updated, "removed": removed,
            "links": made, "mode": mode, "source": source}


# --- dependencies -------------------------------------------------------------

LINK_TYPES = ("FS", "SS", "FF", "SF")


def list_links(job_number: str) -> list[dict[str, Any]]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM schedule_links WHERE job_number = ?", (job_number,))]


def add_link(job_number: str, pred_id: str, succ_id: str, *, link_type: str = "FS",
             lag_days: float = 0.0, source: str = "manual", inferred: bool = False,
             confidence: float | None = None, actor: str | None = None,
             commit: bool = True) -> dict[str, Any] | None:
    """One dependency. Returns None when it would be a duplicate or a self-link.

    A task depending on itself is always a data error, never an intention, and
    it would make the forward pass chase its own tail.
    """
    link_type = (link_type or "FS").upper()
    if link_type not in LINK_TYPES:
        raise ScheduleError(f"Link type must be one of {', '.join(LINK_TYPES)}.")
    if pred_id == succ_id:
        return None
    rec = {"id": db.new_id(), "job_number": job_number, "pred_id": pred_id,
           "succ_id": succ_id, "link_type": link_type,
           "lag_days": float(lag_days or 0), "source": source,
           "inferred": 1 if inferred else 0, "confidence": confidence,
           "confirmed_at": db.now() if inferred else None,
           "confirmed_by": actor if inferred else None,
           "created_at": db.now()}
    conn = db.connect()
    try:
        cols = ", ".join(rec)
        conn.execute(f"INSERT INTO schedule_links ({cols}) "  # noqa: S608
                     f"VALUES ({','.join('?' * len(rec))})", tuple(rec.values()))
    except sqlite3.IntegrityError:
        return None                     # already linked, or a task that vanished
    if commit:
        conn.commit()
    return rec


def delete_link(job_number: str, link_id: str, actor: str | None = None) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM schedule_links WHERE id = ? AND job_number = ?",
                       (link_id, job_number))
    conn.commit()
    if cur.rowcount:
        db.log_activity(actor, job_number, "schedule.link.delete", link_id)
    return cur.rowcount > 0


def sync_links_from_text(job_number: str, source: str = "manual",
                         actor: str | None = None, commit: bool = True) -> int:
    """Materialise the `predecessors` text column into real link rows.

    The text column is an input format — what you type in the grid, what an
    xlsx "Predecessors" column holds — and this is the one place it becomes
    something the engine reads. Idempotent: existing links are left alone and
    duplicates are refused by the unique index, so running it twice is a no-op.

    References that don't resolve to a task in this job are skipped rather than
    guessed at; they show up as a task with fewer predecessors than its text
    claims, which is visible, instead of a link to the wrong task, which isn't.
    """
    tasks = list_tasks(job_number)
    by_ext = {str(t["external_id"]): t["id"] for t in tasks if t["external_id"]}
    # Hand-added tasks have no external_id; let people reference them by name
    # so a manual task can be a predecessor at all (it never could before).
    by_name = {(t["name"] or "").strip().lower(): t["id"] for t in tasks if t["name"]}

    made = 0
    for t in tasks:
        if not t["predecessors"]:
            continue
        for ext, ltype, lag in _parse_preds(t["predecessors"]):
            pred = by_ext.get(ext) or by_name.get(ext.strip().lower())
            if not pred or pred == t["id"]:
                continue
            if add_link(job_number, pred, t["id"], link_type=ltype, lag_days=lag,
                        source=source, actor=actor, commit=False):
                made += 1
    if commit:
        db.connect().commit()
    return made


# --- staged imports -----------------------------------------------------------
# Parse, show, then commit. A schedule import replaces the plan the whole team
# works to, so it gets the same "validated before it is trusted" treatment as
# the Vista extract (D28) — and a PDF import produces *candidate* dependencies
# traced from arrows, which have to be looked at by a human before they can
# move a single date. The payload is where those candidates wait; they never
# reach schedule_links unaccepted.

def stage_import(job_number: str, filename: str, data: bytes,
                 actor: str | None = None) -> dict[str, Any]:
    import json

    parsed = parse_any(filename, data)
    rec = {"id": db.new_id(), "job_number": job_number, "filename": filename,
           "source": parsed["source"],
           "payload": json.dumps({"tasks": parsed["tasks"], "links": parsed["links"],
                                  "warnings": parsed["warnings"]}),
           "status": "staged", "created_at": db.now(), "created_by": actor,
           "settled_at": None, "settled_by": None}
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO schedule_imports ({cols}) "  # noqa: S608
                 f"VALUES ({','.join('?' * len(rec))})", tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "schedule.import.staged",
                    f"{filename} · {len(parsed['tasks'])} tasks, "
                    f"{len(parsed['links'])} proposed links")
    return summarise_import(rec["id"])


def get_import(import_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM schedule_imports WHERE id = ?",
                       (import_id,)).fetchone()
    return dict(row) if row else None


def summarise_import(import_id: str) -> dict[str, Any]:
    import json

    rec = get_import(import_id)
    if rec is None:
        raise ScheduleError("That import is no longer available.")
    payload = json.loads(rec["payload"])
    tasks = payload.get("tasks", [])
    links = payload.get("links", [])
    by_ext = {t["external_id"]: t.get("name") for t in tasks}
    for lk in links:
        lk["pred_name"] = by_ext.get(lk["pred_external_id"])
        lk["succ_name"] = by_ext.get(lk["succ_external_id"])
        lk["id"] = f"{lk['pred_external_id']}>{lk['succ_external_id']}"
    return {
        "id": rec["id"], "job_number": rec["job_number"],
        "filename": rec["filename"], "source": rec["source"],
        "status": rec["status"], "created_at": rec["created_at"],
        "tasks": tasks, "links": links,
        "warnings": payload.get("warnings", []),
        "counts": {
            "tasks": len(tasks),
            "milestones": sum(1 for t in tasks if t.get("is_milestone")),
            "summaries": sum(1 for t in tasks if t.get("is_summary")),
            "dated": sum(1 for t in tasks if t.get("start")),
            "links": len(links),
            "inferred_links": sum(1 for lk in links if lk.get("inferred")),
        },
    }


def commit_import(import_id: str, mode: str = "replace",
                  accepted_link_ids: list[str] | None = None,
                  actor: str | None = None) -> dict[str, Any]:
    """Apply a staged import: tasks, then the dependencies that were accepted.

    Both in one transaction — a crash between them would leave a schedule whose
    dependencies had quietly gone missing, which looks exactly like a schedule
    that never had any.
    """
    import json

    rec = get_import(import_id)
    if rec is None:
        raise ScheduleError("That import is no longer available.")
    if rec["status"] != "staged":
        raise ScheduleError(f"That import was already {rec['status']}.")

    payload = json.loads(rec["payload"])
    job = rec["job_number"]
    accepted = set(accepted_link_ids or [])

    conn = db.connect()
    try:
        result = import_tasks(job, payload.get("tasks", []), rec["source"],
                              mode=mode, actor=actor, commit=False)
        by_ext = {str(t["external_id"]): t["id"]
                  for t in list_tasks(job) if t["external_id"]}
        made = 0
        for lk in payload.get("links", []):
            key = f"{lk['pred_external_id']}>{lk['succ_external_id']}"
            if key not in accepted:
                continue
            p, s = by_ext.get(str(lk["pred_external_id"])), by_ext.get(str(lk["succ_external_id"]))
            if not p or not s:
                continue
            if add_link(job, p, s, link_type=lk.get("link_type", "FS"),
                        lag_days=lk.get("lag_days", 0), source=rec["source"],
                        inferred=bool(lk.get("inferred")),
                        confidence=lk.get("confidence"), actor=actor, commit=False):
                made += 1
        conn.execute("UPDATE schedule_imports SET status = 'committed', "
                     "settled_at = ?, settled_by = ? WHERE id = ?",
                     (db.now(), actor, import_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    db.log_activity(actor, job, "schedule.import.commit",
                    f"{rec['filename']} · {result['added']} added, "
                    f"{result['updated']} updated, {made} links accepted")
    result["links_accepted"] = made
    result["links_rejected"] = len(payload.get("links", [])) - made
    return result


def discard_import(import_id: str, actor: str | None = None) -> bool:
    conn = db.connect()
    cur = conn.execute("UPDATE schedule_imports SET status = 'discarded', "
                       "settled_at = ?, settled_by = ? WHERE id = ? AND status = 'staged'",
                       (db.now(), actor, import_id))
    conn.commit()
    return cur.rowcount > 0


def latest_staged(job_number: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute(
        "SELECT id FROM schedule_imports WHERE job_number = ? AND status = 'staged' "
        "ORDER BY created_at DESC LIMIT 1", (job_number,)).fetchone()
    return summarise_import(row["id"]) if row else None


def add_task(job_number: str, fields: dict[str, Any],
             actor: str | None = None) -> dict[str, Any]:
    conn = db.connect()
    nxt = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 n FROM schedule_tasks "
                       "WHERE job_number = ?", (job_number,)).fetchone()["n"]
    rec = {k: None for k in FIELDS}
    rec.update({"percent_complete": 0, "outline_level": 1,
                "is_milestone": 0, "is_summary": 0, "sort_order": nxt})
    rec.update({k: v for k, v in fields.items() if k in FIELDS})
    rec.update({"id": db.new_id(), "job_number": job_number, "external_id": None,
                "source": "manual", "created_by": actor, "created_at": db.now()})
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO schedule_tasks ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    if rec.get("predecessors"):
        sync_links_from_text(job_number, source="manual", actor=actor)
    db.log_activity(actor, job_number, "schedule.task.add", rec["name"] or "(unnamed)")
    return dict(conn.execute("SELECT * FROM schedule_tasks WHERE id = ?",
                             (rec["id"],)).fetchone())


def update_task(job_number: str, task_id: str, fields: dict[str, Any],
                actor: str | None = None) -> dict[str, Any] | None:
    clean = {k: v for k, v in fields.items() if k in FIELDS}
    if not clean:
        return None
    conn = db.connect()
    sets = ", ".join(f"{k} = ?" for k in clean)
    cur = conn.execute(f"UPDATE schedule_tasks SET {sets} WHERE id = ? AND job_number = ?",  # noqa: S608
                       (*clean.values(), task_id, job_number))
    conn.commit()
    if cur.rowcount == 0:
        return None
    if "predecessors" in clean:
        # Retyping the predecessors of a task replaces that task's links.
        # Only the ones pointing AT this task are cleared — a link somebody
        # drew by hand from this task to something else is not being edited.
        conn.execute("DELETE FROM schedule_links WHERE succ_id = ? AND inferred = 0",
                     (task_id,))
        conn.commit()
        sync_links_from_text(job_number, source="manual", actor=actor)
    db.log_activity(actor, job_number, "schedule.task.update",
                    f"{task_id}: {', '.join(clean)}")
    return dict(conn.execute("SELECT * FROM schedule_tasks WHERE id = ?",
                             (task_id,)).fetchone())


def delete_task(job_number: str, task_id: str, actor: str | None = None) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM schedule_tasks WHERE id = ? AND job_number = ?",
                       (task_id, job_number))
    conn.commit()
    if cur.rowcount:
        db.log_activity(actor, job_number, "schedule.task.delete", task_id)
    return cur.rowcount > 0


# --- working time -------------------------------------------------------------

DEFAULT_WORKDAYS = "1111100"          # Mon-Fri, index 0 = Monday


class Calendar:
    """Working time for a job: which weekdays count, and which dates don't.

    One calendar per job. Per-task calendars are a real MS Project feature, but
    nothing importable carries them — a printed PDF certainly doesn't — and
    inventing one per task is exactly the kind of guess this refuses to make.
    """

    __slots__ = ("workdays", "holidays")

    def __init__(self, workdays: str = DEFAULT_WORKDAYS,
                 holidays: set[date] | None = None):
        mask = (workdays or DEFAULT_WORKDAYS).strip()
        if len(mask) != 7 or set(mask) - {"0", "1"} or "1" not in mask:
            mask = DEFAULT_WORKDAYS      # a calendar with no working day never ends
        self.workdays = mask
        self.holidays = holidays or set()

    def is_workday(self, d: date) -> bool:
        return self.workdays[d.weekday()] == "1" and d not in self.holidays

    def next_workday(self, d: date) -> date:
        cur, guard = d, 0
        while not self.is_workday(cur) and guard < 400:
            cur += timedelta(days=1)
            guard += 1
        return cur

    def workdays_between(self, a: date, b: date) -> int:
        """Working days from `a` to `b`; same day = 0, signed."""
        if b < a:
            return -self.workdays_between(b, a)
        n, cur = 0, a
        while cur < b:
            cur += timedelta(days=1)
            if self.is_workday(cur):
                n += 1
        return n

    def add_workdays(self, base: date, n: float) -> date:
        """Advance `n` working days from `base`, landing on a working day."""
        cur = self.next_workday(base)
        rem = int(round(n))
        if rem <= 0:
            return cur
        guard = 0
        while rem and guard < 20000:
            cur += timedelta(days=1)
            guard += 1
            if self.is_workday(cur):
                rem -= 1
        return cur

    def add_calendar_days(self, base: date, n: float) -> date:
        """Elapsed duration: runs straight through weekends and holidays.

        MS Project's "edays" mean exactly this, which is why the unit is kept
        rather than converted — a 60-eday delivery lead that gets silently
        turned into 60 working days lands twelve weeks late.
        """
        return base + timedelta(days=int(round(n)))


def get_calendar(job_number: str) -> Calendar:
    conn = db.connect()
    row = conn.execute("SELECT * FROM schedule_calendars WHERE job_number = ?",
                       (job_number,)).fetchone()
    if row is None:
        return Calendar()
    holidays = set()
    if row["holidays"]:
        import json
        try:
            holidays = {date.fromisoformat(d) for d in json.loads(row["holidays"])}
        except (ValueError, TypeError):
            holidays = set()
    return Calendar(row["workdays"], holidays)


def set_calendar(job_number: str, workdays: str | None = None,
                 holidays: list[str] | None = None,
                 actor: str | None = None) -> dict[str, Any]:
    import json
    cal = get_calendar(job_number)
    mask = workdays if workdays is not None else cal.workdays
    days = holidays if holidays is not None else sorted(d.isoformat() for d in cal.holidays)
    conn = db.connect()
    conn.execute(
        "INSERT INTO schedule_calendars (job_number, workdays, holidays, updated_at, updated_by) "
        "VALUES (?,?,?,?,?) ON CONFLICT(job_number) DO UPDATE SET "
        "workdays = excluded.workdays, holidays = excluded.holidays, "
        "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
        (job_number, Calendar(mask).workdays, json.dumps(days), db.now(), actor))
    conn.commit()
    db.log_activity(actor, job_number, "schedule.calendar", f"{mask} · {len(days)} holidays")
    return {"workdays": Calendar(mask).workdays, "holidays": days}


# Kept as module-level helpers on the default calendar: the look ahead and the
# older tests reach for these, and a Mon-Fri week is still the common case.
_DEFAULT_CAL = Calendar()


def _weekdays_between(a: date, b: date) -> int:
    return _DEFAULT_CAL.workdays_between(a, b)


def _add_workdays(base: date, n: int) -> date:
    return _DEFAULT_CAL.add_workdays(base, n)


# Lag units, expressed in working days. MS Project and Smartsheet both write
# the unit out ("12FS+2 days", "5SS-1 wk"); a week of lag is a WORK week.
_LAG_UNITS = {
    "d": 1.0, "day": 1.0, "days": 1.0,
    "w": 5.0, "wk": 5.0, "wks": 5.0, "week": 5.0, "weeks": 5.0,
    "mon": 20.0, "mons": 20.0, "month": 20.0, "months": 20.0,
    "h": 1.0 / HOURS_PER_DAY, "hr": 1.0 / HOURS_PER_DAY, "hrs": 1.0 / HOURS_PER_DAY,
    "hour": 1.0 / HOURS_PER_DAY, "hours": 1.0 / HOURS_PER_DAY,
}
_LINK_TYPES = ("FS", "SS", "FF", "SF")

# A predecessor reference, taken apart from the end: optional lag with a unit,
# optional two-letter link type, and whatever precedes both is the id.
_PRED_RE = re.compile(
    r"^(?P<id>.+?)\s*"
    r"(?P<type>FS|SS|FF|SF)?\s*"
    r"(?:(?P<lag>[+-]\s*\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z]+))?$",
    re.IGNORECASE)
# The unitless form, allowed ONLY when the id is purely numeric — see below.
_PRED_NUMERIC_RE = re.compile(
    r"^(?P<id>\d+)\s*(?P<type>FS|SS|FF|SF)?\s*"
    r"(?P<lag>[+-]\s*\d+(?:\.\d+)?)?\s*(?P<unit>[A-Za-z]*)$",
    re.IGNORECASE)


def _parse_preds(raw: str | None) -> list[tuple[str, str, float]]:
    """Parse a predecessor string into (external_id, link_type, lag_days).

    Accepts what MS Project, Smartsheet and hand-typing all produce:
    `12`, `12FS`, `12FS+2 days`, `5SS-1wk`, `A-100`, `A-100FF+3d`.

    Two things this has to get right that the previous version did not.

    **Ids containing a hyphen.** `A-100` is an extremely common activity id,
    and the old pattern (`[^+\\-]+?`) split it into id `A` with a lag of -100.
    So a lag is only recognised when it carries a UNIT — except where the id is
    purely numeric, in which case `12+2` is unambiguous and allowed. That rule
    is what separates `A-100` (an id) from `12-2d` (id 12, two days of lead).

    **Link types.** `12SS+2d` used to fail the pattern entirely and fall
    through to a predecessor literally named "12SS+2d", which then resolved to
    nothing — a dependency silently dropped. Types are now parsed; the engine
    treats everything as FS until the typed-link rewrite, but the value is
    carried so nothing is lost on the way through.

    Unknown trailing text is treated as part of the id rather than guessed at.
    """
    out: list[tuple[str, str, float]] = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue

        m = _PRED_RE.match(part)
        unit = (m.group("unit") or "").lower() if m else ""
        if m and m.group("lag") and unit in _LAG_UNITS:
            lag = float(m.group("lag").replace(" ", "")) * _LAG_UNITS[unit]
            out.append((m.group("id").strip(), (m.group("type") or "FS").upper(), lag))
            continue

        n = _PRED_NUMERIC_RE.match(part)
        if n and not n.group("unit"):
            lag = float(n.group("lag").replace(" ", "")) if n.group("lag") else 0.0
            out.append((n.group("id"), (n.group("type") or "FS").upper(), lag))
            continue

        # No recognisable lag. Strip a trailing link type if there is one and
        # take the rest as the id verbatim.
        bare = part
        ltype = "FS"
        if len(bare) > 2 and bare[-2:].upper() in _LINK_TYPES:
            ltype, bare = bare[-2:].upper(), bare[:-2].strip()
        out.append((bare, ltype, 0.0))
    return out


def analyze(job_number: str) -> dict[str, Any]:
    """Forward/backward pass -> early/late dates, float, critical path.

    Arithmetic is in WORK DAYS off the project start, because that is the unit
    Microsoft Project durations are in. Running it in calendar days made every
    weekend gap look like slack — a chain whose tasks ran Fri→Mon appeared to
    have two days of float and nothing came out critical.

    Three rules worth stating outright, because each one is load-bearing:

    **A task's own start is a floor, not a suggestion.** The network only ever
    pushes a task *later*; it never pulls one earlier than the date the source
    gave it. Real schedules are full of tasks held by procurement, weather and
    constraints that no dependency in the file explains, and a schedule
    imported from a PDF has no links at all until a human confirms them — drop
    the floor and all 392 tasks stack up on the project start date. Treat this
    as an implicit start-no-earlier-than on everything, because that is what an
    imported date means.

    **Links come from `schedule_links` only.** The `predecessors` text column
    is an input format; `sync_links_from_text` turns it into rows. Two sources
    of truth would mean a schedule that reschedules differently depending on
    which one you believed.

    **Summary rows are excluded from the network.** Their dates are roll-ups of
    their children, not work of their own; including them double-counts every
    child's duration.

    Cycle tolerance is deliberate: imported schedules occasionally contain
    them, and a bounded relaxation degrades where a topological sort raises.
    """
    cal = get_calendar(job_number)
    tasks = list_tasks(job_number)
    net = [t for t in tasks if not t["is_summary"]]
    if not net:
        # Same shape as a populated result — an empty schedule must not make
        # callers branch on which keys exist.
        return {"tasks": [], "links": [], "project_start": None,
                "project_finish": None, "critical_count": 0, "duration_days": 0,
                "calendar": {"workdays": cal.workdays,
                             "holidays": sorted(d.isoformat() for d in cal.holidays)}}

    starts = [t["start"] for t in net if t["start"]]
    project_start = min(starts) if starts else date.today().isoformat()
    base = date.fromisoformat(project_start)

    dur: dict[str, float] = {}
    floor: dict[str, float] = {}
    ids = {t["id"] for t in net}
    for t in net:
        d = t["duration_days"]
        if d is None and t["start"] and t["finish"]:
            # No stated duration: measure it. +1 because a task that starts and
            # finishes on the same day is one day long, not zero.
            d = cal.workdays_between(date.fromisoformat(t["start"]),
                                     date.fromisoformat(t["finish"])) + 1
        dur[t["id"]] = max(0.0, float(d if d is not None else 0))
        floor[t["id"]] = (float(cal.workdays_between(base, date.fromisoformat(t["start"])))
                          if t["start"] else 0.0)

    # Predecessor lists, typed. (pred_id, link_type, lag)
    preds: dict[str, list[tuple[str, str, float]]] = {tid: [] for tid in ids}
    succs: dict[str, list[tuple[str, str, float]]] = {tid: [] for tid in ids}
    links = [dict(row) for row in list_links(job_number)]
    for lk in links:
        p, s = lk["pred_id"], lk["succ_id"]
        if p in ids and s in ids and p != s:
            preds[s].append((p, lk["link_type"], float(lk["lag_days"] or 0)))
            succs[p].append((s, lk["link_type"], float(lk["lag_days"] or 0)))

    order = [t["id"] for t in net]

    # --- forward pass: earliest start honouring the link type ---------------
    # FS: successor starts after predecessor FINISHES
    # SS: after predecessor STARTS
    # FF: successor FINISHES after predecessor finishes -> start = that - own duration
    # SF: successor FINISHES after predecessor starts
    es = {tid: floor[tid] for tid in order}
    for _ in range(len(order) + 1):
        changed = False
        for tid in order:
            if not preds[tid]:
                continue
            want = es[tid]
            for p, ltype, lag in preds[tid]:
                if ltype == "SS":
                    cand = es[p] + lag
                elif ltype == "FF":
                    cand = es[p] + dur[p] + lag - dur[tid]
                elif ltype == "SF":
                    cand = es[p] + lag - dur[tid]
                else:                                   # FS
                    cand = es[p] + dur[p] + lag
                want = max(want, cand)
            # The floor again: a link may push a task later, never earlier.
            want = max(want, floor[tid])
            if want > es[tid] + 1e-9:
                es[tid] = want
                changed = True
        if not changed:
            break

    ef = {tid: es[tid] + dur[tid] for tid in order}
    project_finish_off = max(ef.values()) if ef else 0.0

    # --- backward pass: latest finish ---------------------------------------
    lf = {tid: project_finish_off for tid in order}
    for _ in range(len(order) + 1):
        changed = False
        for tid in reversed(order):
            if not succs[tid]:
                continue
            want = lf[tid]
            for s, ltype, lag in succs[tid]:
                ls_s = lf[s] - dur[s]
                if ltype == "SS":
                    cand = ls_s - lag + dur[tid]        # own LS >= ... -> LF
                elif ltype == "FF":
                    cand = lf[s] - lag
                elif ltype == "SF":
                    cand = lf[s] - lag + dur[tid]
                else:                                   # FS
                    cand = ls_s - lag
                want = min(want, cand)
            if want < lf[tid] - 1e-9:
                lf[tid] = want
                changed = True
        if not changed:
            break

    # Free float: how far a task can slip without moving ANY successor —
    # distinct from total float, which is slack against the project end.
    free: dict[str, float] = {}
    for tid in order:
        if not succs[tid]:
            free[tid] = round(lf[tid] - ef[tid], 2)
            continue
        room = None
        for s, ltype, lag in succs[tid]:
            if ltype == "SS":
                slack = es[s] - (es[tid] + lag)
            elif ltype == "FF":
                slack = (es[s] + dur[s]) - (ef[tid] + lag)
            elif ltype == "SF":
                slack = (es[s] + dur[s]) - (es[tid] + lag)
            else:
                slack = es[s] - (ef[tid] + lag)
            room = slack if room is None else min(room, slack)
        free[tid] = round(max(0.0, room or 0.0), 2)

    def as_date(offset_days: float) -> str:
        return cal.add_workdays(base, int(round(offset_days))).isoformat()

    out = []
    critical = 0
    for t in tasks:
        tid = t["id"]
        row = dict(t)
        if t["is_summary"] or tid not in es:
            row.update({"total_float": None, "free_float": None, "is_critical": 0,
                        "early_start": None, "early_finish": None,
                        "late_start": None, "late_finish": None})
        else:
            float_days = round(lf[tid] - ef[tid], 2)
            row["total_float"] = float_days
            row["free_float"] = free[tid]
            row["is_critical"] = 1 if float_days <= 0.01 else 0
            row["early_start"] = as_date(es[tid])
            row["early_finish"] = as_date(max(es[tid], ef[tid] - 1))
            row["late_start"] = as_date(lf[tid] - dur[tid])
            row["late_finish"] = as_date(max(0.0, lf[tid] - 1))
            critical += row["is_critical"]
        out.append(row)

    finishes = [t["finish"] for t in net if t["finish"]]
    return {
        "tasks": out,
        "links": links,
        "project_start": project_start,
        "project_finish": max(finishes) if finishes else as_date(project_finish_off),
        "critical_count": critical,
        "duration_days": int(project_finish_off),
        "calendar": {"workdays": cal.workdays,
                     "holidays": sorted(d.isoformat() for d in cal.holidays)},
    }
