"""The field role — the email on the job setup line IS the role.

Doctrine as sentences: a field account's office writes are refused with a
sentence naming where that work lives; the field's own work keeps working;
an administrator is never field-limited; and the role is per job — the same
person can be the PM somewhere else.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import auth, db, field, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANWISE_VISTA_WORKBOOK", "")
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def make_users():
    auth.bootstrap_admin(auth.setup_token(), "Ross Hixon", "a-good-password")
    auth.set_email("Ross Hixon", "rhixon@1910Legacy.com", actor="Ross Hixon")
    u = auth.register("tkowalski@1910Legacy.com", "Terry", "Kowalski", "a-good-password")
    auth.approve_account(u["name"], actor="Ross Hixon")


def signin(name):
    c = TestClient(app_module.app)
    assert c.post("/api/auth/login",
                  json={"name": name, "password": "a-good-password"}).status_code == 200
    return c


def test_the_setup_email_line_is_the_role():
    make_users()
    store.patch_meta("24-003", {"field_leader": "Terry Kowalski",
                                "field_leader_email": "TKowalski@1910legacy.COM"},
                     actor="Ross Hixon")
    assert field.field_jobs_for("tkowalski@1910Legacy.com") == ["24-003"], \
        "matching is by email, case-insensitively"
    assert field.field_jobs_for("rhixon@1910Legacy.com") == []


def test_office_writes_refuse_with_a_sentence_and_field_work_keeps_working():
    make_users()
    store.patch_meta("24-003", {"superintendent_email": "tkowalski@1910Legacy.com"},
                     actor="Ross Hixon")
    c = signin("Terry Kowalski")

    r = c.post("/api/jobs/24-003/pos", json={"po_number": "P-9", "vendor": "X",
                                             "original_amount": 5})
    assert r.status_code == 403 and "office app" in r.json()["detail"]
    r = c.patch("/api/jobs/24-003/meta", json={"project_manager": "Terry"})
    assert r.status_code == 403, "the setup page that grants the role is office-only"

    # The field's own work: raise a draft RFI, and read the registers.
    r = c.post("/api/jobs/24-003/records", json={"kind": "rfi", "title": "Bus spacing"})
    assert r.status_code == 200, r.text
    assert c.get("/api/jobs/24-003/records").status_code == 200

    status = c.get("/api/auth/status").json()
    assert status["field_jobs"] == ["24-003"]


def test_the_role_is_per_job_not_per_person():
    make_users()
    store.patch_meta("24-003", {"field_leader_email": "tkowalski@1910Legacy.com"},
                     actor="Ross Hixon")
    c = signin("Terry Kowalski")
    r = c.post("/api/jobs/26-101/pos", json={"po_number": "P-1", "vendor": "Y",
                                             "original_amount": 10})
    assert r.status_code == 200, "on 26-101 Terry is not the field role — full app"


def test_an_administrator_is_never_field_limited():
    make_users()
    store.patch_meta("24-003", {"superintendent_email": "rhixon@1910Legacy.com"},
                     actor="Ross Hixon")
    c = signin("Ross Hixon")
    r = c.post("/api/jobs/24-003/pos", json={"po_number": "P-2", "vendor": "Z",
                                             "original_amount": 1})
    assert r.status_code == 200, "the owner cannot lock himself out of his office"
    assert c.get("/api/auth/status").json()["field_jobs"] == []
