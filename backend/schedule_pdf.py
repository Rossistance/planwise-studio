"""Read a schedule out of a printed PDF — the format customers actually send.

WHY THIS EXISTS. A customer's scheduler works in MS Project and sends a PDF.
Not the .mpp, not an XML export — a print. Until now that meant somebody
retyped 392 rows, or the schedule simply never made it into PlanWise. This
reads it.

WHAT IS ACTUALLY IN SUCH A FILE, MEASURED. A "Microsoft: Print To PDF" of a
Gantt view is vector, not a scan: the table cells are real text runs, the bars
are placed images, the timescale and dependency arrows are stroked paths. So
the printed columns (ID, WBS, Task Name, Duration, Start, Finish, % Complete)
come back exactly, and the drawing yields bar spans and dependency arrows.

WHAT IS NOT IN IT, AT ALL. Everything that wasn't printed. There is no hidden
layer in a print-to-PDF: resources, costs, calendars, baselines, constraints
and actual dates are simply absent, and no amount of cleverness recovers them.
If the Predecessors column wasn't printed — it usually isn't — then the only
evidence of a dependency is the arrow drawn between two bars.

THE RULE THIS MODULE IS BUILT AROUND: never invent. A row exists only where
there is printed text for it. Bars and arrows may *corroborate* or *flag*, and
arrows may *propose* a dependency, but nothing geometric ever creates a task or
silently sets a date. Proposals leave here marked `inferred` with a confidence
and go to a human before they can move anything.


WHAT WE LEARNED BY MARKING OUR OWN HOMEWORK (2026-08-12)
========================================================
This importer was written against the printed 24-003 Siemens schedule with no
access to the source file. Afterwards the customer's actual `.mpp` turned up
and was used to score the result. Findings, because the next PDF will NOT come
with a source file to check against and these are the lessons that transfer:

**1. The printed text layer is trustworthy. Reading it is not the hard part.**
All 106 printed rows were recovered, with no phantom rows and no missed ones.
Of 106 task names, 94 matched the .mpp verbatim. Every one of the other 12
turned out to be a genuine revision difference, not a misread — "MGC DES"
became "MGC Equipment DES", "Installation of Car Ports" became "Erection of
Car Ports (Parking Lot East Side)" and was split in two, "EV Chargers
Transformers SRE" lost a word. Against the same revision, name fidelity is
effectively total. Trust the text; spend the effort on structure.

**2. A print is a SNAPSHOT, and schedules are renamed constantly.** The PDF was
October, the .mpp was January, and three months moved a dozen task names. So
matching an imported row to an existing one by NAME is unsafe — the same task
routinely arrives with different words. Match on the printed ID (which is what
`external_id` is for), and treat name changes as edits rather than as new
tasks. This is also why re-import reconciles by external_id rather than name.

**3. The printed row count is not the task count.** IDs on this sheet run to
393 while only 106 rows are printed: the view was outline-collapsed and
filtered before printing. Do not treat a gap in IDs as missing data, do not try
to "fill in" the absent ids, and never warn that rows are missing — the printer
chose what to show, and that choice is itself information about what the
customer considered worth sending.

**4. Typography drifts between the file and the print.** The .mpp holds
typographic quotes and dashes ("Disconnect Switch", en-dashes in ranges) which
a print may render — and a text extractor may decode — as their ASCII
equivalents, or not. Names are normalised on the way out for exactly this
reason; without it, two spellings of the same task look like two tasks.

**5. What could NOT be checked, and therefore stays humble.** Outline levels,
summary flags and dependencies could not be verified against the .mpp without
a Java runtime (MPXJ needs a JVM; this machine has none). The hierarchy
derived here from WBS codes and printed indentation is *consistent* with the
document but unverified against the source. That is precisely why inferred
dependencies go to a human, and why the importer says out loud what it could
not see rather than presenting a complete-looking plan.

**6. If a source file is ever available, prefer it outright.** This module
exists because customers send prints. An .mpp or MSPDI export carries
resources, calendars, constraints, baselines and real typed dependencies —
none of which any print contains. A PDF import is a good answer to a bad
situation, not a substitute for the file.
"""
from __future__ import annotations

import io
import re
from typing import Any

from .schedule import ScheduleError, parse_date_text, parse_duration_text

# Text below this height is a footnote or a page number, not a task row.
MIN_FONT = 3.0
# Two runs within this many points of each other vertically are on one line.
ROW_TOLERANCE = 3.0


# --- content-stream reading ---------------------------------------------------

def _mul(a: list[float], b: list[float]) -> list[float]:
    """Compose two PDF matrices (a then b)."""
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


class Page:
    """Everything drawn on one page, in device coordinates."""

    def __init__(self):
        self.texts: list[dict[str, Any]] = []   # {x, y, text, size}
        self.images: list[dict[str, Any]] = []  # {x, y, w, h}  (Gantt bars)
        self.strokes: list[list[tuple[float, float]]] = []
        self.fills: list[list[tuple[float, float]]] = []
        self.width = 0.0
        self.height = 0.0


import contextvars as _ctxv

_PAGE_BYTES: "_ctxv.ContextVar[bytes]" = _ctxv.ContextVar("pdf_bytes", default=b"")
_PAGE_INDEX: "_ctxv.ContextVar[int]" = _ctxv.ContextVar("pdf_page_index", default=0)


def read_page(page) -> Page:
    """Everything drawn on a page: decoded text with positions, plus graphics.

    Text comes from pypdf's extraction visitor rather than a hand-rolled walk
    of the content stream. That is not laziness — a Project print embeds subset
    fonts with their own encodings (the header comes off the wire as
    "7DVN\\x031DPH", which is "Task Name" shifted by 0x1D), and decoding those
    properly means implementing /Differences, ToUnicode CMaps and CID fonts.
    pypdf already does. The visitor hands over the decoded string together with
    the matrices, which is exactly what's needed.

    The matrix composition is still the part that bites: text positions live in
    TEXT space and only become page coordinates after `Tm × CTM`. Reading Tm
    alone gives x values in the tens of thousands — which look like nonsense
    but are simply unscaled, and any column detection built on them quietly
    sorts every row into one band.

    Graphics still need the raw walk: bars are placed images and the links are
    stroked paths, neither of which any text API exposes.
    """
    out = Page()
    box = page.mediabox
    out.width, out.height = float(box.width), float(box.height)

    # Two text extractors, tried in order. pypdf's visitor is the proven
    # path — the Siemens fixture pins it — but a print that routes its text
    # through Form XObjects loses all geometry there: every run lands on one
    # point (seen on the GUC Community Solar prints, 2026-08-21). When the
    # visitor's output is degenerate like that, pdfminer's layout engine
    # reads the same page with real positions. pypdf still does the graphics
    # walk below — pdfminer has no equivalent.
    def visit(text, cm, tm, _font, size):
        if not text or not text.strip():
            return
        m = _mul(list(tm), list(cm))
        eff = abs(float(size or 0) * (m[3] or 1.0)) or abs(float(size or 0))
        out.texts.append({"x": m[4], "y": m[5], "text": text.strip(),
                          "size": eff or 8.0})

    try:
        page.extract_text(visitor_text=visit)
    except Exception as exc:  # noqa: BLE001 — a page that won't decode is a warning
        raise ScheduleError(f"The text on this page could not be decoded: {exc}") from exc

    if out.texts:
        # Broken geometry has a signature: runs PARKED at the page's origin
        # corner (x≈0, y≈page height) because their XObject matrices never
        # composed. A handful can be real furniture; dozens cannot.
        parked = sum(1 for t in out.texts
                     if t["x"] < 1.0 and t["y"] > out.height - 1.0)
        if parked < max(10, 0.15 * len(out.texts)):
            _read_graphics(page, out)
            return out
        out.texts = []          # degenerate geometry: fall through to pdfminer

    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTChar, LTTextContainer, LTTextLine

        for layout in extract_pages(io.BytesIO(_PAGE_BYTES.get()), page_numbers=[_PAGE_INDEX.get()]):
            for element in layout:
                if not isinstance(element, LTTextContainer):
                    continue
                for line in element:
                    if not isinstance(line, LTTextLine):
                        continue
                    # Split a line into CELLS at column-sized gaps only:
                    # "1067 days" and "Wed 7/17/24" must stay one text (the
                    # duration and date parsers see whole cells), while the
                    # wide gaps between a print's columns must break — which
                    # is also what un-fuses a header emitted as one string.
                    frag, x0, size, prev_x1 = "", None, 8.0, None
                    def flush():
                        nonlocal frag, x0, prev_x1
                        if frag.strip():
                            out.texts.append({"x": x0 or 0.0, "y": line.y0,
                                              "text": frag.strip(), "size": size})
                        frag, x0, prev_x1 = "", None, None
                    for ch in line:
                        if not isinstance(ch, LTChar):
                            continue
                        c = ch.get_text()
                        gap = (ch.x0 - prev_x1) if prev_x1 is not None else 0.0
                        if gap > max(2.2 * (ch.size or 8.0) * 0.5, 4.0):
                            flush()
                        if c.isspace():
                            if frag and not frag.endswith(" "):
                                frag += " "
                            prev_x1 = ch.x1
                            continue
                        if x0 is None:
                            x0 = ch.x0
                        size = ch.size or size
                        frag += c
                        prev_x1 = ch.x1
                    flush()
    except Exception as exc:  # noqa: BLE001 — a page that won't decode is a warning
        raise ScheduleError(f"The text on this page could not be decoded: {exc}") from exc

    _read_graphics(page, out)
    return out


def _read_graphics(page, out: Page) -> None:
    """Bars (placed images) and paths (timescale, links) in device space."""
    from pypdf.generic import ContentStream

    cs = ContentStream(page.get_contents(), None)
    ctm = [1, 0, 0, 1, 0, 0]
    stack: list[list[float]] = []
    cur: list[tuple[float, float]] = []

    for operands, op in cs.operations:
        o = op.decode() if isinstance(op, bytes) else str(op)
        try:
            if o == "q":
                stack.append(list(ctm))
            elif o == "Q":
                ctm = stack.pop() if stack else [1, 0, 0, 1, 0, 0]
            elif o == "cm":
                ctm = _mul([float(v) for v in operands], ctm)
            elif o == "m":
                if cur:
                    out.strokes.append(cur)
                cur = [(float(operands[0]), float(operands[1]))]
            elif o in ("l", "v", "y"):
                cur.append((float(operands[-2]), float(operands[-1])))
            elif o == "c" and len(operands) >= 6:
                cur.append((float(operands[4]), float(operands[5])))
            elif o == "re":
                x, y, w, h = (float(v) for v in operands[:4])
                cur = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            elif o in ("S", "s"):
                if cur:
                    out.strokes.append(cur)
                cur = []
            elif o in ("f", "F", "f*", "B", "B*", "b", "b*"):
                if cur:
                    out.fills.append(cur)
                cur = []
            elif o == "n":
                cur = []
            elif o == "Do":
                # A placed image. In a Project print these are the bar fills —
                # one thin gradient strip stretched to the bar's extent.
                out.images.append({"x": ctm[4], "y": ctm[5],
                                   "w": abs(ctm[0]), "h": abs(ctm[3])})
        except (ValueError, TypeError, IndexError):
            continue                      # one malformed operator is not fatal
    if cur:
        out.strokes.append(cur)


# --- rows and columns ---------------------------------------------------------

HEADER_WORDS = ("task name", "duration", "start", "finish", "complete",
                "wbs", "id", "predecessor", "resource")


def group_rows(texts: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Cluster text runs into visual lines by y."""
    body = [t for t in texts if t["size"] >= MIN_FONT and t["text"].strip()]
    rows: list[list[dict[str, Any]]] = []
    for t in sorted(body, key=lambda r: (-r["y"], r["x"])):
        if rows and abs(rows[-1][0]["y"] - t["y"]) <= ROW_TOLERANCE:
            rows[-1].append(t)
        else:
            rows.append([t])
    for r in rows:
        r.sort(key=lambda x: x["x"])
    return rows


def find_header(rows: list[list[dict[str, Any]]]) -> tuple[int, dict[str, float]]:
    """Locate the column header and return each column's left edge.

    Bands are keyed by what the header says, so a print with different columns
    (or in a different order) still lands in the right place.
    """
    for i, row in enumerate(rows[:12]):
        joined = " ".join(t["text"] for t in row).lower()
        if "task name" in joined and ("start" in joined or "duration" in joined):
            cols: dict[str, float] = {}
            # Runs can be split mid-phrase ("Task" "Name"); rebuild by scanning
            # for each known heading across the row's concatenated text.
            for t in row:
                label = t["text"].strip().lower()
                for word in HEADER_WORDS:
                    if label.startswith(word.split()[0]) and word not in cols:
                        cols[word] = t["x"]
            return i, cols
    return -1, {}


_ID_RE = re.compile(r"^\d{1,5}$")
_PCT_RE = re.compile(r"^\d{1,3}%$")
_WBS_RE = re.compile(r"^\d+(?:\.\d+)*$")


def find_chart_left(rows: list[list[dict[str, Any]]], page: Page) -> float:
    """Where the table ends and the Gantt chart begins.

    Not taken from the header: a Project print emits the whole heading as one
    or two runs ("Task Name Duration Start Finish % Complete" arrives as a
    single string), so the header gives no column edges beyond the first.
    Using it put the boundary at x≈198 and silently discarded every date and
    duration on the page — the rows still parsed, they just had no dates.

    The timescale tier is the reliable landmark instead: a row of many very
    short runs (month initials, week numbers) that exists nowhere else on the
    page. Its leftmost run is the chart's left edge.
    """
    for row in rows[:8]:
        if len(row) >= 8 and sum(1 for c in row if len(c["text"]) <= 3) >= len(row) * 0.8:
            return min(c["x"] for c in row) - 6
    # No timescale found (a table-only print). Fall back to the rightmost text
    # that looks like table content, and failing that most of the page width.
    dated = [c["x"] for row in rows for c in row
             if _PCT_RE.match(c["text"].strip()) or len(c["text"]) > 6]
    return (max(dated) + 40) if dated else page.width * 0.55


def parse_page(page: Page, warnings: list[str], page_no: int) -> list[dict[str, Any]]:
    """Turn one page into task rows.

    **A row exists only where an integer sits in the ID column.** That anchor
    is what stops a wrapped task name from becoming a phantom task: any text
    between two ID anchors belongs to the row above it. Clustering on y alone
    would invent a task every time a long name spilled onto a second line, and
    an invented task is precisely what this must never produce.
    """
    rows = group_rows(page.texts)
    hdr_i, cols = find_header(rows)
    if hdr_i < 0:
        warnings.append(f"Page {page_no}: no column header found — page skipped.")
        return []

    id_x = cols.get("id", min((t["x"] for t in rows[hdr_i]), default=0.0))
    name_x = cols.get("task name", id_x + 40)
    chart_x = find_chart_left(rows, page)

    tasks: list[dict[str, Any]] = []
    for row in rows[hdr_i + 1:]:
        cells = [t for t in row if t["x"] < chart_x]
        if not cells:
            continue
        head = cells[0]
        if not _ID_RE.match(head["text"].strip()) or head["x"] > name_x - 4:
            # No ID anchor: a continuation of the previous row's name, or page
            # furniture. Append it to the name rather than inventing a task.
            if tasks and cells and head["x"] >= name_x - 4:
                extra = " ".join(c["text"] for c in cells).strip()
                if extra and not _looks_like_furniture(extra):
                    tasks[-1]["name"] = normalise_name(f"{tasks[-1]['name']} {extra}")
            continue

        task = _row_to_task(cells, head, name_x, page_no, warnings)
        if task:
            task["_y"] = head["y"]
            tasks.append(task)
    return tasks


def _looks_like_furniture(s: str) -> bool:
    low = s.lower()
    return (low.startswith(("page ", "project:", "date:")) or
            bool(re.match(r"^[\d/\-\s]+$", s)) and len(s) < 12)


# Typography drifts between a source file and its print: Project stores
# typographic quotes and dashes, and a print — or a text extractor — may hand
# back either those or their ASCII equivalents. Left alone, the same task reads
# as two different ones depending on which side you came from. Found by
# comparing this importer's output against the customer's own .mpp, where
# «"Disconnect Switch" SRE» could not be matched for exactly this reason.
_TYPOGRAPHY = {
    "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
    "–": "-", "—": "-", "−": "-", " ": " ", "…": "...",
}


def normalise_name(s: str) -> str:
    for a, b in _TYPOGRAPHY.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _row_to_task(cells, head, name_x, page_no, warnings) -> dict[str, Any] | None:
    """Assign a row's cells to fields by shape rather than by column x.

    Right-aligned columns make x-banding unreliable (the header's left edge
    and a right-aligned value's left edge are unrelated), but the values are
    self-identifying: an ID is a bare integer, a WBS is dotted digits, a
    percentage ends in %, a duration carries a unit, and a date parses as one.
    """
    rest = cells[1:]
    ext_id = head["text"].strip()
    wbs = None
    if rest and _WBS_RE.match(rest[0]["text"].strip()) and rest[0]["x"] < name_x:
        wbs = rest[0]["text"].strip()
        rest = rest[1:]

    name_parts, dates, duration, unit, pct = [], [], None, None, None
    for c in rest:
        s = c["text"].strip()
        if not s:
            continue
        # Word-granular extraction splits "Wed 7/17/24" into two tokens; the
        # bare weekday belongs to the date column, never to a task name.
        if re.fullmatch(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)", s):
            continue
        if _PCT_RE.match(s):
            pct = float(s.rstrip("%"))
            continue
        iso, dow_ok = parse_date_text(s)
        if iso and re.search(r"\d/\d|\d-\d", s):
            if not dow_ok:
                warnings.append(
                    f"Page {page_no}, id {ext_id}: '{s}' names a weekday that "
                    f"doesn't match the date — check that row.")
            dates.append(iso)
            continue
        d, u = parse_duration_text(s)
        if d is not None and re.search(r"\d", s) and duration is None \
                and not _WBS_RE.match(s):
            duration, unit = d, u
            continue
        name_parts.append(s)

    name = normalise_name(" ".join(name_parts))
    # A tight print can fuse the date cell onto the name cell; a task name
    # never legitimately ends in "Wed 7/17/24".
    while True:
        trimmed = re.sub(
            r"\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*$",
            "", name)
        if trimmed == name:
            break
        name = trimmed.strip()
    if not name:
        return None

    start = dates[0] if dates else None
    finish = dates[1] if len(dates) > 1 else None
    return {
        "external_id": ext_id,
        "wbs": wbs,
        "name": name,
        "start": start,
        "finish": finish,
        "duration_days": duration,
        "duration_unit": unit,
        "percent_complete": pct if pct is not None else 0.0,
        "is_milestone": 1 if (duration == 0) else 0,
        "is_summary": 0,                      # decided structurally below
        "predecessors": None,
        "name_x": head["x"] if not wbs else head["x"],
        "_name_x": next((c["x"] for c in rest if c["text"].strip() in name), None),
    }


def apply_hierarchy(tasks: list[dict[str, Any]], warnings: list[str]) -> None:
    """Derive outline level, then mark summaries structurally.

    WBS is the honest signal where it exists — `70.101.050.010` is depth four
    and says so. Many rows have no WBS at all, and for those the printed
    INDENT of the task name is the evidence: MS Project prints outline depth as
    name indentation. Neither is a guess about intent; both read what the
    document actually shows.

    A row is a summary iff the row after it is deeper. That is structural, not
    inferred — it's the same thing the printed indentation means.
    """
    indents = sorted({round(t["_name_x"] or 0, 1) for t in tasks if t.get("_name_x")})
    # Quantise indents into levels: MS Project steps them evenly.
    def level_from_indent(x: float | None) -> int:
        if x is None or not indents:
            return 1
        base = indents[0]
        step = 0.0
        for a, b in zip(indents, indents[1:]):
            gap = b - a
            if gap > 1.5 and (step == 0.0 or gap < step):
                step = gap
        if step <= 0:
            return 1
        return max(1, int(round((x - base) / step)) + 1)

    for t in tasks:
        by_wbs = len(t["wbs"].split(".")) if t.get("wbs") else None
        by_indent = level_from_indent(t.get("_name_x"))
        if by_wbs and abs(by_wbs - by_indent) > 1:
            warnings.append(
                f"Id {t['external_id']}: WBS depth ({by_wbs}) and printed indent "
                f"({by_indent}) disagree — outline level taken from the WBS.")
        t["outline_level"] = by_wbs or by_indent

    for i, t in enumerate(tasks):
        nxt = tasks[i + 1] if i + 1 < len(tasks) else None
        t["is_summary"] = 1 if nxt and nxt["outline_level"] > t["outline_level"] else 0
        if t["is_summary"]:
            t["is_milestone"] = 0


# --- the chart: bars and dependency arrows ------------------------------------

# Timescale tier labels a Project print uses above the bars.
_HALF_RE = re.compile(r"\bHalf\s*([12])\s*,?\s*(\d{4})", re.I)
_QTR_RE = re.compile(r"\bQtr\s*([1-4])\s*,?\s*(\d{4})", re.I)
_MONTHYEAR_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})", re.I)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")


def calibrate(page: Page, chart_left: float) -> tuple[float, float] | None:
    """Pixels per day for THIS page, from its own timescale.

    Deliberately per page: a multi-page print has an independent timescale on
    each sheet, and reusing page one's scale would date every bar on the later
    pages wrongly while looking entirely plausible.

    The labels are tier headings rather than plain dates — "Half 2, 2022",
    "Qtr 3, 2024", "Sep 2024" — each of which pins a known calendar date to a
    known x. Two of them give a scale. Returns (x, px_per_day) anchored on the
    leftmost label, or None when the page doesn't offer enough evidence, in
    which case the bars are simply not used for anything.
    """
    from datetime import date as _date

    labels: list[tuple[float, _date]] = []
    for t in page.texts:
        if t["x"] < chart_left or t["size"] < MIN_FONT:
            continue
        s = t["text"].strip()
        m = _HALF_RE.search(s)
        if m:
            labels.append((t["x"], _date(int(m.group(2)), 1 if m.group(1) == "1" else 7, 1)))
            continue
        m = _QTR_RE.search(s)
        if m:
            labels.append((t["x"], _date(int(m.group(2)), (int(m.group(1)) - 1) * 3 + 1, 1)))
            continue
        m = _MONTHYEAR_RE.search(s)
        if m:
            labels.append((t["x"], _date(int(m.group(2)),
                                         _MONTHS.index(m.group(1)[:3].lower()) + 1, 1)))
            continue
        iso, _ok = parse_date_text(s)
        if iso and re.search(r"\d/\d", s):
            labels.append((t["x"], _date.fromisoformat(iso)))

    if len(labels) < 2:
        return None
    labels.sort()
    (x1, d1), (x2, d2) = labels[0], labels[-1]
    days = (d2 - d1).days
    if days <= 0 or (x2 - x1) <= 0:
        return None
    ppd = (x2 - x1) / days

    # Sanity: the scale must reproduce the intermediate labels too, or the
    # tiers were misread and the bars must not be trusted.
    for x, d in labels[1:-1]:
        predicted = x1 + (d - d1).days * ppd
        if abs(predicted - x) > 30:
            return None
    return x1, ppd


def calibration_origin(calib, page_tasks, bars):
    """Turn (x, px/day) into an absolute x→date mapping.

    Anchored on the MEDIAN of every bar on the page, not the first one. A
    single anchor inherits whatever is wrong with that one row — pick a task
    whose bar was mis-matched and every other row on the page then "disagrees"
    with its own printed dates, which is a wall of warnings caused entirely by
    the checker.
    """
    from datetime import date as _date, timedelta
    if not calib:
        return None
    x0, ppd = calib
    offsets = []
    for t in page_tasks:
        b = bars.get(t["external_id"])
        if b and t["start"] and not t.get("is_summary"):
            days_at_x = (b["x"] - x0) / ppd
            offsets.append((_date.fromisoformat(t["start"])
                            - timedelta(days=days_at_x)).toordinal())
    if not offsets:
        return None
    offsets.sort()
    return _date.fromordinal(offsets[len(offsets) // 2]), x0, ppd


def bars_by_row(page: Page, tasks: list[dict[str, Any]], chart_left: float
                ) -> dict[str, dict[str, float]]:
    """Match placed images (bar fills) to task rows by vertical position.

    Where a row has several strips — Project draws progress as a second,
    thinner one over the bar — the widest is the bar itself.
    """
    # A bar is drawn as SEVERAL image placements laid end to end — Project
    # tiles a narrow gradient strip rather than stretching one. Taking the
    # widest single placement therefore measured a tile (a constant six points,
    # i.e. "a few days" no matter the real duration); the bar is the union of
    # every placement sitting on that row.
    spans: dict[str, list[tuple[float, float]]] = {}
    for img in page.images:
        if img["x"] < chart_left or img["w"] < 0.5:
            continue
        best, best_dy = None, 1e9
        for t in tasks:
            dy = abs(t["_y"] - img["y"])
            if dy < best_dy:
                best, best_dy = t, dy
        # Tight tolerance on purpose: a loose one lets a summary row claim the
        # bar belonging to the child beneath it.
        if best is None or best_dy > 4:
            continue
        spans.setdefault(best["external_id"], []).append((img["x"], img["x"] + img["w"]))

    out: dict[str, dict[str, float]] = {}
    for ext, pieces in spans.items():
        left = min(a for a, _ in pieces)
        right = max(b for _, b in pieces)
        out[ext] = {"x": left, "w": max(0.5, right - left)}
    return out


def cross_check_bars(tasks, bars, calib, warnings, page_no) -> None:
    """Compare each bar's drawn span against the printed dates.

    The bar never wins. Printed text is the source of truth; the geometry is
    here only to catch a row that was assembled wrongly — a date read out of
    the wrong column, a row clustered with its neighbour. A disagreement raises
    a warning for a human to look at, and the dates stay exactly as printed.
    """
    if not calib or not bars:
        if bars:
            warnings.append(
                f"Page {page_no}: the timescale couldn't be calibrated, so the "
                f"bars weren't used to check the printed dates.")
        return
    from datetime import date as _date, timedelta

    anchored = calibration_origin(calib, tasks, bars)
    if not anchored:
        return
    origin, x0, ppd = anchored

    mismatched = 0
    for t in tasks:
        b = bars.get(t["external_id"])
        if not b or not t["start"] or not t["finish"]:
            continue
        # Only rows drawn as an ordinary bar are comparable. Summaries are
        # brackets and milestones are diamonds — neither is an image strip, so
        # anything matched to them came from a neighbour.
        if t.get("is_summary") or t.get("duration_days") == 0:
            continue
        drawn_start = origin + timedelta(days=(b["x"] - x0) / ppd)
        drawn_days = b["w"] / ppd
        printed_days = (_date.fromisoformat(t["finish"])
                        - _date.fromisoformat(t["start"])).days + 1
        if abs((drawn_start - _date.fromisoformat(t["start"])).days) > 21 \
                or abs(drawn_days - printed_days) > max(21, printed_days * 0.6):
            mismatched += 1
            if mismatched <= 8:           # a wall of these helps nobody
                warnings.append(
                    f"Id {t['external_id']} ({t['name'][:40]}): the drawn bar and "
                    f"the printed dates disagree — dates kept as printed.")
    if mismatched > 8:
        warnings.append(f"Page {page_no}: {mismatched} rows where the bar and the "
                        f"printed dates disagree (first 8 listed).")


def infer_links(page: Page, tasks: list[dict[str, Any]], bars, chart_left: float
                ) -> list[dict[str, Any]]:
    """Propose dependencies from the arrows drawn between bars.

    This is the only evidence of a dependency a print carries, and it is
    evidence, not fact — so every result leaves here as a PROPOSAL with a
    confidence, for a person to accept or reject. Nothing here writes a link.

    How an arrow is recognised: Project draws a link as an elbow polyline from
    the predecessor's bar to the successor's, ending in a small filled
    triangle. Full-height verticals and full-width horizontals are timescale
    and row chrome and are discarded first. What survives is matched to the
    nearest bar edge at each end.

    Links whose two ends are on different pages cannot be seen at all — half
    the polyline isn't there — and are not guessed at.
    """
    heads = [p for p in page.fills if _is_arrowhead(p)]
    if not heads or not tasks:
        return []

    rows = sorted(tasks, key=lambda t: -t["_y"])
    proposals: list[dict[str, Any]] = []
    for head in heads:
        hx = sum(x for x, _ in head) / len(head)
        hy = sum(y for _, y in head) / len(head)
        if hx < chart_left:
            continue
        succ = _nearest_row(rows, hy)
        if succ is None:
            continue
        path = _path_into(page, hx, hy)
        if not path:
            continue
        sx, sy = path[0]
        pred = _nearest_row(rows, sy)
        if pred is None or pred["external_id"] == succ["external_id"]:
            continue

        # Confidence: how cleanly each end lands on a row, and whether the
        # source end sits at a bar edge rather than in open space.
        dy_s = abs(succ["_y"] - hy)
        dy_p = abs(pred["_y"] - sy)
        conf = max(0.0, 1.0 - (dy_s + dy_p) / 24.0)
        pb = bars.get(pred["external_id"])
        at_edge = pb and (abs(sx - (pb["x"] + pb["w"])) < 6 or abs(sx - pb["x"]) < 6)
        conf = min(1.0, conf + (0.15 if at_edge else -0.25))
        if conf < 0.25:
            continue
        # Geometry only distinguishes "leaves the end of the bar" from "leaves
        # the start"; that is FS versus SS, and it is still an inference.
        ltype = "FS"
        if pb and abs(sx - pb["x"]) < abs(sx - (pb["x"] + pb["w"])):
            ltype = "SS"
        proposals.append({
            "pred_external_id": pred["external_id"],
            "succ_external_id": succ["external_id"],
            "link_type": ltype,
            "lag_days": 0.0,
            "inferred": True,
            "confidence": round(conf, 2),
        })

    # One proposal per pair, keeping the most confident.
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for p in proposals:
        key = (p["pred_external_id"], p["succ_external_id"])
        if key not in best or p["confidence"] > best[key]["confidence"]:
            best[key] = p

    # Where the same two tasks were traced in BOTH directions, the geometry
    # did not actually establish which way the arrow points. Proposing one at
    # random would be inventing a dependency; proposing both would be
    # nonsense. Unless one reading is clearly stronger, drop the pair and say
    # nothing about it.
    resolved: dict[tuple[str, str], dict[str, Any]] = {}
    for key, p in best.items():
        mirror = best.get((key[1], key[0]))
        if mirror and mirror["confidence"] >= p["confidence"] - 0.15:
            continue
        resolved[key] = p
    return sorted(resolved.values(), key=lambda p: -p["confidence"])


def _is_arrowhead(path: list[tuple[float, float]]) -> bool:
    if not 3 <= len(path) <= 5:
        return False
    xs = [x for x, _ in path]
    ys = [y for _, y in path]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    return 0.5 <= w <= 8 and 0.5 <= h <= 8


def _nearest_row(rows, y: float, tol: float = 14.0):
    best, best_dy = None, 1e9
    for t in rows:
        dy = abs(t["_y"] - y)
        if dy < best_dy:
            best, best_dy = t, dy
    return best if best_dy <= tol else None


def _path_into(page: Page, hx: float, hy: float):
    """The polyline that terminates at this arrowhead, returned source-first.

    Either end may be the one touching the arrowhead — nothing obliges a
    producer to draw a link in the direction it points — so both are tried and
    the far end is handed back as the source.
    """
    best, best_d, flip = None, 1e9, False
    for path in page.strokes:
        if len(path) < 2 or _is_chrome(path, page):
            continue
        for tail, is_start in ((path[-1], False), (path[0], True)):
            d = abs(tail[0] - hx) + abs(tail[1] - hy)
            if d < best_d:
                best, best_d, flip = path, d, is_start
    if best is None or best_d > 8:
        return None
    return list(reversed(best)) if flip else best


def _is_chrome(path, page: Page) -> bool:
    """Timescale gridlines and row rules, which span the page."""
    xs = [x for x, _ in path]
    ys = [y for _, y in path]
    return (max(ys) - min(ys) > page.height * 0.4
            or max(xs) - min(xs) > page.width * 0.5)


# --- entry point --------------------------------------------------------------

def parse_pdf(data: bytes) -> dict[str, Any]:
    """A printed schedule -> {tasks, links, warnings}.

    `links` are PROPOSALS: every one carries `inferred: True` and a confidence,
    and none of them is a dependency until somebody says so.
    """
    from io import BytesIO

    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — pypdf raises many shapes
        raise ScheduleError(f"That PDF could not be opened: {exc}") from exc
    _PAGE_BYTES.set(data)

    warnings: list[str] = []
    tasks: list[dict[str, Any]] = []
    link_props: list[dict[str, Any]] = []
    per_page: list[tuple[int, list[dict[str, Any]], dict, Any]] = []

    for n, pg in enumerate(reader.pages, start=1):
        try:
            _PAGE_INDEX.set(n - 1)
            page = read_page(pg)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Page {n} could not be read ({exc}); skipped.")
            continue
        if not page.texts:
            warnings.append(
                f"Page {n} has no selectable text. If this PDF was scanned or "
                f"flattened to an image, the schedule cannot be read from it.")
            continue

        page_tasks = parse_page(page, warnings, n)
        if not page_tasks:
            continue
        rows = group_rows(page.texts)
        chart_left = find_chart_left(rows, page)
        bars = bars_by_row(page, page_tasks, chart_left)
        link_props.extend(infer_links(page, page_tasks, bars, chart_left))
        per_page.append((n, page_tasks, bars, calibrate(page, chart_left)))
        tasks.extend(page_tasks)

    if not tasks:
        raise ScheduleError(
            "No schedule rows were found in that PDF. It needs to be a printed "
            "schedule with an ID and Task Name column — a scanned or "
            "image-only PDF cannot be read.")

    # Hierarchy first: the bar check has to know which rows are summaries and
    # milestones, because neither is drawn as an ordinary bar.
    apply_hierarchy(tasks, warnings)
    for n, page_tasks, bars, calib in per_page:
        cross_check_bars(page_tasks, bars, calib, warnings, n)
    for i, t in enumerate(tasks):
        t["sort_order"] = i
        t.pop("_y", None)
        t.pop("_name_x", None)
        t.pop("name_x", None)

    known = {t["external_id"] for t in tasks}
    links = [lk for lk in link_props
             if lk["pred_external_id"] in known and lk["succ_external_id"] in known]

    # A printed view is usually outline-collapsed and filtered, so the ids jump
    # (this file prints 106 rows with ids running to 393). That is NOT missing
    # data and must never be reported as such — the person printing chose what
    # to show, and the choice is itself information. Said plainly here so that
    # a gap in the numbers doesn't look like a fault in the import.
    numeric = [int(t["external_id"]) for t in tasks if str(t["external_id"]).isdigit()]
    if numeric and (max(numeric) - min(numeric) + 1) > len(numeric) * 1.5:
        warnings.append(
            f"The printed view is filtered or collapsed: {len(tasks)} rows are "
            f"shown with ids running to {max(numeric)}. Everything printed has "
            f"been imported — the rows in between were not on the page.")

    if reader.pages and len(reader.pages) > 1:
        warnings.append(
            "Dependencies are read from the arrows drawn on the chart, so any "
            "link between tasks printed on different pages cannot be seen and "
            "is not included.")
    warnings.append(
        f"{len(links)} dependency proposal(s) traced from arrows. Nothing in a "
        f"printed PDF records resources, costs, calendars, baselines or "
        f"constraints — those fields are left empty rather than guessed.")
    return {"tasks": tasks, "links": links, "warnings": warnings}
