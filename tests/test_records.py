"""Pipeline records + the outbound package's isolation guarantee."""
from __future__ import annotations

import io

import pytest

from backend import db, documents, records


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def make_pdf(pages: int = 2) -> bytes:
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_record_crud_and_status_validation():
    rfi = records.add_record("24-003", "rfi", {"number": "RFI-001",
                                              "title": "Slab detail conflict",
                                              "question": "Which detail governs?"},
                             actor="Ross")
    assert rfi["status"] == "Draft"
    sub = records.add_record("24-003", "submittal", {"number": "SUB-001"}, actor="Ross")

    records.update_record(sub["id"], {"status": "Revise & Resubmit"})
    assert records.get_record(sub["id"])["status"] == "Revise & Resubmit"

    with pytest.raises(records.RecordError, match="not a valid rfi status"):
        records.update_record(rfi["id"], {"status": "Approved"})  # submittal-only
    with pytest.raises(records.RecordError, match="kind"):
        records.add_record("24-003", "memo", {})

    assert len(records.list_records("24-003")) == 2
    assert [r["kind"] for r in records.list_records("24-003", kind="rfi")] == ["rfi"]
    assert records.delete_record(sub["id"]) is True


def test_attachments_reference_real_document_pages():
    doc = documents.add_document("24-003", "E-101.pdf", make_pdf(2))
    rfi = records.add_record("24-003", "rfi", {"number": "RFI-001"})
    att = records.attach_page(rfi["id"], doc["id"], 2, actor="Ross")
    assert att["document_name"] == "E-101.pdf"
    assert records.get_record(rfi["id"])["attachments"][0]["page"] == 2

    with pytest.raises(records.RecordError, match="out of range"):
        records.attach_page(rfi["id"], doc["id"], 9)
    with pytest.raises(records.RecordError, match="No such document"):
        records.attach_page(rfi["id"], "nope", 1)

    assert records.detach_page(rfi["id"], att["id"]) is True


def test_deleting_a_record_removes_its_layer_but_not_internal():
    doc = documents.add_document("24-003", "d.pdf", make_pdf(1))
    rfi = records.add_record("24-003", "rfi", {})
    layer = records.layer_for(rfi)
    documents.add_annotation(doc["id"], 1, "internal", {"type": "rect"})
    documents.add_annotation(doc["id"], 1, layer, {"type": "rect"})

    records.delete_record(rfi["id"])
    assert documents.list_annotations(doc["id"], layer="internal") != []
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) c FROM annotations WHERE layer = ?",
                        (layer,)).fetchone()["c"] == 0


def test_package_contains_record_layer_and_never_internal():
    """THE pipeline guarantee. A page carrying both internal redlines and the
    RFI's own markups exports with ONLY the RFI layer burned in."""
    from pypdf import PdfReader

    doc = documents.add_document("24-003", "E-101.pdf", make_pdf(2))
    rfi = records.add_record("24-003", "rfi", {"number": "RFI-001"})
    layer = records.layer_for(rfi)

    # internal redline with an unmistakable text marker + a shape
    documents.add_annotation(doc["id"], 2, "internal",
                             {"type": "text", "x": .1, "y": .1,
                              "text": "INTERNAL-ONLY-REDLINE-XYZZY"})
    documents.add_annotation(doc["id"], 2, "internal",
                             {"type": "rect", "x": .7, "y": .7, "w": .1, "h": .1})
    # the RFI's own markups
    documents.add_annotation(doc["id"], 2, layer,
                             {"type": "text", "x": .3, "y": .3, "text": "SEE RFI QUESTION"})
    documents.add_annotation(doc["id"], 2, layer,
                             {"type": "ellipse", "x": .4, "y": .4, "w": .2, "h": .1})

    records.attach_page(rfi["id"], doc["id"], 2)
    data = records.build_package(rfi["id"])

    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 1  # single-page extract, not the whole set
    content = reader.pages[0].get_contents().get_data().decode("latin-1")
    assert "SEE RFI QUESTION" in content
    import re
    assert re.search(r"c\s+S", content)  # the ellipse's Bézier strokes
    assert "INTERNAL-ONLY-REDLINE-XYZZY" not in content
    text = reader.pages[0].extract_text()
    assert "SEE RFI QUESTION" in text
    assert "XYZZY" not in text


def test_package_orders_pages_and_requires_attachments():
    doc = documents.add_document("24-003", "set.pdf", make_pdf(3))
    rfi = records.add_record("24-003", "rfi", {})
    with pytest.raises(records.RecordError, match="No pages attached"):
        records.build_package(rfi["id"])
    records.attach_page(rfi["id"], doc["id"], 3)
    records.attach_page(rfi["id"], doc["id"], 1)
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(records.build_package(rfi["id"])))
    assert len(reader.pages) == 2


def test_rotated_page_markup_lands_in_display_orientation():
    """The Enersys bug: a page with /Rotate 90 displays upright in the app,
    but the overlay burned into unrotated space — markups came out vertical.
    The overlay must pass through the same rotation the viewer applies."""
    import re
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    pg = w.add_blank_page(width=612, height=792)
    pg.rotate(90)
    buf = io.BytesIO()
    w.write(buf)

    doc = documents.add_document("24-003", "rotated.pdf", buf.getvalue())
    rfi = records.add_record("24-003", "rfi", {"number": "RFI-002"})
    documents.add_annotation(doc["id"], 1, records.layer_for(rfi),
                             {"type": "text", "x": .3, "y": .1, "text": "ROTATED-MARK"})
    records.attach_page(rfi["id"], doc["id"], 1)

    reader = PdfReader(io.BytesIO(records.build_package(rfi["id"])))
    page = reader.pages[0]
    assert page.rotation % 360 == 90  # original orientation preserved
    content = page.get_contents().get_data().decode("latin-1")
    assert "ROTATED" in content  # pypdf may octal-escape punctuation (\055)
    # the display->page transform matrix for /Rotate 90
    assert re.search(r"0\s+1\s+-1\s+0\s+612(\.0+)?\s+0\s+cm", content)


def test_package_with_clean_page_has_no_overlay():
    doc = documents.add_document("24-003", "d.pdf", make_pdf(1))
    rfi = records.add_record("24-003", "rfi", {})
    records.attach_page(rfi["id"], doc["id"], 1)
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(records.build_package(rfi["id"])))
    assert len(reader.pages) == 1
