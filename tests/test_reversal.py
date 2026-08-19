"""The reversal engine — undo made structural (2.0, LOGIC-MERGE decision I).

Every mutation that knows its own inverse stores it on its activity entry;
reversing applies that inverse and APPENDS a reversal entry. Two doctrine
rules are load-bearing and pinned here: the log is append-only (a reversal is
a new fact, never an erasure), and the checks the confirm dialog shows are
the checks the apply path enforces — same function, so the dialog cannot
promise what the server would refuse.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import auth, db, reversal, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANWISE_VISTA_WORKBOOK", "")
    db.reset_for_tests()
    yield
    db.reset_for_tests()


@pytest.fixture
def admin():
    c = TestClient(app_module.app)
    auth.bootstrap_admin(auth.setup_token(), "Ross Hixon", "a-good-password")
    assert c.post("/api/auth/login",
                  json={"name": "Ross Hixon", "password": "a-good-password"}).status_code == 200
    return c


def test_a_created_po_can_be_reversed_and_the_log_keeps_both_entries(admin):
    po = store.add_po("24-003", {"po_number": "P-1", "vendor": "Cinco Steel",
                                 "original_amount": 1000}, actor="Ross Hixon")
    aid = po["activity_id"]

    r = admin.post(f"/api/activity/{aid}/reverse")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True

    # The PO is gone…
    assert store.list_pos("24-003") == []
    # …but the log holds BOTH entries: the original and the reversal beneath it.
    rows = store.list_activity("24-003", 10)
    actions = [row["action"] for row in rows]
    assert "po.create" in actions and "reversed" in actions
    reversal_row = next(row for row in rows if row["action"] == "reversed")
    assert reversal_row["reversal_of"] == aid


def test_reversing_a_deletion_restores_the_order_with_its_invoices(admin):
    po = store.add_po("24-003", {"po_number": "P-2", "vendor": "Caprock",
                                 "original_amount": 500}, actor="Ross Hixon")
    store.add_invoice("24-003", po["id"], {"invoice_number": "4412", "amount": 200},
                      actor="Ross Hixon")
    assert store.delete_po("24-003", po["id"], actor="Ross Hixon")
    del_entry = store.list_activity("24-003", 5)[0]
    assert del_entry["action"] == "po.delete"

    r = admin.post(f"/api/activity/{del_entry['id']}/reverse")
    assert r.status_code == 200, r.text

    restored = store.list_pos("24-003")
    assert len(restored) == 1
    assert restored[0]["po_number"] == "P-2"
    assert len(restored[0]["invoices"]) == 1, "the cascade-deleted invoice came back too"


def test_an_update_reverses_to_the_exact_prior_values(admin):
    po = store.add_po("24-003", {"po_number": "P-3", "vendor": "Llano",
                                 "original_amount": 300, "status": "Open"},
                      actor="Ross Hixon")
    updated = store.update_po("24-003", po["id"], {"status": "Closed",
                                                   "original_amount": 999},
                              actor="Ross Hixon")

    r = admin.post(f"/api/activity/{updated['activity_id']}/reverse")
    assert r.status_code == 200, r.text
    back = store.list_pos("24-003")[0]
    assert back["status"] == "Open"
    assert back["original_amount"] == 300


def test_a_reversal_is_not_itself_reversible(admin):
    po = store.add_po("24-003", {"po_number": "P-4"}, actor="Ross Hixon")
    aid = po["activity_id"]
    assert admin.post(f"/api/activity/{aid}/reverse").status_code == 200

    again = admin.post(f"/api/activity/{aid}/reverse")
    assert again.status_code == 409
    labels = [c[1] for c in again.json()["checks"]]
    assert "Already reversed" in labels


def test_entries_without_a_stored_inverse_refuse_honestly(admin):
    aid = db.log_activity("Ross Hixon", "24-003", "vista.workbook.push", "5 MB")
    r = admin.post(f"/api/activity/{aid}/reverse")
    assert r.status_code == 409
    body = r.json()
    assert body["blocked"] is True
    kinds = {c[1]: c[0] for c in body["checks"]}
    assert kinds["Source of record"] == "fail"


def test_the_checks_endpoint_shows_what_apply_enforces(admin):
    po = store.add_po("24-003", {"po_number": "P-5"}, actor="Ross Hixon")
    checks = admin.get(f"/api/activity/{po['activity_id']}/checks")
    assert checks.status_code == 200
    body = checks.json()
    assert body["blocked"] is False
    assert "never deleted" in body["verdict"]
    heads = [c[1] for c in body["checks"]]
    assert heads[:2] == ["Source of record", "Age"]


def test_someone_elses_entry_needs_an_admin(admin, monkeypatch):
    # A second, non-admin account.
    c2 = TestClient(app_module.app)
    r = c2.post("/api/auth/register", json={
        "email": "jane@wecc.com", "first_name": "Jane", "last_name": "Smith",
        "password": "another-good-password"})
    assert r.status_code == 200
    admin.post("/api/users/Jane Smith/approved", json={"approved": True})

    po = store.add_po("24-003", {"po_number": "P-6"}, actor="Ross Hixon")
    denied = c2.post(f"/api/activity/{po['activity_id']}/reverse")
    assert denied.status_code == 409
    kinds = {c[1]: c[0] for c in denied.json()["checks"]}
    assert kinds["Permission"] == "fail"

    # The admin can.
    assert admin.post(f"/api/activity/{po['activity_id']}/reverse").status_code == 200


def test_a_reversal_whose_object_has_since_vanished_is_blocked(admin):
    po = store.add_po("24-003", {"po_number": "P-7", "status": "Open"}, actor="Ross Hixon")
    upd = store.update_po("24-003", po["id"], {"status": "Closed"}, actor="Ross Hixon")
    store.delete_po("24-003", po["id"], actor="Ross Hixon")

    r = admin.post(f"/api/activity/{upd['activity_id']}/reverse")
    assert r.status_code == 409
    kinds = {c[1]: c[0] for c in r.json()["checks"]}
    assert kinds["Downstream conflict"] == "fail"


def test_record_send_reversal_restores_draft_without_claiming_to_unsend(admin):
    from backend import records
    rec = records.add_record("24-003", "rfi", {"title": "Stub-up count"},
                             actor="Ross Hixon")
    sent = records.mark_sent(rec["id"], actor="Ross Hixon")
    assert sent["status"] == "Sent"

    r = admin.post(f"/api/activity/{sent['activity_id']}/reverse")
    assert r.status_code == 200, r.text
    back = records.get_record(rec["id"])
    assert back["status"] == "Draft"
    assert back["sent_at"] is None
