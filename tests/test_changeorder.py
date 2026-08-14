"""Change order letters — the document that actually goes to a customer.

Two properties carry the weight here. A customer letter must never be built
without somebody to address it to, because a change order addressed to no one
is worse than an error message. And a subcontractor letter must never carry
clarifications and exceptions: those are WECC's negotiating positions with
whoever is paying, and putting them in front of a sub is a different
conversation entirely.
"""
from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import auth, changeorder, db, store


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
    assert c.post("/api/auth/login",
                  json={"name": "Ross Hixon", "password": "a-good-password"}).status_code == 200
    return c


def make_co(kind="customer", **kw):
    fields = {"kind": kind, "co_number": "001", "date_submitted": "2026-08-14",
              "description": "Feeder rerouted through cable tray along the roof.",
              "amount_submitted": 177353.00}
    fields.update(kw)
    return store.add_co("24-003", fields, actor="Ross Hixon")


def with_contact():
    store.patch_meta("24-003", {
        "customer": "Axis Energy Inc.",
        "contacts": [{"name": "Josh Miller", "email": "josh@axis.example",
                      "role": "Customer PM"}]}, actor="Ross Hixon")


# --- the no-contact guard -----------------------------------------------------

def test_a_customer_letter_without_a_contact_says_where_to_add_one(client):
    co = make_co()
    r = client.get(f"/api/jobs/24-003/cos/{co['id']}/document.pdf")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["needs_contact"] is True
    assert "Overview" in detail["detail"]


def test_a_subcontractor_letter_needs_no_customer_contact(client):
    """It is addressed to the sub, so the customer contact is irrelevant —
    requiring one would block a document that has nothing to do with them."""
    co = make_co(kind="subcontractor", subcontractor="Badger Electric")
    r = client.get(f"/api/jobs/24-003/cos/{co['id']}/document.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


# --- what each letter carries -------------------------------------------------

def test_the_customer_letter_carries_the_selected_clarifications(client):
    with_contact()
    co = make_co()
    picked = changeorder.SEED_CLARIFICATIONS[:2]
    assert client.patch(f"/api/jobs/24-003/cos/{co['id']}/clarifications",
                        json={"clarifications": picked}).status_code == 200

    r = client.get(f"/api/jobs/24-003/cos/{co['id']}/document.pdf")
    assert r.status_code == 200
    from pypdf import PdfReader
    text = PdfReader(BytesIO(r.content)).pages[0].extract_text()
    for line in picked:
        assert line.split(".")[0][:40] in text
    assert "Axis Energy Inc." in text                  # addressee
    assert "$177,353.00" in text
    assert "WHITE ELECTRICAL CONSTRUCTION COMPANY" in text


def test_a_subcontractor_letter_never_carries_clarifications(client):
    """Even if some were somehow attached to the row, they are WECC's
    positions with the paying party and do not belong in front of a sub."""
    co = make_co(kind="subcontractor", subcontractor="Badger Electric")
    changeorder.set_selected(co["id"], changeorder.SEED_CLARIFICATIONS[:3])

    from pypdf import PdfReader
    r = client.get(f"/api/jobs/24-003/cos/{co['id']}/document.pdf")
    text = PdfReader(BytesIO(r.content)).pages[0].extract_text()
    assert "White Electrical has not included" not in text
    assert changeorder.COMPENSATION[:40] not in text
    assert "Badger Electric" in text                   # still addressed to them


def test_the_subcontractor_share_leaves_the_to_line_blank(client):
    with_contact()                                     # present, and still unused
    co = make_co(kind="subcontractor", subcontractor="Badger Electric")
    share = client.get(f"/api/jobs/24-003/cos/{co['id']}/share").json()
    assert share["to"] == ""
    assert share["contacts"] == []

    customer = make_co(co_number="002")
    cshare = client.get(f"/api/jobs/24-003/cos/{customer['id']}/share").json()
    assert cshare["to"] == "josh@axis.example"


def test_the_share_attaches_both_word_and_pdf(client):
    with_contact()
    co = make_co()
    share = client.get(f"/api/jobs/24-003/cos/{co['id']}/share").json()
    names = [a["filename"] for a in share["attachments"]]
    assert any(n.endswith(".pdf") for n in names), names
    assert any(n.endswith(".docx") for n in names), names

    import base64
    docx = next(a for a in share["attachments"] if a["filename"].endswith(".docx"))
    z = zipfile.ZipFile(BytesIO(base64.b64decode(docx["content_b64"])))
    assert z.testzip() is None
    assert "word/document.xml" in z.namelist()
    assert "word/media/letterhead.jpg" in z.namelist()   # same banner as Word's


# --- the standing library -----------------------------------------------------

def test_the_library_seeds_itself_and_never_duplicates(client):
    first = client.get("/api/co-clarifications").json()["clarifications"]
    assert len(first) == len(changeorder.SEED_CLARIFICATIONS)
    again = client.get("/api/co-clarifications").json()["clarifications"]
    assert len(again) == len(first)
    assert all("White Electrical" in c["text"] or "Pricing" in c["text"]
               or "This change" in c["text"] for c in first)


def test_seeded_clarifications_name_no_customer_or_vendor(client):
    """They came from real letters. A clarification still naming last year's
    customer would go out on this year's change order."""
    for c in client.get("/api/co-clarifications").json()["clarifications"]:
        for name in ("Axis", "Siemens", "Duke", "Pure Power", "Hanwha", "Tesla"):
            assert name.lower() not in c["text"].lower(), c["text"]


def test_a_pm_can_add_one_and_it_is_offered_next_time(client):
    r = client.post("/api/co-clarifications",
                    json={"text": "White Electrical has excluded all trenching through rock."})
    assert r.status_code == 200
    assert r.json()["seeded"] == 0

    texts = [c["text"] for c in client.get("/api/co-clarifications").json()["clarifications"]]
    assert "White Electrical has excluded all trenching through rock." in texts

    # Adding the same wording twice is one entry, not two.
    client.post("/api/co-clarifications",
                json={"text": "White Electrical has excluded all trenching through rock."})
    after = [c["text"] for c in client.get("/api/co-clarifications").json()["clarifications"]]
    assert after.count("White Electrical has excluded all trenching through rock.") == 1


def test_editing_the_library_never_rewrites_a_sent_letter(client):
    """A change order is a record of what was said. Clarifications are stored
    on the CO as text, so archiving or changing the library entry afterwards
    cannot alter what an old letter claimed."""
    with_contact()
    co = make_co()
    original = changeorder.SEED_CLARIFICATIONS[0]
    changeorder.set_selected(co["id"], [original])

    lib = client.get("/api/co-clarifications").json()["clarifications"]
    entry = next(c for c in lib if c["text"] == original)
    client.delete(f"/api/co-clarifications/{entry['id']}")

    assert changeorder.get_selected(co["id"]) == [original]
    from pypdf import PdfReader
    r = client.get(f"/api/jobs/24-003/cos/{co['id']}/document.pdf")
    assert original.split(".")[0][:40] in PdfReader(BytesIO(r.content)).pages[0].extract_text()
