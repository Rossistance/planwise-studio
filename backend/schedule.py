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
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Any

from . import db

MSPDI_NS = {"m": "http://schemas.microsoft.com/project"}
HOURS_PER_DAY = 8.0

FIELDS = {"name", "start", "finish", "duration_days", "percent_complete",
          "outline_level", "is_milestone", "is_summary", "predecessors", "sort_order"}


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
    """MSPDI durations are ISO-8601 like 'PT40H0M0S' or 'P5D'."""
    if not value:
        return None
    m = re.match(r"^P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?"
                 r"(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$", value.strip())
    if not m:
        return None
    days, hours, minutes, seconds = (float(g or 0) for g in m.groups())
    total_hours = days * HOURS_PER_DAY + hours + minutes / 60 + seconds / 3600
    return round(total_hours / HOURS_PER_DAY, 3) or None


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
            lag = ""
            try:
                # LinkLag is in tenths of a minute
                lag_days = round(float(lag_raw or 0) / 10 / 60 / HOURS_PER_DAY, 2)
                if lag_days:
                    lag = f"{'+' if lag_days > 0 else ''}{lag_days:g}d"
            except (TypeError, ValueError):
                pass
            preds.append(f"{puid}{lag}")

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
            "predecessors": ",".join(preds) or None,
            "sort_order": i,
        })
    if not out:
        raise ScheduleError("The XML parsed but contained no schedule tasks.")
    return out


def mpp_available() -> tuple[bool, str]:
    """Can this machine read a binary .mpp? (MPXJ needs a JVM.)"""
    try:
        import jpype  # noqa: F401
        import mpxj  # noqa: F401
    except ImportError:
        return False, "MPXJ is not installed (pip install mpxj JPype1)."
    try:
        import jpype
        if not jpype.isJVMStarted():
            jpype.getDefaultJVMPath()
        return True, "ready"
    except Exception as exc:  # noqa: BLE001
        return False, (
            "No Java runtime found. Reading binary .mpp needs a JRE — install "
            "one (e.g. Temurin 17) and restart PlanWise. Until then, export "
            "the schedule from Microsoft Project as XML (File > Save As > "
            f"XML) and import that. [{type(exc).__name__}]")


def parse_mpp(data: bytes) -> list[dict[str, Any]]:
    """Binary .mpp via MPXJ. Honest failure when no JVM is present."""
    ok, detail = mpp_available()
    if not ok:
        raise ScheduleError(detail)

    import pathlib
    import tempfile

    import jpype
    import mpxj

    if not jpype.isJVMStarted():
        jars = [str(p) for p in pathlib.Path(mpxj.__file__).parent.rglob("*.jar")]
        jpype.startJVM(classpath=jars)

    from net.sf.mpxj.reader import UniversalProjectReader  # type: ignore

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="planwise_mpp_")) / "schedule.mpp"
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
    if not out:
        raise ScheduleError("The .mpp parsed but contained no tasks.")
    return out


def parse_schedule(filename: str, data: bytes) -> tuple[list[dict[str, Any]], str]:
    name = (filename or "").lower()
    if name.endswith(".mpp"):
        return parse_mpp(data), "mpp"
    if name.endswith((".xml", ".mspdi")):
        return parse_mspdi(data), "mspdi"
    # content sniff: MSPDI is XML, MPP is an OLE compound file
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return parse_mpp(data), "mpp"
    if data.lstrip()[:1] == b"<":
        return parse_mspdi(data), "mspdi"
    raise ScheduleError(
        "Unsupported schedule file. Import a Microsoft Project .mpp or an "
        "MSPDI .xml export.")


# --- storage ----------------------------------------------------------------

def list_tasks(job_number: str) -> list[dict[str, Any]]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM schedule_tasks WHERE job_number = ? "
        "ORDER BY sort_order, rowid", (job_number,))]


def import_tasks(job_number: str, tasks: list[dict[str, Any]], source: str,
                 mode: str = "replace", actor: str | None = None) -> dict[str, Any]:
    """Replace the schedule, or merge onto it by external_id.

    Merge updates authoritative fields on tasks the source still knows about
    and leaves locally-added ones alone — re-importing a revised schedule
    must not orphan work the PM added by hand.
    """
    if mode not in ("replace", "merge"):
        raise ScheduleError("mode must be 'replace' or 'merge'.")
    conn = db.connect()
    existing = {t["external_id"]: t for t in list_tasks(job_number) if t["external_id"]}

    added = updated = 0
    if mode == "replace":
        conn.execute("DELETE FROM schedule_tasks WHERE job_number = ?", (job_number,))
        existing = {}

    for t in tasks:
        prior = existing.get(t.get("external_id"))
        if prior:
            sets = ", ".join(f"{k} = ?" for k in FIELDS if k in t)
            conn.execute(f"UPDATE schedule_tasks SET {sets} WHERE id = ?",  # noqa: S608
                         (*[t[k] for k in FIELDS if k in t], prior["id"]))
            updated += 1
        else:
            rec = {k: t.get(k) for k in FIELDS}
            rec.update({"id": db.new_id(), "job_number": job_number,
                        "external_id": t.get("external_id"), "source": source,
                        "created_by": actor, "created_at": db.now()})
            cols = ", ".join(rec)
            conn.execute(
                f"INSERT INTO schedule_tasks ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                tuple(rec.values()))
            added += 1
    conn.commit()
    db.log_activity(actor, job_number, "schedule.import",
                    f"{source} · {added} added, {updated} updated ({mode})")
    return {"added": added, "updated": updated, "mode": mode, "source": source}


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


# --- critical path ----------------------------------------------------------

def _weekdays_between(a: date, b: date) -> int:
    """Work days from `a` to `b` (same day = 0, Mon-Fri only)."""
    if b < a:
        return -_weekdays_between(b, a)
    weeks, rem = divmod((b - a).days, 7)
    n = weeks * 5
    cur = a
    for _ in range(rem):
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def _add_workdays(base: date, n: int) -> date:
    cur = base
    while cur.weekday() >= 5:          # start from a working day
        cur += timedelta(days=1)
    weeks, rem = divmod(max(0, int(n)), 5)
    cur += timedelta(weeks=weeks)
    while rem:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            rem -= 1
    return cur


def _parse_preds(raw: str | None) -> list[tuple[str, float]]:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^([^+\-]+?)\s*([+-]\s*\d+(?:\.\d+)?)?\s*d?$", part, re.I)
        if not m:
            out.append((part, 0.0))
            continue
        lag = float(m.group(2).replace(" ", "")) if m.group(2) else 0.0
        out.append((m.group(1).strip(), lag))
    return out


def analyze(job_number: str) -> dict[str, Any]:
    """Forward/backward pass -> early/late dates, total float, critical path.

    Arithmetic is in WORK DAYS off the project start, because that is the unit
    Microsoft Project durations are in. Running it in calendar days made every
    weekend gap look like slack — a chain whose tasks ran Fri→Mon appeared to
    have two days of float and nothing came out critical.

    Summary rows are excluded from the network (their dates are roll-ups of
    their children, not work).
    """
    tasks = [t for t in list_tasks(job_number)]
    net = [t for t in tasks if not t["is_summary"]]
    if not net:
        return {"tasks": [], "project_start": None, "project_finish": None,
                "critical_count": 0, "duration_days": 0}

    starts = [t["start"] for t in net if t["start"]]
    project_start = min(starts) if starts else date.today().isoformat()
    base = date.fromisoformat(project_start)

    def offset(d: str | None) -> float | None:
        return float(_weekdays_between(base, date.fromisoformat(d))) if d else None

    dur: dict[str, float] = {}
    by_ext: dict[str, str] = {}
    for t in net:
        d = t["duration_days"]
        if d is None and t["start"] and t["finish"]:
            d = _weekdays_between(date.fromisoformat(t["start"]),
                                  date.fromisoformat(t["finish"])) + 1
        dur[t["id"]] = max(0.0, float(d or 0))
        if t["external_id"]:
            by_ext[str(t["external_id"])] = t["id"]

    preds: dict[str, list[tuple[str, float]]] = {}
    for t in net:
        links = []
        for ext, lag in _parse_preds(t["predecessors"]):
            tid = by_ext.get(ext)
            if tid and tid != t["id"]:
                links.append((tid, lag))
        preds[t["id"]] = links

    order = [t["id"] for t in net]
    es: dict[str, float] = {}
    # Forward pass. Iterate to a fixed point rather than topologically sorting:
    # imported schedules occasionally contain cycles, and a bounded loop
    # degrades gracefully where a topological sort would raise.
    for tid in order:
        es[tid] = offset(next(t["start"] for t in net if t["id"] == tid)) or 0.0
    for _ in range(len(order)):
        changed = False
        for t in net:
            tid = t["id"]
            if preds[tid]:
                want = max(es[p] + dur[p] + lag for p, lag in preds[tid])
                if want > es[tid] + 1e-9:
                    es[tid] = want
                    changed = True
        if not changed:
            break

    ef = {tid: es[tid] + dur[tid] for tid in order}
    project_finish_off = max(ef.values()) if ef else 0.0

    succs: dict[str, list[tuple[str, float]]] = {tid: [] for tid in order}
    for tid, links in preds.items():
        for p, lag in links:
            succs[p].append((tid, lag))

    lf = {tid: project_finish_off for tid in order}
    for _ in range(len(order)):
        changed = False
        for tid in reversed(order):
            if succs[tid]:
                want = min(lf[s] - dur[s] - lag for s, lag in succs[tid])
                if want < lf[tid] - 1e-9:
                    lf[tid] = want
                    changed = True
        if not changed:
            break

    out = []
    critical = 0
    for t in tasks:
        tid = t["id"]
        row = dict(t)
        if t["is_summary"] or tid not in es:
            row.update({"total_float": None, "is_critical": 0,
                        "early_start": None, "late_finish": None})
        else:
            float_days = round(lf[tid] - ef[tid], 2)
            row["total_float"] = float_days
            row["is_critical"] = 1 if float_days <= 0.01 else 0
            row["early_start"] = _add_workdays(base, int(es[tid])).isoformat()
            row["late_finish"] = _add_workdays(base, int(lf[tid])).isoformat()
            critical += row["is_critical"]
        out.append(row)

    finishes = [t["finish"] for t in net if t["finish"]]
    return {
        "tasks": out,
        "project_start": project_start,
        "project_finish": max(finishes) if finishes else
            _add_workdays(base, int(project_finish_off)).isoformat(),
        "critical_count": critical,
        "duration_days": int(project_finish_off),
    }
