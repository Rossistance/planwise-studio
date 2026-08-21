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
import ctypes
import gc
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
                    "captured": 0, "matched": 0, "threads": 0, "drafts": 0,
                    "sends_detected": 0,
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
# How often to look for Outlook's window. Far shorter than WATCH_CHECK because
# a person is standing there waiting for Outlook to close, and enumerating
# windows costs microseconds where asking Outlook a question does not. Half a
# second is chosen against the user's experience rather than the machine's:
# Outlook complains that "another program is using Outlook" the instant it is
# asked to quit while we hold it, so the gap between their click and our
# letting go is exactly how long that message stays on their screen.
WATCH_WINDOW_CHECK = 0.5
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


# Outlook's main explorer window class, unchanged since Outlook 2003 and still
# what classic Outlook 365 uses. Verified on this machine while Outlook was
# open: FindWindowW returned 1510426.
_OUTLOOK_WINDOW_CLASS = "rctrl_renwnd32"
_ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p) \
    if hasattr(ctypes, "WINFUNCTYPE") else None


def outlook_is_open() -> bool:
    """Is there an Outlook on screen for this user?

    Asked before every background pass, because the answer is the difference
    between attaching to the user's Outlook and conjuring a second one out of
    nothing (see `_outlook`).

    WHY THIS IS A WINDOW HANDLE AND NOT `GetActiveObject`.

    The obvious probe is COM's own: `GetActiveObject("Outlook.Application")`
    binds to a running instance and fails when there is none. It does not work
    for Outlook. Measured here with Outlook open and visible, twice, on both
    ProgIDs: `com_error(-2147221021, 'Operation unavailable')` — MK_E_UNAVAILABLE
    — while `FindWindowW` returned a live handle for the same process. Outlook
    does not register itself in the running-object table, so the ROT cannot
    answer this question and a companion trusting it would decide Outlook was
    closed while the user was reading mail in it.

    Its window can, and it answers a slightly better question besides: not "is
    an OUTLOOK.EXE alive" but "is there an Outlook the user can see". A
    windowless Outlook left behind by automation is deliberately not counted —
    there is nothing there for a person to work with, and treating it as
    available is what kept the ghost alive in the first place.

    VISIBLE, and that word is load-bearing. `FindWindowW` was the first
    attempt and is not enough: it matches hidden windows, and enumerating a
    live Outlook shows it owns an INVISIBLE `rctrl_renwnd32` alongside the
    real ones. A held-open Outlook — closed by the user, kept alive by an
    automation client — keeps exactly that kind of window, so a search that
    ignores visibility answers "still open" for the very state this is meant
    to detect, and the companion would never let go.

    Any visible one counts, not just the Inbox explorer: an open draft is also
    `rctrl_renwnd32`, and while a message window is on screen Outlook is
    plainly still in use.
    """
    try:
        user32 = ctypes.windll.user32
    except Exception:  # noqa: BLE001 — no windll off Windows; treat as closed
        return False

    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.EnumWindows.argtypes = [_ENUM_PROC, ctypes.c_void_p]

    found: list = []
    name = ctypes.create_unicode_buffer(64)

    def visit(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            user32.GetClassNameW(hwnd, name, 64)
            if name.value == _OUTLOOK_WINDOW_CLASS:
                found.append(hwnd)
                return False          # stop enumerating; one is enough
        return True

    try:
        # Returns False when the callback stopped it early, which is a result
        # and not an error — hence the answer comes from `found`.
        user32.EnumWindows(_ENUM_PROC(visit), None)
    except Exception:  # noqa: BLE001
        return False
    return bool(found)


def _outlook_window_pid() -> int | None:
    """PID of the visible Outlook window, or None. Same enum as
    outlook_is_open(), kept separate so that hot path stays a bool."""
    try:
        user32 = ctypes.windll.user32
    except Exception:  # noqa: BLE001
        return None
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.EnumWindows.argtypes = [_ENUM_PROC, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]

    pids: list[int] = []
    name = ctypes.create_unicode_buffer(64)

    def visit(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            user32.GetClassNameW(hwnd, name, 64)
            if name.value == _OUTLOOK_WINDOW_CLASS:
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pids.append(pid.value)
                return False
        return True

    try:
        user32.EnumWindows(_ENUM_PROC(visit), None)
    except Exception:  # noqa: BLE001
        return None
    return pids[0] if pids else None


def _process_is_elevated(pid: int | None) -> bool | None:
    """True/False for the process's admin elevation, None when unknowable.

    Why the companion cares: COM cannot cross the elevation boundary. When
    Outlook runs "as administrator" and the companion does not, Dispatch
    cannot attach to it — Windows tries to START a second, normal-level
    Outlook instead, and Outlook's single-instance rule answers with the
    modal "Only one version of Outlook can run at a time". Seen live
    2026-08-20: Outlook open on Drafts, dialog on every draft attempt.
    Detecting the mismatch FIRST means the user gets a sentence naming the
    fix, and the OS dialog is never provoked.

    An access-denied on the token read is itself the answer: a normal
    process can read a normal same-user process's token; being refused is
    the elevated case wearing its uniform.
    """
    if pid is None:
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        advapi32 = ctypes.windll.advapi32
    except Exception:  # noqa: BLE001
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY, TokenElevation = 0x0008, 20
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return True  # cannot even open with the limited right: elevated
    try:
        tok = ctypes.c_void_p()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return True  # token refused to a same-user caller: elevated
        try:
            info = ctypes.c_ulong()
            ret = ctypes.c_ulong()
            if not advapi32.GetTokenInformation(tok, TokenElevation,
                                                ctypes.byref(info), 4,
                                                ctypes.byref(ret)):
                return None
            return bool(info.value)
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def _self_is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _outlook_process_exists() -> bool:
    """Any OUTLOOK.EXE process, window or not — the starting/closing states
    a window probe cannot see."""
    import subprocess
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "OUTLOOK.EXE" in (out.stdout or "")
    except Exception:  # noqa: BLE001
        return False


def _make_visible(app_) -> None:
    """Never leave a headless Outlook behind.

    An Outlook that COM started has no window. If we are going to start one at
    all, the user gets to see the thing that is now using their machine.
    """
    try:
        if app_.Explorers.Count == 0:
            ns = app_.GetNamespace("MAPI")
            app_.Explorers.Add(ns.GetDefaultFolder(6), 0).Display()  # olFolderInbox
    except Exception as exc:  # noqa: BLE001 — cosmetic; the draft still works
        log.warning("could not show the Outlook window (%s)", exc)


def new_outlook_preferred() -> bool:
    """Is NEW Outlook (olk.exe) this person's Outlook?

    Two signals, either sufficient: the toggle classic writes when someone
    flips "Try the new Outlook" (UseNewOutlook=1), or olk.exe actually
    running right now. New Outlook has no COM surface at all, so when it is
    the daily driver the draft window path is pointless — the useful move is
    to save the draft through a HIDDEN classic instance and push it to the
    mailbox, where new Outlook's Drafts folder shows it seconds later
    (owner's design, 2026-08-21).
    """
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Office\16.0\Outlook\Preferences") as k:
            if winreg.QueryValueEx(k, "UseNewOutlook")[0] == 1:
                return True
    except OSError:
        pass
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq olk.exe", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "olk.exe" in (out.stdout or "")
    except Exception:  # noqa: BLE001
        return False


def _outlook(start_if_needed: bool = False, visible: bool = True):
    """Attach to the user's Outlook. Start one ONLY when a person asked.

    WHY THIS IS NOT `Dispatch`.

    `Dispatch("Outlook.Application")` does not mean "find Outlook". It means
    "find Outlook, OR START IT" — and every background path in this file used
    to call it: the 15-second sweep, the watcher's re-attach, and /health,
    which the browser polls while PlanWise is open. So on a PC where Outlook
    was closed, the companion started it. Within seconds. Every time. Closing
    Outlook did not stop it, because the next sweep brought it straight back.

    An Outlook started this way has no window, and it is not a stub: it loads
    the profile, syncs the OST, runs Windows Search indexing and every add-in
    — invisibly, with nothing on screen to explain where the disk and the CPU
    went. Measured on this machine: the companion itself costs 1.8% of one
    core, so the companion was never the load. The Outlook it kept resurrecting
    was.

    It is also how a slow add-in gets switched off. Outlook times each add-in's
    load and disables the slow ones ("...was disabled because it is running
    slowly"); an unattended automation start is exactly the contended load
    where that timer trips. On this PC it tripped MS Project's Outlook Change
    Notifier — an add-in PlanWise does not own, did not install, and only ever
    harmed by starting the host it lives in.

    So the rule is: ASK FIRST, then Dispatch. Dispatch is not the villain —
    an unguarded Dispatch is. Once `outlook_is_open()` has confirmed there is
    an Outlook to attach to, Dispatch attaches to that one and starts nothing;
    the only way it creates a process is if we call it having established that
    none exists, which is now a deliberate decision rather than an accident.
    `start_if_needed` is that decision, reserved for the paths a human
    explicitly triggered — drafting, showing the Drafts folder — and even those
    make the window visible rather than leaving a ghost.
    """
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()

    running = outlook_is_open()
    if not running and not start_if_needed:
        raise HTTPException(status_code=503, detail=(
            "Outlook isn't open on this PC. Open Outlook and PlanWise will "
            "pick up from there."))

    if running and not _self_is_elevated() \
            and _process_is_elevated(_outlook_window_pid()) is True:
        # Dispatching here would not attach — it would provoke the OS's
        # "Only one version of Outlook can run at a time" dialog. Refuse
        # with the fix instead (see _process_is_elevated).
        raise HTTPException(status_code=503, detail=(
            "Outlook is open but running as administrator, and Windows "
            "blocks the companion from reaching an elevated program. Close "
            "Outlook and reopen it normally — from the Start menu or "
            "taskbar, without 'Run as administrator'."))

    if not running and _outlook_process_exists():
        # Outlook's process exists with no visible window: it is starting
        # up or shutting down. Dispatching NOW races that transition and
        # loses (a second OUTLOOK.EXE, refused by the single-instance
        # rule — seen live 2026-08-20, a draft clicked 47 seconds into
        # Outlook's start). The state is short; wait for the window.
        for _ in range(10):
            time.sleep(2)
            if outlook_is_open():
                running = True
                break

    try:
        app_ = win32com.client.Dispatch("Outlook.Application")
    except Exception as exc:  # noqa: BLE001 — surfaced honestly to the UI
        hint = ("An Outlook process exists but would not take the "
                "connection — it may be mid-start, mid-exit, or running "
                "as administrator. Give it a few seconds, or close and "
                "reopen Outlook normally, then try again."
                if _outlook_process_exists()
                else "Open classic Outlook and try again.")
        raise HTTPException(status_code=503, detail=(
            f"Desktop Outlook is not reachable via COM: {exc}. {hint}")) from exc

    started = not running
    if started and visible:
        _make_visible(app_)

    try:
        return app_, app_.GetNamespace("MAPI"), started
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=(
            f"Outlook is open but not answering: {exc}. "
            "It may still be starting up.")) from exc


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
        _app, ns, _started = _outlook()
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
    # A person pressed "Draft in Outlook". Starting Outlook is what they
    # asked for, so this is one of the two paths allowed to. HOW it starts
    # depends on which Outlook this person lives in: classic users get the
    # draft window as always; new-Outlook users get a hidden classic
    # instance that saves the draft and pushes it to the mailbox, because a
    # classic window would be a stranger on their desktop and new Outlook
    # itself has no COM to drive.
    new_pref = new_outlook_preferred()
    app_, ns, started = _outlook(start_if_needed=True, visible=not new_pref)

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
    mode = "window"
    if new_pref:
        # New-Outlook mode: no window to show. Kick a sync so the saved
        # draft reaches the mailbox — that is where new Outlook reads its
        # Drafts folder from — and if this request started the hidden
        # classic instance, give the sync a moment and fold it away (a
        # lingering headless Outlook is the ghost this file's own notes
        # warn about).
        mode = "mailbox"
        try:
            sync = ns.SyncObjects
            for i in range(1, sync.Count + 1):
                sync.Item(i).Start()
        except Exception:  # noqa: BLE001 — cached mode syncs on its own soon
            pass
        if started:
            time.sleep(6)
            try:
                app_.Quit()
            except Exception:  # noqa: BLE001
                pass
    elif body.get("display", True):
        try:
            mail.Display(False)  # modeless — never block the companion
            opened = True
        except Exception:  # noqa: BLE001 — a draft they must hunt for still beats none
            pass

    return {"drafted": True, "entry_id": mail.EntryID,
            "conversation_topic": mail.Subject,
            "opened": opened, "mode": mode,
            "unresolved": unresolved}


@app.post("/show-drafts")
def show_drafts(body: dict = Body(...)):
    """Bring the Drafts folder to the front.

    For the bulk case — several sends prepared in the field and drafted at
    once — opening a window per item would be obnoxious. Selecting the folder
    forces the view to repaint, which is the thing that was missing.
    """
    _check(body.get("token"))
    # Likewise: the whole point of this call is to put Outlook in front of the
    # user, so an Outlook that has to be started is started where they can see it.
    _app, ns, _started = _outlook(start_if_needed=True)
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


def _scan_sent(queries: list[dict]) -> list[dict]:
    """One pass over Sent Items, matching every drafted record at once.

    Shared by the browser's on-demand check and the background sweep. The
    sweep needs it because the live ItemAdd event on Sent Items is the least
    reliable one Outlook offers: under Exchange cached mode the sent copy is
    frequently created by a server-side sync rather than locally, and no
    ItemAdd fires at all. Relying on the event alone meant a send could go
    undetected forever — and since a record only joins the reply watch list
    once it is Sent, the customer's reply was then invisible too. One missed
    event silently killed the whole chain.
    """
    _app, ns, _started = _outlook()
    sent_folder = ns.GetDefaultFolder(5)  # olFolderSentMail

    wanted: dict[str, str] = {}
    for q in queries or []:
        topic = _norm_topic(q.get("subject"))
        if topic:
            wanted.setdefault(topic, q.get("record_id"))
    if not wanted:
        return []

    items = sent_folder.Items
    try:
        items.Sort("[SentOn]", True)
    except Exception as exc:  # noqa: BLE001
        # Sorting is an optimisation, not a requirement — an unsorted scan
        # still finds the message. Losing the whole scan because the sort
        # failed would be the wrong trade.
        log.warning("sent scan: could not sort (%s); scanning unsorted", exc)

    found: dict[str, dict] = {}
    examined = skipped = 0
    for item in items:
        if len(found) == len(wanted):
            break
        examined += 1
        try:
            if getattr(item, "Class", 0) != 43:
                continue
            topic = _norm_topic(getattr(item, "ConversationTopic", None)
                                or getattr(item, "Subject", None))
            if topic not in wanted or topic in found:
                continue
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            log.warning("sent scan: unreadable item skipped (%s: %s)",
                        type(exc).__name__, exc)
            continue

        # THE MATCH IS THE FACT; the timestamp and recipient are garnish.
        # These reads used to live in the same try as the match, so a COM
        # conversion error on SentOn voided a successful match — the record
        # stayed Draft forever while the scan cheerfully reported the item as
        # merely 'unreadable'. The server treats a missing sent_at as "now",
        # which is close enough for a fact whose alternative was 'never'.
        entry: dict = {"record_id": wanted[topic], "sent_on": None, "to": None}
        try:
            so = item.SentOn
            entry["sent_on"] = (so.isoformat() if hasattr(so, "isoformat")
                                else str(so))
        except Exception as exc:  # noqa: BLE001
            log.warning("sent scan: matched %r but SentOn unreadable (%s: %s)",
                        topic, type(exc).__name__, exc)
        try:
            entry["to"] = getattr(item, "To", None)
        except Exception:  # noqa: BLE001
            pass
        found[topic] = entry
    # Silence here is what made this hard to diagnose: a scan that examined
    # nothing and a scan that examined everything and matched nothing looked
    # identical from outside.
    log.info("sent scan: %d items examined, %d unreadable, looking for %d topic(s) %s, matched %d",
             examined, skipped, len(wanted), sorted(wanted)[:3], len(found))
    return list(found.values())


@app.post("/sent")
def sent_check(body: dict = Body(...)):
    """Did a message on this thread actually leave? Checks Sent Items by
    conversation topic — so PlanWise flips Draft → Sent automatically instead
    of asking the PM to bookkeep what Outlook already knows."""
    _check(body.get("token"))
    return {"sent": _scan_sent(body.get("queries") or [])}


def _scan_inbox(queries: list[dict]) -> dict:
    """One pass over the inbox, matching every watched thread at once.

    Per-query iteration was O(inbox x threads); with background polling over
    every open RFI and submittal that becomes the dominant cost, so the topic
    map is built first and the folder is walked once.
    """
    _app, ns, _started = _outlook()
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
    ns = None
    checked = window_checked = 0.0

    def let_go(why: str):
        """Release every COM reference we hold, so Outlook can actually exit.

        THE SECOND HALF OF D45. Not starting Outlook was necessary and not
        sufficient: an automation client that holds a reference also stops
        Outlook CLOSING. The user clicks the X, Outlook cannot exit while we
        hold the object model, so it retreats to the tray and says so —
        "Another program is using Outlook. To disconnect programs and exit
        Outlook, click the Outlook icon and then click Exit Now." What is left
        behind is the same windowless Outlook as before, still syncing the OST
        and running every add-in, and the user has no idea which program is
        holding it.

        Worse, it was self-sustaining. The liveness check below asks Outlook
        for `Items.Count` and concludes Outlook is alive — but Outlook was only
        alive BECAUSE WE WERE HOLDING IT. The check could never fail, so the
        references were never dropped, and one accidental attach lasted until
        the companion was killed.

        Three references, all of them load-bearing: the two event sinks, the
        folders, and `ns` — the namespace is a local of the loop, so it stays
        bound long after the line that created it and pins Outlook on its own.
        """
        nonlocal folders, ns
        global _sinks
        # State first, references second. /health and the chip read these
        # without a lock, and the collection below is not instant — announcing
        # the detachment afterwards leaves a window in which the companion
        # holds nothing while still claiming to be watching.
        watch_state.update(running=False, error=why)
        _sinks, folders, ns = [], [], None
        # Event sinks reference the object they are attached to, so refcounting
        # alone will not break the cycle — and an uncollected cycle here means
        # Outlook stays up, which is the entire bug. Collecting runs
        # EventsProxy.__del__, which is what disconnects the sink.
        gc.collect()

    try:
        while not _watch_stop.is_set():
            # (Re)attach. Closing and reopening Outlook invalidates the COM
            # objects, and the subscription then dies *silently* — no error,
            # no events, and a thread still happily reporting "running". So
            # liveness is checked rather than assumed, and lost subscriptions
            # are rebuilt. Without this, one Outlook restart would quietly put
            # replies back on the half-hour sweep.
            if not _sinks:
                # Outlook closed is a normal state, not a fault. Waiting for it
                # is the whole fix: this line used to Dispatch, which STARTED
                # Outlook — so a user who closed Outlook got a headless one
                # back seconds later, for ever. Watch what the user has open;
                # never manufacture something to watch.
                if not outlook_is_open():
                    watch_state.update(running=False, error="Outlook is not open")
                    _watch_stop.wait(WATCH_RETRY)
                    continue
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
                    let_go(f"attach: {exc}")
                    _watch_stop.wait(WATCH_RETRY)
                    continue

            pythoncom.PumpWaitingMessages()
            time.sleep(0.2)

            now = time.time()
            # Let go the moment the window goes, and check often, because the
            # user is standing there waiting for Outlook to close. Reading a
            # window handle costs nothing, so this can afford to be prompt in a
            # way that asking Outlook a question never could — and asking
            # Outlook is precisely what cannot detect this, since Outlook only
            # answers at all because we are the ones keeping it alive.
            if now - window_checked >= WATCH_WINDOW_CHECK:
                window_checked = now
                if not outlook_is_open():
                    log.info("Outlook window closed; releasing it")
                    let_go("Outlook is not open")
                    continue

            if now - checked >= WATCH_CHECK:
                checked = now
                try:
                    for f in folders:
                        _ = f.Items.Count      # throws once Outlook has gone
                except Exception as exc:  # noqa: BLE001
                    log.warning("live watch lost Outlook (%s); re-attaching", exc)
                    let_go(f"lost Outlook: {exc}")
    finally:
        # On the way out too: a companion being shut down must not be the
        # reason Outlook cannot close.
        let_go("stopped")
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
        poll_state["drafts"] = len(manifest.get("drafts") or [])
        if not manifest.get("enabled"):
            poll_state["last_error"] = None
            poll_state["last_run"] = datetime.now().isoformat(timespec="seconds")
            return

        threads = manifest.get("threads") or []
        drafts = manifest.get("drafts") or []

        # Neither scan below can run without Outlook, and asking for Outlook
        # must never start it (see `_outlook`). A closed Outlook is a normal
        # state — the user went home — so record it and wait, rather than
        # raising a 503 into the log every fifteen seconds.
        if threads or drafts:
            if not await asyncio.to_thread(outlook_is_open):
                poll_state["outlook"] = "not open"
                poll_state["last_error"] = None
                poll_state["last_run"] = datetime.now().isoformat(timespec="seconds")
                return
            poll_state["outlook"] = "open"
        else:
            # Nothing was watched, so nothing was looked at. Saying "open"
            # here would be reporting a check that never happened.
            poll_state["outlook"] = "not checked"

        # SENDS FIRST, and unconditionally — not gated on there being reply
        # threads to watch.
        #
        # This sweep used to scan the Inbox only, and returned early when the
        # thread list was empty. A record that is drafted but not yet sent has
        # no reply thread by definition, so the sweep did nothing at all for
        # it, leaving Draft -> Sent entirely dependent on Outlook's ItemAdd
        # event on Sent Items — the least reliable event it offers (Exchange
        # cached mode routinely creates the sent copy by server sync, firing
        # nothing). A missed event was therefore permanent, and because a
        # record only joins the reply watch list once it is Sent, the
        # customer's reply went unseen too. That is precisely the gap the
        # backstop exists to close (D35); it had only ever closed half of it.
        if drafts:
            for hit in await asyncio.to_thread(_scan_sent, drafts):
                rid = hit["record_id"]
                resp = await client.post(f"{base}/api/records/{rid}/sent",
                                         json={"sent_at": hit.get("sent_on")},
                                         headers={"X-PlanWise-Companion": token})
                if resp.status_code != 200:
                    poll_state["last_error"] = (
                        f"server refused a send: {resp.status_code} {resp.text[:120]}")
                    log.warning("poll: server refused a send (%s)", resp.status_code)
                    continue
                poll_state["sends_detected"] = poll_state.get("sends_detected", 0) + 1
                log.info("poll: %s went out", hit.get("record_id"))
            # The record has just become a reply thread; pick that up now
            # rather than a sweep later, so a fast reply isn't missed.
            _fetch_manifest(force=True)

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
        # Only when something happened. An idle sweep every 15 seconds is 5,700
        # identical lines a day, which buries the one line that matters on the
        # day someone asks why a reply was missed. The counters are always in
        # /health for a live look; the log is for what CHANGED.
        log.log(logging.INFO if captured else logging.DEBUG,
                "poll: %d threads, %d messages scanned, %d on-thread, %d newly filed",
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
