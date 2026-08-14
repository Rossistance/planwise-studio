"""Read purchase orders out of Vista's printed purchase agreement.

Tuned against 16 real POs from job 24-003 (Capital Electric, State Electric
Supply, CentiMark, Hurricane Fence, Rexel/Mayer). They are rendered by
"Microsoft Reporting Services PDF Rendering Extension" — SSRS — which means
the layout is a report template rather than free text, and the fields sit
behind stable labels:

    Vendor:
    CAPITAL ELECTRIC                        (468)
    ...
    Item  Description  UM  Units  Unit Cost  Total
    1
    Siemens 4/30/25 Misc. Electrical
    Job:     24-003 Siemens - Wendell
    Phase:   95-100 - 1 EPC of a 1,518 kWdc Carport solar & 3916 kWh BESS
    LS  0.000  $0.000  $7,993.490
    Subtotal: $7,993.49
    Purchase Agreement #: 24-003041

THE NUMBER COMES FROM THE DOCUMENT, NEVER THE FILENAME. Exporting from Vista
sometimes puts an extra digit in the filename — `PO_3_24-003011.pdf` — that
means nothing to anybody and is deleted by whoever renames the file, or isn't.
That digit appears nowhere inside the PDF, so reading `Purchase Agreement #`
is both more accurate and immune to how the file was named.

Everything here is a PROPOSAL. The PO register drives Open/Committed on the
Cost Breakdown (D8), so a misread amount moves a number the whole job is
judged by; the caller shows these for confirmation and writes nothing until a
human has agreed.
"""
from __future__ import annotations

import re
from typing import Any

# `Purchase Agreement #: 24-003041` — the authoritative PO number.
_PA = re.compile(r"Purchase\s+Agreement\s*#\s*:?\s*([0-9]{2}-[0-9]{4,}|[A-Z0-9][\w-]{3,})", re.I)
# `Subtotal: $7,993.49`. SSRS prints unit costs to three decimals and the
# subtotal to two, so anchoring on the label avoids picking up a line rate.
_SUBTOTAL = re.compile(r"Subtotal\s*:?\s*\$?\s*([\d,]+\.\d{2})", re.I)
_TOTAL = re.compile(r"\bTotal\s*:?\s*\$?\s*([\d,]+\.\d{2})", re.I)
_JOB = re.compile(r"Job\s*:?\s*([0-9]{2}-[0-9]{3,})", re.I)
_PHASE = re.compile(r"Phase\s*:?\s*([0-9]{2}-[0-9]{3})", re.I)
# `CAPITAL ELECTRIC   (468)` — the vendor code in brackets ends the name.
_VENDOR = re.compile(r"Vendor\s*:?\s*(.+?)\s*\(\s*\d+\s*\)", re.S | re.I)
_VENDOR_LOOSE = re.compile(r"Vendor\s*:?\s*\n?\s*([A-Z][A-Z0-9 ,.&'\-/]{2,60})")


def _money(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _description(flat: str) -> str:
    """The item line — what was actually bought.

    Sits between the table header and the `Job:` label. Falls back to the
    phase description, which carries the scope when the item line is terse.
    """
    m = re.search(r"Unit\s+Cost\s+Total\s*(?:\d+\s+)?(.{3,120}?)\s*Job\s*:", flat, re.I | re.S)
    if m:
        return " ".join(m.group(1).split())
    m = re.search(r"Phase\s*:?\s*[0-9]{2}-[0-9]{3}\s*-?\s*\d*\s*(.{5,120}?)\s*(?:LS|EA|Subtotal)",
                  flat, re.I | re.S)
    return " ".join(m.group(1).split()) if m else ""


def parse(data: bytes, filename: str = "") -> dict[str, Any]:
    """Candidates and warnings from one PDF. Never raises for content."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as exc:  # noqa: BLE001
        return {"candidates": [], "detail":
                f"That file couldn't be read as a PDF ({type(exc).__name__})."}

    if not any(p.strip() for p in pages):
        return {"candidates": [], "detail":
                "That PDF has no text layer — it is probably a scan. Export the "
                "purchase agreement from Vista rather than scanning a printout."}

    # One purchase agreement per page is the normal shape, but a batch export
    # puts several in one file — so each page is examined on its own and
    # de-duplicated by number afterwards.
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in pages:
        flat = " ".join(page.split())
        pa = _PA.search(flat)
        if not pa:
            continue
        number = pa.group(1)
        if number in seen:
            continue

        amount_m = _SUBTOTAL.search(flat) or _TOTAL.search(flat)
        amount = _money(amount_m.group(1)) if amount_m else None
        vendor_m = _VENDOR.search(flat) or _VENDOR_LOOSE.search(flat)
        vendor = " ".join(vendor_m.group(1).split()) if vendor_m else ""
        job_m, phase_m = _JOB.search(flat), _PHASE.search(flat)

        seen.add(number)
        out.append({
            "po_number": number,
            "vendor": vendor,
            "description": _description(flat),
            "amount": amount,
            "job_number": job_m.group(1) if job_m else None,
            "phase": phase_m.group(1) if phase_m else None,
            # What it was read from, so a human can check it in one glance
            # rather than opening the PDF again.
            "evidence": f"Purchase Agreement #: {number}"
                        + (f" · Subtotal ${amount_m.group(1)}" if amount_m else " · no subtotal found"),
        })

    if not out:
        return {"candidates": [], "detail":
                "No purchase agreement number was found. This reader expects the "
                "PDF Vista produces for a purchase agreement — a terms-and-conditions "
                "page or a scanned copy won't have one."}
    return {"candidates": out, "detail": ""}


def check_job(candidates: list[dict], job_number: str) -> list[str]:
    """Warn when a PO belongs to a different job.

    Worth stopping on: these figures feed Open/Committed for the job they land
    in, so a PO filed against the wrong one moves two jobs' numbers at once
    and looks perfectly reasonable in both.
    """
    wrong = {c["job_number"] for c in candidates
             if c.get("job_number") and c["job_number"] != job_number}
    if not wrong:
        return []
    return [f"This purchase order is for job {', '.join(sorted(wrong))}, not "
            f"{job_number}. Importing it here would add its value to the wrong "
            f"job's committed cost."]
