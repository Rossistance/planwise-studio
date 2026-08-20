"""One-time monthly cost-history backfill, straight from the Power BI source.

The owner's call (2026-08-20): the forecast chart needs history from job
inception, the workbook is snapshot-only, so pull the past directly from the
semantic model once — everything after accrues from the daily workbook push.

Rides on SiteScope's proven plumbing: the same MSAL token cache the daily
`vista_pull.py` task refreshes (delegated Build access, DPAPI-protected on
this PC) and its `run_query` wrapper. The month window is the same
JCDateSKey-on-the-fact-row pattern that pull's MTD measures validated in
production — no Calendar relationship, no model time-intelligence.

Writes PERIOD amounts per (job, month) into `vista_monthly`:
  * locally, into the PLANWISE_DATA_DIR database (default ~/.planwise), and
  * to the hosted instance when PLANWISE_URL / PLANWISE_INGEST_TOKEN are set
    (the same env vars the daily push uses), via POST /api/vista/monthly.

Everything before START_MONTH collapses into one opening month — that is
also where Vista's 1900-dated conversion sentinels land, harmlessly.

Run it with the repo venv:  .venv/Scripts/python.exe tools/vista_history_backfill.py
Re-running is safe: the table upserts on (job, month).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, r"C:\Users\rhixon\SiteScope\tools")

import vista_pull as vp  # noqa: E402 — auth + run_query, deliberately shared

START_MONTH = (2010, 1)          # opening rollup absorbs anything earlier
OPENING_KEY = "2009-12"


def month_windows():
    today = dt.date.today()
    y, m = START_MONTH
    while (y, m) <= (today.year, today.month):
        first = dt.date(y, m, 1)
        nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
        last = nxt - dt.timedelta(days=1)
        yield (f"{y:04d}-{m:02d}",
               int(first.strftime("%Y%m%d")), int(last.strftime("%Y%m%d")))
        y, m = nxt.year, nxt.month


def window_dax(lo: int | None, hi: int) -> str:
    win = f"'Job Cost Details'[JCDateSKey] <= {hi}"
    if lo is not None:
        win = f"'Job Cost Details'[JCDateSKey] >= {lo}, " + win
    return f"""
EVALUATE
SUMMARIZECOLUMNS (
    'Job Cost Details'[Job],
    "cost",   CALCULATE ( SUM ( 'Job Cost Details'[CostActualAmt] ), {win} ),
    "billed", CALCULATE ( SUM ( 'Job Cost Details'[ContractBilledAmt] ), {win} ),
    "hours",  CALCULATE ( SUM ( 'Job Cost Details'[CostActualHours] ), {win} )
)
"""


def job_number(raw: str) -> str:
    """Fact-row [Job] is the raw Vista code, padded and dash-terminated
    ('  8500-', ' 24-003-'). Strip the padding and the terminator only —
    interior dashes are part of the number."""
    return raw.strip().rstrip("-").strip()


def main() -> int:
    token = vp.acquire_token(interactive=False)

    all_rows: list[dict] = []
    lo0 = int(f"{START_MONTH[0]:04d}{START_MONTH[1]:02d}01")
    opening = vp.run_query(token, window_dax(None, lo0 - 1), label="opening rollup")
    for r in opening:
        job = job_number(str(vp.val(r, "Job") or ""))
        if job:
            all_rows.append({"job": job, "month": OPENING_KEY,
                             "cost": vp.numopt(r, "cost"),
                             "billed": vp.numopt(r, "billed"),
                             "hours": vp.numopt(r, "hours")})
    print(f"opening (<{START_MONTH[0]}): {len(opening)} jobs")

    for month, lo, hi in month_windows():
        rows = vp.run_query(token, window_dax(lo, hi), label=f"month {month}")
        for r in rows:
            job = job_number(str(vp.val(r, "Job") or ""))
            if job:
                all_rows.append({"job": job, "month": month,
                                 "cost": vp.numopt(r, "cost"),
                                 "billed": vp.numopt(r, "billed"),
                                 "hours": vp.numopt(r, "hours")})
        print(f"{month}: {len(rows)} jobs with postings")

    print(f"total rows: {len(all_rows)}")
    dashy = sum(1 for r in all_rows if re.match(r"^\d{2}-\d{3}$", r["job"]))
    print(f"rows on NN-NNN style jobs: {dashy}")

    # Local write, through the app's own schema.
    os.environ.setdefault("PLANWISE_DATA_DIR", str(Path.home() / ".planwise"))
    from backend import db
    conn = db.connect()
    for r in all_rows:
        conn.execute(
            "INSERT INTO vista_monthly (job_number, month, cost, billed, hours,"
            " captured_at) VALUES (?,?,?,?,?,?) ON CONFLICT(job_number, month)"
            " DO UPDATE SET cost=excluded.cost, billed=excluded.billed,"
            " hours=excluded.hours, captured_at=excluded.captured_at",
            (r["job"], r["month"], r["cost"], r["billed"], r["hours"], db.now()))
    conn.commit()
    print(f"local: wrote {len(all_rows)} rows into {os.environ['PLANWISE_DATA_DIR']}")

    base = (os.environ.get("PLANWISE_URL") or "").strip().rstrip("/")
    tok = (os.environ.get("PLANWISE_INGEST_TOKEN") or "").strip()
    if base and tok:
        import requests
        for i in range(0, len(all_rows), 5000):
            chunk = all_rows[i:i + 5000]
            resp = requests.post(f"{base}/api/vista/monthly",
                                 headers={"X-PlanWise-Ingest": tok},
                                 json={"rows": chunk}, timeout=120)
            resp.raise_for_status()
            print(f"hosted: {i + len(chunk)}/{len(all_rows)} rows pushed")
    else:
        print("PLANWISE_URL / PLANWISE_INGEST_TOKEN not set; hosted push skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
