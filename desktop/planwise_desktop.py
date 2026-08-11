"""PlanWise on the desktop — the app window, frozen into PlanWise.exe.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT.

It is an application window onto the hosted PlanWise, plus the plumbing that
makes the desktop feel like an app: a Start-menu entry, its own taskbar icon,
no browser chrome, and the Outlook companion started for you.

It is NOT a second copy of PlanWise running locally, and that is the whole
point. D9 says one shared database — six people looking at the same jobs,
change orders and RFIs. A desktop build with its own SQLite would give every
person a private, diverging island of data, which is precisely the failure the
rebuild exists to end. So the data stays in one place (D27: hosted) and this
is a window onto it.

WHY EDGE'S APP MODE RATHER THAN A BUNDLED BROWSER.

Windows 11 ships the WebView2 runtime and Edge; `msedge --app=<url>` opens a
chromeless window that is, to the user, an application. Bundling Chromium
(Electron) would add ~200MB to an installer whose entire appeal is that it
needs no admin rights and no IT ticket (A2), and pulling in pywebview would add
a .NET/pythonnet dependency to a frozen build — the same class of runtime
dependency that corporate TLS inspection already makes painful to install
(D37). A dedicated --user-data-dir keeps the PlanWise session out of the
user's ordinary browsing profile and keeps them signed in between launches.

If Edge is somehow absent, this falls back to the default browser rather than
failing: an ugly window beats no window.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

APP_NAME = "PlanWise"
# Baked in so the installer needs to ask nobody anything. Overridable by the
# file below, which the installer writes and a curious user can edit.
DEFAULT_URL = "https://planwise-rahj.onrender.com"

CONFIG_DIR = Path.home() / ".planwise"
URL_FILE = CONFIG_DIR / "server_url.txt"
PROFILE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PlanWise" / "browser"

COMPANION_PORT = 8772
COMPANION_EXE = "PlanWiseCompanion.exe"


def planwise_url() -> str:
    """Where PlanWise lives. The same file the companion reads, so the two
    halves of the install can never drift onto different servers."""
    try:
        url = URL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        url = ""
    # A bare scheme is what a half-finished install leaves behind; treat it as
    # absent rather than trying to open "https://".
    if url in ("", "http://", "https://"):
        return DEFAULT_URL
    return url.rstrip("/")


def find_edge() -> str | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def companion_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", COMPANION_PORT), timeout=0.4):
            return True
    except OSError:
        return False


def start_companion() -> None:
    """Start the companion if it isn't already up.

    Installed side by side, so it is found relative to this executable. Purely
    best-effort: PlanWise is completely usable without it — sharing falls back
    to downloading an email file — so a companion that won't start is never a
    reason to refuse to open the app.
    """
    if companion_running():
        return
    here = Path(sys.executable).parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent.parent / "dist"
    exe = here / COMPANION_EXE
    if not exe.is_file():
        return
    try:
        # DETACHED_PROCESS: the companion outlives this window, which is the
        # point — it watches Outlook whether or not PlanWise is open.
        subprocess.Popen([str(exe)], close_fds=True,
                         creationflags=0x00000008 | 0x08000000)
    except OSError:
        pass


def main() -> int:
    start_companion()

    url = planwise_url()
    edge = find_edge()
    if edge is None:
        webbrowser.open(url)
        return 0

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # --app strips the browser UI; the window takes the site's own icon and
    # gets its own taskbar entry. The separate profile keeps the PlanWise
    # session alive between launches without touching normal browsing.
    subprocess.Popen([
        edge,
        f"--app={url}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
    ], close_fds=True)
    # Give the window a moment to appear before this process exits, so the
    # taskbar doesn't flash an entry that immediately vanishes.
    time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
