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


# --- breakout pricing ---------------------------------------------------------

def test_line_items_are_itemised_and_drive_the_total(client):
    with_contact()
    co = make_co(amount_submitted=1.00)          # deliberately wrong on the row
    client.put(f"/api/jobs/24-003/cos/{co['id']}/items", json={"items": [
        {"description": "Cable Tray Install", "amount": 149049.00},
        {"description": "Duke Meter H Frame", "amount": 4901.00},
        {"description": "BESS Reactor Firewall", "amount": -1500.00},
    ]})

    from pypdf import PdfReader
    text = PdfReader(BytesIO(
        client.get(f"/api/jobs/24-003/cos/{co['id']}/document.pdf").content)).pages[0].extract_text()
    assert "Cable Tray Install" in text
    assert "$149,049.00" in text
    assert "($1,500.00)" in text                 # a credit reads as a credit
    assert "$152,450.00" in text                 # totalled from the lines, not the row

    # The register follows the breakout, so the table and the letter agree.
    row = next(c for c in store.list_cos("24-003") if c["id"] == co["id"])
    assert row["amount_submitted"] == 152450.00


def test_without_line_items_the_typed_amount_still_rules(client):
    with_contact()
    co = make_co(amount_submitted=177353.00)
    from pypdf import PdfReader
    text = PdfReader(BytesIO(
        client.get(f"/api/jobs/24-003/cos/{co['id']}/document.pdf").content)).pages[0].extract_text()
    assert "$177,353.00" in text


def test_the_narrative_is_what_the_letter_says(client):
    """`description` is a register label — "Additional Conduit" — and reads as
    nothing in a letter."""
    with_contact()
    co = make_co(description="Additional Conduit")
    store.update_co("24-003", co["id"], {
        "narrative": "The engineering team has requested the feeder be installed in "
                     "cable tray along the roof of the building."}, actor="Ross Hixon")

    from pypdf import PdfReader
    text = PdfReader(BytesIO(
        client.get(f"/api/jobs/24-003/cos/{co['id']}/document.pdf").content)).pages[0].extract_text()
    assert "cable tray along the roof" in text


# --- the subcontractor log ----------------------------------------------------

def test_the_subcontractor_pdf_is_a_log_and_never_names_the_customer(client):
    """It was rendering as a customer letter — "Dear Jon," and the customer's
    company on a document about a subcontractor's money."""
    with_contact()                               # customer contact exists...
    store.add_co("24-003", {"kind": "subcontractor", "co_number": "001",
                            "subcontractor": "Badger Electric",
                            "description": "delay compensation",
                            "amount_submitted": 1000.00,
                            "amount_approved": 1000.00}, actor="Ross Hixon")
    sub = next(c for c in store.list_cos("24-003") if c["kind"] == "subcontractor")

    from pypdf import PdfReader
    text = PdfReader(BytesIO(
        client.get(f"/api/jobs/24-003/cos/{sub['id']}/document.pdf").content)).pages[0].extract_text()

    assert "Subcontractor Change Order Log" in text
    assert "Badger Electric" in text
    assert "delay compensation" in text
    assert "Dear" not in text                    # ...and it is addressed to nobody
    assert "Axis Energy" not in text
    assert changeorder.CLOSING[:30] not in text


def test_the_sub_log_totals_the_register(client):
    for n, amt in (("001", 1000.00), ("002", 2500.00)):
        store.add_co("24-003", {"kind": "subcontractor", "co_number": n,
                                "subcontractor": "Badger Electric",
                                "description": f"work {n}",
                                "amount_submitted": amt, "amount_approved": amt},
                     actor="Ross Hixon")
    sub = next(c for c in store.list_cos("24-003") if c["kind"] == "subcontractor")
    from pypdf import PdfReader
    text = PdfReader(BytesIO(
        client.get(f"/api/jobs/24-003/cos/{sub['id']}/document.pdf").content)).pages[0].extract_text()
    assert "$3,500.00" in text                   # both, added up
    assert "2 change orders" in text


def test_a_po_raised_against_a_sub_co_records_which_one(client):
    """An approved sub CO is a commitment the sub will invoice against — but
    they can only invoice a PO. Without the link the change order would sit on
    the "awaiting a PO" list forever, even after the PO existed."""
    sub = store.add_co("24-003", {"kind": "subcontractor", "co_number": "001",
                                  "subcontractor": "Badger Electric",
                                  "description": "delay compensation",
                                  "amount_approved": 1000.00}, actor="Ross Hixon")
    po = client.post("/api/jobs/24-003/pos", json={
        "po_number": "PO-001", "vendor": "Badger Electric",
        "adjusted_amount": 1000.00, "cost_type": "Subcontractor",
        "source_co_id": sub["id"]}).json()
    assert po["source_co_id"] == sub["id"]

    # And it survives the round trip, which is what the UI filters on.
    stored = next(p for p in store.list_pos("24-003") if p["id"] == po["id"])
    assert stored["source_co_id"] == sub["id"]


# --- reading purchase orders out of a Vista PDF -------------------------------

def _pdf_with_lines(lines):
    """A one-page PDF carrying exactly these text lines."""
    from backend.changeorder import _esc_pdf, _write_pdf
    ops, y = [], 720
    for ln in lines:
        ops.append(f"BT /F1 10 Tf 0 g 1 0 0 1 60 {y} Tm ({_esc_pdf(ln)}) Tj ET")
        y -= 16
    return _write_pdf("\n".join(ops).encode("latin-1", "replace"), None, 0, 0)


def test_a_vista_pdf_is_proposed_never_written(client):
    """The PO register drives Open/Committed on the Cost Breakdown (D8), so a
    misread amount moves a number the whole job is judged by. Nothing lands
    until a human has looked at it."""
    pdf = _pdf_with_lines([
        "Purchase Order Report - Job 24-003",
        "PO 24-003113  SENSEHAWK INC.  Monitoring subscription   2,000.00",
        "PO 24-003114  BADGER ELECTRIC  Trenching and backfill   21,450.00",
        "Total                                                   23,450.00",
    ])
    r = client.post("/api/jobs/24-003/pos/import",
                    files={"file": ("vista-pos.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    got = r.json()["candidates"]
    numbers = {c["po_number"] for c in got}
    assert "24-003113" in numbers and "24-003114" in numbers
    assert any(c["amount"] == 2000.0 for c in got)
    assert any(c["amount"] == 21450.0 for c in got)
    # Every candidate says which line it came from, so it can be checked.
    assert all(c["evidence"] for c in got)

    # And absolutely nothing was written.
    assert store.list_pos("24-003") == []


def test_a_scanned_pdf_says_so_rather_than_returning_nothing(client):
    """An empty result and an unreadable file are different problems, and
    "nothing found" would send someone hunting a layout issue that isn't."""
    from backend.changeorder import _write_pdf
    r = client.post("/api/jobs/24-003/pos/import", files={
        "file": ("scan.pdf", _write_pdf(b"", None, 0, 0), "application/pdf")})
    assert r.status_code == 200
    assert r.json()["candidates"] == []
    assert "scan" in r.json()["detail"].lower()


def test_an_unrecognised_layout_asks_for_a_copy(client):
    pdf = _pdf_with_lines(["Some report", "with no purchase orders on it at all"])
    r = client.post("/api/jobs/24-003/pos/import",
                    files={"file": ("other.pdf", pdf, "application/pdf")})
    assert r.json()["candidates"] == []
    assert "taught its layout" in r.json()["detail"]
