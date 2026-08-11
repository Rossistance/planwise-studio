"""SQLite — the shared store for everything PM-entered (decision D9).

Vista stays read-only truth; this database holds what Vista cannot. One file
in data_dir(), WAL mode so six concurrent writers on a LAN behave, schema
created idempotently at first touch.

Every mutating write records an activity row with the acting user — with six
writers, "who changed this" is part of the data, not a nicety.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

-- Outbox (Phase 5g). A phone can't drive desktop Outlook — there is no COM on
-- iOS — so a send prepared in the field waits here until its author opens
-- PlanWise at a machine that has a companion. Mail therefore still leaves
-- from the account of the person who asked for it (D10/D11); only the moment
-- moves. Intent is stored rather than a rendered document, so what actually
-- goes out reflects the sheet at drafting time rather than a stale snapshot.
CREATE TABLE IF NOT EXISTS outbox (
    id          TEXT PRIMARY KEY,
    job_number  TEXT NOT NULL,
    kind        TEXT NOT NULL,        -- 'lookahead' | 'record'
    target_id   TEXT NOT NULL,
    audience    TEXT,                 -- customer | team
    weeks       INTEGER,              -- look ahead only
    note        TEXT,                 -- what the field wanted to say
    queued_by   TEXT,
    queued_at   TEXT NOT NULL,
    drafted_at  TEXT,
    drafted_by  TEXT
);
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON outbox(queued_by, drafted_at);

-- Web push devices (Phase 5e). Keyed on the endpoint so re-subscribing the
-- same device updates it rather than accumulating duplicates that would each
-- fire their own copy of every notification.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint    TEXT PRIMARY KEY,
    user_name   TEXT,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_push_user ON push_subscriptions(user_name);

-- Opaque session tokens (Phase 5a). Held in an HttpOnly cookie, so nothing
-- readable from JavaScript ever identifies a user; deleting the row is what
-- signing out, disabling an account, or changing a password all do.
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id              TEXT PRIMARY KEY,
    job_number      TEXT NOT NULL,
    po_number       TEXT,
    vendor          TEXT,
    description     TEXT,
    order_date      TEXT,
    ordered_by      TEXT,
    original_amount REAL,
    adjusted_amount REAL,
    cost_type       TEXT,
    status          TEXT NOT NULL DEFAULT 'Open',
    created_by      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_po_job ON purchase_orders(job_number);

CREATE TABLE IF NOT EXISTS invoices (
    id              TEXT PRIMARY KEY,
    po_id           TEXT NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    invoice_number  TEXT,
    date            TEXT,
    amount          REAL,
    created_by      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_inv_po ON invoices(po_id);

CREATE TABLE IF NOT EXISTS change_orders (
    id               TEXT PRIMARY KEY,
    job_number       TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('customer','subcontractor')),
    co_number        TEXT,
    cust_co_number   TEXT,
    date_submitted   TEXT,
    description      TEXT,
    amount_submitted REAL,
    amount_pending   REAL,
    amount_approved  REAL,
    approved_by      TEXT,
    subcontractor    TEXT,
    status           TEXT,
    created_by       TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_co_job ON change_orders(job_number);

-- PM-entered Overview supplements, one JSON blob per job. Schema-light on
-- purpose: these fields are still being settled page by page.
CREATE TABLE IF NOT EXISTS project_meta (
    job_number  TEXT PRIMARY KEY,
    data        TEXT NOT NULL DEFAULT '{}',
    updated_by  TEXT,
    updated_at  TEXT
);

-- Document library (Phase 2). Files live in data_dir()/documents/<id>.pdf;
-- the original is immutable — annotations never touch it (layer model, D-pipeline).
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    job_number  TEXT NOT NULL,
    name        TEXT NOT NULL,
    filename    TEXT,
    page_count  INTEGER,
    size_bytes  INTEGER,
    sha256      TEXT,
    uploaded_by TEXT,
    uploaded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_doc_job ON documents(job_number);

-- One row per shape. Coordinates are normalized (0..1 of the page box) so
-- they are zoom- and DPI-independent. `layer` is the isolation boundary:
-- 'internal' = team redlines; 'rfi:<id>' / 'submittal:<id>' arrive in Phase 3.
CREATE TABLE IF NOT EXISTS annotations (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    layer       TEXT NOT NULL DEFAULT 'internal',
    shape       TEXT NOT NULL,
    author      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ann_doc ON annotations(document_id, page, layer);

-- RFI / Submittal pipeline records (Phase 3). One table, two kinds: the
-- lifecycle machinery (attachments, layers, outbound package, Outlook thread)
-- is identical; only a few fields differ per kind.
CREATE TABLE IF NOT EXISTS pipeline_records (
    id            TEXT PRIMARY KEY,
    job_number    TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('rfi','submittal')),
    number        TEXT,
    title         TEXT,
    question      TEXT,          -- rfi
    answer        TEXT,          -- rfi (from the reply, PM-confirmed)
    spec_section  TEXT,          -- submittal
    status        TEXT NOT NULL DEFAULT 'Draft',
    to_name       TEXT,
    to_email      TEXT,
    due_date      TEXT,
    sent_at       TEXT,
    outlook_conversation_id TEXT, -- reply matching (Phase 3b)
    created_by    TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rec_job ON pipeline_records(job_number, kind);

-- Pages attached to a record: "send page N of document D". The extract at
-- send time composites the ORIGINAL page + the record's own layer only.
CREATE TABLE IF NOT EXISTS record_attachments (
    id          TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL REFERENCES pipeline_records(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    added_by    TEXT,
    added_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_att_rec ON record_attachments(record_id);

-- App settings (Phase 3b): AI provider keys, model choices, spend cap,
-- companion token. Key/value; secrets are masked on read via the API.
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

-- Shared-team AI spend, for the monthly gate (ported from AI Intake, D13).
CREATE TABLE IF NOT EXISTS ai_spend (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    provider   TEXT,
    model      TEXT,
    tokens_in  INTEGER,
    tokens_out INTEGER,
    cost_est   REAL,
    purpose    TEXT
);

-- Email drafts for pipeline records (kept out of pipeline_records so the
-- existing table needs no migration).
CREATE TABLE IF NOT EXISTS record_drafts (
    record_id  TEXT PRIMARY KEY REFERENCES pipeline_records(id) ON DELETE CASCADE,
    subject    TEXT,
    body       TEXT,
    source     TEXT,          -- 'ai' | 'template' | 'edited'
    updated_by TEXT,
    updated_at TEXT
);

-- Replies captured from Outlook. The AI/heuristic proposal is STAGED here —
-- nothing touches the record until a PM confirms (D-pipeline trust model).
CREATE TABLE IF NOT EXISTS record_replies (
    id              TEXT PRIMARY KEY,
    record_id       TEXT NOT NULL REFERENCES pipeline_records(id) ON DELETE CASCADE,
    from_name       TEXT,
    from_email      TEXT,
    received_at     TEXT,
    body            TEXT,
    proposed_status TEXT,
    proposed_answer TEXT,
    proposal_source TEXT,     -- 'ai' | 'heuristic'
    confirmed_at    TEXT,
    confirmed_by    TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reply_rec ON record_replies(record_id);

CREATE TABLE IF NOT EXISTS reply_attachments (
    id         TEXT PRIMARY KEY,
    reply_id   TEXT NOT NULL REFERENCES record_replies(id) ON DELETE CASCADE,
    filename   TEXT,
    path       TEXT,
    size_bytes INTEGER
);

-- Schedule (Phase 4). One row per task. `external_id` is the source system's
-- UID so a re-import updates in place instead of duplicating.
CREATE TABLE IF NOT EXISTS schedule_tasks (
    id               TEXT PRIMARY KEY,
    job_number       TEXT NOT NULL,
    external_id      TEXT,
    name             TEXT,
    start            TEXT,
    finish           TEXT,
    duration_days    REAL,
    percent_complete REAL DEFAULT 0,
    outline_level    INTEGER DEFAULT 1,
    is_milestone     INTEGER DEFAULT 0,
    is_summary       INTEGER DEFAULT 0,
    predecessors     TEXT,          -- comma-separated external_ids, optional +/-lag
    sort_order       INTEGER,
    source           TEXT,          -- manual | mspdi | mpp
    created_by       TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sched_job ON schedule_tasks(job_number, sort_order);

-- Two-week look ahead. Seeded from the schedule, then fully hand-editable —
-- the master schedule doesn't reach daily granularity and the field changes.
CREATE TABLE IF NOT EXISTS lookahead_periods (
    id          TEXT PRIMARY KEY,
    job_number  TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    notes       TEXT,
    created_by  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_la_job ON lookahead_periods(job_number, start_date);

CREATE TABLE IF NOT EXISTS lookahead_items (
    id          TEXT PRIMARY KEY,
    period_id   TEXT NOT NULL REFERENCES lookahead_periods(id) ON DELETE CASCADE,
    task_id     TEXT,          -- schedule task it came from, when seeded
    description TEXT,
    crew        TEXT,
    start       TEXT,
    finish      TEXT,
    status      TEXT DEFAULT 'Planned',
    notes       TEXT,
    sort_order  INTEGER,
    created_by  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_la_item ON lookahead_items(period_id, sort_order);

-- Optional work areas for the look ahead. Owned by the JOB so they carry
-- across periods; `active` is the "in use" tick — a retired area stays for
-- history but drops out of the picker.
CREATE TABLE IF NOT EXISTS lookahead_areas (
    id          TEXT PRIMARY KEY,
    job_number  TEXT NOT NULL,
    name        TEXT NOT NULL,
    color       TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER,
    created_by  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_la_area ON lookahead_areas(job_number, sort_order);

CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    actor       TEXT,
    job_number  TEXT,
    action      TEXT NOT NULL,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS ix_act_job ON activity(job_number);
"""


# Additive migrations. CREATE TABLE IF NOT EXISTS never alters an existing
# table, so columns added after a database exists are applied here — cheap,
# idempotent, and safe to run on every connect.
MIGRATIONS = [
    ("pipeline_records", "sent_by", "TEXT"),
    ("record_replies", "message_id", "TEXT"),
    # Look ahead reworked to the field's day-grid format (2026-08-09)
    ("lookahead_periods", "prepared_by", "TEXT"),
    ("lookahead_periods", "tools_needed", "TEXT"),
    ("lookahead_periods", "materials_needed", "TEXT"),
    ("lookahead_items", "days", "TEXT"),
    # Per-row internal columns + optional work-area colour coding (2026-08-09),
    # matching the AEFORM two-week sheet.
    ("lookahead_items", "requirements", "TEXT"),
    ("lookahead_items", "tools", "TEXT"),
    ("lookahead_items", "materials", "TEXT"),
    ("lookahead_items", "work_area_id", "TEXT"),
    # 2 or 3 weeks on show; ticks are always stored 21 days wide (2026-08-09).
    ("lookahead_periods", "weeks", "INTEGER"),
    # Phase 5a: real accounts, now that PlanWise is going on a public URL.
    ("users", "password_hash", "TEXT"),
    ("users", "is_admin", "INTEGER"),
    ("users", "disabled", "INTEGER"),
    ("users", "must_change_password", "INTEGER"),
    # Zero-token access (2026-08-10): self-service sign-up and password-based
    # companion pairing. `name` stays the attribution string everywhere
    # (activity, outbox, push subs); email is what you sign in with. `pending`
    # is NULL for accounts that predate approval-gating — NULL means approved,
    # so the bootstrap admin is never locked out by his own migration.
    ("users", "email", "TEXT"),
    ("users", "first_name", "TEXT"),
    ("users", "last_name", "TEXT"),
    ("users", "pending", "INTEGER"),
    ("users", "companion_token", "TEXT"),
]

POST_MIGRATION_SQL = """
CREATE INDEX IF NOT EXISTS ix_reply_msgid ON record_replies(message_id);
-- ALTER TABLE ADD COLUMN can't carry UNIQUE, so email uniqueness lives in a
-- partial index: NOCASE so Ross@ and ross@ are one identity, partial so the
-- accounts that predate email (NULL) don't collide with each other.
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email
    ON users(email COLLATE NOCASE) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_users_companion
    ON users(companion_token) WHERE companion_token IS NOT NULL;
"""


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")  # noqa: S608
    conn.executescript(POST_MIGRATION_SQL)
    conn.commit()


def connect() -> sqlite3.Connection:
    """One connection per thread; schema ensured on first use."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    path = config.data_dir() / "planwise.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    _local.conn = conn
    return conn


def reset_for_tests() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_activity(actor: str | None, job_number: str | None, action: str,
                 detail: str = "") -> None:
    conn = connect()
    conn.execute(
        "INSERT INTO activity (ts, actor, job_number, action, detail) VALUES (?,?,?,?,?)",
        (now(), actor, job_number, action, detail))
    conn.commit()
