"""The additive-migration idiom, exercised the way production hits it.

Render's disk carries a database written by an older build, and every deploy
runs the current SCHEMA + MIGRATIONS against it on first connect. These tests
stand in for that moment: build a database missing the new columns, reconnect,
and prove the columns appear, appear once, and don't disturb existing rows.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend import config, db


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def _user_columns() -> set[str]:
    conn = db.connect()
    return {r["name"] for r in conn.execute("PRAGMA table_info(users)")}


def test_pre_migration_database_gains_the_new_user_columns():
    # Fabricate the pre-zero-token shape: users exists with the Phase 5a
    # columns but nothing newer, plus one real row.
    path = config.data_dir() / "planwise.db"
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
            password_hash TEXT, is_admin INTEGER, disabled INTEGER,
            must_change_password INTEGER
        );
        INSERT INTO users (id, name, created_at, is_admin)
        VALUES ('abc123', 'Ross Hixon', '2026-08-08T00:00:00', 1);
        """
    )
    raw.commit()
    raw.close()

    cols = _user_columns()
    for col in ("email", "first_name", "last_name", "pending", "companion_token"):
        assert col in cols, col

    # The pre-existing account survives untouched, and NULL pending reads as
    # approved — the bootstrap admin must never be locked out by a migration.
    row = db.connect().execute("SELECT * FROM users WHERE id='abc123'").fetchone()
    assert row["name"] == "Ross Hixon"
    assert row["pending"] is None
    assert row["email"] is None


def test_migration_is_idempotent_across_reconnects():
    first = _user_columns()
    db.reset_for_tests()
    second = _user_columns()
    assert first == second


def test_email_uniqueness_is_case_insensitive_and_null_tolerant():
    conn = db.connect()
    conn.execute("INSERT INTO users (id, name, created_at, email) VALUES ('a', 'A', 't', 'ross@wecc.com')")
    # Same address, different case: refused.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO users (id, name, created_at, email) VALUES ('b', 'B', 't', 'ROSS@wecc.com')")
    # But any number of pre-email accounts (NULL) coexist.
    conn.execute("INSERT INTO users (id, name, created_at) VALUES ('c', 'C', 't')")
    conn.execute("INSERT INTO users (id, name, created_at) VALUES ('d', 'D', 't')")
    conn.commit()


def test_two_point_oh_tables_and_activity_columns_exist():
    """2.0 additions: vista_history + briefings tables, and the reversal
    columns on activity — all additive, so a 1.x database opens unchanged."""
    conn = db.connect()
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"vista_history", "briefings"} <= tables
    act_cols = {r["name"] for r in conn.execute("PRAGMA table_info(activity)")}
    assert {"object_kind", "object_id", "revert", "reversal_of"} <= act_cols
    # And a plain 1.x-era insert (no new columns) still works.
    conn.execute("INSERT INTO activity (ts, actor, action) VALUES ('t', 'a', 'x')")
    conn.commit()
