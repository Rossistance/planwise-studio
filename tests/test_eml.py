"""The .eml share path — install-free sharing for companion-less machines.

The file the server hands over must be a genuine RFC-822 message that classic
desktop Outlook opens in compose mode, and it must obey exactly the same
audience rules as the companion path: the customer version carries recipients
and no internal columns; the team version ships unaddressed and INTERNAL-
tagged. These tests parse the actual bytes with the stdlib parser — the same
grammar Outlook reads.
"""
from __future__ import annotations

from email import policy
from email.parser import BytesParser

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import auth, db, eml, lookahead, records, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANWISE_VISTA_WORKBOOK", "")
    db.reset_for_tests()
    yield
    db.reset_for_tests()


@pytest.fixture
def client():
    c = TestClient(app_module.app)
    auth.bootstrap_admin(auth.setup_token(), "Ross Hixon", "a-good-password")
    r = c.post("/api/auth/login", json={"name": "Ross Hixon", "password": "a-good-password"})
    assert r.status_code == 200
    return c


def parse(raw: bytes):
    return BytesParser(policy=policy.default).parsebytes(raw)


def lookahead_period(with_contact=True):
    if with_contact:
        store.patch_meta("24-003", {"contacts": [
            {"name": "Jane GC", "email": "jane@gc.com", "role": "Customer PM"}]},
            actor="Ross Hixon")
    period = lookahead.get_or_create_period("24-003", "2026-08-10")
    item = lookahead.add_item(period["id"], {"task": "Pull wire L2", "days": "1" * 5})
    lookahead.toggle_day(item["id"], 0, True)
    return period


# --- the builder itself -------------------------------------------------------

def test_build_eml_is_a_parseable_compose_mode_message():
    raw = eml.build_eml("Subject here", "a@x.com;b@y.com",
                        html="<p>Hello <b>there</b></p>",
                        attachments=[("sheet.pdf", b"%PDF-1.4 fake")])
    msg = parse(raw)
    assert msg["Subject"] == "Subject here"
    assert msg["To"] == "a@x.com, b@y.com"
    assert msg["X-Unsent"] == "1"                      # what opens compose mode
    assert msg.get_body(("html",)).get_content().strip() == "<p>Hello <b>there</b></p>"
    # The plain alternative exists and carries the words, not the markup.
    plain = msg.get_body(("plain",)).get_content()
    assert "Hello" in plain and "<b>" not in plain
    [att] = list(msg.iter_attachments())
    assert att.get_filename() == "sheet.pdf"
    assert att.get_content_type() == "application/pdf"
    assert att.get_content() == b"%PDF-1.4 fake"


def test_build_eml_plain_text_and_no_recipients():
    raw = eml.build_eml("Internal sheet", "", text="Plain words only.")
    msg = parse(raw)
    assert msg["To"] is None                           # PM addresses it in Outlook
    assert msg.get_content_type() == "text/plain"
    assert "Plain words only." in msg.get_content()


# --- look ahead ---------------------------------------------------------------

def test_lookahead_customer_eml_carries_contacts_and_pdf(client):
    period = lookahead_period()
    r = client.get(f"/api/lookahead/{period['id']}/share.eml?audience=customer")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("message/rfc822")
    assert 'filename="Look-Ahead-2wk-24-003-2026-08-10.eml"' in r.headers["content-disposition"]

    msg = parse(r.content)
    assert msg["X-Unsent"] == "1"
    assert "jane@gc.com" in msg["To"]
    [att] = list(msg.iter_attachments())
    assert att.get_filename() == "Look-Ahead-2wk-24-003-2026-08-10.pdf"
    assert att.get_content().startswith(b"%PDF")
    # Customer version: no internal columns in the body.
    assert "Tools" not in msg.get_body(("html",)).get_content()


def test_lookahead_team_eml_is_internal_and_unaddressed(client):
    period = lookahead_period()
    lookahead.update_item(lookahead.list_items(period["id"])[0]["id"],
                          {"tools": "Bender, fish tape"})
    r = client.get(f"/api/lookahead/{period['id']}/share.eml?audience=team")
    assert r.status_code == 200
    msg = parse(r.content)
    assert msg["To"] is None                           # deliberately blank
    assert "[Internal]" in msg["Subject"]
    assert "INTERNAL" in r.headers["content-disposition"]
    assert "Bender, fish tape" in msg.get_body(("html",)).get_content()


def test_an_empty_lookahead_is_a_422_not_an_empty_email(client):
    period = lookahead.get_or_create_period("24-003", "2026-08-10")
    r = client.get(f"/api/lookahead/{period['id']}/share.eml")
    assert r.status_code == 422
    assert "no line items" in r.json()["detail"]


# --- records ------------------------------------------------------------------

def record_with_draft(to_email="gc@customer.com"):
    rec = records.add_record("24-003", "rfi", {
        "title": "Conduit routing at grid B", "number": "RFI-014",
        "to_email": to_email}, actor="Ross Hixon")
    records.save_draft(rec["id"], "RFI-014: Conduit routing at grid B",
                       "Please advise on the routing conflict.", "template")
    return rec


def test_record_eml_uses_the_saved_draft_as_plain_text(client):
    rec = record_with_draft()
    r = client.get(f"/api/records/{rec['id']}/share.eml")
    assert r.status_code == 200
    msg = parse(r.content)
    assert msg["Subject"] == "RFI-014: Conduit routing at grid B"
    assert msg["To"] == "gc@customer.com"
    assert msg["X-Unsent"] == "1"
    assert msg.get_content_type() == "text/plain"      # record drafts are text
    assert "routing conflict" in msg.get_content()
    # No pages attached -> no package, and that is fine, matching the UI guard.
    assert list(msg.iter_attachments()) == []


def test_record_eml_refuses_until_a_draft_exists(client):
    rec = records.add_record("24-003", "rfi", {"title": "No draft yet"},
                             actor="Ross Hixon")
    r = client.get(f"/api/records/{rec['id']}/share.eml")
    assert r.status_code == 409
    assert "draft" in r.json()["detail"].lower()


def test_eml_routes_are_session_gated():
    c = TestClient(app_module.app)                     # no sign-in
    assert c.get("/api/lookahead/x/share.eml").status_code == 401
    assert c.get("/api/records/x/share.eml").status_code == 401
    assert c.get("/api/outbox/x/eml").status_code == 401


# --- outbox: records can now be queued from a phone too -----------------------

def queue_record(client, rec):
    r = client.post("/api/outbox", json={
        "job_number": rec["job_number"], "kind": "record", "target_id": rec["id"],
        "note": "from the van"})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_queued_record_renders_a_document_not_a_422(client):
    rec = record_with_draft()
    item = queue_record(client, rec)
    r = client.get(f"/api/outbox/{item['id']}/document")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["subject"] == "RFI-014: Conduit routing at grid B"
    assert doc["to"] == "gc@customer.com"
    assert doc["body"].startswith("from the van")       # queued note leads
    assert "routing conflict" in doc["body"]
    assert "html" not in doc                            # records are plain text
    assert "pdf_b64" not in doc                         # no pages attached


def test_a_queued_record_downloads_as_eml_and_the_claim_is_not_burned(client):
    rec = record_with_draft()
    item = queue_record(client, rec)

    r = client.get(f"/api/outbox/{item['id']}/eml")
    assert r.status_code == 200
    msg = parse(r.content)
    assert msg["X-Unsent"] == "1"
    assert "from the van" in msg.get_content()

    # The GET claimed but did NOT mark drafted — a cancelled download must
    # cost nothing. The item is still pending and downloadable again...
    assert client.get(f"/api/outbox/{item['id']}/eml").status_code == 200
    # ...until the frontend confirms the download landed.
    assert client.post(f"/api/outbox/{item['id']}/drafted").status_code == 200
    assert client.get(f"/api/outbox/{item['id']}/eml").status_code == 409


def test_a_queued_record_without_a_draft_says_why(client):
    rec = records.add_record("24-003", "rfi", {"title": "No draft"}, actor="Ross Hixon")
    item = queue_record(client, rec)
    r = client.get(f"/api/outbox/{item['id']}/document")
    assert r.status_code == 409
    assert "draft" in r.json()["detail"].lower()
