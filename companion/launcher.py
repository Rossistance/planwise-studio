"""PlanWise Companion — the entry point frozen into PlanWiseCompanion.exe.

Why this exists: teammates have no Python and can't install one, and pip at
runtime fails behind corporate TLS inspection. Freezing ships the interpreter
and every dependency in one file, so the companion is a double-click with no
install, no admin rights, and no IT ticket. Same reasoning that produced
SiteScope.exe (A2).

It has no window on purpose. The companion is a background service: it drafts
into your Outlook when PlanWise asks, and watches your Inbox and Sent Items so
replies and sends reach PlanWise within a second (D35). The only UI it ever
needs is the one-time pairing form, which is served on loopback and opened in
the default browser — that keeps a GUI toolkit out of the build entirely.

Loopback only, always. Windows Firewall prompts when a process listens on a
routable interface, and that prompt needs an administrator; binding 127.0.0.1
avoids it and keeps the port unreachable from the network, which is the right
answer anyway for something that can drive your mailbox.
"""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

PORT = 8772
PAIR_DIR = Path.home() / ".planwise"
LOG_FILE = PAIR_DIR / "companion.log"
AUTH_FILE = PAIR_DIR / "companion_auth.json"
TOKEN_FILE = PAIR_DIR / "companion_token.txt"   # legacy company-wide token
SERVER_FILE = PAIR_DIR / "server_url.txt"
STARTUP_LINK = (Path(os.environ.get("APPDATA", Path.home()))
                / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                / "PlanWise Companion.lnk")


def _notify(text: str, title: str = "PlanWise Companion", style: int = 0x40) -> None:
    """A dialog, because a windowless app has nowhere else to say anything."""
    with_ctypes = getattr(ctypes, "windll", None)
    if with_ctypes:
        ctypes.windll.user32.MessageBoxW(0, text, title, style)
    else:  # pragma: no cover - non-Windows dev
        print(f"{title}: {text}")


def already_running() -> bool:
    """One companion per PC. A second would double-file every reply and fight
    the first for Outlook's single-threaded apartment."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        probe.bind(("127.0.0.1", PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def install_startup_shortcut() -> bool:
    """Put the companion in Startup.

    This matters more than it looks: a companion that only runs when someone
    remembers to launch it will be forgotten, and the first symptom is a
    customer reply nobody sees. Best-effort — a missing shortcut is not worth
    refusing to start over.
    """
    if STARTUP_LINK.exists():
        return True
    try:
        import pythoncom
        from win32com.client import Dispatch

        pythoncom.CoInitialize()
        STARTUP_LINK.parent.mkdir(parents=True, exist_ok=True)
        link = Dispatch("WScript.Shell").CreateShortCut(str(STARTUP_LINK))
        link.Targetpath = sys.executable
        link.WorkingDirectory = str(Path(sys.executable).parent)
        link.Description = "Drafts PlanWise mail in your Outlook and watches for replies"
        link.save()
        return True
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("planwise.companion").warning("no startup shortcut: %s", exc)
        return False


def paired() -> bool:
    """A pairing is the JSON file written by signing in. A leftover
    companion_token.txt from the shared-token era does NOT count — it reads as
    unpaired on purpose, so an upgraded PC is sent to the sign-in page instead
    of being told it is already set up."""
    try:
        import json
        return bool(json.loads(AUTH_FILE.read_text(encoding="utf-8")).get("token"))
    except (OSError, ValueError, AttributeError):
        return False


def open_pairing_when_ready() -> None:
    """Wait for the server to answer, then send the user to the form."""
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    webbrowser.open(f"http://127.0.0.1:{PORT}/pair")


class _NullStream:
    """Stand-in for the stdio a windowed build doesn't have.

    With console=False there is no console, so sys.stdout and sys.stderr are
    None — and anything that reaches for them dies. uvicorn's default log
    formatter calls sys.stdout.isatty() to decide about colour, which crashed
    the frozen build on startup while working perfectly in development.
    """

    def write(self, *_a): return 0
    def flush(self): pass
    def isatty(self): return False
    def fileno(self): raise OSError("no console")


def main() -> int:
    if sys.stdout is None:
        sys.stdout = _NullStream()   # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _NullStream()   # type: ignore[assignment]

    PAIR_DIR.mkdir(parents=True, exist_ok=True)
    # ROTATED, because this program never stops. A companion in Startup runs
    # for months and writes a line per sweep; the first one found in the wild
    # had reached 3.8MB of 25,000 lines, which is both a slowly growing file
    # nobody asked for and — the part that actually costs something — a log
    # you cannot read when you need it. Five 1MB files keep roughly the last
    # fortnight, which is the window in which anyone reports a problem.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=4, encoding="utf-8")])

    argv = [a.lower() for a in sys.argv[1:]]
    if "--pair" in argv:                       # re-run pairing on demand
        AUTH_FILE.unlink(missing_ok=True)
        TOKEN_FILE.unlink(missing_ok=True)

    if already_running():
        # Not an error: double-clicking a background app twice is the normal
        # way to ask "is this thing on?", so answer that question.
        if not paired():
            webbrowser.open(f"http://127.0.0.1:{PORT}/pair")
        else:
            _notify("PlanWise Companion is already running.\n\n"
                    "It has no window — it works in the background, drafting into your "
                    "Outlook and watching for customer replies.\n\n"
                    f"Log: {LOG_FILE}")
        return 0

    install_startup_shortcut()

    if not paired():
        threading.Thread(target=open_pairing_when_ready, daemon=True).start()

    try:
        import uvicorn

        from companion.companion import app
    except ImportError:                        # frozen: flat module layout
        import uvicorn

        from companion import app  # type: ignore[no-redef]

    try:
        # log_config=None: uvicorn's own dictConfig installs a colour-aware
        # formatter that needs a console. We have a log file instead, and its
        # records reach it by propagating to the root logger configured above.
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_config=None,
                    log_level="info", access_log=False)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("planwise.companion").exception("companion stopped")
        _notify(f"PlanWise Companion stopped:\n\n{exc}\n\nLog: {LOG_FILE}",
                style=0x10)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
