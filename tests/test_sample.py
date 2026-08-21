"""The sample project — the one job the guided tour can promise things about.

What matters: seeding is idempotent, reset is total, the synthetic Vista view
flows through the SAME derivations as a real job (cost types, exposure), and
the sample opens on a machine with no extract at all — which is exactly the
machine a brand-new user is sitting at.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import auth, db, sample, store, vista


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANWISE_VISTA_WORKBOOK", "")   # no extract anywhere
    db.reset_for_tests()
    vista._cached = None
    yield
    db.reset_for_tests()
    vista._cached = None


@pytest.fixture
def client():
    c = TestClient(app_module.app)
    auth.bootstrap_admin(auth.setup_token(), "Ross Hixon", "a-good-password")
    assert c.post("/api/auth/login",
                  json={"name": "Ross Hixon", "password": "a-good-password"}).status_code == 200
    return c


def test_seeding_builds_every_surface_and_is_idempotent(client):
    r = client.post("/api/sample/ensure", json={})
    assert r.status_code == 200 and r.json()["seeded"] is True
    assert client.post("/api/sample/ensure", json={}).json()["seeded"] is False

    jd = client.get(f"/api/jobs/{sample.JOB}").json()
    assert jd["job"]["job_name"] == "Meadowlark Substation & Solar Yard"
    assert jd["stale"] is False
    # The rollup ran through vista.cost_types_for — real derivation, not a canned list.
    types = {c["cost_type"] for c in jd["cost_types"]}
    assert {"Labor", "Material", "Subcontract", "Equipment", "Other"} <= types
    # S-001 approved with no PO -> genuine exposure through store.approved_no_po.
    assert jd["approved_no_po"]["total"] == 48_200
    assert len(jd["purchase_orders"]) == 4
    assert len(jd["change_orders"]) == 4
    assert len(jd["meta"]["contacts"]) == 2

    sched = client.get(f"/api/jobs/{sample.JOB}/schedule").json()
    assert len(sched["tasks"]) == 17
    assert len(sched["links"]) >= 8

    recs = client.get(f"/api/jobs/{sample.JOB}/records").json()["records"]
    by_no = {r["number"]: r for r in recs}
    assert by_no["RFI-001"]["status"] == "Answered"
    assert by_no["SUB-003"]["status"] == "Revise & Resubmit"
    replies = client.get(f"/api/records/{by_no['RFI-001']['id']}/replies").json()["replies"]
    assert replies and replies[0]["attachments"], "the answered RFI carries a returned file"

    docs = client.get(f"/api/jobs/{sample.JOB}/documents").json()["documents"]
    assert docs and docs[0]["page_count"] == 2 and docs[0]["internal_annotation_count"] == 3

    hist = client.get(f"/api/jobs/{sample.JOB}/history").json()
    assert len([p for p in hist["history"] if p["grain"] == "month"]) == 6
    assert hist.get("projection"), "the dashed tail needs the overlay's job row"


def test_the_sample_is_findable_with_no_extract_on_the_machine(client):
    client.post("/api/sample/ensure", json={})
    out = client.get("/api/jobs", params={"q": "meadow"}).json()
    assert out["jobs"][0]["job_number"] == sample.JOB
    # And a search that can't match it still reports the honest 503.
    assert client.get("/api/jobs", params={"q": "24-003"}).status_code == 503


def test_reset_rebuilds_the_canonical_state(client):
    client.post("/api/sample/ensure", json={})
    store.add_co(sample.JOB, {"kind": "customer", "co_number": "099",
                              "description": "tour leftover"}, actor="Someone")
    assert len(store.list_cos(sample.JOB)) == 5
    client.post("/api/sample/ensure", json={"reset": True})
    cos = store.list_cos(sample.JOB)
    assert len(cos) == 4 and not any(c["co_number"] == "099" for c in cos)


def test_unseeded_sample_stays_a_404_and_real_jobs_never_see_the_overlay(client):
    assert client.get(f"/api/jobs/{sample.JOB}").status_code == 404
    assert client.get("/api/jobs/24-003").status_code == 503  # no extract, honest error


def test_the_tour_stamp_is_per_account_and_sticks():
    c = TestClient(app_module.app)
    auth.bootstrap_admin(auth.setup_token(), "Ross Hixon", "a-good-password")
    c.post("/api/auth/login", json={"name": "Ross Hixon", "password": "a-good-password"})
    assert c.get("/api/auth/status").json()["user"]["toured"] is False
    assert c.post("/api/auth/toured").status_code == 200
    assert c.get("/api/auth/status").json()["user"]["toured"] is True
