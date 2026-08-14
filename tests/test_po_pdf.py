"""Reading Vista's printed purchase agreement.

Tuned against the real thing: 16 purchase orders from job 24-003, and the two
dozen other PDFs that live in the same vendor folders — quotes, W9s, insurance
certificates, credit applications, a terms-and-conditions page. Telling those
apart is most of the job. A reader that scrapes any number it sees would fill
the register with quote totals, and the register drives Open/Committed on the
Cost Breakdown (D8).

The sample lives outside the repo (customer data, never committed), so the
real-file tests skip when it is absent — the synthetic ones below always run.
"""
from __future__ import annotations

import pathlib

import pytest

from backend import po_pdf

VENDOR_DIR = pathlib.Path(
    r"C:\Users\rhixon\1910 Legacy Enterprises\Axis Share - Documents"
    r"\1. Axis Active Project Files\24-003 - Siemens Wendell\014 - Vendor")
real = pytest.mark.skipif(not VENDOR_DIR.is_dir(),
                          reason="the Siemens vendor folder isn't on this machine")


def _page(text: str) -> bytes:
    """A one-page PDF carrying this text, for the cases we can synthesise."""
    from backend.changeorder import _esc_pdf, _write_pdf
    ops, y = [], 740
    for line in text.strip().splitlines():
        ops.append(f"BT /F1 9 Tf 0 g 1 0 0 1 40 {y} Tm ({_esc_pdf(line.strip())}) Tj ET")
        y -= 12
    return _write_pdf("\n".join(ops).encode("latin-1", "replace"), None, 0, 0)


SAMPLE = """
Vendor:
CAPITAL ELECTRIC ( 468 )
PO BOX 404749 ATLANTA , GA 30384-4749
Item Description UM Units Unit Cost Total
1
Siemens 4/30/25 Misc. Electrical
Job: 24-003 Siemens - Wendell
Phase: 95-100 - 1 EPC of a 1,518 kWdc Carport solar
LS 0.000 $0.000 $7,993.490
Subtotal: $7,993.49
Purchase Agreement #: 24-003041
"""


# --- the shape of the document ------------------------------------------------

def test_the_fields_come_from_their_labels():
    got = po_pdf.parse(_page(SAMPLE))["candidates"]
    assert len(got) == 1
    c = got[0]
    assert c["po_number"] == "24-003041"
    assert c["vendor"] == "CAPITAL ELECTRIC"
    assert c["amount"] == 7993.49           # the subtotal, not the 0.000 unit cost
    assert c["job_number"] == "24-003"
    assert c["phase"] == "95-100"
    assert "Misc. Electrical" in c["description"]


def test_the_number_comes_from_the_document_not_the_filename():
    """Exporting from Vista sometimes puts an extra digit in the filename —
    PO_3_24-003011.pdf — that means nothing to anybody. It appears nowhere
    inside the PDF, so reading the document is both more accurate and immune
    to how the file was named."""
    got = po_pdf.parse(_page(SAMPLE), "PO_3_24-003041.pdf")["candidates"]
    assert got[0]["po_number"] == "24-003041"
    assert "3_" not in got[0]["po_number"]


def test_a_document_with_no_purchase_agreement_number_yields_nothing():
    got = po_pdf.parse(_page("Quotation\nAcme Supply\nTotal: $12,500.00"))
    assert got["candidates"] == []
    assert "purchase agreement" in got["detail"].lower()


def test_a_scan_is_told_apart_from_an_empty_result():
    """'Nothing found' would send someone hunting a layout problem that isn't
    there."""
    from backend.changeorder import _write_pdf
    got = po_pdf.parse(_write_pdf(b"", None, 0, 0))
    assert got["candidates"] == []
    assert "scan" in got["detail"].lower()


def test_a_po_for_another_job_is_flagged():
    """These figures feed Open/Committed for whichever job they land in, so a
    PO filed against the wrong one moves two jobs' numbers and looks
    reasonable in both."""
    cands = po_pdf.parse(_page(SAMPLE))["candidates"]
    assert po_pdf.check_job(cands, "24-003") == []
    warn = po_pdf.check_job(cands, "8435")
    assert warn and "24-003" in warn[0] and "8435" in warn[0]


# --- against the real exports -------------------------------------------------

@real
def test_every_real_purchase_agreement_reads():
    found = {}
    for f in sorted(VENDOR_DIR.rglob("*.pdf")):
        for c in po_pdf.parse(f.read_bytes(), f.name)["candidates"]:
            found[c["po_number"]] = c

    # Spot-checked against the PDFs themselves.
    expected = {
        "24-003041": (7993.49, "CAPITAL ELECTRIC"),
        "24-003048": (7840.11, "CAPITAL ELECTRIC"),
        "24-003053": (586.83, "CAPITAL ELECTRIC"),
        "24-003007": (45000.00, "CAPITAL ELECTRIC"),
        "24-003031": (794252.02, "STATE ELECTRIC SUPPLY"),
        "24-003025": (7243.00, "CENTIMARK"),
        "24-003010": (13598.00, "HURRICANE FENCE"),
        "24-003023": (29700.00, "REXEL"),
    }
    for number, (amount, vendor_starts) in expected.items():
        assert number in found, f"{number} was not read"
        assert found[number]["amount"] == amount, number
        assert found[number]["vendor"].startswith(vendor_starts), found[number]["vendor"]
        assert found[number]["job_number"] == "24-003", number
    # 16 purchase agreement PDFs, 15 distinct numbers: 24-003006 is filed in
    # two vendor folders, and de-duplicating by number is the point — the same
    # PO must not become two commitments.
    assert len(found) == 15


@real
def test_the_other_paperwork_in_those_folders_is_left_alone():
    """Quotes, W9s, insurance certificates, credit applications and the terms
    page all live beside the purchase orders. A greedy reader would turn quote
    totals into commitments."""
    noise = 0
    for f in sorted(VENDOR_DIR.rglob("*.pdf")):
        name = f.name.lower()
        if any(k in name for k in ("quote", "w9", "certificate", "credit",
                                   "conditions", "estimate", "resubmittal",
                                   "authorization", "agreement.pdf")):
            assert po_pdf.parse(f.read_bytes(), f.name)["candidates"] == [], f.name
            noise += 1
    assert noise >= 8, "expected to have checked a decent sample of non-POs"
