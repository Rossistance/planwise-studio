"""Build the getting-started guide that ships alongside the installer.

    .venv/Scripts/python.exe scripts/make-getting-started.py

Written as a generator rather than a hand-made PDF checked into the repo, so
it cannot drift from the app: the URL, the account flow and the pairing steps
all live here next to the code that implements them, and regenerating takes a
second when something changes.

Same hand-authored PDF technique as the change order letters and the look
ahead sheet — WECC letterhead at the top, no PDF library.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.changeorder import (  # noqa: E402
    FOOTER_TEXT, LETTERHEAD, _esc_pdf, _jpeg_size, _latin1, _tw, _wrap,
)

PW, PH = 612.0, 792.0
MARGIN = 62.0
COL = PW - 2 * MARGIN
URL = "https://planwise-rahj.onrender.com"

# (kind, text) — kind drives the styling, so the content below reads as the
# document it becomes.
CONTENT: list[tuple[str, str]] = [
    ("title", "PlanWise — Getting Started"),
    ("sub", "Project controls for White Electrical. Everything below takes about five minutes."),

    ("h", "1.  Install it"),
    ("p", "Run PlanWise-Setup — the installer that came with this guide. It installs for you "
          "only, so it needs no administrator rights and no IT ticket."),
    ("p", "Two programs arrive together: PlanWise itself, and a small Outlook companion that "
          "runs in the background. You will find PlanWise on the Start menu and on your desktop."),

    ("h", "2.  Create your account"),
    ("p", "Open PlanWise. The first screen asks for your work email and a password you choose. "
          "Nobody sends you a password, and there is nothing to copy from anyone."),
    ("p", "You will then see a short waiting screen. New accounts are approved by an "
          "administrator before they show job data — Ross is notified the moment you sign up, "
          "so this is usually a minute or two. The screen lets you in by itself once approved; "
          "you do not need to refresh or sign in again."),

    ("h", "3.  Take the tour"),
    ("p", "Your first sign-in offers a guided tour. Take it. It opens a fully-built sample "
          "project — every number fake, every mechanism real — and walks you through every "
          "page, inviting you to click and type as you go: open a change order, issue a "
          "purchase order against real exposure, zoom the schedule, mark up a drawing, read "
          "an RFI thread. Nothing you do in the sample matters, which is the point."),
    ("p", "About five minutes, and you can end it at any time. Skip it and PlanWise simply "
          "waits for you to look up your first job. The tour stays under Settings whenever "
          "you want it again, and the sample project stays in the job switcher as a safe "
          "place to try things."),

    ("h", "4.  Connect your Outlook  (optional, but do it)"),
    ("p", "The companion is what lets PlanWise put a draft into YOUR Outlook and notice when a "
          "customer replies. It opens its own page the first time it runs; if you missed it, "
          "browse to http://127.0.0.1:8772/pair."),
    ("p", "Sign in there with the same email and password you just chose. That is the whole "
          "setup — mail always leaves from your own mailbox, and PlanWise never sends anything "
          "itself. You review every draft and press Send. New Outlook or classic both work: "
          "classic opens the draft window, new Outlook finds the draft waiting in Drafts."),
    ("p", "Without the companion PlanWise still works: every share offers a Download email "
          "(.eml) file that opens in Outlook as a ready-made draft. What you lose is one-click "
          "drafting and automatic reply tracking."),

    ("h", "5.  On your phone"),
    ("p", f"Open {URL} on the phone and sign in. In Safari: Share > Add to Home Screen; in "
          "Chrome: menu > Install app. Launch it from that icon and it behaves like an app, "
          "with a layout built for a phone."),
    ("p", "Superintendents and field leads named on a job's setup page get the field version "
          "automatically — today's plan, the drawings, and the records that concern them, "
          "sized for gloves and sunlight."),
    ("p", "Turn on notifications under Settings > Notifications on this device, and an RFI "
          "reply or a returned submittal reaches the phone even with PlanWise closed."),

    ("h", "What you can do straight away"),
    ("b", "Search a job by number or name, and see Vista's cost picture — estimate, actual, "
          "projected, variance, and where each cost type sits by phase code. The data "
          "refreshes itself every morning, and Settings can ask for a fresh pull anytime."),
    ("b", "Produce customer change order letters on WECC letterhead — breakout pricing, your "
          "narrative, the standing clarifications — with a live preview, as Word and PDF."),
    ("b", "See approved subcontractor work with no purchase order as exposure, and issue the "
          "covering PO in one step from the Invoices & POs page."),
    ("b", "Import a schedule from Microsoft Project (.mpp or XML), Excel, CSV — or from a "
          "printed PDF of a customer's schedule — and get a real engine: dependencies, float, "
          "the critical path, and a compare of what changed on re-import."),
    ("b", "Build a two- or three-week look ahead and share it — a customer version, and an "
          "internal one carrying tools and materials that the customer version never shows."),
    ("b", "Raise RFIs and submittals, mark up the drawing pages that go with them, and send "
          "the package from your own Outlook. Replies file themselves back against the "
          "record, and you can compare what came back against what you sent, page by page."),
    ("b", "Let the weekly briefing write its own first draft from the registers, then edit it "
          "in your words and send the customer and internal copies."),
    ("b", "Undo anything you send. Every outbound or destructive act shows an Undo bar, and "
          "the activity log keeps append-only history with reversals recorded beneath."),

    ("h", "If something looks wrong"),
    ("p", "PlanWise tells you when a number is missing rather than showing a confident zero, and "
          "labels anything it is showing from cache with how old it is. If a figure looks wrong, "
          "it is worth reporting rather than working around — that is the whole point of the "
          "rebuild."),
    ("p", "Ross Hixon  ·  rhixon@1910legacy.com"),
]


def build() -> bytes:
    img = LETTERHEAD.read_bytes() if LETTERHEAD.is_file() else None
    iw, ih = _jpeg_size(img) if img else (0, 0)

    pages: list[list[str]] = []
    ops: list[str] = []
    y = PH

    def new_page():
        nonlocal ops, y
        if ops:
            pages.append(ops)
        ops = []
        y = PH - 30.0
        if img:
            bw = PW - 2 * 44.0
            bh = bw * ih / iw
            y = PH - 26.0 - bh
            ops.append(f"q {bw:.2f} 0 0 {bh:.2f} 44 {y:.2f} cm /Im0 Do Q")
            y -= 26

    def room(need: float):
        if y - need < 66:
            new_page()

    new_page()
    for kind, text in CONTENT:
        if kind == "title":
            room(40)
            ops.append(f"BT /F2 19 Tf 0 g 1 0 0 1 {MARGIN:.1f} {y:.1f} Tm "
                       f"({_esc_pdf(_latin1(text))}) Tj ET")
            y -= 22
        elif kind == "sub":
            room(30)
            for chunk in _wrap(text, COL, 11):
                ops.append(f"BT /F1 11 Tf 0.36 0.39 0.44 rg 1 0 0 1 {MARGIN:.1f} {y:.1f} Tm "
                           f"({_esc_pdf(chunk)}) Tj ET")
                y -= 15
            y -= 14
        elif kind == "h":
            room(38)
            y -= 6
            ops.append(f"BT /F2 13 Tf 0.78 0.26 0.04 rg 1 0 0 1 {MARGIN:.1f} {y:.1f} Tm "
                       f"({_esc_pdf(_latin1(text))}) Tj ET")
            y -= 8
            ops.append(f"q 0.6 w 0.85 0.84 0.81 RG {MARGIN:.1f} {y:.1f} m "
                       f"{PW - MARGIN:.1f} {y:.1f} l S Q")
            y -= 16
        elif kind == "p":
            lines = _wrap(text, COL, 11)
            room(len(lines) * 15 + 8)
            for chunk in lines:
                ops.append(f"BT /F1 11 Tf 0 g 1 0 0 1 {MARGIN:.1f} {y:.1f} Tm "
                           f"({_esc_pdf(chunk)}) Tj ET")
                y -= 15
            y -= 8
        elif kind == "b":
            lines = _wrap(text, COL - 16, 11)
            room(len(lines) * 15 + 6)
            ops.append(f"BT /F1 11 Tf 0.78 0.26 0.04 rg 1 0 0 1 {MARGIN:.1f} {y:.1f} Tm "
                       f"({_esc_pdf('-')}) Tj ET")
            for chunk in lines:
                ops.append(f"BT /F1 11 Tf 0 g 1 0 0 1 {MARGIN + 16:.1f} {y:.1f} Tm "
                           f"({_esc_pdf(chunk)}) Tj ET")
                y -= 15
            y -= 6
    pages.append(ops)

    # Footer on every page, and the address on the last one.
    for i, page_ops in enumerate(pages):
        label = f"PlanWise — Getting Started    ·    page {i + 1} of {len(pages)}"
        page_ops.append(f"BT /F1 8 Tf 0.55 0.57 0.6 rg 1 0 0 1 "
                        f"{(PW - _tw(_latin1(label), 8)) / 2:.1f} 46 Tm "
                        f"({_esc_pdf(_latin1(label))}) Tj ET")
        page_ops.append(f"BT /F1 8 Tf 0.0 0.173 0.467 rg 1 0 0 1 "
                        f"{(PW - _tw(_latin1(FOOTER_TEXT), 8)) / 2:.1f} 32 Tm "
                        f"({_esc_pdf(_latin1(FOOTER_TEXT))}) Tj ET")

    return _write(pages, img, iw, ih)


def _write(pages: list[list[str]], img: bytes | None, iw: int, ih: int) -> bytes:
    import io

    n = len(pages)
    first_content = 3 + n
    f_reg, f_bold = first_content + n, first_content + n + 1
    logo_obj = f_bold + 1 if img else None

    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [%s] /Count %d >>"
         % (" ".join(f"{3 + i} 0 R" for i in range(n)), n)).encode(),
    ]
    xobj = f" /XObject << /Im0 {logo_obj} 0 R >>" if img else ""
    for i in range(n):
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PW:.0f} {PH:.0f}] "
                     f"/Resources << /Font << /F1 {f_reg} 0 R /F2 {f_bold} 0 R >>{xobj} >> "
                     f"/Contents {first_content + i} 0 R >>").encode())
    for page_ops in pages:
        s = "\n".join(page_ops).encode("latin-1", "replace")
        objs.append(b"<< /Length " + str(len(s)).encode() + b" >>\nstream\n" + s + b"\nendstream")
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


if __name__ == "__main__":
    dest = Path(__file__).resolve().parent.parent / "dist" / "PlanWise-Getting-Started.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(build())
    print(f"wrote {dest} ({dest.stat().st_size:,} bytes)")
