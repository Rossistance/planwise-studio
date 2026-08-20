"""Document library + annotation layers. PDFs are generated with pypdf —
no binary fixtures, and tests never touch real files."""
from __future__ import annotations

import io

import pytest

from backend import config, db, documents


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def make_pdf(pages: int = 3) -> bytes:
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_upload_stores_file_and_counts_pages():
    doc = documents.add_document("24-003", "E-101 Site Plan.pdf", make_pdf(3), actor="Ross")
    assert doc["page_count"] == 3
    assert doc["uploaded_by"] == "Ross"
    assert documents.doc_path(doc["id"]).is_file()
    assert documents.list_documents("24-003")[0]["name"] == "E-101 Site Plan.pdf"
    assert documents.list_documents("other") == []


def test_non_pdf_is_refused_and_nothing_persists():
    with pytest.raises(documents.DocumentError, match="Only PDF"):
        documents.add_document("24-003", "x.docx", b"PK\x03\x04 not a pdf")
    with pytest.raises(documents.DocumentError, match="readable"):
        documents.add_document("24-003", "x.pdf", b"%PDF-1.7 truncated garbage")
    assert documents.list_documents("24-003") == []
    assert list((config.data_dir() / "documents").glob("*.pdf")) == []


def test_annotations_round_trip_with_layers():
    doc = documents.add_document("24-003", "d.pdf", make_pdf(2))
    a1 = documents.add_annotation(doc["id"], 1, "internal",
                                  {"type": "rect", "x": .1, "y": .2, "w": .3, "h": .1,
                                   "color": "#C23A2E"}, actor="Ross")
    documents.add_annotation(doc["id"], 2, "internal", {"type": "pen", "points": [[0, 0], [1, 1]]})
    documents.add_annotation(doc["id"], 1, "rfi:abc123", {"type": "text", "x": .5, "y": .5, "text": "See note"})

    internal_p1 = documents.list_annotations(doc["id"], layer="internal", page=1)
    assert [a["id"] for a in internal_p1] == [a1["id"]]
    assert internal_p1[0]["shape"]["type"] == "rect"
    assert internal_p1[0]["author"] == "Ross"

    # The isolation boundary: an rfi-layer query never returns internal shapes.
    rfi = documents.list_annotations(doc["id"], layer="rfi:abc123")
    assert len(rfi) == 1 and rfi[0]["shape"]["text"] == "See note"

    assert len(documents.list_annotations(doc["id"])) == 3


def test_bad_layer_page_and_shape_are_refused():
    doc = documents.add_document("24-003", "d.pdf", make_pdf(1))
    with pytest.raises(documents.DocumentError, match="layer"):
        documents.add_annotation(doc["id"], 1, "public", {"type": "rect"})
    with pytest.raises(documents.DocumentError, match="out of range"):
        documents.add_annotation(doc["id"], 9, "internal", {"type": "rect"})
    with pytest.raises(documents.DocumentError, match="Shape type"):
        documents.add_annotation(doc["id"], 1, "internal", {"type": "blob"})
    with pytest.raises(documents.DocumentError, match="layer"):
        documents.list_annotations(doc["id"], layer="internal; DROP TABLE")


def test_delete_document_cascades_annotations_and_removes_file():
    doc = documents.add_document("24-003", "d.pdf", make_pdf(1))
    documents.add_annotation(doc["id"], 1, "internal", {"type": "rect"})
    assert documents.delete_document(doc["id"], actor="Ross") is True
    assert documents.get_document(doc["id"]) is None
    assert not documents.doc_path(doc["id"]).is_file()
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) c FROM annotations").fetchone()["c"] == 0


def test_delete_single_annotation():
    doc = documents.add_document("24-003", "d.pdf", make_pdf(1))
    a = documents.add_annotation(doc["id"], 1, "internal", {"type": "rect"})
    assert documents.delete_annotation(a["id"], actor="Ross") is True
    assert documents.delete_annotation(a["id"]) is False
    assert documents.list_annotations(doc["id"]) == []


def test_annotation_counts_surface_in_library_listing():
    doc = documents.add_document("24-003", "d.pdf", make_pdf(2))
    documents.add_annotation(doc["id"], 1, "internal", {"type": "rect"})
    documents.add_annotation(doc["id"], 1, "rfi:x", {"type": "text", "text": "t"})
    listed = documents.list_documents("24-003")[0]
    assert listed["internal_annotation_count"] == 1  # rfi layer not counted


def test_a_v2_mark_round_trips_and_the_old_vocabulary_still_works():
    """2.0 marks ({v:2, tool, x%, y%}) join the 1.x shapes on the same
    layer-scoped rows — both dialects valid forever, junk still refused."""
    doc = documents.add_document("24-003", "E-201.pdf", make_pdf(2), actor="pm")
    mark = {"v": 2, "tool": "Cloud", "x": 61.2, "y": 40.0, "ink": "#A9291D",
            "weight": 2.5, "text": ""}
    row = documents.add_annotation(doc["id"], 1, "internal", mark, actor="pm")
    assert row["shape"]["tool"] == "Cloud"

    legacy = {"type": "rect", "x0": 0.1, "y0": 0.1, "x1": 0.3, "y1": 0.2,
              "color": "#A9291D"}
    documents.add_annotation(doc["id"], 1, "internal", legacy, actor="pm")
    assert len(documents.list_annotations(doc["id"])) == 2

    with pytest.raises(documents.DocumentError):
        documents.add_annotation(doc["id"], 1, "internal",
                                 {"v": 2, "tool": "Scribble", "x": 1, "y": 1}, actor="pm")
    with pytest.raises(documents.DocumentError):
        documents.add_annotation(doc["id"], 1, "internal",
                                 {"v": 2, "tool": "Pin", "x": 140, "y": 1}, actor="pm")
