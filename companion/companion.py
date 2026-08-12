"""PlanWise Outlook companion (decision D10).

Runs on EACH USER'S PC, bound to 127.0.0.1 only. The PlanWise web app (in
this user's browser) calls it to:

  * create email drafts — with attachments — in THIS user's signed-in desktop
    Outlook (classic, via COM). The draft lands in their Drafts folder; the
    human presses Send in Outlook. The companion never sends mail.
  * detect that a thread was actually sent (Sent Items), so PlanWise flips
    Draft -> Sent without the PM bookkeeping it.
  * watch THIS user's Inbox and Sent Items live, via Outlook's ItemAdd
    events, so a customer's reply is filed and a Draft flips to Sent within
    about a second rather than at the next sweep. A slower periodic scan
    stays as a backstop for what events miss.

The background poller lives here rather than on the server because only a
companion can see a mailbox, and it must keep working with no browser tab
open. Every companion polls the whole open-thread list: a reply exists only in
the mailbox it was sent to, so a companion without it simply finds nothing —
which removes any need to map PlanWise users to mailboxes.

Mail therefore always flows through the account of the person who clicked —
the server never touches a mailbox (D11). No Graph, no tenant approval, no
stored credentials: COM talks to the Outlook that is already open.

Auth: every request must carry the shared token (fetched by the web app from
the PlanWise server). CORS reflects that browser flow; a foreign website
cannot read the token, so it cannot puppet Outlook through this port.

Run:  companion.bat   (or: python -m uvicorn companion.companion:app --port 8772)
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# Verify TLS against the WINDOWS certificate store, not certifi's bundle.
#
# WECC inspects TLS: the proxy terminates the connection and re-signs it with a
# corporate root CA. That root is installed in the Windows store — every browser
# on the LAN trusts it — but it is not in certifi, which is what httpx uses by
# default. So every HTTPS call out of here failed CERTIFICATE_VERIFY_FAILED the
# moment PlanWise moved from http://127.0.0.1 to https://…onrender.com (D27).
# It was invisible before that: loopback never exercised TLS at all.
#
# inject_into_ssl() patches ssl.SSLContext process-wide, so httpx, requests and
# urllib all pick it up without touching individual call sites. The alternative
# — verify=False — would have "worked" and is exactly wrong: this connection
# carries the token that drives someone's mailbox, so it is the last one that
# should skip certificate checks. Same corporate interception that stops pip
# from installing at runtime, which is why the companion is frozen (A2).
try:
    import truststore

    truststore.inject_into_ssl()
except Exception as exc:  # noqa: BLE001 - never block startup over this
    logging.getLogger("planwise.companion").warning(
        "truststore unavailable, TLS will fall back to certifi: %s", exc)

PAIR_DIR = Path.home() / ".planwise"
# The pairing lives in one JSON file now: token, server and the user it belongs
# to. Its own name, rather than reusing companion_token.txt, so an upgraded PC
# still holding the old company-wide token reads as UNPAIRED and gets the
# sign-in page instead of the "already paired" refusal.
AUTH_FILE = PAIR_DIR / "companion_auth.json"
TOKEN_FILE = PAIR_DIR / "companion_token.txt"   # legacy; deleted once re-paired
SERVER_FILE = PAIR_DIR / "server_url.txt"
DEFAULT_SERVER = "http://127.0.0.1:8771"
PORT = 8772                   # loopback only; the launcher binds the same

log = logging.getLogger("planwise.companion")

app = FastAPI(title="PlanWise Companion")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # token is the gate; the port only listens on loopback
    allow_methods=["*"],
    allow_headers=["*"],
    # PRIVATE NETWORK ACCESS. Hosting PlanWise turned every browser call to
    # this companion into a *public HTTPS origin* reaching a *loopback*
    # address, and Chrome and Edge gate exactly that: the browser sends a
    # preflight carrying `Access-Control-Request-Private-Network: true`, and a
    # server that doesn't answer `Access-Control-Allow-Private-Network: true`
    # has the whole request blocked before it is ever made.
    #
    # Starlette refuses those preflights by default — it answers 400
    # "Disallowed CORS private-network" — so drafting from the hosted app
    # failed at the network layer, which is indistinguishable from the
    # companion not running, and was reported as exactly that. It never
    # appeared while PlanWise was served from 127.0.0.1, because a private
    # origin reaching a private address sends no such preflight.
    #
    # This does not widen what the port accepts: the token still gates every
    # endpoint that does anything, and the socket is still bound to loopback,
    # so nothing off this machine can reach it at all.
    allow_private_network=True,
)

# Background-poll status, surfaced on /health so the UI can show it.
poll_state: dict = {"running": False, "last_run": None, "last_error": None,
                    "captured": 0, "matched": 0, "threads": 0,
                    "interval_seconds": None, "sweeping": False,
                    "last_sweep_ms": None}

# Messages already filed, so a sweep every few seconds doesn't rebuild the same
# payloads forever. Rebuilding means saving every attachment to disk and
# base64-encoding it — fine every half hour, ruinous every fifteen seconds.
# The server dedupes anyway; this stops the CLIENT doing the expensive part
# over and over. Bounded, because a companion can run for weeks.
_filed_ids: dict[str, None] = {}
FILED_CACHE_MAX = 2000

# Live-watch status. The watcher is the fast path; the poll above is a
# backstop for what events miss (see _watch_loop).
watch_state: dict = {"running": False, "started": None, "error": None,
                     "events": 0, "last_event": None,
                     "replies_filed": 0, "sends_detected": 0}

# Strong references to the Outlook Items collections we've subscribed to.
# Load-bearing: let these fall out of scope and Outlook stops delivering
# events with no error of any kind. This is THE classic COM-events bug.
_sinks: list = []
_watch_stop = threading.Event()
_manifest: dict = {"threads": [], "drafts": [], "at": 0.0}
_manifest_lock = threading.Lock()
MANIFEST_TTL = 30.0          # seconds; refreshed on demand when an event lands
WATCH_CHECK = 30.0           # how often to prove the subscription is still alive
WATCH_RETRY = 15.0           # wait before retrying when Outlook is closed


def _auth() -> dict:
    """The pairing on this PC: {token, server, user_name}.

    Written by /pair after PlanWise verifies an email and password. The old
    companion_token.txt held one company-wide secret that every teammate had
    to be handed; it is deliberately NOT read as a pairing any more — a stale
    copy of it is treated as unpaired so the pairing page comes back rather
    than the 409 guard turning an upgraded PC into a dead end.
    """
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("token") else {}


def _expected_token() -> str | None:
    return _auth().get("token")


def paired_user() -> str | None:
    return _auth().get("user_name")


def server_url() -> str:
    url = (_auth().get("server") or "").strip()
    if url:
        return url
    try:                                    # pre-pairing hint from the installer
        return SERVER_FILE.read_text(encoding="utf-8").strip() or DEFAULT_SERVER
    except OSError:
        return DEFAULT_SERVER


def _check(token: str | None) -> None:
    expected = _expected_token()
    if expected is None:
        raise HTTPException(status_code=503, detail=(
            "This PC's companion isn't paired yet. Open "
            f"http://127.0.0.1:{PORT}/pair and sign in with your PlanWise email."))
    if token != expected:
        # Name whose companion this is. The usual cause is two people sharing a
        # desk: drafting from here would put their mail in someone else's
        # Sent Items, so refusing is right — but silence would look broken.
        who = paired_user()
        raise HTTPException(status_code=401, detail=(
            f"This PC's companion is paired to {who}. Sign in to PlanWise as {who} "
            "to draft from here, or re-pair it to yourself."
            if who else "Bad companion token."))


def _outlook():
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        app_ = win32com.client.Dispatch("Outlook.Application")
        return app_, app_.GetNamespace("MAPI")
    except Exception as exc:  # noqa: BLE001 — surfaced honestly to the UI
        raise HTTPException(status_code=503, detail=(
            f"Desktop Outlook is not reachable via COM: {exc}. "
            "Open classic Outlook and try again.")) from exc


# Reply/forward markers and bracketed tags that mail systems bolt onto a
# subject in transit. Verified on this tenant 2026-08-08: a reply came back as
# ConversationTopic '[External] RFI 002 — Siemens - Wendell' against a sent
# topic of 'RFI 002 — Siemens - Wendell', so exact matching found nothing.
# Both sides get normalized, so a tag in the ORIGINAL subject is harmless too.
_TOPIC_NOISE = re.compile(
    r"^\s*(?:(?:re|fw|fwd|aw|antw|sv|vs|tr|rv|res)\s*(?:\[\d+\])?\s*:|\[[^\]]{1,40}\])\s*",
    re.IGNORECASE)


def _norm_topic(subject: str | None) -> str:
    """Compare threads on the stable part of the subject."""
    t = (subject or "").strip()
    prev = None
    while prev != t:                      # peel repeats: "RE: FW: [External] ..."
        prev = t
        t = _TOPIC_NOISE.sub("", t).strip()
    return re.sub(r"\s+", " ", t).casefold()


def _parse_since(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None) if value else None
    except (TypeError, ValueError):
        return None


@app.get("/health")
def health():
    info = {"companion": "PlanWise", "paired": _expected_token() is not None,
            "paired_user": paired_user(),
            "server": server_url(), "poll": poll_state, "watch": watch_state}
    try:
        _app, ns = _outlook()
        acct = ns.Accounts.Item(1).SmtpAddress if ns.Accounts.Count else None
        info.update({"outlook": True, "account": acct})
    except HTTPException as exc:
        info.update({"outlook": False, "detail": exc.detail})
    return info


PAIR_PAGE = """<!doctype html><meta charset="utf-8"><title>Pair PlanWise Companion</title>
<style>
 body{font:15px/1.5 'Segoe UI',system-ui,sans-serif;background:#F2F1EC;color:#1A1D20;
      display:flex;min-height:100vh;margin:0;align-items:center;justify-content:center}
 .card{background:#FCFBF8;border:1px solid #B9B6AA;border-radius:4px;padding:26px 28px;width:430px;
       box-shadow:0 10px 40px rgba(20,22,24,.14)}
 h1{font-size:18px;margin:0 0 4px;letter-spacing:.02em}
 p{color:#5C6470;font-size:13.5px;margin:0 0 18px}
 label{display:block;font:600 10.5px/1 ui-monospace,Consolas,monospace;letter-spacing:.14em;
       text-transform:uppercase;color:#8A8F94;margin:14px 0 5px}
 input{width:100%;padding:8px 10px;border:1px solid #DEDCD3;border-radius:4px;
       background:#F7F6F1;font:15px inherit;box-sizing:border-box}
 button{margin-top:20px;width:100%;padding:10px;border:0;border-radius:4px;background:#C7420A;
        color:#fff;font:600 14px inherit;cursor:pointer}
 .ok{color:#1E7A46} .err{color:#C23A2E}
 .msg{margin-top:14px;font-size:13.5px;min-height:20px}
</style>
<div class="card">
  <h1>Connect this PC to PlanWise</h1>
  <p>Mail is drafted in <b>your own</b> Outlook, on this machine — so sign in as yourself.
     Your password is sent to PlanWise to prove who you are and is never stored here.</p>
  <form id="f">
    <label>PlanWise address</label>
    <input name="server" value="__SERVER__" placeholder="https://planwise.onrender.com" required>
    <!-- Not type="email": accounts that predate email sign-in still identify
         by name, and the browser would refuse to submit one. The server
         accepts either, exactly as the app's own sign-in does. -->
    <label>Work email</label>
    <input name="email" autocomplete="username" required>
    <label>Password</label>
    <input name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Connect</button>
  </form>
  <div class="msg" id="m"></div>
</div>
<script>
f.onsubmit = async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(f).entries());
  m.className = "msg"; m.textContent = "Signing in…";
  const r = await fetch("/pair", {method:"POST", headers:{"Content-Type":"application/json"},
                                  body: JSON.stringify(body)});
  const d = await r.json().catch(() => ({}));
  m.className = "msg " + (r.ok ? "ok" : "err");
  m.textContent = r.ok
    ? "Connected as " + d.user_name + ". You can close this window — the companion runs in the background."
    : (d.detail || "Couldn't connect.");
  if (r.ok) f.reset();
};
</script>"""


@app.get("/pair", response_class=HTMLResponse)
def pair_page():
    """A local pairing form, so setup needs no GUI toolkit in the build.

    Served only on 127.0.0.1 (the whole process binds loopback), and only
    while UNPAIRED — see the POST below for why that matters.
    """
    if _expected_token():
        who = paired_user()
        return HTMLResponse(
            "<p style='font:15px sans-serif;padding:40px'>This PC's companion is already "
            f"connected{f' as <b>{who}</b>' if who else ''}.<br><br>"
            "Run <code>PlanWiseCompanion.exe --pair</code> to connect it as someone else.</p>")
    return HTMLResponse(PAIR_PAGE.replace("__SERVER__", server_url()))


@app.post("/pair")
def pair(body: dict = Body(...), origin: str | None = Header(default=None)):
    """Exchange a PlanWise sign-in for this user's companion token.

    The password is relayed to PlanWise and never written down here — what
    lands on disk is the token PlanWise issues, which is scoped to exactly the
    two endpoints a companion writes to.

    Two guards, because this endpoint decides where the companion sends every
    reply it captures:

      * only while unpaired — otherwise a page you happened to visit could
        re-point an already-working companion at someone else's server;
      * no cross-origin callers — a browser attaches Origin to a fetch from
        another site, and the pairing page itself (same origin) does not.
    """
    if _expected_token():
        raise HTTPException(status_code=409, detail=(
            f"This PC is already connected as {paired_user()}. Run the companion "
            "with --pair to connect it as someone else."))
    if origin and origin.rstrip("/") not in (f"http://127.0.0.1:{PORT}",
                                             f"http://localhost:{PORT}"):
        raise HTTPException(status_code=403, detail="Pairing must be done on this PC.")

    server = (body.get("server") or "").strip().rstrip("/")
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    if not server.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="The address should start with https://")
    if not email or not password:
        raise HTTPException(status_code=422, detail="Email and password are both needed.")

    import socket

    try:
        r = httpx.post(f"{server}/api/auth/companion-pair",
                       json={"email": email, "password": password,
                             "device": socket.gethostname()}, timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=(
            f"Couldn't reach PlanWise at {server}: {exc}")) from exc
    if r.status_code == 401:
        raise HTTPException(status_code=401,
                            detail=r.json().get("detail", "That email and password don't match."))
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=(
            f"PlanWise refused the pairing ({r.status_code})."))

    out = r.json()
    PAIR_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(
        {"token": out["token"], "server": server, "user_name": out["user_name"]},
        indent=2), encoding="utf-8")
    SERVER_FILE.write_text(server, encoding="utf-8")
    # The company-wide token this replaces is worth removing rather than
    # leaving on disk: it still opened the same two endpoints until the
    # server-side fallback is withdrawn.
    TOKEN_FILE.unlink(missing_ok=True)
    log.info("connected to %s as %s", server, out["user_name"])
    return {"paired": True, "server": server, "user_name": out["user_name"]}


@app.post("/draft")
def create_draft(body: dict = Body(...)):
    """Create (never send) a draft in this user's Outlook Drafts folder."""
    _check(body.get("token"))
    app_, _ns = _outlook()

    mail = app_.CreateItem(0)  # olMailItem
    mail.Subject = body.get("subject") or ""
    # HTMLBody when the caller sends markup (the look ahead is a table), plain
    # Body otherwise — setting both makes Outlook drop one of them.
    if body.get("html"):
        mail.HTMLBody = body["html"]
    else:
        mail.Body = body.get("body") or ""

    # Recipients must be ADDED and RESOLVED, not assigned as a string.
    # Setting mail.To = "a@b.com" leaves the address unresolved — Outlook
    # shows it red-underlined and refuses to send ("There was a problem
    # sending this message") until a human clicks it and picks the match.
    # Recipients.Add + Resolve() does what that click does.
    unresolved = []
    raw = (body.get("to") or "").replace(",", ";")
    for addr in [a.strip() for a in raw.split(";") if a.strip()]:
        recip = mail.Recipients.Add(addr)
        recip.Type = 1  # olTo
        if not recip.Resolve():
            unresolved.append(addr)
    mail.Recipients.ResolveAll()

    tmpdir = Path(tempfile.mkdtemp(prefix="planwise_att_"))
    for att in body.get("attachments") or []:
        data = base64.b64decode(att.get("content_b64") or "")
        if not data:
            continue
        fname = (att.get("filename") or "attachment.pdf").replace("/", "_").replace("\\", "_")
        p = tmpdir / fname
        p.write_bytes(data)
        mail.Attachments.Add(str(p))

    mail.Save()  # -> Drafts. The human presses Send in Outlook.

    # ...and then SHOW it. Measured 2026-08-10: creating the draft takes 0.26s
    # end to end, and it is in the correct Drafts folder immediately — but
    # Outlook's Explorer does not repaint for an item injected by an external
    # MAPI session, so it can sit there unseen until the view happens to
    # refresh. That looked, from the outside, like PlanWise taking ten minutes
    # to write a draft.
    #
    # Display() also fits the workflow better than Save() alone ever did: the
    # whole point is that a human reviews and presses Send (D10), so putting
    # the composed mail in front of them beats asking them to go and find it.
    opened = False
    if body.get("display", True):
        try:
            mail.Display(False)  # modeless — never block the companion
            opened = True
        except Exception:  # noqa: BLE001 — a draft they must hunt for still beats none
            pass

    return {"drafted": True, "entry_id": mail.EntryID,
            "conversation_topic": mail.Subject,
            "opened": opened,
            "unresolved": unresolved}


@app.post("/show-drafts")
def show_drafts(body: dict = Body(...)):
    """Bring the Drafts folder to the front.

    For the bulk case — several sends prepared in the field and drafted at
    once — opening a window per item would be obnoxious. Selecting the folder
    forces the view to repaint, which is the thing that was missing.
    """
    _check(body.get("token"))
    _app, ns = _outlook()
    drafts = ns.GetDefaultFolder(16)  # olFolderDrafts
    try:
        explorer = _app.ActiveExplorer()
        if explorer is None:
            explorer = drafts.GetExplorer()
        explorer.CurrentFolder = drafts
        explorer.Display()
        explorer.Activate()
    except Exception as exc:  # noqa: BLE001
        return {"shown": False, "detail": str(exc), "count": drafts.Items.Count}
    return {"shown": True, "count": drafts.Items.Count}


@app.post("/sent")
def sent_check(body: dict = Body(...)):
    """Did a message on this thread actually leave? Checks Sent Items by
    conversation topic — so PlanWise flips Draft → Sent automatically instead
    of asking the PM to bookkeep what Outlook already knows."""
    _check(body.get("token"))
    _app, ns = _outlook()
    sent_folder = ns.GetDefaultFolder(5)  # olFolderSentMail

    wanted = {}
    for q in body.get("queries") or []:
        topic = _norm_topic(q.get("subject"))
        if topic:
            wanted.setdefault(topic, q.get("record_id"))
    if not wanted:
        return {"sent": []}

    items = sent_folder.Items
    items.Sort("[SentOn]", True)
    found: dict[str, dict] = {}
    for item in items:
        if len(found) == len(wanted):
            break
        try:
            if getattr(item, "Class", 0) != 43:
                continue
            topic = _norm_topic(item.ConversationTopic)
            if topic not in wanted or topic in found:
                continue
            found[topic] = {
                "record_id": wanted[topic],
                "sent_on": item.SentOn.isoformat()
                    if hasattr(item.SentOn, "isoformat") else str(item.SentOn),
                "to": getattr(item, "To", None),
            }
        except Exception:  # noqa: BLE001
            continue
    return {"sent": list(found.values())}


def _scan_inbox(queries: list[dict]) -> dict:
    """One pass over the inbox, matching every watched thread at once.

    Per-query iteration was O(inbox x threads); with background polling over
    every open RFI and submittal that becomes the dominant cost, so the topic
    map is built first and the folder is walked once.
    """
    _app, ns = _outlook()
    inbox = ns.GetDefaultFolder(6)  # olFolderInbox

    watched: dict[str, list[dict]] = {}
    earliest: datetime | None = None
    for q in queries:
        topic = _norm_topic(q.get("subject"))
        if not topic:
            continue
        since = _parse_since(q.get("since"))
        watched.setdefault(topic, []).append({"record_id": q.get("record_id"), "since": since})
        if since and (earliest is None or since < earliest):
            earliest = since
    if not watched:
        return {"replies": [], "scanned": 0}

    floor = (earliest or datetime.now() - timedelta(days=30)) - timedelta(minutes=1)
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)
    items = items.Restrict(f"[ReceivedTime] >= '{floor.strftime('%m/%d/%Y %I:%M %p')}'")

    out, scanned = [], 0
    for item in items:
        try:
            if getattr(item, "Class", 0) != 43:  # olMail
                continue
            scanned += 1
            targets = watched.get(_norm_topic(item.ConversationTopic))
            if not targets:
                continue
            # Already filed on an earlier sweep (or by the live watcher):
            # skip before touching attachments, which is the costly part.
            if item.EntryID in _filed_ids:
                continue

            received = item.ReceivedTime
            received_dt = received.replace(tzinfo=None) if hasattr(received, "replace") else None
            payload = _reply_payload(item)

            for t in targets:
                if t["since"] and received_dt and received_dt < t["since"]:
                    continue   # predates this record being sent
                out.append({"record_id": t["record_id"], **payload})
        except Exception:  # noqa: BLE001 — one bad item must not kill the scan
            continue
    # `scanned` makes "no new replies" honest: it distinguishes "looked at 40
    # messages, none on this thread" from "looked at nothing".
    return {"replies": out, "scanned": scanned}


@app.post("/scan")
def scan(body: dict = Body(...)):
    """On-demand scan (the Check for Replies button)."""
    _check(body.get("token"))
    return _scan_inbox(body.get("queries") or [])


# --- background poller -------------------------------------------------------

def _reply_payload(item) -> dict:
    """The shape the server's reply endpoint wants, from an Outlook mail item.

    Shared by the periodic scan and the live watcher so the two can never
    drift into filing subtly different things for the same message.
    """
    received = item.ReceivedTime
    atts = []
    for i in range(1, item.Attachments.Count + 1):
        a = item.Attachments.Item(i)
        path = Path(tempfile.mkdtemp(prefix="planwise_reply_")) / a.FileName
        a.SaveAsFile(str(path))
        atts.append({"filename": a.FileName,
                     "content_b64": base64.b64encode(path.read_bytes()).decode()})
    return {
        "message_id": item.EntryID,          # server dedupes on this
        "from_name": item.SenderName,
        "from_email": getattr(item, "SenderEmailAddress", None),
        "received_at": received.isoformat() if hasattr(received, "isoformat") else str(received),
        "body": (item.Body or "")[:20000],
        "attachments": atts,
    }


# --- live watch: Outlook tells us, instead of us asking every half hour ------
#
# Polling for replies was the original design and it was too slow to be useful:
# a customer answers an RFI and the PM finds out at the next sweep. Outlook
# raises an ItemAdd event on a folder's Items collection the moment a message
# lands, which turns half an hour into about a second.
#
# The periodic sweep stays, because events alone are not trustworthy:
#   * Outlook is documented to skip ItemAdd when a large batch arrives at once
#     (a sync catching up after being offline, typically);
#   * a companion that was closed sees nothing that happened while it was down;
#   * a rule that moves mail out of the Inbox first can beat the handler.
# So: events for speed, a sweep for completeness. Neither is sufficient alone.

def _fetch_manifest(force: bool = False) -> dict:
    """Which threads are worth reacting to. Cached, because an event can
    arrive per message and the server shouldn't be asked each time."""
    now = time.time()
    with _manifest_lock:
        if not force and now - _manifest["at"] < MANIFEST_TTL:
            return dict(_manifest)
    token = _expected_token()
    if not token:
        return {"threads": [], "drafts": [], "at": now}
    try:
        r = httpx.get(f"{server_url()}/api/companion/poll",
                      params={"token": token}, timeout=20)
        r.raise_for_status()
        data = r.json()
        fresh = {"threads": data.get("threads") or [],
                 "drafts": data.get("drafts") or [], "at": now}
    except Exception as exc:  # noqa: BLE001 — a stale manifest beats no watcher
        watch_state["error"] = f"manifest: {exc}"
        with _manifest_lock:
            return dict(_manifest)
    with _manifest_lock:
        _manifest.update(fresh)
        return dict(fresh)


def _auth_headers() -> dict:
    """The companion runs with no browser, so it has no session — it presents
    its own token instead. The server accepts it for exactly these writes."""
    return {"X-PlanWise-Companion": _expected_token() or ""}


def _remember_filed(entry_id: str | None) -> None:
    if not entry_id:
        return
    _filed_ids[entry_id] = None
    while len(_filed_ids) > FILED_CACHE_MAX:
        _filed_ids.pop(next(iter(_filed_ids)))      # oldest first (dicts keep order)


def _file_reply(item, thread: dict) -> None:
    entry_id = item.EntryID
    r = httpx.post(f"{server_url()}/api/records/{thread['record_id']}/replies",
                   json=_reply_payload(item), headers=_auth_headers(), timeout=60)
    if r.status_code != 200:
        watch_state["error"] = f"filing a reply: {r.status_code} {r.text[:120]}"
        log.warning("live: server refused a reply (%s)", r.status_code)
        return
    _remember_filed(entry_id)
    if not r.json().get("deduped"):
        watch_state["replies_filed"] += 1
        log.info("live: filed a reply on %s", thread.get("subject"))


def _file_sent(item, draft: dict) -> None:
    sent_on = getattr(item, "SentOn", None)
    r = httpx.post(f"{server_url()}/api/records/{draft['record_id']}/sent",
                   json={"sent_at": sent_on.isoformat()
                         if hasattr(sent_on, "isoformat") else None},
                   headers=_auth_headers(), timeout=30)
    if r.status_code != 200:
        watch_state["error"] = f"marking sent: {r.status_code} {r.text[:120]}"
        log.warning("live: server refused a send (%s)", r.status_code)
        return
    watch_state["sends_detected"] += 1
    log.info("live: %s went out", draft.get("subject"))


def _on_new_item(item, where: str) -> None:
    """Called by Outlook on its own thread. Must not raise — an exception
    escaping into COM can tear the subscription down silently."""
    try:
        if getattr(item, "Class", 0) != 43:          # olMail
            return
        topic = _norm_topic(getattr(item, "ConversationTopic", None)
                            or getattr(item, "Subject", None))
        if not topic:
            return
        watch_state["events"] += 1
        watch_state["last_event"] = datetime.now().isoformat(timespec="seconds")

        manifest = _fetch_manifest()
        if where == "inbox":
            for thread in manifest["threads"]:
                if _norm_topic(thread.get("subject")) == topic:
                    _file_reply(item, thread)
        else:
            for draft in manifest["drafts"]:
                if _norm_topic(draft.get("subject")) == topic:
                    _file_sent(item, draft)
                    # It's no longer a draft; don't match it again on the
                    # cached copy before the next refresh.
                    _fetch_manifest(force=True)
    except Exception as exc:  # noqa: BLE001
        watch_state["error"] = str(exc)
        log.warning("live watch handler: %s", exc)


class _InboxSink:
    def OnItemAdd(self, item):        # noqa: N802 — COM event name
        _on_new_item(item, "inbox")


class _SentSink:
    def OnItemAdd(self, item):        # noqa: N802 — COM event name
        _on_new_item(item, "sent")


def _watch_loop() -> None:
    """Own thread, own COM apartment, own message pump.

    COM events are delivered by pumping Windows messages, which asyncio's loop
    does not do — hence a dedicated thread rather than a task.
    """
    global _sinks
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pragma: no cover - Windows only
        watch_state["error"] = f"pywin32 unavailable: {exc}"
        return

    pythoncom.CoInitialize()
    folders: list = []
    checked = 0.0
    try:
        while not _watch_stop.is_set():
            # (Re)attach. Closing and reopening Outlook invalidates the COM
            # objects, and the subscription then dies *silently* — no error,
            # no events, and a thread still happily reporting "running". So
            # liveness is checked rather than assumed, and lost subscriptions
            # are rebuilt. Without this, one Outlook restart would quietly put
            # replies back on the half-hour sweep.
            if not _sinks:
                try:
                    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
                    folders = [ns.GetDefaultFolder(6), ns.GetDefaultFolder(5)]
                    _sinks = [
                        win32com.client.DispatchWithEvents(folders[0].Items, _InboxSink),
                        win32com.client.DispatchWithEvents(folders[1].Items, _SentSink),
                    ]
                    watch_state.update(running=True, error=None,
                                       started=datetime.now().isoformat(timespec="seconds"))
                    log.info("live watch attached to Inbox and Sent Items")
                except Exception as exc:  # noqa: BLE001 — Outlook may just be closed
                    _sinks, folders = [], []
                    watch_state.update(running=False, error=f"attach: {exc}")
                    _watch_stop.wait(WATCH_RETRY)
                    continue

            pythoncom.PumpWaitingMessages()
            time.sleep(0.2)

            now = time.time()
            if now - checked >= WATCH_CHECK:
                checked = now
                try:
                    for f in folders:
                        _ = f.Items.Count      # throws once Outlook has gone
                except Exception as exc:  # noqa: BLE001
                    log.warning("live watch lost Outlook (%s); re-attaching", exc)
                    _sinks, folders = [], []
                    watch_state.update(running=False, error=f"lost Outlook: {exc}")
    finally:
        _sinks = []
        watch_state["running"] = False
        with contextlib.suppress(Exception):
            pythoncom.CoUninitialize()


async def _poll_once() -> None:
    token = _expected_token()
    if not token:
        poll_state["last_error"] = "not paired"
        return
    base = server_url()

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{base}/api/companion/poll", params={"token": token})
        r.raise_for_status()
        manifest = r.json()

        poll_state["interval_seconds"] = manifest.get("interval_seconds")
        poll_state["threads"] = len(manifest.get("threads") or [])
        if not manifest.get("enabled"):
            poll_state["last_error"] = None
            poll_state["last_run"] = datetime.now().isoformat(timespec="seconds")
            return

        threads = manifest.get("threads") or []
        if not threads:
            poll_state["last_error"] = None
            poll_state["last_run"] = datetime.now().isoformat(timespec="seconds")
            return

        result = await asyncio.to_thread(_scan_inbox, threads)

        captured = seen = 0
        for rep in result["replies"]:
            rid = rep.pop("record_id")
            resp = await client.post(f"{base}/api/records/{rid}/replies", json=rep,
                                     headers={"X-PlanWise-Companion": token})
            if resp.status_code != 200:
                # Never silently. A 401 here once looked exactly like "the
                # customer hasn't replied", for an entire phase.
                poll_state["last_error"] = (
                    f"server refused a reply: {resp.status_code} {resp.text[:120]}")
                log.warning("poll: server refused a reply (%s)", resp.status_code)
                continue
            seen += 1
            _remember_filed(rep.get("message_id"))
            # The server is idempotent and flags a re-seen reply as deduped,
            # so this counts only what was genuinely filed this cycle.
            if not resp.json().get("deduped"):
                captured += 1

        poll_state["captured"] = captured
        poll_state["matched"] = seen
        poll_state["last_error"] = None
        poll_state["last_run"] = datetime.now().isoformat(timespec="seconds")
        log.info("poll: %d threads, %d messages scanned, %d on-thread, %d newly filed",
                 len(threads), result["scanned"], seen, captured)


async def _poll_loop() -> None:
    """The backstop sweep. Seconds, not minutes — the old floor of five
    minutes was hard-coded here and silently overrode whatever the server
    asked for."""
    await asyncio.sleep(10)  # let Outlook settle after a cold start
    while True:
        seconds = poll_state.get("interval_seconds") or 60
        started = time.perf_counter()
        try:
            # A sweep that outlasts its own interval would otherwise stack up
            # on a slow mailbox and fight the live watcher for Outlook.
            poll_state["sweeping"] = True
            await _poll_once()
        except Exception as exc:  # noqa: BLE001 — a bad cycle must not end the loop
            poll_state["last_error"] = f"{type(exc).__name__}: {exc}"
            log.warning("poll failed: %s", exc)
        finally:
            poll_state["sweeping"] = False
            poll_state["last_sweep_ms"] = int((time.perf_counter() - started) * 1000)
        seconds = poll_state.get("interval_seconds") or seconds
        await asyncio.sleep(max(15, int(seconds)))


@app.on_event("startup")
async def _start_poller() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s")
    poll_state["running"] = True
    app.state.poller = asyncio.create_task(_poll_loop())
    _watch_stop.clear()
    app.state.watcher = threading.Thread(target=_watch_loop, name="planwise-watch",
                                         daemon=True)
    app.state.watcher.start()


@app.on_event("shutdown")
async def _stop_poller() -> None:
    poll_state["running"] = False
    task = getattr(app.state, "poller", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    _watch_stop.set()


@app.post("/poll-now")
async def poll_now(body: dict = Body(...)):
    """Force a cycle immediately and report what it did.

    Must be async: a sync handler runs in FastAPI's threadpool where there is
    no running event loop, so scheduling work from it silently did nothing.
    """
    _check(body.get("token"))
    try:
        await _poll_once()
    except Exception as exc:  # noqa: BLE001
        poll_state["last_error"] = f"{type(exc).__name__}: {exc}"
        raise HTTPException(status_code=502, detail=poll_state["last_error"]) from exc
    return {"polled": True, **poll_state}
