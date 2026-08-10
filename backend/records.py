"""RFI / Submittal pipeline records (Phase 3a).

A record's markups live on its own annotation layer (``rfi:<id>`` /
``submittal:<id>``). The outbound package composites each attached page from
the immutable original plus ONLY that layer — ``build_package`` never queries
any other layer, which is the leak-proofing, structurally.

Status flow (D-pipeline): Draft → Sent → (Answered | a disposition) → Closed.
Dispositions arrive from replies in Phase 3b, staged for PM confirmation.
"""
from __future__ import annotations

import io
from typing import Any

from . import db, documents

RFI_STATUSES = ["Draft", "Sent", "Answered", "Closed"]
SUBMITTAL_STATUSES = ["Draft", "Sent", "Approved", "Approved as Noted",
                      "Revise & Resubmit", "Rejected", "Closed"]

FIELDS = {"number", "title", "question", "answer", "spec_section", "status",
          "to_name", "to_email", "due_date"}


class RecordError(ValueError):
    pass


def layer_for(rec: dict[str, Any]) -> str:
    return f"{rec['kind']}:{rec['id']}"


def _statuses(kind: str) -> list[str]:
    return RFI_STATUSES if kind == "rfi" else SUBMITTAL_STATUSES


def _clean(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
    out = {k: (str(v) if v is not None else None)
           for k, v in fields.items() if k in FIELDS}
    if "status" in out and out["status"] not in _statuses(kind):
        raise RecordError(
            f"'{out['status']}' is not a valid {kind} status. "
            f"Valid: {', '.join(_statuses(kind))}.")
    return out


def list_records(job_number: str, kind: str | None = None) -> list[dict[str, Any]]:
    conn = db.connect()
    q = "SELECT * FROM pipeline_records WHERE job_number = ?"
    args: list[Any] = [job_number]
    if kind:
        q += " AND kind = ?"
        args.append(kind)
    q += " ORDER BY created_at DESC, rowid DESC"
    recs = [dict(r) for r in conn.execute(q, args)]
    for r in recs:
        r["attachments"] = _attachments(r["id"])
        r["markup_count"] = conn.execute(
            "SELECT COUNT(*) c FROM annotations WHERE layer = ?",
            (layer_for(r),)).fetchone()["c"]
    return recs


def get_record(rec_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM pipeline_records WHERE id = ?", (rec_id,)).fetchone()
    if row is None:
        return None
    rec = dict(row)
    rec["attachments"] = _attachments(rec_id)
    return rec


def _attachments(rec_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(
        "SELECT ra.*, d.name AS document_name, d.page_count "
        "FROM record_attachments ra JOIN documents d ON d.id = ra.document_id "
        "WHERE ra.record_id = ? ORDER BY ra.added_at", (rec_id,))]


def add_record(job_number: str, kind: str, fields: dict[str, Any],
               actor: str | None = None) -> dict[str, Any]:
    if kind not in ("rfi", "submittal"):
        raise RecordError("kind must be 'rfi' or 'submittal'.")
    rec = {k: None for k in FIELDS}
    rec["status"] = "Draft"
    rec.update(_clean(kind, fields))
    rec.update({"id": db.new_id(), "job_number": job_number, "kind": kind,
                "sent_at": None, "outlook_conversation_id": None,
                "created_by": actor, "created_at": db.now()})
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO pipeline_records ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, f"{kind}.create",
                    f"{rec['number'] or '(unnumbered)'} · {rec['title'] or ''}")
    rec["attachments"] = []
    return rec


def update_record(rec_id: str, fields: dict[str, Any],
                  actor: str | None = None) -> dict[str, Any] | None:
    rec = get_record(rec_id)
    if rec is None:
        return None
    clean = _clean(rec["kind"], fields)
    if clean:
        conn = db.connect()
        sets = ", ".join(f"{k} = ?" for k in clean)
        conn.execute(f"UPDATE pipeline_records SET {sets} WHERE id = ?",  # noqa: S608
                     (*clean.values(), rec_id))
        conn.commit()
        db.log_activity(actor, rec["job_number"], f"{rec['kind']}.update",
                        f"{rec_id}: {', '.join(clean)}")
    return get_record(rec_id)


def delete_record(rec_id: str, actor: str | None = None) -> bool:
    rec = get_record(rec_id)
    if rec is None:
        return False
    conn = db.connect()
    # the record's markup layer goes with it — those shapes belong to nobody else
    conn.execute("DELETE FROM annotations WHERE layer = ?", (layer_for(rec),))
    conn.execute("DELETE FROM pipeline_records WHERE id = ?", (rec_id,))
    conn.commit()
    db.log_activity(actor, rec["job_number"], f"{rec['kind']}.delete",
                    rec["number"] or rec_id)
    return True


def attach_page(rec_id: str, document_id: str, page: int,
                actor: str | None = None) -> dict[str, Any]:
    rec = get_record(rec_id)
    if rec is None:
        raise RecordError("No such record.")
    doc = documents.get_document(document_id)
    if doc is None:
        raise RecordError("No such document.")
    if not (1 <= int(page) <= (doc["page_count"] or 1)):
        raise RecordError(f"Page {page} is out of range (1..{doc['page_count']}).")
    att = {"id": db.new_id(), "record_id": rec_id, "document_id": document_id,
           "page": int(page), "added_by": actor, "added_at": db.now()}
    conn = db.connect()
    cols = ", ".join(att)
    conn.execute(f"INSERT INTO record_attachments ({cols}) VALUES ({','.join('?' * len(att))})",  # noqa: S608
                 tuple(att.values()))
    conn.commit()
    db.log_activity(actor, rec["job_number"], f"{rec['kind']}.attach",
                    f"{doc['name']} p{page}")
    att["document_name"] = doc["name"]
    return att


def detach_page(rec_id: str, attachment_id: str, actor: str | None = None) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM record_attachments WHERE id = ? AND record_id = ?",
                       (attachment_id, rec_id))
    conn.commit()
    return cur.rowcount > 0


# --- email drafts + replies (Phase 3b) --------------------------------------


def get_draft(rec_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM record_drafts WHERE record_id = ?", (rec_id,)).fetchone()
    return dict(row) if row else None


def save_draft(rec_id: str, subject: str, body: str, source: str,
               actor: str | None = None) -> dict[str, Any]:
    conn = db.connect()
    conn.execute(
        "INSERT INTO record_drafts (record_id, subject, body, source, updated_by, updated_at) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(record_id) DO UPDATE SET "
        "subject = excluded.subject, body = excluded.body, source = excluded.source, "
        "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
        (rec_id, subject, body, source, actor, db.now()))
    conn.commit()
    return get_draft(rec_id)  # type: ignore[return-value]


def mark_sent(rec_id: str, actor: str | None = None,
              sent_at: str | None = None) -> dict[str, Any] | None:
    """Flip Draft → Sent. ``sent_at`` is Outlook's own SentOn when the
    companion detected the send (the normal path); now() when set by hand."""
    rec = get_record(rec_id)
    if rec is None:
        return None
    conn = db.connect()
    conn.execute("UPDATE pipeline_records SET status = 'Sent', sent_at = ?, "
                 "sent_by = COALESCE(sent_by, ?) WHERE id = ?",
                 (sent_at or db.now(), actor, rec_id))
    conn.commit()
    db.log_activity(actor, rec["job_number"], f"{rec['kind']}.sent",
                    f"{rec['number'] or rec_id}"
                    + (" (detected in Outlook Sent Items)" if sent_at else ""))
    return get_record(rec_id)


def _replies_dir():
    from . import config
    d = config.data_dir() / "replies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_reply(rec_id: str, fields: dict[str, Any],
              attachments: list[dict[str, Any]] | None = None,
              actor: str | None = None) -> dict[str, Any]:
    """Store a captured reply and STAGE an AI/heuristic proposal. The record
    itself does not change until confirm_reply — the PM stays the authority."""
    import base64

    from . import ai

    rec = get_record(rec_id)
    if rec is None:
        raise RecordError("No such record.")

    conn = db.connect()
    # Idempotent: background polling re-sees the same inbox items every cycle,
    # and a reply must be filed exactly once. Two keys, because neither alone
    # is sufficient — the message id is exact but absent on replies captured
    # before it was recorded (and on hand-entered ones), so sender + received
    # timestamp backs it up. Outlook reports ReceivedTime to the millisecond,
    # so a collision would need the same sender twice in the same millisecond
    # on one thread.
    message_id = fields.get("message_id")
    received_at = fields.get("received_at")
    from_email = fields.get("from_email")
    existing = None
    if message_id:
        existing = conn.execute(
            "SELECT id FROM record_replies WHERE record_id = ? AND message_id = ?",
            (rec_id, message_id)).fetchone()
    if existing is None and received_at and from_email:
        existing = conn.execute(
            "SELECT id FROM record_replies WHERE record_id = ? AND from_email = ? "
            "AND received_at = ?", (rec_id, from_email, received_at)).fetchone()
        if existing is not None and message_id:
            # adopt the id so future cycles hit the exact-match path
            conn.execute("UPDATE record_replies SET message_id = ? WHERE id = ?",
                         (message_id, existing["id"]))
            conn.commit()
    if existing is not None:
        # `deduped` is response-only (never stored) so a caller — the poller
        # above all — can tell "already had this" from "just filed this" and
        # report honest counts.
        return {**get_reply(existing["id"]), "deduped": True}  # type: ignore[dict-item]

    body = str(fields.get("body") or "")
    proposal = ai.analyze_reply(rec, body)
    reply = {
        "id": db.new_id(), "record_id": rec_id,
        "from_name": fields.get("from_name"), "from_email": fields.get("from_email"),
        "received_at": fields.get("received_at"), "body": body[:20000],
        "message_id": message_id,
        **proposal, "confirmed_at": None, "confirmed_by": None,
        "created_at": db.now(),
    }
    cols = ", ".join(reply)
    conn.execute(f"INSERT INTO record_replies ({cols}) VALUES ({','.join('?' * len(reply))})",  # noqa: S608
                 tuple(reply.values()))

    for att in attachments or []:
        data = base64.b64decode(att.get("content_b64") or "")
        if not data:
            continue
        fname = (att.get("filename") or "attachment").replace("/", "_").replace("\\", "_")
        path = _replies_dir() / f"{reply['id']}_{fname}"
        path.write_bytes(data)
        conn.execute("INSERT INTO reply_attachments (id, reply_id, filename, path, size_bytes) "
                     "VALUES (?,?,?,?,?)",
                     (db.new_id(), reply["id"], fname, str(path), len(data)))
    conn.commit()
    db.log_activity(actor, rec["job_number"], f"{rec['kind']}.reply",
                    f"from {reply['from_email'] or reply['from_name'] or 'unknown'} · "
                    f"proposed {proposal['proposed_status'] or 'nothing'}")
    return get_reply(reply["id"])  # type: ignore[return-value]


def open_threads() -> list[dict[str, Any]]:
    """Records a companion should watch for replies.

    Every running companion polls the whole list rather than a per-user slice:
    a reply only exists in the mailbox it was sent from, so a companion that
    doesn't have it simply finds nothing. That keeps the identity mapping out
    of the design entirely — no need to know which user sent what.
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT r.id, r.job_number, r.kind, r.number, r.sent_at, d.subject "
        "FROM pipeline_records r JOIN record_drafts d ON d.record_id = r.id "
        "WHERE r.status NOT IN ('Draft', 'Closed') AND d.subject IS NOT NULL "
        "ORDER BY r.sent_at DESC")
    return [{"record_id": r["id"], "subject": r["subject"], "since": r["sent_at"],
             "job_number": r["job_number"], "kind": r["kind"], "number": r["number"]}
            for r in rows]


def draft_threads() -> list[dict[str, Any]]:
    """Records whose mail is drafted but not yet sent.

    The companion watches Sent Items for these, so Draft → Sent flips within
    seconds of the human pressing Send rather than waiting for someone to open
    a browser tab. Same reasoning as open_threads(): every companion gets the
    whole list, and one that doesn't have the message simply finds nothing.
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT r.id, r.job_number, r.kind, r.number, d.subject "
        "FROM pipeline_records r JOIN record_drafts d ON d.record_id = r.id "
        "WHERE r.status = 'Draft' AND d.subject IS NOT NULL "
        "ORDER BY r.created_at DESC")
    return [{"record_id": r["id"], "subject": r["subject"],
             "job_number": r["job_number"], "kind": r["kind"], "number": r["number"]}
            for r in rows]


def list_replies(rec_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    out = []
    for r in conn.execute("SELECT * FROM record_replies WHERE record_id = ? "
                          "ORDER BY created_at DESC, rowid DESC", (rec_id,)):
        rep = dict(r)
        rep["attachments"] = [dict(a) for a in conn.execute(
            "SELECT id, filename, size_bytes FROM reply_attachments WHERE reply_id = ?",
            (rep["id"],))]
        out.append(rep)
    return out


def get_reply(reply_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM record_replies WHERE id = ?", (reply_id,)).fetchone()
    if row is None:
        return None
    rep = dict(row)
    rep["attachments"] = [dict(a) for a in conn.execute(
        "SELECT id, filename, size_bytes FROM reply_attachments WHERE reply_id = ?",
        (reply_id,))]
    return rep


def confirm_reply(reply_id: str, fields: dict[str, Any],
                  actor: str | None = None) -> dict[str, Any] | None:
    """PM applies the proposal (possibly edited) to the record."""
    rep = get_reply(reply_id)
    if rep is None:
        return None
    rec = get_record(rep["record_id"])
    status = fields.get("status") or rep["proposed_status"]
    answer = fields.get("answer", rep["proposed_answer"])

    updates: dict[str, Any] = {}
    if status:
        updates["status"] = status
    if rec["kind"] == "rfi" and answer:
        updates["answer"] = answer
    if updates:
        update_record(rec["id"], updates, actor=actor)

    conn = db.connect()
    conn.execute("UPDATE record_replies SET confirmed_at = ?, confirmed_by = ?, "
                 "proposed_status = ?, proposed_answer = ? WHERE id = ?",
                 (db.now(), actor, status, answer, reply_id))
    conn.commit()
    db.log_activity(actor, rec["job_number"], f"{rec['kind']}.confirm",
                    f"{rec['number'] or rec['id']} → {status or 'no status change'}")
    return get_reply(reply_id)


# --- outbound package -------------------------------------------------------


def build_package(rec_id: str) -> bytes:
    """One PDF: each attached page extracted from its immutable original and
    composited with ONLY this record's layer.

    Internal redlines cannot appear in the output because this function never
    reads any layer except ``layer_for(record)`` — the isolation is the shape
    of the code, not a filter that can be misconfigured.
    """
    from pypdf import PdfReader, PdfWriter

    rec = get_record(rec_id)
    if rec is None:
        raise RecordError("No such record.")
    if not rec["attachments"]:
        raise RecordError("No pages attached to this record yet.")

    writer = PdfWriter()
    for att in rec["attachments"]:
        reader = PdfReader(str(documents.doc_path(att["document_id"])))
        page = reader.pages[att["page"] - 1]
        shapes = [a["shape"] for a in documents.list_annotations(
            att["document_id"], layer=layer_for(rec), page=att["page"])]
        if shapes:
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            # Markups were drawn on the page AS DISPLAYED — PDF.js honors the
            # page's /Rotate — so the overlay must be transformed through the
            # same rotation or every shape lands 90/180/270° off.
            overlay = PdfReader(io.BytesIO(
                _overlay_pdf(shapes, w, h, rotation=page.rotation % 360))).pages[0]
            page.merge_page(overlay)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _hex_rgb(color: str | None) -> tuple[float, float, float]:
    c = (color or "#C23A2E").lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0.76, 0.23, 0.18)


def _pdf_escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _overlay_pdf(shapes: list[dict[str, Any]], w: float, h: float,
                 rotation: int = 0) -> bytes:
    """A minimal one-page PDF whose content stream draws the shapes.

    Burned into the content stream (not PDF annotation objects) so every
    viewer renders it identically — annotation appearance streams are exactly
    the kind of viewer-dependent behavior an outbound legal-ish document
    cannot afford. Normalized y is top-down; PDF user space is bottom-up.

    ``rotation`` is the target page's /Rotate. Shapes are drawn in DISPLAY
    space (the upright view the PM drew on) and a single leading `cm` matrix
    maps display space onto the unrotated page — one transform, every shape
    type handled identically.
    """
    K = 0.5523  # Bézier circle constant

    # Display-space dimensions: a 90/270-rotated page displays transposed.
    disp_w, disp_h = (h, w) if rotation in (90, 270) else (w, h)
    CM = {
        0: None,
        90: f"0 1 -1 0 {w:.2f} 0 cm",
        180: f"-1 0 0 -1 {w:.2f} {h:.2f} cm",
        270: f"0 -1 1 0 0 {h:.2f} cm",
    }.get(rotation)
    w, h = disp_w, disp_h  # all shape math below runs in display space

    ops: list[str] = []
    if CM:
        ops.append(f"q {CM}")
    for s in shapes:
        r, g, b = _hex_rgb(s.get("color"))
        lw = max(1.0, (s.get("width") or 0.0035) * w)
        ops.append(f"q {r:.3f} {g:.3f} {b:.3f} RG {r:.3f} {g:.3f} {b:.3f} rg {lw:.2f} w 1 J 1 j")
        t = s.get("type")
        if t == "pen" and s.get("points"):
            pts = [(p[0] * w, h - p[1] * h) for p in s["points"]]
            ops.append(f"{pts[0][0]:.2f} {pts[0][1]:.2f} m " +
                       " ".join(f"{x:.2f} {y:.2f} l" for x, y in pts[1:]) + " S")
        elif t == "rect":
            ops.append(f"{s['x'] * w:.2f} {h - (s['y'] + s['h']) * h:.2f} "
                       f"{s['w'] * w:.2f} {s['h'] * h:.2f} re S")
        elif t == "ellipse":
            cx, cy = (s["x"] + s["w"] / 2) * w, h - (s["y"] + s["h"] / 2) * h
            rx, ry = (s["w"] / 2) * w, (s["h"] / 2) * h
            ops.append(
                f"{cx + rx:.2f} {cy:.2f} m "
                f"{cx + rx:.2f} {cy + K * ry:.2f} {cx + K * rx:.2f} {cy + ry:.2f} {cx:.2f} {cy + ry:.2f} c "
                f"{cx - K * rx:.2f} {cy + ry:.2f} {cx - rx:.2f} {cy + K * ry:.2f} {cx - rx:.2f} {cy:.2f} c "
                f"{cx - rx:.2f} {cy - K * ry:.2f} {cx - K * rx:.2f} {cy - ry:.2f} {cx:.2f} {cy - ry:.2f} c "
                f"{cx + K * rx:.2f} {cy - ry:.2f} {cx + rx:.2f} {cy - K * ry:.2f} {cx + rx:.2f} {cy:.2f} c S")
        elif t == "arrow":
            import math
            x1, y1 = s["x1"] * w, h - s["y1"] * h
            x2, y2 = s["x2"] * w, h - s["y2"] * h
            ops.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")
            ang = math.atan2(y2 - y1, x2 - x1)
            hd = max(9.0, lw * 3.2)
            ax1 = x2 - hd * math.cos(ang - 0.45)
            ay1 = y2 - hd * math.sin(ang - 0.45)
            ax2 = x2 - hd * math.cos(ang + 0.45)
            ay2 = y2 - hd * math.sin(ang + 0.45)
            ops.append(f"{x2:.2f} {y2:.2f} m {ax1:.2f} {ay1:.2f} l {ax2:.2f} {ay2:.2f} l f")
        elif t == "text" and s.get("text"):
            size = max(9.0, (s.get("size") or 0.016) * h)
            if s.get("w"):  # text box: border + naive wrap on width
                bx, by = s["x"] * w, h - (s["y"] + (s.get("h") or 0.04)) * h
                ops.append(f"{bx:.2f} {by:.2f} {s['w'] * w:.2f} {(s.get('h') or 0.04) * h:.2f} re S")
                max_chars = max(8, int((s["w"] * w - 8) / (size * 0.5)))
                words, lines, line = s["text"].split(), [], ""
                for word in words:
                    probe = f"{line} {word}".strip()
                    if line and len(probe) > max_chars:
                        lines.append(line)
                        line = word
                    else:
                        line = probe
                if line:
                    lines.append(line)
                ty = h - s["y"] * h - size
                for ln in lines:
                    ops.append(f"BT /F1 {size:.1f} Tf {s['x'] * w + 4:.2f} {ty:.2f} Td "
                               f"({_pdf_escape(ln)}) Tj ET")
                    ty -= size * 1.25
            else:
                ops.append(f"BT /F1 {size:.1f} Tf {s['x'] * w:.2f} {h - s['y'] * h - size:.2f} Td "
                           f"({_pdf_escape(s['text'])}) Tj ET")
        ops.append("Q")

    if CM:
        ops.append("Q")

    # MediaBox stays in PAGE space — the cm above already maps into it.
    box_w, box_h = (h, w) if rotation in (90, 270) else (w, h)
    stream = "\n".join(ops).encode("latin-1", errors="replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {box_w:.2f} {box_h:.2f}] "
         f"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>").encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
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
