"""PlanWise — per-job project controls, sourced from the shared Vista extract.

Shared server (decision D9): one instance, the team uses it from their
browsers. Since D27 that instance is hosted rather than a PC on the LAN, so
identity is real: per-user accounts and session cookies (see auth.py), and
every write records who made it. The X-PlanWise-User header that used to carry
identity is now only a local-development fallback — the session wins.
"""
from __future__ import annotations

import io
import re
import secrets
from contextvars import ContextVar
from pathlib import Path

from fastapi import Body, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (ai, attention, auth, briefing, changeorder, config, db,
               documents, eml, lookahead, outbox, po_pdf, push, records,
               reversal, schedule, store, vista)

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
               "/api/auth/register", "/api/auth/companion-pair",
               "/api/auth/bootstrap", "/api/auth/status", "/api/companion/poll",
               "/api/vista/workbook"}
_OPEN_PREFIXES = ()

# What a PENDING account may still do while it waits on the approval screen:
# the open paths (status is its heartbeat, logout its exit) plus change its
# own password — an admin resetting a pending user's password sets
# must_change, and gating the change endpoint would deadlock that screen.
_PENDING_ALLOWED = {"/api/auth/password"}

# Endpoints a companion legitimately WRITES to, with its own token instead of
# a session: it runs with no browser open, so there is no session to have.
#
# This was missed when the session gate went in, and the companion's reply
# filing has been 401ing silently ever since — the poller treated any non-200
# as "nothing found". Scoped by pattern rather than a blanket token bypass, so
# the companion token stays worth exactly these two calls.
_COMPANION_WRITES = re.compile(r"^/api/records/[^/]+/(replies|sent)$")


def _companion_token(request: Request) -> str:
    """Header first; the query param remains because the poll's manifest fetch
    is a GET on an open path."""
    return (request.headers.get("x-planwise-companion")
            or request.query_params.get("token") or "")


def _companion_user(token: str) -> dict | None:
    """Whose companion is calling — or None if the token is wrong (or is the
    legacy global one, handled separately below).

    Per-user tokens are what finally give companion-filed replies an author:
    until now the server had no way to tell whose Outlook a reply arrived in,
    so every background capture recorded actor=NULL.
    """
    if not token:
        return None
    user = auth.user_by_companion_token(token)
    return auth._public(user) if user else None


def _legacy_companion_token_ok(token: str) -> bool:
    """TRANSITIONAL — removed once every companion has re-paired.

    Installed companions hold the one global pairing token. Refusing it the
    moment this deploys would stop reply capture on every PC until someone is
    physically at each one. Nothing is lost either way (filing is only marked
    done on a 200), but a silent gap in detection is exactly what D35 exists
    to prevent.
    """
    expected = ai.companion_token() or ""
    return bool(token and expected and secrets.compare_digest(token, expected))


def _companion_authorised(request: Request, path: str) -> bool:
    if not _COMPANION_WRITES.match(path):
        return False
    token = _companion_token(request)
    return _companion_user(token) is not None or _legacy_companion_token_ok(token)


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

    # A companion presenting a per-user token becomes the context user for
    # ATTRIBUTION only, and only on the two paths it may write to — which is
    # why this resolution lives inside the _COMPANION_WRITES branch rather
    # than beside the cookie lookup above. Hoisted out, a companion token
    # would satisfy `user is not None` for every route in the app and become
    # a skeleton key; there is a regression test that says so.
    if user is None and _COMPANION_WRITES.match(path):
        user = _companion_user(_companion_token(request))

    reset = _CURRENT_USER.set(user)
    try:
        if (path.startswith("/api/") and path not in _OPEN_PATHS
                and not path.startswith(_OPEN_PREFIXES) and user is None
                and not _companion_authorised(request, path)):
            return JSONResponse(status_code=401, content={"detail": "Sign in to continue."})
        if (user is not None and user.get("pending")
                and path.startswith("/api/") and path not in _OPEN_PATHS
                and path not in _PENDING_ALLOWED):
            # Signed in but not yet approved: a real session, held at the
            # door. `pending` in the body is what the frontend keys the
            # waiting screen on — NOT the 403 status, which _require_admin
            # also uses and which must not open that screen.
            return JSONResponse(status_code=403, content={
                "detail": "Your access request hasn't been approved yet.",
                "pending": True})
        return await call_next(request)
    finally:
        _CURRENT_USER.reset(reset)


@app.get("/api/health")
def health():
    """Is the app up, and is the Vista data current? Never guesses."""
    wb = config.vista_workbook()
    mpp_ok, mpp_detail = schedule.mpp_available()
    out = {
        "app": config.APP_NAME,
        "data_dir": str(config.data_dir()),
        "workbook": str(wb) if wb else None,
        "workbook_found": wb is not None,
        # Whether binary .mpp import works on THIS machine. Here rather than
        # behind a session because it's a property of the deployment, not of
        # anyone's data — and because the only way to check that the build
        # actually installed a JRE should not require signing in.
        "mpp_import": {"available": mpp_ok, "detail": mpp_detail},
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


def _lookahead_doc(period: dict, *, audience: str, weeks: int | None,
                   note: str | None = None) -> tuple[dict, bytes]:
    """The ONE place a look-ahead share is assembled.

    Subject, HTML, the internal/customer split (team → tools and materials in,
    recipients deliberately blank), suggested contacts, filename — used by the
    JSON share route, the outbox renderer, and the .eml download, so the
    audience rules can never fork between them. Returns the JSON-ready
    document (without pdf_b64) and the PDF bytes; callers encode or attach.

    Raises LookaheadError for an empty sheet — callers turn that into a 422.
    """
    try:
        job = _snapshot().jobs.get(period["job_number"], {})
    except HTTPException:
        # No Vista extract on this instance (fresh deploy, test env). The job
        # name on the sheet is cosmetic — the number is the identity — so a
        # missing workbook must not make sharing impossible.
        job = {}
    job_name = job.get("job_name") or period["job_number"]
    out = lookahead.share_html(period["id"], job_name, period["job_number"],
                               audience, weeks)
    pdf = lookahead.share_pdf(period["id"], job_name, period["job_number"],
                              audience, weeks)

    # Recipients come from the PM-entered contacts on Overview, so "share with
    # the customer" knows who that actually is. The team version has no such
    # list — who needs it changes week to week — so the PM fills it in.
    internal = lookahead.is_internal(audience)
    meta = store.get_meta(period["job_number"])
    out["contacts"] = [] if internal else [
        {"name": c.get("name") or c["email"], "email": c["email"], "role": c.get("role")}
        for c in (meta.get("contacts") or []) if c.get("email")]
    out["to"] = ";".join(c["email"] for c in out["contacts"])
    out["audience"] = "team" if internal else "customer"
    out["weeks"] = lookahead.share_weeks(period, weeks)
    out["filename"] = (f"Look-Ahead-{out['weeks']}wk{'-INTERNAL' if internal else ''}"
                       f"-{period['job_number']}-{period['start_date']}.pdf")
    if note:
        out["html"] = f"<p>{lookahead._esc(note)}</p>" + out["html"]
    return out, pdf


def _record_doc(rec: dict) -> tuple[dict, bytes | None]:
    """An RFI/Submittal share: saved draft text + the outbound package.

    Mirrors what the record UI sends the companion — the draft is plain text
    (`body`, not `html`) and the package exists only when pages are attached
    (build_package raises on zero pages, so it is skipped, matching the UI's
    own attachments-length guard).
    """
    draft = records.get_draft(rec["id"])
    if not draft:
        raise HTTPException(
            status_code=409,
            detail="Generate the email draft first — it carries the subject and body.")
    pdf = None
    if rec.get("attachments"):
        try:
            pdf = records.build_package(rec["id"])
        except records.RecordError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    doc = {"subject": draft["subject"], "body": draft["body"],
           "to": rec.get("to_email") or "",
           "filename": f"{rec['kind'].upper()}-{rec['number'] or rec['id']}.pdf"
                       if pdf else None}
    return doc, pdf


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

    if item["kind"] == "lookahead":
        period = lookahead.get_period(item["target_id"])
        if period is None:
            raise HTTPException(status_code=404, detail="That look ahead no longer exists.")
        try:
            out, pdf = _lookahead_doc(period, audience=item["audience"] or "customer",
                                      weeks=item["weeks"], note=item.get("note"))
        except lookahead.LookaheadError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        out["pdf_b64"] = base64.b64encode(pdf).decode()
        return out

    rec = records.get_record(item["target_id"])
    if rec is None:
        raise HTTPException(status_code=404, detail="That record no longer exists.")
    out, pdf = _record_doc(rec)
    if item.get("note"):
        out["body"] = f"{item['note']}\n\n{out['body']}"
    if pdf is not None:
        out["pdf_b64"] = base64.b64encode(pdf).decode()
    return out


def _outbox_eml(item_id: str) -> Response:
    """The queued item as a ready-to-send .eml.

    Claim only — claim is repeatable by design (outbox.py), while marking
    drafted is a one-shot the frontend performs AFTER the download lands.
    Marking on this GET would burn the item on a cancelled download.
    """
    me = _CURRENT_USER.get()
    try:
        item = outbox.claim(item_id, me["name"])
    except outbox.OutboxError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if item["kind"] == "lookahead":
        period = lookahead.get_period(item["target_id"])
        if period is None:
            raise HTTPException(status_code=404, detail="That look ahead no longer exists.")
        try:
            out, pdf = _lookahead_doc(period, audience=item["audience"] or "customer",
                                      weeks=item["weeks"], note=item.get("note"))
        except lookahead.LookaheadError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        data = eml.build_eml(out["subject"], out["to"], html=out["html"],
                             attachments=[(out["filename"], pdf)])
        name = out["filename"].removesuffix(".pdf")
    else:
        rec = records.get_record(item["target_id"])
        if rec is None:
            raise HTTPException(status_code=404, detail="That record no longer exists.")
        out, pdf = _record_doc(rec)
        body = f"{item['note']}\n\n{out['body']}" if item.get("note") else out["body"]
        data = eml.build_eml(out["subject"], out["to"], text=body,
                             attachments=[(out["filename"], pdf)] if pdf else None)
        name = out["filename"].removesuffix(".pdf") if out["filename"] else f"{rec['kind']}-{rec['id']}"
    return Response(content=data, media_type="message/rfc822",
                    headers={"Content-Disposition": f'attachment; filename="{name}.eml"'})


@app.get("/api/outbox/{item_id}/eml")
def outbox_eml(item_id: str):
    return _outbox_eml(item_id)


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
    _capture_history(snap)                     # 2.0: accrue the forecast chart's history
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
    me = _CURRENT_USER.get()
    return {"needs_setup": needs_setup,
            "signed_in": me is not None,
            # The waiting screen polls this endpoint and watches this flip.
            # It is an open path, so the poll keeps working while the account
            # itself is held at the door.
            "pending": bool(me and me.get("pending")),
            "user": me}


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


def _notify_admins(title: str, body_text: str, *, url: str = "/",
                   tag: str | None = None) -> None:
    """Push to every working administrator's devices. Best-effort — push.send
    never raises, and an admin with no subscribed device simply isn't buzzed."""
    for account in auth.list_accounts():
        if account["is_admin"] and not account["disabled"] and not account["pending"]:
            push.send(title, body_text, url=url, tag=tag, user=account["name"])


@app.post("/api/auth/register")
def auth_register(response: Response, request: Request, body: dict = Body(...)):
    """Self-service sign-up. The account works immediately — signed in, cookie
    set — but pending, so the waiting screen is all it can reach until an
    administrator approves it under Settings → Users."""
    try:
        user = auth.register(body.get("email", ""), body.get("first_name", ""),
                             body.get("last_name", ""), body.get("password", ""))
    except auth.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _set_session_cookie(response, request, auth.issue_session(user))
    # The push leads with the EMAIL: with no server-side mail there is no
    # verification step, so the address an admin reads here is the identity
    # they are approving. Fixed tag — a flood of sign-ups collapses into one
    # notification per device rather than one buzz each.
    _notify_admins("PlanWise access request",
                   f"{user['name']} <{user['email']}> requested access.",
                   url="/#users", tag="registrations")
    return {"user": user}


@app.post("/api/auth/companion-pair")
def auth_companion_pair(body: dict = Body(...)):
    """Sign-in credentials in, this user's companion token out.

    Open by necessity — the companion is pairing precisely because it holds no
    credential yet. Not a new guessing oracle: /api/auth/login is already open
    and answers the same question, with the same deliberately vague refusal
    and the same ~0.2s PBKDF2 cost per attempt.
    """
    try:
        return auth.companion_pair(body.get("email", ""), body.get("password", ""),
                                   body.get("device"))
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


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
    # Admin-gated since self-service registration: this list now carries
    # pending strangers' names and email addresses. That is the review queue —
    # for the reviewer, not for every signed-in account.
    _require_admin()
    return {"users": auth.list_accounts()}


@app.post("/api/users/{name}/approved")
def approve_user(name: str):
    me = _require_admin()
    user = auth.approve_account(name, actor=me["name"])
    if user is None:
        raise HTTPException(status_code=404, detail="No such user.")
    return user


@app.delete("/api/users/{name}")
def delete_user(name: str):
    """Deny a pending request, or remove an account outright."""
    me = _require_admin()
    if name.strip().lower() == me["name"].strip().lower():
        raise HTTPException(status_code=422, detail="You can't remove your own account.")
    try:
        if not auth.delete_account(name, actor=me["name"]):
            raise HTTPException(status_code=404, detail="No such user.")
    except auth.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"deleted": name}


@app.post("/api/users/{name}/admin")
def set_user_admin(name: str, body: dict = Body(...)):
    me = _require_admin()
    try:
        if not auth.set_admin(name, bool(body.get("is_admin")), actor=me["name"]):
            raise HTTPException(status_code=404, detail="No such user.")
    except auth.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"name": name, "is_admin": bool(body.get("is_admin"))}


@app.post("/api/users/{name}/email")
def set_user_email(name: str, body: dict = Body(...)):
    """Backfill or correct an address — how the bootstrap account, which
    predates email sign-in, gets one."""
    me = _require_admin()
    try:
        return auth.set_email(name, body.get("email", ""), actor=me["name"])
    except auth.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    # 2.0: approved subcontractor work with no PO — exposure, counted
    # separately from commitment (the prototype's "Approved, no PO" column).
    uncovered = store.approved_no_po(job_number)
    unc_by_ct = dict(uncovered["by_cost_type"])
    for row in cost_types:
        row["open_committed"] = committed.pop(row["cost_type"], None)
        row["approved_no_po"] = unc_by_ct.pop(row["cost_type"], None)
    for name, amount in committed.items():
        cost_types.append({
            "cost_type": name, "phase_count": 0, "phase_codes": [],
            "actual_cost": None, "current_estimate": None,
            "projected_cost": None, "hours_units": None, "mtd_cost": None,
            "variance": None, "pct_complete": None,
            "open_committed": amount, "po_only": True,
            "approved_no_po": unc_by_ct.pop(name, None),
        })
    for name, amount in unc_by_ct.items():
        cost_types.append({
            "cost_type": name, "phase_count": 0, "phase_codes": [],
            "actual_cost": None, "current_estimate": None,
            "projected_cost": None, "hours_units": None, "mtd_cost": None,
            "variance": None, "pct_complete": None,
            "open_committed": None, "po_only": True, "approved_no_po": amount,
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
        "approved_no_po": uncovered,
        "meta": store.get_meta(job_number),
    }


def _capture_history(snap) -> None:
    """One vista_history row per job per extract date, idempotent.

    The Vista snapshot has no time axis; the dashboard's cost curve must plot
    real history or nothing. Each push appends today's figures, and UNIQUE
    (job_number, as_of) makes a re-push of the same extract a no-op rather
    than a duplicate point.
    """
    as_of = snap.as_of.isoformat() if snap.as_of else db.now()[:10]
    conn = db.connect()
    for num, rec in snap.jobs.items():
        conn.execute(
            "INSERT OR IGNORE INTO vista_history (as_of, job_number, actual_cost,"
            " projected_cost, current_estimate, actual_billed, pct_complete, captured_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (as_of, num, rec.get("actual_cost"), rec.get("projected_cost"),
             rec.get("current_estimate"), rec.get("actual_billed"),
             rec.get("pct_complete"), db.now()))
    conn.commit()


@app.get("/api/jobs/{job_number}/history")
def job_history(job_number: str):
    """Accrued Vista extract history for the forecast chart. Two points make
    a line; fewer make an honest empty state."""
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT as_of, actual_cost, projected_cost, current_estimate,"
        " actual_billed, pct_complete FROM vista_history WHERE job_number = ?"
        " ORDER BY as_of", (job_number,))]
    return {"history": rows}


@app.get("/api/jobs/{job_number}/attention")
def job_attention(job_number: str):
    """The Needs-attention panel: only items genuinely waiting on the user,
    newest cause first, each deep-linking to where it can be finished.
    Derived, never stored — items disappear because the cause row changed."""
    snap = None
    stale, as_of = False, None
    try:
        snap = _snapshot()
        stale, as_of = snap.is_stale, (snap.as_of.isoformat() if snap.as_of else None)
    except HTTPException:
        pass
    items = attention.items_for(job_number, vista_stale=stale, vista_as_of=as_of)
    return {"items": items, "count": len(items)}


@app.post("/api/activity/{activity_id}/reverse")
def reverse_activity(activity_id: int):
    """Apply an entry's stored inverse. The checks returned are the SAME list
    the confirm dialog rendered — this endpoint enforces what that dialog
    promised. Appends a reversal entry; deletes nothing."""
    me = _CURRENT_USER.get() or {}
    result = reversal.apply(activity_id, actor=me.get("name") or "unknown",
                            is_admin=bool(me.get("is_admin")))
    if not result.get("ok"):
        return JSONResponse(status_code=409, content=result)
    return result


@app.get("/api/activity/{activity_id}/checks")
def activity_checks(activity_id: int):
    """The pass/warn/fail list for the confirm dialog, computed server-side so
    the dialog shows exactly what the apply path will enforce."""
    me = _CURRENT_USER.get() or {}
    entry = reversal.get_entry(activity_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No such activity entry.")
    gate = reversal.checks_for(entry, actor=me.get("name") or "unknown",
                               is_admin=bool(me.get("is_admin")))
    return {"entry": {k: entry.get(k) for k in
                      ("id", "ts", "actor", "action", "detail", "object_kind", "object_id")},
            **gate}


# --- weekly briefing (2.0) ----------------------------------------------------

@app.get("/api/jobs/{job_number}/briefing")
def get_briefing(job_number: str, week: str | None = None):
    """This week's briefing (or the named week's), created from live-register
    proposals on first read."""
    me = _CURRENT_USER.get() or {}
    return briefing.get_or_create(job_number, week, actor=me.get("name"))


@app.patch("/api/briefings/{briefing_id}")
def patch_briefing(briefing_id: str, body: dict = Body(...)):
    me = _CURRENT_USER.get() or {}
    out = briefing.patch(briefing_id, body, actor=me.get("name"))
    if out is None:
        raise HTTPException(status_code=404, detail="No such briefing.")
    return out


@app.post("/api/briefings/{briefing_id}/reseed")
def reseed_briefing(briefing_id: str):
    """Replace the blocks with fresh proposals from the registers — the PM
    asked for a redo, so their edits are deliberately overwritten."""
    me = _CURRENT_USER.get() or {}
    conn = db.connect()
    row = conn.execute("SELECT * FROM briefings WHERE id = ?", (briefing_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such briefing.")
    return briefing.patch(briefing_id, {"blocks": briefing.seed_blocks(row["job_number"])},
                          actor=me.get("name"))


@app.get("/api/briefings/{briefing_id}/share")
def share_briefing(briefing_id: str, audience: str = "customer"):
    """Outlook payload for one audience: subject + HTML body + contacts.
    audience=customer strips the money; audience=team appends the position."""
    conn = db.connect()
    row = conn.execute("SELECT * FROM briefings WHERE id = ?", (briefing_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such briefing.")
    b = dict(row)
    import json as _json
    b["blocks"] = _json.loads(b["blocks"] or "{}") or {}
    job = None
    try:
        job = _snapshot().jobs.get(b["job_number"])
    except HTTPException:
        pass
    internal = audience == "team"
    name = (job or {}).get("job_name") or b["job_number"]
    subject = ("[Internal] " if internal else "") +         f"Weekly briefing — {name} (week of {b['week_start']})"
    meta = store.get_meta(b["job_number"])
    contacts = meta.get("contacts") or []
    return {"subject": subject,
            "html": briefing.render_html(b, job, audience),
            "to": "" if internal else "; ".join(
                c.get("email") for c in contacts if c.get("email")),
            "contacts": contacts, "audience": audience}


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


# --- change order documents ---------------------------------------------------

@app.post("/api/jobs/{job_number}/pos/import")
async def import_po_pdf(job_number: str, file: UploadFile = File(...)):
    """Read purchase orders out of Vista's printed purchase agreement.

    A PROPOSAL, never a write — see backend/po_pdf.py. The caller shows these
    for confirmation; nothing reaches the register until a human agrees.
    """
    data = await _read_capped(file)
    result = po_pdf.parse(data, file.filename or "")
    result["filename"] = file.filename
    result["warnings"] = po_pdf.check_job(result["candidates"], job_number)

    # Flag numbers the register already carries, so a second import of the
    # same file adds duplicate commitments only if somebody means to.
    have = {(p.get("po_number") or "").strip() for p in store.list_pos(job_number)}
    for c in result["candidates"]:
        c["already_on_register"] = c["po_number"] in have
    return result


@app.get("/api/co-clarifications")
def co_clarifications():
    """The standing library of clarifications and exceptions."""
    return {"clarifications": changeorder.list_clarifications()}


@app.post("/api/co-clarifications")
def add_co_clarification(body: dict = Body(...)):
    me = _CURRENT_USER.get()
    try:
        return changeorder.add_clarification(body.get("text", ""),
                                             actor=(me or {}).get("name"))
    except changeorder.ChangeOrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/co-clarifications/{cid}")
def archive_co_clarification(cid: str):
    me = _CURRENT_USER.get()
    if not changeorder.archive_clarification(cid, actor=(me or {}).get("name")):
        raise HTTPException(status_code=404, detail="No such clarification.")
    return {"archived": cid}


def _co_document(job_number: str, co_id: str, clarifications: list[str] | None):
    """Assemble one change order letter. Shared by preview and share so the
    document someone previews is byte-for-byte what gets sent."""
    co = next((c for c in store.list_cos(job_number) if c["id"] == co_id), None)
    if co is None:
        raise HTTPException(status_code=404, detail="No such change order.")

    try:
        job = _snapshot().jobs.get(job_number, {})
    except HTTPException:
        job = {}
    job = {**job, "job_number": job_number}
    meta = store.get_meta(job_number)
    contacts = [c for c in (meta.get("contacts") or []) if c.get("email")]

    is_customer = (co.get("kind") or "customer") == "customer"
    if is_customer and not contacts:
        # A customer letter with nobody to send it to is not a document worth
        # building. Say what's missing and where to fix it, rather than
        # producing a letter addressed to no one.
        raise HTTPException(status_code=409, detail={
            "detail": "This job has no customer contact with an email address yet. "
                      "Add one on the Overview tab and the change order can go out.",
            "needs_contact": True, "job_number": job_number})

    me = _CURRENT_USER.get() or {}
    selected = (changeorder.get_selected(co_id) if clarifications is None
                else clarifications)
    doc = changeorder.compose(
        co, job,
        clarifications=selected,
        items=changeorder.list_items(co_id),
        contact=contacts[0] if contacts else None,
        customer=meta.get("customer"),
        prepared_by={"name": me.get("name"), "phone": meta.get("pm_phone")})
    return co, doc, contacts


@app.get("/api/jobs/{job_number}/cos/{co_id}/items")
def get_co_items(job_number: str, co_id: str):
    return {"items": changeorder.list_items(co_id),
            "total": changeorder.items_total(co_id)}


@app.put("/api/jobs/{job_number}/cos/{co_id}/items")
def put_co_items(job_number: str, co_id: str, body: dict = Body(...)):
    items = changeorder.set_items(co_id, body.get("items") or [])
    # The register's headline figure follows the breakout, so the table and the
    # letter can never show two different numbers for the same change order.
    total = changeorder.items_total(co_id)
    if total is not None:
        me = _CURRENT_USER.get() or {}
        store.update_co(job_number, co_id, {"amount_submitted": total},
                        actor=me.get("name"))
    return {"items": items, "total": total}


def _sub_log(job_number: str) -> tuple[dict, bytes, str]:
    """The subcontractor register as a log document."""
    try:
        job = _snapshot().jobs.get(job_number, {})
    except HTTPException:
        job = {}
    job = {**job, "job_number": job_number}
    cos = [c for c in store.list_cos(job_number) if (c.get("kind") or "") == "subcontractor"]
    name = f"Subcontractor_CO_Log_{job_number}"
    return job, changeorder.build_sub_log_pdf(job, cos), name


@app.get("/api/jobs/{job_number}/cos/{co_id}/document.pdf")
def co_document_pdf(job_number: str, co_id: str):
    co = next((c for c in store.list_cos(job_number) if c["id"] == co_id), None)
    if co is None:
        raise HTTPException(status_code=404, detail="No such change order.")
    if (co.get("kind") or "customer") == "subcontractor":
        # A sub CO is a log entry, not a letter to anybody — see
        # changeorder.build_sub_log_pdf.
        _job, pdf, name = _sub_log(job_number)
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})
    _co, doc, _contacts = _co_document(job_number, co_id, None)
    return Response(content=changeorder.build_pdf(doc), media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'inline; filename="{doc["filename"]}.pdf"'})


@app.get("/api/jobs/{job_number}/cos/{co_id}/document.docx")
def co_document_docx(job_number: str, co_id: str):
    _co, doc, _contacts = _co_document(job_number, co_id, None)
    return Response(
        content=changeorder.build_docx(doc),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}.docx"'})


@app.get("/api/jobs/{job_number}/cos/{co_id}/clarifications")
def get_co_clarifications(job_number: str, co_id: str):
    return {"clarifications": changeorder.get_selected(co_id)}


@app.get("/api/jobs/{job_number}/cos/{co_id}/share.eml")
def co_share_eml(job_number: str, co_id: str):
    """The letter as a ready-to-send email file, for a PC with no companion —
    same escape hatch every other share has (D41)."""
    co, doc, contacts = _co_document(job_number, co_id, None)
    number = co.get("co_number") or co.get("cust_co_number") or ""
    is_customer = doc["is_customer"]
    body = (f"{doc['salutation']}\n\nPlease find attached Change Order Request "
            f"#{number} for {doc['project']}, in the amount of {doc['total']}.\n\n"
            f"{changeorder.CLOSING}\n\nThank you,")
    if not is_customer:
        body = (f"Attached is Change Order #{number} for {doc['project']}, "
                f"in the amount of {doc['total']}.\n\nThank you,")
    data = eml.build_eml(
        f"Change Order Request #{number} — {doc['project']}".strip(" —"),
        ";".join(c["email"] for c in contacts) if is_customer else "",
        text=body,
        attachments=[(f"{doc['filename']}.pdf", changeorder.build_pdf(doc))])
    return Response(content=data, media_type="message/rfc822",
                    headers={"Content-Disposition":
                             f'attachment; filename="{doc["filename"]}.eml"'})


@app.patch("/api/jobs/{job_number}/cos/{co_id}/clarifications")
def set_co_clarifications(job_number: str, co_id: str, body: dict = Body(...)):
    me = _CURRENT_USER.get() or {}
    texts = changeorder.set_selected(co_id, body.get("clarifications") or [],
                                     actor=me.get("name"))
    return {"clarifications": texts}


@app.get("/api/jobs/{job_number}/cos/{co_id}/share")
def share_co(job_number: str, co_id: str):
    """Subject, body, recipients and both attachments for the Outlook draft.

    Word AND PDF go out together on purpose: the customer edits the Word file
    when they come back with questions, and the PDF is what the job folder
    keeps as the record of what was sent.
    """
    import base64

    co = next((c for c in store.list_cos(job_number) if c["id"] == co_id), None)
    if co is None:
        raise HTTPException(status_code=404, detail="No such change order.")

    if (co.get("kind") or "customer") == "subcontractor":
        job, pdf, name = _sub_log(job_number)
        project = job.get("job_name") or job_number
        return {
            "subject": f"Subcontractor Change Order Log — {project}",
            "body": (f"Attached is the current subcontractor change order log for "
                     f"{project}.\n\nThank you,"),
            "to": "",                     # blank on purpose — the PM addresses it
            "contacts": [],
            "kind": "subcontractor",
            "attachments": [{"filename": f"{name}.pdf",
                             "content_b64": __import__("base64").b64encode(pdf).decode()}],
        }

    co, doc, contacts = _co_document(job_number, co_id, None)
    is_customer = doc["is_customer"]
    number = co.get("co_number") or co.get("cust_co_number") or ""
    subject = f"Change Order Request #{number} — {doc['project']}".strip(" —")

    body = (f"{doc['salutation']}\n\nPlease find attached Change Order Request "
            f"#{number} for {doc['project']}, in the amount of {doc['total']}.\n\n"
            f"{changeorder.CLOSING}\n\nThank you,")

    return {
        "subject": subject,
        "body": body,
        # A subcontractor CO deliberately ships with a blank To: line — the PM
        # picks the sub's contact themselves in Outlook (same reasoning as the
        # internal look-ahead share, D19).
        "to": ";".join(c["email"] for c in contacts),
        "contacts": [{"name": c.get("name") or c["email"], "email": c["email"]}
                     for c in contacts],
        "kind": doc["kind"],
        "attachments": [
            {"filename": f"{doc['filename']}.pdf",
             "content_b64": base64.b64encode(changeorder.build_pdf(doc)).decode()},
            {"filename": f"{doc['filename']}.docx",
             "content_b64": base64.b64encode(changeorder.build_docx(doc)).decode()},
        ],
    }


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


@app.get("/api/records/{rec_id}/share.eml")
def record_share_eml(rec_id: str):
    """RFI/Submittal as a ready-to-send email file, for companion-less machines.

    409 until a draft exists — the draft carries the subject and body, same
    prerequisite the Outlook-draft button already has. The package attaches
    only when pages are attached, matching the UI's own guard.
    """
    rec = records.get_record(rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No such record.")
    out, pdf = _record_doc(rec)
    data = eml.build_eml(out["subject"], out["to"], text=out["body"],
                         attachments=[(out["filename"], pdf)] if pdf else None)
    name = out["filename"].removesuffix(".pdf") if out["filename"] else \
        f"{rec['kind'].upper()}-{rec['number'] or rec_id}"
    return Response(content=data, media_type="message/rfc822",
                    headers={"Content-Disposition": f'attachment; filename="{name}.eml"'})


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
    """The signed-in user's OWN companion token, minted on first ask.

    This is what the browser puts in the body of its calls to the companion on
    127.0.0.1, so drafting works when the desk companion is paired to the same
    person. A different person signed in at that desk gets the companion's
    401 — correct rather than unfortunate: their mail would otherwise leave
    from someone else's mailbox (D10).
    """
    me = _CURRENT_USER.get()
    return {"token": auth.companion_token_for(me["id"]), "user_name": me["name"]}


@app.get("/api/companion/poll")
def companion_poll(request: Request, token: str | None = None):
    """Manifest for a companion's background poll: which threads to watch and
    how often. Token-gated because it names live job/RFI subjects."""
    presented = _companion_token(request) or (token or "")
    if not (_companion_user(presented) or _legacy_companion_token_ok(presented)):
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

    name = row["filename"] or "attachment"
    # Serve anything a browser can render INLINE. `filename=` alone sets
    # Content-Disposition: attachment, which forced a download for every
    # returned file — so a customer's screenshot could not be shown in the
    # sent-vs-returned comparison, and clicking the link saved the file
    # instead of previewing it. Everything else still downloads, which is
    # right for a .docx or a .zip.
    inline = name.lower().endswith(
        (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif", ".txt"))
    return FileResponse(row["path"], filename=name,
                        content_disposition_type="inline" if inline else "attachment")


# --- schedule (Phase 4) ------------------------------------------------------

@app.get("/api/jobs/{job_number}/schedule")
def get_schedule(job_number: str):
    result = schedule.analyze(job_number)
    ok, detail = schedule.mpp_available()
    result["mpp"] = {"available": ok, "detail": detail}
    return result


# A schedule file is a few hundred KB; a hundred megabytes is a mistake or an
# attack, and reading it into memory first is how a small server falls over.
_MAX_SCHEDULE_BYTES = 32 * 1024 * 1024


async def _read_capped(file: UploadFile) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_SCHEDULE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"That file is larger than "
                       f"{_MAX_SCHEDULE_BYTES // (1024 * 1024)}MB.")
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/api/jobs/{job_number}/schedule/import")
async def import_schedule(job_number: str, mode: str = "replace",
                          file: UploadFile = File(...),
                          x_planwise_user: str | None = Header(default=None)):
    """Parse and stage. Nothing is applied to the live schedule here.

    An import replaces the plan the whole team works to, so it is shown before
    it is applied — and a PDF import produces candidate dependencies traced
    from arrows, which must be looked at before they can move any date.

    Sources that carry their dependencies explicitly and raise no warnings
    commit straight away: there is nothing for a human to decide, and making
    someone confirm a clean MSPDI import twice would just teach them to click
    through the screen that matters.
    """
    data = await _read_capped(file)
    actor = _actor(x_planwise_user)
    try:
        staged = schedule.stage_import(job_number, file.filename or "", data, actor=actor)
        if not staged["links"] and not staged["warnings"]:
            result = schedule.commit_import(staged["id"], mode=mode, actor=actor)
            result["staged"] = False
            return result
        staged["staged"] = True
        staged["mode"] = mode
        return staged
    except schedule.ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # Deliberately broad, for the same reason the Vista push is (D28):
        # a parser meets files nobody anticipated, and "Internal Server Error"
        # tells the person holding the file nothing at all. Log the trace for
        # us, hand them the reason and a way forward.
        import logging
        import traceback
        logging.getLogger("planwise").error(
            "schedule import failed for %s: %s", file.filename, traceback.format_exc())
        raise HTTPException(
            status_code=422,
            detail=f"That file couldn't be read ({type(exc).__name__}: {exc}). "
                   f"If it is a .mpp, exporting it as XML from Project "
                   f"(File > Save As > XML) is the reliable path."
        ) from exc


@app.get("/api/jobs/{job_number}/schedule/import/staged")
def staged_schedule_import(job_number: str):
    return schedule.latest_staged(job_number) or {"id": None}


@app.get("/api/schedule/import/{import_id}")
def get_schedule_import(import_id: str):
    try:
        return schedule.summarise_import(import_id)
    except schedule.ScheduleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/schedule/import/{import_id}/commit")
def commit_schedule_import(import_id: str, body: dict = Body(default={}),
                           x_planwise_user: str | None = Header(default=None)):
    try:
        return schedule.commit_import(
            import_id, mode=body.get("mode", "replace"),
            accepted_link_ids=body.get("accepted_link_ids") or [],
            actor=_actor(x_planwise_user))
    except schedule.ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/schedule/import/{import_id}/discard")
def discard_schedule_import(import_id: str,
                            x_planwise_user: str | None = Header(default=None)):
    if not schedule.discard_import(import_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="Nothing staged with that id.")
    return {"discarded": import_id}


@app.post("/api/jobs/{job_number}/schedule/calendar")
def set_schedule_calendar(job_number: str, body: dict = Body(...),
                          x_planwise_user: str | None = Header(default=None)):
    return schedule.set_calendar(job_number, workdays=body.get("workdays"),
                                 holidays=body.get("holidays"),
                                 actor=_actor(x_planwise_user))


@app.post("/api/jobs/{job_number}/schedule/links")
def create_schedule_link(job_number: str, body: dict = Body(...),
                         x_planwise_user: str | None = Header(default=None)):
    try:
        link = schedule.add_link(job_number, body.get("pred_id", ""),
                                 body.get("succ_id", ""),
                                 link_type=body.get("link_type", "FS"),
                                 lag_days=float(body.get("lag_days") or 0),
                                 source="manual", actor=_actor(x_planwise_user))
    except schedule.ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if link is None:
        raise HTTPException(status_code=409,
                            detail="Those two are already linked, or that's the same task.")
    return link


@app.delete("/api/jobs/{job_number}/schedule/links/{link_id}")
def remove_schedule_link(job_number: str, link_id: str,
                         x_planwise_user: str | None = Header(default=None)):
    if not schedule.delete_link(job_number, link_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such link.")
    return {"deleted": link_id}


@app.post("/api/jobs/{job_number}/schedule/tasks")
def create_task(job_number: str, body: dict = Body(...),
                x_planwise_user: str | None = Header(default=None)):
    return schedule.add_task(job_number, body, actor=_actor(x_planwise_user))


@app.patch("/api/jobs/{job_number}/schedule/tasks/{task_id}")
def patch_task(job_number: str, task_id: str, body: dict = Body(...),
               x_planwise_user: str | None = Header(default=None)):
    """Edit a task. The response carries `moved` — which OTHER tasks the CPM
    engine rescheduled because of this edit — so the UI can announce
    "N dependent tasks moved with it" from the engine's truth, not a client
    guess (2.0 schedule interactions, LOGIC-MERGE)."""
    before = {t["id"]: (t.get("early_start"), t.get("early_finish"))
              for t in schedule.analyze(job_number)["tasks"]}
    t = schedule.update_task(job_number, task_id, body, actor=_actor(x_planwise_user))
    if t is None:
        raise HTTPException(status_code=404, detail="No such task.")
    moved = []
    for row in schedule.analyze(job_number)["tasks"]:
        if row["id"] == task_id:
            continue
        prev = before.get(row["id"])
        if prev and prev != (row.get("early_start"), row.get("early_finish")):
            moved.append({"id": row["id"], "name": row["name"]})
    t["moved"] = moved
    return t


@app.delete("/api/jobs/{job_number}/schedule/tasks/{task_id}")
def remove_task(job_number: str, task_id: str,
                x_planwise_user: str | None = Header(default=None)):
    if not schedule.delete_task(job_number, task_id, actor=_actor(x_planwise_user)):
        raise HTTPException(status_code=404, detail="No such task.")
    return {"deleted": task_id}


@app.delete("/api/jobs/{job_number}/schedule/tasks")
def clear_schedule(job_number: str,
                   x_planwise_user: str | None = Header(default=None)):
    """Empty the schedule for this job — the way back from a bad import."""
    return {"cleared": schedule.clear_tasks(job_number, actor=_actor(x_planwise_user))}


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
    try:
        out, pdf = _lookahead_doc(period, audience=audience, weeks=weeks)
    except lookahead.LookaheadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out["pdf_b64"] = base64.b64encode(pdf).decode()
    return out


@app.get("/api/lookahead/{period_id}/share.eml")
def share_lookahead_eml(period_id: str, audience: str = "customer",
                        weeks: int | None = None):
    """The share as a ready-to-send email file — the path for machines with no
    companion installed. Opens in classic desktop Outlook as an editable draft
    (X-Unsent), recipient(s), body and PDF already in place."""
    period = lookahead.get_period(period_id)
    if period is None:
        raise HTTPException(status_code=404, detail="No such period.")
    try:
        out, pdf = _lookahead_doc(period, audience=audience, weeks=weeks)
    except lookahead.LookaheadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data = eml.build_eml(out["subject"], out["to"], html=out["html"],
                         attachments=[(out["filename"], pdf)])
    name = out["filename"].removesuffix(".pdf")
    return Response(content=data, media_type="message/rfc822",
                    headers={"Content-Disposition": f'attachment; filename="{name}.eml"'})


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


# 2.0 development mount: while the redesign is built in frontend2/, both UIs
# run against this one backend — 1.x at /, 2.0 at /v2. The cutover (plan
# Phase 12) moves frontend2/ over frontend/ and deletes this block.
FRONTEND2 = FRONTEND.parent / "frontend2"
if FRONTEND2.is_dir():
    @app.get("/v2")
    @app.get("/v2/")
    def index_v2():
        return FileResponse(FRONTEND2 / "index.html")

    app.mount("/v2", StaticFiles(directory=FRONTEND2), name="frontend2")

# Frontend last so /api/* wins.
if FRONTEND.is_dir():
    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
