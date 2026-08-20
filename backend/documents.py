"""Document library + annotation layers (Phase 2).

The original PDF is immutable. It lands in data_dir()/documents/<id>.pdf at
upload and is never modified; every markup is a vector shape row in a named
layer, composited at render time. That is what makes the pipeline's isolation
guarantee structural: an outbound render for a customer composites the
original plus ONLY the RFI/submittal layer — the internal redlines cannot
leak because that code path never reads them.

Layers:
    'internal'          team redlines / site markups — visible app-wide
    'rfi:<id>' etc.     per-record outbound markups (Phase 3)
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Any

from . import config, db

_LAYER_RE = re.compile(r"^(internal|rfi:[A-Za-z0-9_-]+|submittal:[A-Za-z0-9_-]+)$")

SHAPE_TYPES = {"pen", "rect", "ellipse", "arrow", "text"}
# 2.0 mark vocabulary (the redesign's click-placed marks): {v: 2, tool, x, y,
# ink, weight, text} with x/y as percentages of the page box. The 1.x kinds
# above stay valid — old shapes render forever; new ones are simply a second
# dialect of the same layer-scoped rows.
MARK_TOOLS = {"Pin", "Box", "Cloud", "Line", "Arrow", "Text", "Highlight", "Dim"}


class DocumentError(ValueError):
    pass


def _doc_dir():
    d = config.data_dir() / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def doc_path(doc_id: str):
    return _doc_dir() / f"{doc_id}.pdf"


def page_count(data: bytes) -> int:
    from pypdf import PdfReader
    try:
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception as exc:
        raise DocumentError(f"Not a readable PDF: {exc}") from exc


def add_document(job_number: str, name: str, data: bytes,
                 actor: str | None = None) -> dict[str, Any]:
    if not data.startswith(b"%PDF"):
        raise DocumentError("Only PDF files are supported in the document library.")
    pages = page_count(data)  # parse BEFORE persisting anything

    rec = {
        "id": db.new_id(),
        "job_number": job_number,
        "name": (name or "Untitled").strip() or "Untitled",
        "filename": name,
        "page_count": pages,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "uploaded_by": actor,
        "uploaded_at": db.now(),
    }
    doc_path(rec["id"]).write_bytes(data)
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO documents ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, job_number, "document.upload",
                    f"{rec['name']} ({pages} pages)")
    return rec


def list_documents(job_number: str) -> list[dict[str, Any]]:
    conn = db.connect()
    docs = [dict(r) for r in conn.execute(
        "SELECT * FROM documents WHERE job_number = ? ORDER BY uploaded_at DESC",
        (job_number,))]
    for d in docs:
        row = conn.execute(
            "SELECT COUNT(*) c FROM annotations WHERE document_id = ? AND layer = 'internal'",
            (d["id"],)).fetchone()
        d["internal_annotation_count"] = row["c"]
    return docs


def get_document(doc_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def delete_document(doc_id: str, actor: str | None = None) -> bool:
    doc = get_document(doc_id)
    if doc is None:
        return False
    conn = db.connect()
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))  # annotations cascade
    conn.commit()
    doc_path(doc_id).unlink(missing_ok=True)
    db.log_activity(actor, doc["job_number"], "document.delete", doc["name"])
    return True


# --- annotations ------------------------------------------------------------


def _validate_layer(layer: str) -> str:
    if not _LAYER_RE.match(layer or ""):
        raise DocumentError(
            f"Unknown layer '{layer}'. Valid: internal, rfi:<id>, submittal:<id>.")
    return layer


def _validate_shape(shape: dict[str, Any]) -> dict[str, Any]:
    if isinstance(shape, dict) and shape.get("v") == 2:
        if shape.get("tool") not in MARK_TOOLS:
            raise DocumentError(f"Mark tool must be one of {sorted(MARK_TOOLS)}.")
        for k in ("x", "y"):
            try:
                val = float(shape.get(k))
            except (TypeError, ValueError):
                raise DocumentError(f"Mark {k} must be a number (percent of the page box).") from None
            if not 0 <= val <= 100:
                raise DocumentError(f"Mark {k} must be between 0 and 100.")
        return shape
    if not isinstance(shape, dict) or shape.get("type") not in SHAPE_TYPES:
        raise DocumentError(f"Shape type must be one of {sorted(SHAPE_TYPES)} "
                            "(or a v:2 mark).")
    return shape


def list_annotations(doc_id: str, layer: str | None = None,
                     page: int | None = None) -> list[dict[str, Any]]:
    conn = db.connect()
    q = "SELECT * FROM annotations WHERE document_id = ?"
    args: list[Any] = [doc_id]
    if layer:
        q += " AND layer = ?"
        args.append(_validate_layer(layer))
    if page is not None:
        q += " AND page = ?"
        args.append(page)
    q += " ORDER BY created_at"
    out = []
    for r in conn.execute(q, args):
        rec = dict(r)
        rec["shape"] = json.loads(rec["shape"])
        out.append(rec)
    return out


def add_annotation(doc_id: str, page: int, layer: str, shape: dict[str, Any],
                   actor: str | None = None) -> dict[str, Any]:
    doc = get_document(doc_id)
    if doc is None:
        raise DocumentError("No such document.")
    if not (1 <= int(page) <= (doc["page_count"] or 1)):
        raise DocumentError(f"Page {page} is out of range (1..{doc['page_count']}).")
    rec = {
        "id": db.new_id(),
        "document_id": doc_id,
        "page": int(page),
        "layer": _validate_layer(layer),
        "shape": json.dumps(_validate_shape(shape)),
        "author": actor,
        "created_at": db.now(),
    }
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO annotations ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, doc["job_number"], "annotation.add",
                    f"{doc['name']} p{page} [{layer}] "
                    f"{shape.get('type') or shape.get('tool') or 'mark'}")
    rec["shape"] = json.loads(rec["shape"])
    return rec


def delete_annotation(ann_id: str, actor: str | None = None) -> bool:
    conn = db.connect()
    row = conn.execute(
        "SELECT a.id, a.layer, a.page, d.job_number, d.name FROM annotations a "
        "JOIN documents d ON d.id = a.document_id WHERE a.id = ?", (ann_id,)).fetchone()
    if row is None:
        return False
    conn.execute("DELETE FROM annotations WHERE id = ?", (ann_id,))
    conn.commit()
    db.log_activity(actor, row["job_number"], "annotation.delete",
                    f"{row['name']} p{row['page']} [{row['layer']}]")
    return True
