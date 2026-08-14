"""PlanWise on the desktop — the app window, frozen into PlanWise.exe.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT.

It is an application window onto the hosted PlanWise, plus the plumbing that
makes the desktop feel like an app: a Start-menu entry, its own taskbar icon,
no browser chrome, and the Outlook companion started for you.

It is NOT a second copy of PlanWise running locally, and that is the whole
point. D9 says one shared database — the team looking at the same jobs, change
orders and RFIs. A desktop build with its own SQLite would give every person a
private, diverging island of data, which is precisely the failure the rebuild
exists to end. So the data stays in one place (D27: hosted) and this is a
window onto it.

WHY THE WINDOW IS OURS RATHER THAN EDGE'S.

The first version launched `msedge --app=<url>`, which looks right and is
wrong in one visible way: the window belongs to Edge's process and carries
Edge's AppUserModelID, so Windows groups it under Edge and paints the TASKBAR
button with the Edge icon. The title bar and thumbnail showed PlanWise; the
taskbar did not, and no amount of unpinning fixes that because the window was
never ours to label.

So we host WebView2 ourselves. The window belongs to PlanWise.exe, which means
the taskbar icon is PlanWise.exe's icon, alt-tab says PlanWise, and pinning it
pins PlanWise. The explicit AppUserModelID below is what stops Windows
folding it into any other application's group.

WebView2 is the same engine Edge uses and ships with Windows 11, so this
renders identically to the browser and adds no download — what it adds is
ownership of the window.
"""
from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
from pathlib import Path

APP_NAME = "PlanWise"
# Identifies this app to the Windows shell. Without it a hosted-browser window
# can be grouped under whatever the runtime belongs to; with it, PlanWise is
# its own taskbar entry that can be pinned.
APP_ID = "Legacy1910.PlanWise.Desktop.1"

# Baked in so the installer needs to ask nobody anything. Overridable by the
# file below, which the installer writes and a curious user can edit.
DEFAULT_URL = "https://planwise-rahj.onrender.com"

CONFIG_DIR = Path.home() / ".planwise"
URL_FILE = CONFIG_DIR / "server_url.txt"
# WebView2's own profile: keeps the PlanWise session alive between launches
# and out of the user's ordinary browsing.
PROFILE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PlanWise" / "webview"

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
    to downloading an email file (D41) — so a companion that won't start is
    never a reason to refuse to open the app.
    """
    if companion_running():
        return
    here = Path(sys.executable).parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent.parent / "dist"
    exe = here / COMPANION_EXE
    if not exe.is_file():
        return
    try:
        # DETACHED_PROCESS | CREATE_NO_WINDOW: the companion outlives this
        # window, which is the point — it watches Outlook whether or not
        # PlanWise is open.
        subprocess.Popen([str(exe)], close_fds=True,
                         creationflags=0x00000008 | 0x08000000)
    except OSError:
        pass


def claim_taskbar_identity() -> None:
    with_shell = getattr(ctypes, "windll", None)
    if not with_shell:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001 — cosmetic; never worth failing to start
        pass


def main() -> int:
    claim_taskbar_identity()
    start_companion()

    url = planwise_url()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # WebView2 reads this rather than a command-line flag, since the runtime is
    # created inside the host process.
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(PROFILE_DIR))

    try:
        import webview
    except ImportError:
        import webbrowser
        webbrowser.open(url)
        return 0

    # Open MAXIMISED, every time.
    #
    # The default 1440x900 was a guess at a window size, and on a smaller or
    # scaled display it opened partly off the bottom of the screen — which is
    # what it did after every launch, not just the first. This app is a wide
    # table of financial columns and a Gantt chart; there is no size a guess
    # gets right, and the honest answer is "as much room as the screen has".
    #
    # width/height remain as the RESTORE size, for when someone un-maximises.
    # Measured, not guessed: the machine this was found on is 1280x800 with a
    # 752px work area once the taskbar is taken out, so anything taller than
    # ~720 reproduces the same overhang the moment the window is restored.
    # pywebview centres a window whose x/y are unset.
    webview.create_window(APP_NAME, url, width=1200, height=720,
                          min_size=(900, 560), maximized=True,
                          confirm_close=False)
    try:
        webview.start()
    except Exception as exc:  # noqa: BLE001
        # No WebView2 runtime (a stripped Windows 10 image, most likely). An
        # ugly window beats no window: fall back to the default browser and
        # say why, rather than exiting silently with nothing on screen.
        import webbrowser
        if getattr(ctypes, "windll", None):
            ctypes.windll.user32.MessageBoxW(
                0, f"PlanWise couldn't open its own window ({exc}).\n\n"
                   "Opening in your browser instead. Installing the Microsoft "
                   "Edge WebView2 Runtime will restore the app window.",
                APP_NAME, 0x40)
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
