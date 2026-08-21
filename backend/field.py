"""Field roles — who gets the field app, and what the office keeps.

The owner's rule (2026-08-20): the email on a job's Superintendent or Field
leader line IS the role. Anyone signed in with that email gets the field
version of PlanWise for that job — the handoff's PlanWise Field design:
today's work, the look ahead, drawings, questions and submittals, read-only
job numbers. Everyone else gets the full app.

The limit is enforced HERE, not just hidden in the UI: a field account's
writes to office registers (POs, COs, job setup, schedule, briefings,
reversals, sends) are refused by the server with a sentence saying where
that work lives. What the field DOES own keeps working: day ticks,
activities and areas, drawing marks, and raising a draft RFI that lands on
the PM's desk.

Administrators are never field-limited — putting your own email on the
Superintendent line must not lock the owner out of his own office app.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import db

_EMAIL_KEYS = ("superintendent_email", "field_leader_email")


def field_jobs_for(email: str | None) -> list[str]:
    """Jobs where this email sits on the Superintendent or Field leader line."""
    if not email:
        return []
    want = email.strip().lower()
    if not want:
        return []
    conn = db.connect()
    out = []
    for row in conn.execute("SELECT job_number, data FROM project_meta"):
        try:
            data = json.loads(row["data"] or "{}")
        except ValueError:
            continue
        for k in _EMAIL_KEYS:
            if str(data.get(k) or "").strip().lower() == want:
                out.append(row["job_number"])
                break
    return sorted(out)


# What a field account may NOT do on its field job. Each entry: an HTTP
# method set and a compiled pattern over the request path. Job-scoped office
# writes match directly; object-scoped ones name a resolver that finds the
# object's job so the rule stays per-job (the same person can be a PM
# elsewhere).
_WRITE = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def _job_of_record(rec_id: str) -> str | None:
    row = db.connect().execute(
        "SELECT job_number FROM pipeline_records WHERE id = ?", (rec_id,)).fetchone()
    return row["job_number"] if row else None


def _job_of_briefing(bid: str) -> str | None:
    row = db.connect().execute(
        "SELECT job_number FROM briefings WHERE id = ?", (bid,)).fetchone()
    return row["job_number"] if row else None


def _job_of_activity(aid: str) -> str | None:
    row = db.connect().execute(
        "SELECT job_number FROM activity WHERE id = ?", (aid,)).fetchone()
    return row["job_number"] if row else None


_RULES: list[tuple[frozenset, re.Pattern, Any, str]] = [
    # Office registers, job-scoped. The field app shows the numbers; the
    # office writes them.
    (_WRITE, re.compile(r"^/api/jobs/([^/]+)/(pos|cos|invoices|meta|schedule|briefing)(/|$)"), 1,
     "created in the office app"),
    # Sending and confirming are the PM's desk: a field draft becomes an RFI
    # the PM reviews and sends.
    (_WRITE, re.compile(r"^/api/records/([^/]+)/(draft|sent|confirm|share)"), _job_of_record,
     "sent from the office app"),
    (frozenset({"DELETE"}), re.compile(r"^/api/records/([^/]+)$"), _job_of_record,
     "removed in the office app"),
    (_WRITE, re.compile(r"^/api/briefings/([^/]+)"), _job_of_briefing,
     "the office app's page"),
    (_WRITE, re.compile(r"^/api/activity/([^/]+)/reverse"), _job_of_activity,
     "reversed from the office app"),
]


def refusal_for(method: str, path: str, user: dict[str, Any] | None) -> str | None:
    """A sentence when this request is an office action on the user's field
    job; None when the request may proceed."""
    if user is None or user.get("is_admin"):
        return None
    if method not in _WRITE:
        return None
    jobs = field_jobs_for(user.get("email"))
    if not jobs:
        return None
    for methods, pat, jobref, where in _RULES:
        if method not in methods:
            continue
        m = pat.match(path)
        if not m:
            continue
        job = m.group(1) if jobref == 1 else jobref(m.group(1))
        if job and job in jobs:
            return f"Your account is the field role on job {job}. This is {where}."
    return None
