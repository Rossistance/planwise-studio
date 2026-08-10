"""PlanWise — per-job project controls, sourced from the shared Vista extract.

Shared server (decision D9): one instance, the team uses it from their
browsers. Since D27 that instance is hosted rather than a PC on the LAN, so
identity is real: per-user accounts and session cookies (see auth.py), and
every write records who made it. The X-PlanWise-User header that used to carry
identity is now only a local-development fallback — the session wins.
"""
from __future__ import annotations

import re
import secrets
from contextvars import ContextVar
from pathlib import Path

from fastapi import Body, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (ai, auth, config, db, documents, lookahead, outbox, push, records,
               schedule, store, vista)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="PlanWise", version="3.0.0-dev")


@app.middleware("http")
async def no_store(request, call_next):
    """Never let the browser cache the app shell.

    A stale cached app.js silently serving yesterday's UI is a fixed cost paid
    on every edit during the walkthrough — and it looks like a bug in the code
    you just wrote. Local-only app; the bandwidth is free.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def _snapshot() -> vista.Snapshot:
    try:
        return vista.load()
    except vista.VistaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _actor(name: str | None) -> str | None:
    """Who to record on a write.

    The signed-in session is the authority — a header can be forged, and the
    activity trail is only worth keeping if it can't be. The X-PlanWise-User
    header survives only as a fallback for the pre-Phase-5a local dev flow.
    """
    user = _CURRENT_USER.get()
    if user:
        return user["name"]
    name = (name or "").strip()
    return name or None


# Set per request by the auth middleware. A ContextVar rather than a FastAPI
# dependency so that ~50 existing endpoints keep their signatures.
_CURRENT_USER: "ContextVar[dict | None]" = ContextVar("planwise_user", default=None)

# Reachable without a session. Everything else under /api requires one.
#   * health           — so a monitor can see the app is up
#   * auth             — you can't sign in if signing in needs a session
#   * companion/poll   — a machine call from each user's local helper, running
#                        with no browser open, guarded by the companion token
#                        instead (D10)
#   * vista/workbook   — the daily extract push from an unattended scheduled
#                        task, guarded by the ingest token (D27 / Phase 5b)
# Note what is NOT here: /api/companion/token. That's the secret that lets a
# caller drive someone's Outlook, so it stays behind a session.
_OPEN_PATHS = {"/api/health", "/api/auth/login", "/api/auth/logout",
               "/api/auth/bootstrap", "/api/auth/status", "/api/companion/poll",
               "/api/vista/workbook"}
_OPEN_PREFIXES = ()

# Endpoints a companion legitimately WRITES to, with its own token instead of
# a session: it runs with no browser open, so there is no session to have.
#
# This was missed when the session gate went in, and the companion's reply
# filing has been 401ing silently ever since — the poller treated any non-200
# as "nothing found". Scoped by pattern rather than a blanket token bypass, so
# the companion token stays worth exactly these two calls.
_COMPANION_WRITES = re.compile(r"^/api/records/[^/]+/(replies|sent)$")


def _companion_authorised(request: Request, path: str) -> bool:
    if not _COMPANION_WRITES.match(path):
        return False
    token = (request.headers.get("x-planwise-companion")
             or request.query_params.get("token") or "")
    expected = ai.companion_token() or ""
    return bool(token and expected and secrets.compare_digest(token, expected))


@app.middleware("http")
async def require_session(request, call_next):
    """Gate every API route behind a session cookie.

    Middleware rather than a per-route dependency deliberately: a whitelist of
    what's open is auditable in one place, and a new endpoint is protected by
    default instead of protected only if someone remembered.
    """
    path = request.url.path
    token = request.cookies.get(auth.COOKIE)
    user = auth.session_user(token) if token else None
    reset = _CURRENT_USER.set(user)
    try:
        if (path.startswith("/api/") and path not in _OPEN_PATHS
                and not path.startswith(_OPEN_PREFIXES) and user is None
                and not _companion_authorised(request, path)):
            return JSONResponse(status_code=401, content={"detail": "Sign in to continue."})
        return await call_next(request)
    finally:
        _CURRENT_USER.reset(reset)


@app.get("/api/health")
def health():
    """Is the app up, and is the Vista data current? Never guesses."""
    wb = config.vista_workbook()
    out = {
        "app": config.APP_NAME,
        "data_dir": str(config.data_dir()),
        "workbook": str(wb) if wb else None,
        "workbook_found": wb is not None,
    }
    if wb is None:
        out["vista"] = {"ok": False, "detail": "Vista workbook not synced to this machine."}
        return out
    try:
        snap = vista.load()
    except vista.VistaUnavailable as exc:
        out["vista"] = {"ok": False, "detail": str(exc)}
        return out

    out["vista"] = {
        "ok": True,
        "as_of": snap.as_of.isoformat() if snap.as_of else None,
        "age_hours": snap.age_hours,
        "stale": snap.is_stale,
        "schema_version": snap.schema_version,
        "job_count": len(snap.jobs),
        "phase_row_count": sum(len(v) for v in snap.phases.values()),
    }
    return out


# --- outbox: the mobile -> desk handoff (Phase 5g) ----------------------------

@app.get("/api/outbox")
def outbox_pending(job_number: str | None = None):
    """What this person has waiting to be drafted into their own Outlook."""
    me = _CURRENT_USER.get()
    items = outbox.pending(me["name"], job_number)
    # Give each one a human label so the desk-side prompt can say what it is
    # without the caller having to fetch every target.
    for it in items:
        if it["kind"] == "lookahead":
            period = lookahead.get_period(it["target_id"])
            it["label"] = (f"{it.get('weeks') or 2}-week look ahead"
                           + (f" · {period['start_date']}" if period else ""))
        else:
            rec = records.get_record(it["target_id"]) or {}
            it["label"] = f"{(rec.get('kind') or 'record').upper()} {rec.get('number') or ''}".strip()
    return {"items": items}


@app.post("/api/outbox")
def outbox_queue(body: dict = Body(...)):
    me = _CURRENT_USER.get()
    try:
        return outbox.queue(body.get("job_number", ""), body.get("kind", ""),
                            body.get("target_id", ""),
                            audience=body.get("audience"), weeks=body.get("weeks"),
                            note=body.get("note"), actor=me["name"])
    except outbox.OutboxError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/outbox/{item_id}/document")
def outbox_document(item_id: str):
    """Everything needed to draft the item, rendered now rather than when it
    was queued — so what goes out reflects the current sheet."""
    import base64

    me = _CURRENT_USER.get()
    try:
        item = outbox.claim(item_id, me["name"])
    except outbox.OutboxError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if item["kind"] != "lookahead":
        raise HTTPException(status_code=422,
                            detail="Only look aheads can be queued from a phone so far.")

    period = lookahead.get_period(item["target_id"])
    if period is None:
        raise HTTPException(status_code=404, detail="That look ahead no longer exists.")
    snap = _snapshot()
    job = snap.jobs.get(period["job_number"], {})
    job_name = job.get("job_name") or period["job_number"]
    audience = item["audience"] or "customer"
    try:
        out = lookahead.share_html(item["target_id"], job_name, period["job_number"],
                                   audience, item["weeks"])
        pdf = lookahead.share_pdf(item["target_id"], job_name, period["job_number"],
                                  audience, item["weeks"])
    except lookahead.LookaheadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    internal = lookahead.is_internal(audience)
    meta = store.get_meta(period["job_number"])
    contacts = [] if internal else [
        {"name": c.get("name") or c["email"], "email": c["email"]}
        for c in (meta.get("contacts") or []) if c.get("email")]
    if item.get("note"):
        out["html"] = f"<p>{lookahead._esc(item['note'])}</p>" + out["html"]
    out["to"] = ";".join(c["email"] for c in contacts)
    out["contacts"] = contacts
    out["weeks"] = lookahead.share_weeks(period, item["weeks"])
    out["filename"] = (f"Look-Ahead-{out['weeks']}wk{'-INTERNAL' if internal else ''}"
                       f"-{period['job_number']}-{period['start_date']}.pdf")
    out["pdf_b64"] = base64.b64encode(pdf).decode()
    return out


@app.post("/api/outbox/{item_id}/drafted")
def outbox_drafted(item_id: str):
    me = _CURRENT_USER.get()
    item = outbox.mark_drafted(item_id, me["name"])
    if item is None:
        raise HTTPException(status_code=409, detail="That one was already drafted.")
    return item


@app.delete("/api/outbox/{item_id}")
def outbox_cancel(item_id: str):
    me = _CURRENT_USER.get()
    try:
        if not outbox.cancel(item_id, me["name"]):
            raise HTTPException(status_code=404, detail="Nothing queued with that id.")
    except outbox.OutboxError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"cancelled": item_id}


# --- push notifications (Phase 5e) --------------------------------------------

@app.get("/api/push/key")
def push_key():
    """The VAPID public key a browser needs in order to subscribe, plus
    whether push can work here at all."""
    return {"key": push.public_key(), "available": push.available()}


@app.post("/api/push/subscribe")
def push_subscribe(body: dict = Body(...)):
    me = _CURRENT_USER.get()
    try:
        return push.subscribe(me["name"], body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: dict = Body(...)):
    return {"removed": push.unsubscribe(body.get("endpoint", ""))}


@app.post("/api/push/test")
def push_test():
    """Prove the whole chain to the person setting it up, rather than making
    them wait for a real reply to find out it never worked."""
    me = _CURRENT_USER.get()
    return push.send("PlanWise", "Notifications are working.",
                     url="/", tag="test", user=me["name"])


# --- Vista extract delivery (Phase 5b) ----------------------------------------

# 7.2MB today; the ceiling is a sanity bound, not a target.
_MAX_WORKBOOK_BYTES = 64 * 1024 * 1024


@app.post("/api/vista/workbook")
async def push_vista_workbook(file: UploadFile = File(...),
                              x_planwise_ingest: str | None = Header(default=None)):
    """Accept the daily Vista extract from `vista_pull.py`.

    A hosted instance has no OneDrive, so the extract has to be delivered. This
    is a machine call from an unattended scheduled task, so it authenticates
    with a shared secret rather than a session.

    The upload is **validated before it is trusted**: it lands in a temp file,
    is parsed with the same reader the app uses, and only replaces the live
    workbook if it parses. A truncated or schema-drifted push therefore fails
    loudly for the uploader instead of silently breaking the app for six
    people. The previous copy is kept alongside so a bad day is recoverable.
    """
    import shutil

    expected = config.ingest_token()
    if expected is None:
        raise HTTPException(status_code=503,
                            detail="Workbook ingest is not configured on this server.")
    if not x_planwise_ingest or not secrets.compare_digest(x_planwise_ingest, expected):
        raise HTTPException(status_code=401, detail="Bad ingest token.")

    dest = config.pushed_workbook()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.pushed_workbook_incoming()

    size = 0
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_WORKBOOK_BYTES:
                    raise HTTPException(status_code=413, detail="Workbook is implausibly large.")
                out.write(chunk)

        try:
            snap = vista._read(tmp)
        except Exception as exc:
            # Deliberately broad: anything that fails to parse is a bad push,
            # and the uploader should get the reason rather than a 500. Bare
            # garbage surfaces as zipfile.BadZipFile, not VistaUnavailable.
            raise HTTPException(
                status_code=422,
                detail=f"That file did not parse as a Vista extract: {exc}") from exc

        if dest.exists():
            shutil.copy2(dest, config.pushed_workbook_previous())
        tmp.replace(dest)                      # atomic: readers never see a partial file
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            # Windows can still hold openpyxl's read-only handle on a workbook
            # that failed to parse. Harmless: the scratch file is never what
            # the app reads, and the next push truncates it.
            pass

    vista.load(force=True)                     # drop the cached snapshot immediately
    db.log_activity(None, None, "vista.workbook.push",
                    f"{size / 1_048_576:.1f} MB · {len(snap.jobs)} jobs")
    return {"received_bytes": size, "jobs": len(snap.jobs),
            "phase_rows": sum(len(v) for v in snap.phases.values()),
            "as_of": snap.as_of.isoformat() if snap.as_of else None,
            "schema_version": snap.schema_version}


# --- auth (Phase 5a) ----------------------------------------------------------

def _is_https(request: Request) -> bool:
    """Whether the *browser* reached us over HTTPS.

    A hosted PlanWise sits behind Render's TLS proxy, which terminates HTTPS
    and forwards plain HTTP into the container — so `request.url.scheme` says
    "http" and the session cookie would quietly lose its Secure flag on the
    one deployment where it matters most. The forwarded header is the truth.
    Reading it unvalidated is safe here because the only thing forging it can
    do is make the cookie *more* restrictive.
    """
    if request.url.scheme == "https":
        return True
    proto = request.headers.get("x-forwarded-proto", "")
    return proto.split(",")[0].strip().lower() == "https"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Secure over HTTPS, so localhost development still works. HttpOnly
    always — no session token should ever be readable from JavaScript."""
    response.set_cookie(
        auth.COOKIE, token, httponly=True, samesite="lax",
        secure=_is_https(request),
        max_age=auth.SESSION_DAYS * 24 * 3600, path="/")


@app.get("/api/auth/status")
def auth_status():
    """What the sign-in screen needs before anyone has signed in: whether this
    instance still needs its first administrator.

    Asking is also what mints the setup token file, so it exists exactly when
    the setup screen is telling someone to go and read it.
    """
    needs_setup = not auth.admin_exists()
    if needs_setup:
        token = auth.setup_token()
        print(f"[PlanWise] No administrator yet. Setup token: {token}\n"
              f"[PlanWise]   also written to {config.data_dir() / auth.SETUP_TOKEN_FILE}",
              flush=True)
    return {"needs_setup": needs_setup,
            "signed_in": _CURRENT_USER.get() is not None,
            "user": _CURRENT_USER.get()}


@app.post("/api/auth/bootstrap")
def auth_bootstrap(response: Response, request: Request, body: dict = Body(...)):
    try:
        auth.bootstrap_admin(body.get("token", ""), body.get("name", ""),
                             body.get("password", ""))
        token, user = auth.login(body.get("name", ""), body.get("password", ""))
    except auth.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _set_session_cookie(response, request, token)
    return {"user": user}


@app.post("/api/auth/login")
def auth_login(response: Response, request: Request, body: dict = Body(...)):
    try:
        token, user = auth.login(body.get("name", ""), body.get("password", ""))
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session_cookie(response, request, token)
    return {"user": user}


@app.post("/api/auth/logout")
def auth_logout(response: Response, request: Request):
    auth.logout(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"signed_out": True}


@app.post("/api/auth/password")
def auth_change_password(response: Response, request: Request, body: dict = Body(...)):
    me = _CURRENT_USER.get()
    try:
        auth.change_password(me["name"], body.get("current", ""), body.get("new", ""))
        # Changing a password drops every session including this one, so hand
        # back a fresh cookie rather than bouncing the user to the login screen.
        token, user = auth.login(me["name"], body.get("new", ""))
    except auth.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _set_session_cookie(response, request, token)
    return {"user": user}


# --- users ------------------------------------------------------------------

def _require_admin() -> dict:
    me = _CURRENT_USER.get()
    if not me or not me.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrators only.")
    return me


@app.get("/api/users")
def users():
    return {"users": auth.list_accounts()}


@app.post("/api/users")
def create_user(body: dict = Body(...)):
    """Admin-created accounts get a temporary password the person is required
    to change on first sign-in."""
    me = _require_admin()
    try:
        return auth.create_account(body.get("name", ""), body.get("password", ""),
                                   is_admin=bool(body.get("is_admin")),
                                   actor=me["name"])
    except auth.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/users/{name}/password")
def reset_user_password(name: str, body: dict = Body(...)):
    me = _require_admin()
    try:
        auth.set_password(name, body.get("password", ""), must_change=True)
    except auth.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db_log = f"{name} (by {me['name']})"
    store.db.log_activity(me["name"], None, "auth.password.reset", db_log)
    return {"reset": name}


@app.post("/api/users/{name}/disabled")
def set_user_disabled(name: str, body: dict = Body(...)):
    me = _require_admin()
    if name.strip().lower() == me["name"].strip().lower():
        raise HTTPException(status_code=422, detail="You can't disable your own account.")
    if not auth.set_disabled(name, bool(body.get("disabled")), actor=me["name"]):
        raise HTTPException(status_code=404, detail="No such user.")
    return {"name": name, "disabled": bool(body.get("disabled"))}


# --- jobs (Vista) -----------------------------------------------------------

@app.get("/api/jobs")
def list_jobs(q: str | None = None, limit: int = 50):
    """Type-ahead over every job. Job-number prefix matches rank first."""
    snap = _snapshot()
    numbers = vista.job_numbers(snap)

    if q:
        needle = q.strip().lower()
        prefix, contains = [], []
        for n in numbers:
            rec = snap.jobs[n]
            name = (rec.get("job_name") or "").lower()
            if n.lower().startswith(needle):
                prefix.append(n)
            elif needle in n.lower() or needle in name:
                contains.append(n)
        numbers = prefix + contains

    return {
        "total": len(numbers),
        "jobs": [
            {
                "job_number": n,
                "job_name": snap.jobs[n].get("job_name"),
                "financial_status": snap.jobs[n].get("financial_status"),
                "job_status": snap.jobs[n].get("job_status"),
                "current_contract": snap.jobs[n].get("current_contract"),
            }
            for n in numbers[:limit]
        ],
    }


@app.get("/api/jobs/{job_number}")
def get_job(job_number: str):
    """Everything Vista knows about one job + the PM-entered registers."""
    snap = _snapshot()
    rec = snap.jobs.get(job_number)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_number}' is not in the Vista extract.")

    cost_types = vista.cost_types_for(snap, job_number)

    # Decision D8: Open/Committed derives from the PM-entered PO register —
    # Σ remaining value of open POs per cost type. (The Power BI model has no
    # commitment data; verified 2026-08-08. Swap to the model if bPOIT lands.)
    committed = store.open_committed_by_cost_type(job_number)
    for row in cost_types:
        row["open_committed"] = committed.pop(row["cost_type"], None)
    for name, amount in committed.items():
        cost_types.append({
            "cost_type": name, "phase_count": 0,
            "actual_cost": None, "current_estimate": None,
            "projected_cost": None, "hours_units": None, "mtd_cost": None,
            "variance": None, "pct_complete": None,
            "open_committed": amount, "po_only": True,
        })

    return {
        "as_of": snap.as_of.isoformat() if snap.as_of else None,
        "stale": snap.is_stale,
        "schema_version": snap.schema_version,
        "job": rec,
        "contract_ar": snap.contract_ar.get(job_number),
        "cost_types": cost_types,
        "phases": vista.phases_for(snap, job_number),
        "purchase_orders": store.list_pos(job_number),
        "change_orders": store.list_cos(job_number),
        "meta": store.get_meta(job_number),
    }


@app.get("/api/jobs/{job_number}/activity")
def job_activity(job_number: str, limit: int = 100):
    return {"activity": store.list_activity(job_number, limit)}


# --- PM-entered PO register -------------------------------------------------

@app.post("/api/jobs/{job_number}/pos")
def create_po(job_number: str, fields: dict = Body(...),
              x_planwise_user: str | None = Header(default=None)):
    return store.add_po(job_number, fields, actor=_actor(x_planwise_user))


@app.patch("/api/jobs/{job_number}/pos/{po_id}")
def patch_po(job_number: str, po_id: str, fields: dict = Body(...),
             x_planwise_user: str | None = Header(default=None)):
    po = store.update_po(job_number, po_id, fields, actor=_actor(x_planwise_user))
    if po is None:
        raise HTTPException(status_code=404, detail="No such PO.")
    return po


@app.delete("/api/jobs/{job_number}/pos/{po_id}")
def remove_po(job_number: str, po_id: str,
              x_planwise_user: str | None = Header(default=None)):
    if not store.delete_po(job_number, po_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such PO.")
    return {"deleted": po_id}


@app.post("/api/jobs/{job_number}/pos/{po_id}/invoices")
def create_invoice(job_number: str, po_id: str, fields: dict = Body(...),
                   x_planwise_user: str | None = Header(default=None)):
    inv = store.add_invoice(job_number, po_id, fields, actor=_actor(x_planwise_user))
    if inv is None:
        raise HTTPException(status_code=404, detail="No such PO.")
    return inv


@app.delete("/api/jobs/{job_number}/pos/{po_id}/invoices/{invoice_id}")
def remove_invoice(job_number: str, po_id: str, invoice_id: str,
                   x_planwise_user: str | None = Header(default=None)):
    if not store.delete_invoice(job_number, po_id, invoice_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such PO or invoice.")
    return {"deleted": invoice_id}


# --- change orders (customer + subcontractor) -------------------------------

@app.post("/api/jobs/{job_number}/cos")
def create_co(job_number: str, fields: dict = Body(...),
              x_planwise_user: str | None = Header(default=None)):
    return store.add_co(job_number, fields, actor=_actor(x_planwise_user))


@app.patch("/api/jobs/{job_number}/cos/{co_id}")
def patch_co(job_number: str, co_id: str, fields: dict = Body(...),
             x_planwise_user: str | None = Header(default=None)):
    co = store.update_co(job_number, co_id, fields, actor=_actor(x_planwise_user))
    if co is None:
        raise HTTPException(status_code=404, detail="No such change order.")
    return co


@app.delete("/api/jobs/{job_number}/cos/{co_id}")
def remove_co(job_number: str, co_id: str,
              x_planwise_user: str | None = Header(default=None)):
    if not store.delete_co(job_number, co_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such change order.")
    return {"deleted": co_id}


# --- project meta -----------------------------------------------------------

@app.patch("/api/jobs/{job_number}/meta")
def patch_meta(job_number: str, fields: dict = Body(...),
               x_planwise_user: str | None = Header(default=None)):
    return store.patch_meta(job_number, fields, actor=_actor(x_planwise_user))


# --- document library + annotation layers (Phase 2) -------------------------

@app.get("/api/jobs/{job_number}/documents")
def list_docs(job_number: str):
    return {"documents": documents.list_documents(job_number)}


@app.post("/api/jobs/{job_number}/documents")
async def upload_doc(job_number: str, file: UploadFile = File(...),
                     x_planwise_user: str | None = Header(default=None)):
    data = await file.read()
    try:
        return documents.add_document(job_number, file.filename or "Untitled",
                                      data, actor=_actor(x_planwise_user))
    except documents.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/documents/{doc_id}/file")
def doc_file(doc_id: str):
    doc = documents.get_document(doc_id)
    if doc is None or not documents.doc_path(doc_id).is_file():
        raise HTTPException(status_code=404, detail="No such document.")
    return FileResponse(documents.doc_path(doc_id), media_type="application/pdf",
                        filename=doc["filename"] or f"{doc_id}.pdf")


@app.delete("/api/documents/{doc_id}")
def remove_doc(doc_id: str, x_planwise_user: str | None = Header(default=None)):
    if not documents.delete_document(doc_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such document.")
    return {"deleted": doc_id}


@app.get("/api/documents/{doc_id}/annotations")
def list_anns(doc_id: str, layer: str | None = None, page: int | None = None):
    try:
        return {"annotations": documents.list_annotations(doc_id, layer, page)}
    except documents.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/documents/{doc_id}/annotations")
def add_ann(doc_id: str, body: dict = Body(...),
            x_planwise_user: str | None = Header(default=None)):
    try:
        return documents.add_annotation(
            doc_id, body.get("page", 0), body.get("layer", "internal"),
            body.get("shape") or {}, actor=_actor(x_planwise_user))
    except documents.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/annotations/{ann_id}")
def remove_ann(ann_id: str, x_planwise_user: str | None = Header(default=None)):
    if not documents.delete_annotation(ann_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such annotation.")
    return {"deleted": ann_id}


# --- RFI / Submittal pipeline records (Phase 3a) -----------------------------

@app.get("/api/jobs/{job_number}/records")
def list_records(job_number: str, kind: str | None = None):
    return {"records": records.list_records(job_number, kind)}


@app.post("/api/jobs/{job_number}/records")
def create_record(job_number: str, body: dict = Body(...),
                  x_planwise_user: str | None = Header(default=None)):
    try:
        return records.add_record(job_number, body.get("kind", ""), body,
                                  actor=_actor(x_planwise_user))
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/records/{rec_id}")
def get_record(rec_id: str):
    rec = records.get_record(rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No such record.")
    return rec


@app.patch("/api/records/{rec_id}")
def patch_record(rec_id: str, body: dict = Body(...),
                 x_planwise_user: str | None = Header(default=None)):
    try:
        rec = records.update_record(rec_id, body, actor=_actor(x_planwise_user))
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rec is None:
        raise HTTPException(status_code=404, detail="No such record.")
    return rec


@app.delete("/api/records/{rec_id}")
def remove_record(rec_id: str, x_planwise_user: str | None = Header(default=None)):
    if not records.delete_record(rec_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such record.")
    return {"deleted": rec_id}


@app.post("/api/records/{rec_id}/attachments")
def attach_page(rec_id: str, body: dict = Body(...),
                x_planwise_user: str | None = Header(default=None)):
    try:
        return records.attach_page(rec_id, body.get("document_id", ""),
                                   body.get("page", 0), actor=_actor(x_planwise_user))
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/records/{rec_id}/attachments/{att_id}")
def detach_page(rec_id: str, att_id: str,
                x_planwise_user: str | None = Header(default=None)):
    if not records.detach_page(rec_id, att_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such attachment.")
    return {"deleted": att_id}


@app.get("/api/records/{rec_id}/package")
def record_package(rec_id: str):
    """The outbound PDF: attached pages + ONLY this record's markup layer."""
    from fastapi.responses import Response
    try:
        data = records.build_package(rec_id)
    except records.RecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rec = records.get_record(rec_id)
    name = f"{rec['kind'].upper()}-{rec['number'] or rec_id}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- settings + AI (Phase 3b) ------------------------------------------------

@app.get("/api/settings")
def get_settings():
    return {"settings": ai.get_settings(), "spend": ai.spend_status()}


@app.patch("/api/settings")
def patch_settings(body: dict = Body(...),
                   x_planwise_user: str | None = Header(default=None)):
    return {"settings": ai.patch_settings(body, actor=_actor(x_planwise_user)),
            "spend": ai.spend_status()}


@app.get("/api/companion/token")
def get_companion_token():
    return {"token": ai.companion_token()}


@app.get("/api/companion/poll")
def companion_poll(token: str | None = None):
    """Manifest for a companion's background poll: which threads to watch and
    how often. Token-gated because it names live job/RFI subjects."""
    if token != ai.companion_token():
        raise HTTPException(status_code=401, detail="Bad companion token.")
    s = ai.get_settings()
    return {
        "enabled": s.get("reply_poll_enabled") == "1",
        # The sweep is a BACKSTOP now, not the mechanism: the companion watches
        # Outlook's ItemAdd events and files replies within a second. Outlook
        # is documented to skip ItemAdd when many items arrive at once, and a
        # companion that was closed misses everything, so a periodic catch-up
        # still earns its place — just not at half-hour granularity.
        # Floored at 15s: below that the sweep starts overlapping itself on a
        # busy mailbox, and events already cover the sub-second case anyway.
        "interval_seconds": max(15, int(s.get("reply_poll_seconds") or 60)),
        "threads": records.open_threads(),
        "drafts": records.draft_threads(),
    }


@app.post("/api/records/{rec_id}/draft")
def generate_draft(rec_id: str, x_planwise_user: str | None = Header(default=None)):
    rec = records.get_record(rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No such record.")
    snap = _snapshot()
    job = snap.jobs.get(rec["job_number"], {"job_name": rec["job_number"]})
    markups = []
    for att in rec["attachments"]:
        markups += documents.list_annotations(att["document_id"],
                                              layer=records.layer_for(rec),
                                              page=att["page"])
    draft = ai.draft_email(rec, job, markups)
    return records.save_draft(rec_id, draft["subject"], draft["body"],
                              draft["source"], actor=_actor(x_planwise_user))


@app.get("/api/records/{rec_id}/draft")
def read_draft(rec_id: str):
    return records.get_draft(rec_id) or {}


@app.patch("/api/records/{rec_id}/draft")
def edit_draft(rec_id: str, body: dict = Body(...),
               x_planwise_user: str | None = Header(default=None)):
    if records.get_record(rec_id) is None:
        raise HTTPException(status_code=404, detail="No such record.")
    return records.save_draft(rec_id, body.get("subject", ""), body.get("body", ""),
                              "edited", actor=_actor(x_planwise_user))


@app.post("/api/records/{rec_id}/sent")
def record_sent(rec_id: str, body: dict = Body(default={}),
                x_planwise_user: str | None = Header(default=None)):
    rec = records.mark_sent(rec_id, actor=_actor(x_planwise_user),
                            sent_at=body.get("sent_at"))
    if rec is None:
        raise HTTPException(status_code=404, detail="No such record.")
    return rec


@app.get("/api/records/{rec_id}/replies")
def list_replies(rec_id: str):
    return {"replies": records.list_replies(rec_id)}


@app.post("/api/records/{rec_id}/replies")
def add_reply(rec_id: str, body: dict = Body(...),
              x_planwise_user: str | None = Header(default=None)):
    try:
        reply = records.add_reply(rec_id, body, body.get("attachments"),
                                  actor=_actor(x_planwise_user))
    except records.RecordError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # A reply landing is the thing worth interrupting someone for — and the
    # reason a phone in the field is useful at all. Not for a re-match: the
    # poller re-sees the same reply on every sweep, and buzzing six phones
    # each time would train everyone to ignore it.
    if not reply.get("deduped"):
        rec = records.get_record(rec_id) or {}
        kind = (rec.get("kind") or "record").upper()
        number = rec.get("number") or rec_id[:8]
        who = reply.get("from_email") or "the customer"
        push.send(f"{kind} {number} — reply received",
                  f"From {who}. {(reply.get('summary') or '').strip()[:120]}".strip(),
                  url=f"/#/job/{rec.get('job_number', '')}/"
                      f"{'rfis' if rec.get('kind') == 'rfi' else 'submittals'}/{rec_id}",
                  tag=f"reply:{rec_id}")
    return reply


@app.post("/api/replies/{reply_id}/confirm")
def confirm_reply(reply_id: str, body: dict = Body(default={}),
                  x_planwise_user: str | None = Header(default=None)):
    rep = records.confirm_reply(reply_id, body, actor=_actor(x_planwise_user))
    if rep is None:
        raise HTTPException(status_code=404, detail="No such reply.")
    return rep


@app.get("/api/replies/{reply_id}/attachments/{att_id}")
def reply_attachment(reply_id: str, att_id: str):
    import sqlite3

    from . import db as _db
    conn = _db.connect()
    row = conn.execute("SELECT * FROM reply_attachments WHERE id = ? AND reply_id = ?",
                       (att_id, reply_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such attachment.")
    return FileResponse(row["path"], filename=row["filename"] or "attachment")


# --- schedule (Phase 4) ------------------------------------------------------

@app.get("/api/jobs/{job_number}/schedule")
def get_schedule(job_number: str):
    result = schedule.analyze(job_number)
    ok, detail = schedule.mpp_available()
    result["mpp"] = {"available": ok, "detail": detail}
    return result


@app.post("/api/jobs/{job_number}/schedule/import")
async def import_schedule(job_number: str, mode: str = "replace",
                          file: UploadFile = File(...),
                          x_planwise_user: str | None = Header(default=None)):
    data = await file.read()
    try:
        tasks, source = schedule.parse_schedule(file.filename or "", data)
        return schedule.import_tasks(job_number, tasks, source, mode,
                                     actor=_actor(x_planwise_user))
    except schedule.ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/jobs/{job_number}/schedule/tasks")
def create_task(job_number: str, body: dict = Body(...),
                x_planwise_user: str | None = Header(default=None)):
    return schedule.add_task(job_number, body, actor=_actor(x_planwise_user))


@app.patch("/api/jobs/{job_number}/schedule/tasks/{task_id}")
def patch_task(job_number: str, task_id: str, body: dict = Body(...),
               x_planwise_user: str | None = Header(default=None)):
    t = schedule.update_task(job_number, task_id, body, actor=_actor(x_planwise_user))
    if t is None:
        raise HTTPException(status_code=404, detail="No such task.")
    return t


@app.delete("/api/jobs/{job_number}/schedule/tasks/{task_id}")
def remove_task(job_number: str, task_id: str,
                x_planwise_user: str | None = Header(default=None)):
    if not schedule.delete_task(job_number, task_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such task.")
    return {"deleted": task_id}


# --- look ahead (Phase 4) -----------------------------------------------------

@app.get("/api/jobs/{job_number}/lookahead")
def get_lookahead(job_number: str, start: str | None = None,
                  x_planwise_user: str | None = Header(default=None)):
    period = lookahead.get_or_create_period(job_number, start, actor=_actor(x_planwise_user))
    full = lookahead.get_period(period["id"])
    full["periods"] = lookahead.list_periods(job_number)
    return full


@app.post("/api/lookahead/{period_id}/seed")
def seed_lookahead(period_id: str, x_planwise_user: str | None = Header(default=None)):
    try:
        return lookahead.seed_from_schedule(period_id, actor=_actor(x_planwise_user))
    except lookahead.LookaheadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/lookahead/{period_id}/items")
def create_la_item(period_id: str, body: dict = Body(...),
                   x_planwise_user: str | None = Header(default=None)):
    return lookahead.add_item(period_id, body, actor=_actor(x_planwise_user),
                              at_top=bool(body.get("at_top", True)))


@app.patch("/api/lookahead/items/{item_id}")
def patch_la_item(item_id: str, body: dict = Body(...),
                  x_planwise_user: str | None = Header(default=None)):
    item = lookahead.update_item(item_id, body, actor=_actor(x_planwise_user))
    if item is None:
        raise HTTPException(status_code=404, detail="No such item.")
    return item


@app.delete("/api/lookahead/items/{item_id}")
def remove_la_item(item_id: str, x_planwise_user: str | None = Header(default=None)):
    if not lookahead.delete_item(item_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such item.")
    return {"deleted": item_id}


@app.patch("/api/lookahead/{period_id}")
def patch_period(period_id: str, body: dict = Body(...),
                 x_planwise_user: str | None = Header(default=None)):
    period = lookahead.update_period(period_id, body, actor=_actor(x_planwise_user))
    if period is None:
        raise HTTPException(status_code=404, detail="No such period, or nothing to update.")
    return period


@app.post("/api/lookahead/items/{item_id}/day/{index}")
def toggle_la_day(item_id: str, index: int, body: dict = Body(default={}),
                  x_planwise_user: str | None = Header(default=None)):
    item = lookahead.toggle_day(item_id, index, body.get("on"),
                                actor=_actor(x_planwise_user))
    if item is None:
        raise HTTPException(status_code=404, detail="No such item or day index.")
    return item


@app.get("/api/jobs/{job_number}/lookahead/areas")
def list_la_areas(job_number: str):
    return {"areas": lookahead.list_areas(job_number), "palette": lookahead.AREA_COLORS}


@app.post("/api/jobs/{job_number}/lookahead/areas")
def create_la_area(job_number: str, body: dict = Body(...),
                   x_planwise_user: str | None = Header(default=None)):
    try:
        return lookahead.add_area(job_number, body.get("name"), body.get("color"),
                                  actor=_actor(x_planwise_user))
    except lookahead.LookaheadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/lookahead/areas/{area_id}")
def patch_la_area(area_id: str, body: dict = Body(...),
                  x_planwise_user: str | None = Header(default=None)):
    area = lookahead.update_area(area_id, body, actor=_actor(x_planwise_user))
    if area is None:
        raise HTTPException(status_code=404, detail="No such area, or nothing to update.")
    return area


@app.delete("/api/lookahead/areas/{area_id}")
def remove_la_area(area_id: str, x_planwise_user: str | None = Header(default=None)):
    if not lookahead.delete_area(area_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such area.")
    return {"deleted": area_id}


@app.get("/api/lookahead/{period_id}/share")
def share_lookahead(period_id: str, audience: str = "customer", weeks: int | None = None):
    """Subject, HTML body, suggested recipients, and the printable PDF the
    companion drafts into the user's own Outlook.

    `audience=team` is the internal version: it carries tools and materials,
    and deliberately leaves `to` blank so the PM addresses it themselves from
    the Outlook draft.
    """
    import base64

    period = lookahead.get_period(period_id)
    if period is None:
        raise HTTPException(status_code=404, detail="No such period.")
    snap = _snapshot()
    job = snap.jobs.get(period["job_number"], {})
    job_name = job.get("job_name") or period["job_number"]
    try:
        out = lookahead.share_html(period_id, job_name, period["job_number"], audience, weeks)
        pdf = lookahead.share_pdf(period_id, job_name, period["job_number"], audience, weeks)
    except lookahead.LookaheadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Recipients come from the PM-entered contacts on Overview, so "share with
    # the customer" knows who that actually is. The team version has no such
    # list — who needs it changes week to week — so the PM fills it in.
    internal = lookahead.is_internal(audience)
    meta = store.get_meta(period["job_number"])
    contacts = [c for c in (meta.get("contacts") or []) if c.get("email")]
    out["contacts"] = [] if internal else [
        {"name": c.get("name") or c["email"], "email": c["email"], "role": c.get("role")}
        for c in contacts]
    out["to"] = ";".join(c["email"] for c in out["contacts"])
    out["audience"] = "team" if internal else "customer"
    out["weeks"] = lookahead.share_weeks(period, weeks)
    out["filename"] = (f"Look-Ahead-{out['weeks']}wk{'-INTERNAL' if internal else ''}"
                       f"-{period['job_number']}-{period['start_date']}.pdf")
    out["pdf_b64"] = base64.b64encode(pdf).decode()
    return out


@app.get("/api/lookahead/{period_id}/pdf")
def lookahead_pdf(period_id: str, audience: str = "customer", weeks: int | None = None):
    from fastapi.responses import Response
    period = lookahead.get_period(period_id)
    if period is None:
        raise HTTPException(status_code=404, detail="No such period.")
    snap = _snapshot()
    job = snap.jobs.get(period["job_number"], {})
    try:
        data = lookahead.share_pdf(period_id, job.get("job_name") or period["job_number"],
                                   period["job_number"], audience, weeks)
    except lookahead.LookaheadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tag = "-INTERNAL" if lookahead.is_internal(audience) else ""
    wk = lookahead.share_weeks(period, weeks)
    name = f"Look-Ahead-{wk}wk{tag}-{period['job_number']}-{period['start_date']}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- activity ------------------------------------------------------------------

@app.get("/api/activity")
def global_activity(limit: int = 150):
    return {"activity": store.list_activity(None, limit)}


# Frontend last so /api/* wins.
if FRONTEND.is_dir():
    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
