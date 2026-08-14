"""Change order documents — the letter that actually goes to the customer.

WHAT THIS PRODUCES, AND WHY BOTH FORMATS.

WECC's real workflow leaves a .docx and a .pdf of every change order side by
side in the job folder, and both are load-bearing: the Word file is what gets
edited when the customer comes back with "can you break out the scaffolding",
and the PDF is the record of what was sent. So this writes both, from the same
content, rather than making someone convert one into the other by hand.

FORMATTING follows the change orders WECC has been sending — same letterhead,
same WECC blue, same order of business:

    [letterhead banner]
    Change Order Request #001-Rev 2          (centred)
    11/21/2024
    Addressee: <customer company>
    RE: <project>
    Dear <first name>,
    <body: what changed and why>
    <line items, each with its price>
    Total: $177,353.00
    Our request for additional compensation includes costs for additional
    labor, materials, subcontractors, equipment, supervision, and general
    expenses.
    • <clarifications and exceptions>
    We will be pleased to review this matter with you at your convenience.
    Sincerely,
    WHITE ELECTRICAL CONSTRUCTION COMPANY
    <signature>
    <name / title / phone>
    [footer band: white-electrical.com · Raleigh Office · address · phone]

CUSTOMER vs SUBCONTRACTOR. Only the customer letter carries clarifications and
exceptions — they are WECC's standing positions about scope it is NOT taking
on, which is a statement made to whoever is paying. A subcontractor change
order is a log artefact: the same letterhead and the same figures, no
negotiating language, and it drafts with a blank To: line so the PM addresses
it themselves.
"""
from __future__ import annotations

import datetime as dt
import html
import io
import re
import struct
import zipfile
from pathlib import Path
from typing import Any

from . import db

ASSETS = Path(__file__).resolve().parent / "assets"
LETTERHEAD = ASSETS / "wecc-letterhead.jpg"
FOOTER_BAND = ASSETS / "wecc-footer-band.jpg"

WECC_BLUE = "002C77"
COMPANY = "WHITE ELECTRICAL CONSTRUCTION COMPANY"
FOOTER_TEXT = ("white-electrical.com    Raleigh Office:  150 Newspaper Way "
               "Holly Springs, NC 27540  (919) 362-0711")
COMPENSATION = ("Our request for additional compensation includes costs for "
                "additional labor, materials, subcontractors, equipment, "
                "supervision, and general expenses.")
CLOSING = "We will be pleased to review this matter with you at your convenience."


class ChangeOrderError(ValueError):
    """Anything the caller should hear about verbatim."""


# --- the standing library -----------------------------------------------------
# Taken from change orders WECC has actually sent. Customer, engineer and
# vendor names are stripped deliberately — these are reusable positions, and a
# clarification naming last year's customer would go out on this year's letter.
# Only WECC's own name survives, because the sentences are about what WECC is
# and is not doing.
SEED_CLARIFICATIONS = [
    "White Electrical has not included costs related to the site-specific equipment spotter requirement.",
    "White Electrical has not included costs for any additional concrete work required.",
    "White Electrical has not included any cost for additional excavation or duct bank work.",
    "White Electrical has not conducted any voltage drop studies and assumes that the EOR has properly calculated for the increased feeder lengths in their updated design.",
    "White Electrical has assumed the use of ty wraps for cable management is acceptable.",
    "White Electrical has assumed flat ventilated covers for all cable tray provided under this change.",
    "White Electrical has assumed the roof blocks proposed are approved for installation directly on the roof membrane and will not require slip sheets.",
    "White Electrical assumes that any ground ring installed under this change does not need to be tied into an existing ground ring elsewhere on site, as this is not noted on the drawings.",
    "White Electrical requests a schedule adjustment of no less than 30 days to accommodate the scheduling delays on this project, as well as the additional scope of work that has been added.",
    "White Electrical has not included costs for premium time, shift work, or overtime.",
    "White Electrical has not included costs for engineering, permits, or third-party inspection.",
    "White Electrical has excluded any work not expressly described above.",
    "Pricing is valid for 30 days from the date of this request.",
    "This change is priced on the drawings and information available at the date of this request; further revisions will be priced separately.",
]


def ensure_seeded() -> None:
    """Put the standing library in place once, on first use.

    Idempotent by text, so re-seeding after an upgrade never duplicates a
    clarification, and one a PM has archived stays archived.
    """
    conn = db.connect()
    have = {r["text"] for r in conn.execute("SELECT text FROM co_clarifications")}
    for text in SEED_CLARIFICATIONS:
        if text in have:
            continue
        conn.execute(
            "INSERT INTO co_clarifications (id, text, seeded, archived, created_at) "
            "VALUES (?,?,1,0,?)", (db.new_id(), text, db.now()))
    conn.commit()


def list_clarifications(include_archived: bool = False) -> list[dict[str, Any]]:
    ensure_seeded()
    conn = db.connect()
    sql = "SELECT * FROM co_clarifications"
    if not include_archived:
        sql += " WHERE archived = 0"
    sql += " ORDER BY seeded DESC, created_at"
    return [dict(r) for r in conn.execute(sql)]


def add_clarification(text: str, actor: str | None = None) -> dict[str, Any]:
    text = " ".join((text or "").split())
    if len(text) < 8:
        raise ChangeOrderError("That's too short to be a clarification.")
    conn = db.connect()
    row = conn.execute("SELECT * FROM co_clarifications WHERE text = ?", (text,)).fetchone()
    if row:                       # already known — un-archive rather than duplicate
        conn.execute("UPDATE co_clarifications SET archived = 0 WHERE id = ?", (row["id"],))
        conn.commit()
        return dict(conn.execute("SELECT * FROM co_clarifications WHERE id = ?",
                                 (row["id"],)).fetchone())
    rec = {"id": db.new_id(), "text": text, "seeded": 0, "archived": 0,
           "created_by": actor, "created_at": db.now()}
    conn.execute("INSERT INTO co_clarifications (id, text, seeded, archived, created_by, created_at) "
                 "VALUES (?,?,?,?,?,?)", tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, None, "co.clarification.add", text[:80])
    return rec


def archive_clarification(cid: str, actor: str | None = None) -> bool:
    conn = db.connect()
    cur = conn.execute("UPDATE co_clarifications SET archived = 1 WHERE id = ?", (cid,))
    conn.commit()
    return cur.rowcount > 0


# --- breakout pricing ---------------------------------------------------------

def list_items(co_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM change_order_items WHERE co_id = ? ORDER BY sort_order, rowid",
        (co_id,))]


def set_items(co_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace the breakout for this change order.

    Replace rather than patch: the UI edits the whole list, and reconciling
    per-row identity would buy nothing but a chance to lose a line.
    """
    conn = db.connect()
    conn.execute("DELETE FROM change_order_items WHERE co_id = ?", (co_id,))
    for i, it in enumerate(items or []):
        desc = " ".join(str(it.get("description") or "").split())
        if not desc:
            continue                       # a blank row is the UI's spare, not data
        try:
            amount = float(it.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        conn.execute("INSERT INTO change_order_items (id, co_id, description, amount, sort_order) "
                     "VALUES (?,?,?,?,?)", (db.new_id(), co_id, desc, amount, i))
    conn.commit()
    return list_items(co_id)


def items_total(co_id: str) -> float | None:
    """What the breakout adds up to, or None when there is no breakout.

    None is the distinction that matters: a change order with no line items
    keeps whatever amount was typed on the register, and one WITH them is
    totalled from them, so the letter and its arithmetic can never disagree.
    """
    rows = list_items(co_id)
    return sum(float(r["amount"] or 0) for r in rows) if rows else None


def get_selected(co_id: str) -> list[str]:
    conn = db.connect()
    return [r["text"] for r in conn.execute(
        "SELECT text FROM change_order_clarifications WHERE co_id = ? "
        "ORDER BY sort_order, rowid", (co_id,))]


def set_selected(co_id: str, texts: list[str], actor: str | None = None) -> list[str]:
    """Replace this change order's clarifications with exactly these.

    Stored as text, not as references to the library: editing a library entry
    must never rewrite what a change order sent last year actually said.
    """
    clean = [" ".join((t or "").split()) for t in texts]
    clean = [t for t in clean if t]
    conn = db.connect()
    conn.execute("DELETE FROM change_order_clarifications WHERE co_id = ?", (co_id,))
    for i, text in enumerate(clean):
        conn.execute("INSERT INTO change_order_clarifications (id, co_id, text, sort_order) "
                     "VALUES (?,?,?,?)", (db.new_id(), co_id, text, i))
    conn.commit()
    return clean


# --- shared content -----------------------------------------------------------

def _money(v: Any) -> str:
    """$1,234.56, and a credit in parentheses the way an accountant reads it."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "$0.00"
    return f"({'${:,.2f}'.format(abs(n))})" if n < 0 else "${:,.2f}".format(n)


def _us_date(iso: str | None) -> str:
    try:
        return dt.date.fromisoformat((iso or "")[:10]).strftime("%-m/%-d/%Y")
    except (ValueError, TypeError):
        try:
            return dt.date.fromisoformat((iso or "")[:10]).strftime("%m/%d/%Y").lstrip("0")
        except (ValueError, TypeError):
            return dt.date.today().strftime("%m/%d/%Y")


def _first_name(full: str | None) -> str:
    return (full or "").strip().split(" ")[0] or "Sir or Madam"


def compose(co: dict, job: dict, *, clarifications: list[str] | None = None,
            contact: dict | None = None, prepared_by: dict | None = None,
            customer: str | None = None, items: list[dict] | None = None) -> dict:
    """Everything both writers need, worked out once.

    Keeping this separate is what stops the .docx and the .pdf drifting into
    two subtly different letters — they are the same document twice.
    """
    kind = co.get("kind") or "customer"
    number = co.get("co_number") or co.get("cust_co_number") or "—"
    is_customer = kind == "customer"

    # Who the letter is addressed to: the customer company for a customer CO,
    # the subcontractor's own name for a sub CO. Falls back to the contact's
    # name rather than leaving the line blank.
    addressee = (customer if is_customer else co.get("subcontractor")) or ""
    addressee = addressee.strip() or (contact or {}).get("name") or ""
    project = job.get("job_name") or job.get("job_number") or ""

    # Breakout wins when there is one: the letter's arithmetic and its lines
    # must agree, and a typed total that disagrees with the lines beneath it is
    # the kind of error a customer finds first.
    lines = [{"description": i.get("description") or "",
              "amount": float(i.get("amount") or 0)} for i in (items or [])]
    amount = sum(l["amount"] for l in lines) if lines else co.get("amount_submitted")
    if amount is None:
        amount = co.get("amount_pending") or co.get("amount_approved") or 0

    # The narrative is what a PM writes; `description` is the register label
    # and is only a fallback so a letter is never wordless.
    body = (co.get("narrative") or "").strip() or (co.get("description") or "").strip()
    if not body:
        body = ("This is to notify you of a change in scope to the "
                "above-referenced project.")
    elif is_customer and addressee:
        body = (f"This is to notify {addressee} of the following change in scope "
                f"to the above-referenced project. {body}")

    who = prepared_by or {}
    return {
        "kind": kind,
        "is_customer": is_customer,
        "title": f"Change Order Request #{number}",
        "date": _us_date(co.get("date_submitted")),
        "addressee": addressee,
        "project": project,
        "salutation": f"Dear {_first_name((contact or {}).get('name'))},",
        "body": body,
        "items": [{"description": l["description"], "amount": _money(l["amount"])}
                  for l in lines],
        "total_label": "Total:",
        "total": _money(amount),
        "clarifications": list(clarifications or []) if is_customer else [],
        "signer": who.get("name") or "",
        "signer_title": who.get("title") or "Branch Manager – Raleigh",
        "signer_phone": who.get("phone") or "",
        "filename": f"Change_Order_{re.sub(r'[^A-Za-z0-9_.-]+', '_', str(number))}",
    }


# --- .docx --------------------------------------------------------------------

def _x(s: Any) -> str:
    return html.escape(str(s or ""), quote=False)


def _p(text: str, *, bold=False, center=False, size=22, color=None,
       font=None, space_after=160) -> str:
    rpr = "".join([
        f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>' if font else "",
        "<w:b/>" if bold else "",
        f'<w:color w:val="{color}"/>' if color else "",
        f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>',
    ])
    return (f'<w:p><w:pPr>{"<w:jc w:val=\"center\"/>" if center else ""}'
            f'<w:spacing w:after="{space_after}"/><w:rPr>{rpr}</w:rPr></w:pPr>'
            f'<w:r><w:rPr>{rpr}</w:rPr>'
            f'<w:t xml:space="preserve">{_x(text)}</w:t></w:r></w:p>')


def build_docx(doc: dict) -> bytes:
    """A Word file, assembled by hand.

    python-docx would be one more dependency that has to install cleanly on
    Render and behind corporate TLS inspection (A2/D37), for something that is
    ultimately a zip of XML. The letterhead and footer band ride along as the
    same JPEGs Word itself embedded in the originals.
    """
    body: list[str] = [
        _p(doc["title"], center=True, size=24, bold=True),
        _p(doc["date"]),
        _p(f"Addressee: {doc['addressee']}") if doc["addressee"] else "",
        _p(f"RE: {doc['project']}"),
        _p(""),
        _p(doc["salutation"]),
        _p(doc["body"]),
    ]
    for it in doc["items"]:
        body.append(_p(f"{it['description']}: {it['amount']}", space_after=60))
    if doc["items"]:
        body.append(_p(""))
    body.append(_p(f"{doc['total_label']} {doc['total']}", bold=True))
    if doc["is_customer"]:
        body.append(_p(COMPENSATION))
        for line in doc["clarifications"]:
            body.append(_p(f"• {line}", space_after=80))
    body += [
        _p(""),
        _p(CLOSING),
        _p(""),
        _p("Sincerely,"),
        _p(COMPANY),
        _p(doc["signer"], font="Brush Script MT", size=48, space_after=0),
        _p(doc["signer"], space_after=0),
        _p(doc["signer_title"], space_after=0),
        _p(doc["signer_phone"]),
    ]

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<w:body>{"".join(b for b in body if b)}'
        '<w:sectPr><w:headerReference w:type="default" r:id="rIdHdr"/>'
        '<w:footerReference w:type="default" r:id="rIdFtr"/>'
        '<w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1800" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="480" w:footer="480" w:gutter="0"/></w:sectPr>'
        '</w:body></w:document>')

    def image_para(rid: str, w_emu: int, h_emu: int) -> str:
        return (
            '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="0"/></w:pPr><w:r><w:drawing>'
            f'<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            f'distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{w_emu}" cy="{h_emu}"/><wp:docPr id="1" name="banner"/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:nvPicPr><pic:cNvPr id="1" name="banner"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{w_emu}" cy="{h_emu}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')

    hdr_ns = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">')
    # 2550x372 at 96dpi, scaled to a 6.5" text column: 6.5" = 5943600 EMU.
    header = (hdr_ns + image_para("rIdImg", 5943600, int(5943600 * 372 / 2550))
              + _p("EMPOWERING PEOPLE    POWERFUL SOLUTIONS", center=True,
                   size=26, color=WECC_BLUE, space_after=0)
              + "</w:hdr>")
    footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
              + _p(FOOTER_TEXT, center=True, size=18, color=WECC_BLUE, space_after=0)
              + "</w:ftr>")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Default Extension="jpg" ContentType="image/jpeg"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                   '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                   '</Relationships>')
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rIdHdr" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
                   '<Relationship Id="rIdFtr" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
                   '</Relationships>')
        z.writestr("word/header1.xml", header)
        z.writestr("word/_rels/header1.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rIdImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/letterhead.jpg"/>'
                   '</Relationships>')
        z.writestr("word/footer1.xml", footer)
        if LETTERHEAD.is_file():
            z.writestr("word/media/letterhead.jpg", LETTERHEAD.read_bytes())
    return out.getvalue()


# --- .pdf ---------------------------------------------------------------------

_PW, _PH = 612.0, 792.0            # US Letter, portrait
_MARGIN = 72.0

# Helvetica advance widths, as used by the look-ahead writer: measuring text
# is what lets a paragraph wrap at the right column instead of running off
# the page.
from .lookahead import text_width as _tw  # noqa: E402


def _esc_pdf(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _latin1(s: str) -> str:
    """Helvetica's built-in encoding has no em dash or curly quotes; swap them
    for shapes it does have rather than dropping characters silently."""
    for a, b in (("—", "-"), ("–", "-"), ("’", "'"),
                 ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("•", "-"), (" ", " ")):
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _wrap(text: str, width: float, size: float, bold: bool = False) -> list[str]:
    out, line = [], ""
    for word in _latin1(text).split():
        trial = f"{line} {word}".strip()
        if _tw(trial, size, bold) <= width or not line:
            line = trial
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out or [""]


def _jpeg_size(data: bytes) -> tuple[int, int]:
    i = 2
    while i < len(data) - 9:
        if data[i] == 0xFF and data[i + 1] in (0xC0, 0xC1, 0xC2):
            return (struct.unpack(">H", data[i + 7:i + 9])[0],
                    struct.unpack(">H", data[i + 5:i + 7])[0])
        i += 1
    return (2550, 372)


def build_pdf(doc: dict) -> bytes:
    """The same letter, hand-authored as PDF.

    Same technique as the look-ahead sheet (D18): content streams written
    directly, no PDF library. The letterhead is embedded as a DCTDecode image
    XObject — the identical JPEG Word uses, so the two formats put the same
    banner at the top of the page.
    """
    img = LETTERHEAD.read_bytes() if LETTERHEAD.is_file() else None
    iw, ih = _jpeg_size(img) if img else (0, 0)

    ops: list[str] = []
    y = _PH - 40.0
    col = _PW - 2 * _MARGIN

    if img:
        bw = _PW - 2 * 36.0
        bh = bw * ih / iw
        y = _PH - 24.0 - bh
        ops.append(f"q {bw:.2f} 0 0 {bh:.2f} 36 {y:.2f} cm /Im0 Do Q")
        y -= 16
        ops.append(f"BT /F1 11 Tf 0.0 0.173 0.467 rg 1 0 0 1 "
                   f"{(_PW - _tw('EMPOWERING PEOPLE    POWERFUL SOLUTIONS', 11)) / 2:.1f} {y:.1f} Tm "
                   f"({_esc_pdf('EMPOWERING PEOPLE    POWERFUL SOLUTIONS')}) Tj ET")
        y -= 30

    def line(text: str, *, size=11, bold=False, center=False, gap=15.0,
             indent=0.0):
        nonlocal y
        for chunk in _wrap(text, col - indent, size, bold):
            x = ((_PW - _tw(chunk, size, bold)) / 2 if center
                 else _MARGIN + indent)
            ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf 0 g "
                       f"1 0 0 1 {x:.1f} {y:.1f} Tm ({_esc_pdf(chunk)}) Tj ET")
            y -= gap
        return y

    line(doc["title"], size=14, bold=True, center=True, gap=26)
    line(doc["date"])
    if doc["addressee"]:
        line(f"Addressee: {doc['addressee']}")
    line(f"RE: {doc['project']}", gap=24)
    line(doc["salutation"], gap=22)
    line(doc["body"], gap=15)
    y -= 8
    for it in doc["items"]:
        # Description left, price right-aligned against the margin, so a
        # column of money reads as a column rather than ragged prose.
        ops.append(f"BT /F1 11 Tf 0 g 1 0 0 1 {_MARGIN:.1f} {y:.1f} Tm "
                   f"({_esc_pdf(_latin1(it['description']))}) Tj ET")
        w = _tw(it["amount"], 11)
        ops.append(f"BT /F1 11 Tf 0 g 1 0 0 1 {_PW - _MARGIN - w:.1f} {y:.1f} Tm "
                   f"({_esc_pdf(it['amount'])}) Tj ET")
        y -= 15
    if doc["items"]:
        y -= 6
    line(f"{doc['total_label']} {doc['total']}", bold=True, gap=24)

    if doc["is_customer"]:
        line(COMPENSATION, gap=15)
        y -= 6
        for text in doc["clarifications"]:
            # Marker before the text, so the extracted reading order matches
            # what the eye sees — a PDF's text layer is what any downstream
            # reader (or this app's own importer) works from.
            ops.append(f"BT /F1 11 Tf 0 g 1 0 0 1 {_MARGIN:.1f} {y:.1f} Tm "
                       f"({_esc_pdf('-')}) Tj ET")
            line(text, indent=16, gap=14)
            y -= 4

    y -= 10
    line(CLOSING, gap=26)
    line("Sincerely,", gap=15)
    line(COMPANY, gap=34)
    if doc["signer"]:
        line(doc["signer"], gap=15)
        line(doc["signer_title"], gap=13)
        if doc["signer_phone"]:
            line(doc["signer_phone"], gap=13)

    ops.append(f"BT /F1 8 Tf 0.0 0.173 0.467 rg 1 0 0 1 "
               f"{(_PW - _tw(_latin1(FOOTER_TEXT), 8)) / 2:.1f} 34 Tm "
               f"({_esc_pdf(_latin1(FOOTER_TEXT))}) Tj ET")

    stream = "\n".join(ops).encode("latin-1", "replace")
    return _write_pdf(stream, img, iw, ih)


def build_sub_log_pdf(job: dict, cos: list[dict]) -> bytes:
    """Subcontractor change orders as a LOG, not a letter.

    A sub CO is not a negotiation with the party paying us — it is a record of
    what a subcontractor is owed, and what the customer has therefore agreed
    to. So this is the register itself: the same columns the screen shows,
    ruled and totalled, under the same letterhead. Addressing it "Dear
    <customer>" was simply wrong, and worse than wrong — it put the customer's
    name on a document about a subcontractor's money.

    Landscape, because eight columns do not fit across a portrait page without
    squeezing the description to uselessness.
    """
    img = LETTERHEAD.read_bytes() if LETTERHEAD.is_file() else None
    iw, ih = _jpeg_size(img) if img else (0, 0)
    pw, ph = 792.0, 612.0                       # letter, landscape
    left, right = 36.0, pw - 36.0

    cols = [("CO #", 52.0, "l"), ("Subcontractor", 118.0, "l"), ("Date", 62.0, "l"),
            ("Description", 216.0, "l"), ("Submitted", 78.0, "r"),
            ("Pending", 70.0, "r"), ("Approved", 78.0, "r"), ("Approved By", 46.0, "l")]

    ops: list[str] = []
    y = ph - 20.0
    if img:
        bw = (right - left) * 0.52
        bh = bw * ih / iw
        y = ph - 18.0 - bh
        ops.append(f"q {bw:.2f} 0 0 {bh:.2f} {left:.1f} {y:.2f} cm /Im0 Do Q")
        y -= 18

    title = f"Subcontractor Change Order Log — {job.get('job_name') or job.get('job_number') or ''}"
    ops.append(f"BT /F2 13 Tf 0 g 1 0 0 1 {left:.1f} {y:.1f} Tm "
               f"({_esc_pdf(_latin1(title))}) Tj ET")
    stamp = dt.date.today().strftime("%m/%d/%Y")
    n = len(cos)
    sub = (f"Job {job.get('job_number') or ''} · {n} change order"
           f"{'' if n == 1 else 's'} · as of {stamp}")
    y -= 14
    ops.append(f"BT /F1 9 Tf 0.35 0.37 0.4 rg 1 0 0 1 {left:.1f} {y:.1f} Tm "
               f"({_esc_pdf(_latin1(sub))}) Tj ET")
    y -= 18

    def rule(at: float, weight: float = 0.6):
        ops.append(f"q {weight} w 0.72 0.71 0.68 RG {left:.1f} {at:.1f} m "
                   f"{right:.1f} {at:.1f} l S Q")

    def row(values: list[str], *, bold=False, size=8.5, height=15.0):
        nonlocal y
        x = left
        for (label, w, align), val in zip(cols, values):
            text = _latin1(str(val or ""))
            while text and _tw(text, size, bold) > w - 8:
                text = text[:-1]
            tx = x + (w - 8 - _tw(text, size, bold)) if align == "r" else x
            ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf 0 g "
                       f"1 0 0 1 {tx + 3:.1f} {y:.1f} Tm ({_esc_pdf(text)}) Tj ET")
            x += w
        y -= height

    rule(y + 11)
    row([c[0] for c in cols], bold=True)
    rule(y + 11, 0.9)

    tot_s = tot_p = tot_a = 0.0
    for co in cos:
        tot_s += float(co.get("amount_submitted") or 0)
        tot_p += float(co.get("amount_pending") or 0)
        tot_a += float(co.get("amount_approved") or 0)
        row([co.get("co_number") or "", co.get("subcontractor") or "",
             _us_date(co.get("date_submitted")) if co.get("date_submitted") else "",
             co.get("description") or "",
             _money(co.get("amount_submitted")) if co.get("amount_submitted") is not None else "",
             _money(co.get("amount_pending")) if co.get("amount_pending") else "",
             _money(co.get("amount_approved")) if co.get("amount_approved") is not None else "",
             co.get("approved_by") or ""])
        rule(y + 11, 0.4)
        if y < 90:                              # one page is the log's scope today
            break

    y -= 4
    rule(y + 11, 0.9)
    row(["", "", "", "Total", _money(tot_s), _money(tot_p) if tot_p else "",
         _money(tot_a), ""], bold=True)

    ops.append(f"BT /F1 8 Tf 0.0 0.173 0.467 rg 1 0 0 1 "
               f"{(pw - _tw(_latin1(FOOTER_TEXT), 8)) / 2:.1f} 26 Tm "
               f"({_esc_pdf(_latin1(FOOTER_TEXT))}) Tj ET")

    return _write_pdf("\n".join(ops).encode("latin-1", "replace"), img, iw, ih,
                      page=(pw, ph))


def _write_pdf(stream: bytes, img: bytes | None, iw: int, ih: int,
               page: tuple[float, float] | None = None) -> bytes:
    pw, ph = page or (_PW, _PH)
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    ]
    xobj = " /XObject << /Im0 7 0 R >>" if img else ""
    objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.0f} {ph:.0f}] "
                 f"/Resources << /Font << /F1 5 0 R /F2 6 0 R >>{xobj} >> "
                 f"/Contents 4 0 R >>").encode())
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    if img:
        objs.append((f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} "
                     f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                     f"/Length {len(img)} >>\nstream\n").encode() + img + b"\nendstream")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
              f"startxref\n{xref}\n%%EOF".encode())
    return out.getvalue()
