# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PlanWiseCompanion.exe.

One self-contained file, so distributing it is a copy and using it is a
double-click — no Python, no pip, no admin rights, no IT ticket. Same
reasoning as SiteScope.exe (A2), and the same three decisions worth repeating:

  * onefile — a single artifact survives OneDrive sync and "just send it to
    me" far better than a folder whose DLLs a colleague might not copy.
  * upx=False — UPX-packed binaries are a well-known antivirus false-positive
    trigger, and a blocked launch on a colleague's PC costs more than the
    megabytes save.
  * console=False — this is a background service. A console window would be a
    black rectangle the user must not close, and closing it would silently
    stop reply detection. Anything they must read goes to a dialog or the log
    at ~/.planwise/companion.log.
"""

from PyInstaller.utils.hooks import collect_submodules

hidden = [
    # COM is the whole point of this program: drafting into Outlook and
    # subscribing to its ItemAdd events. All imported lazily, so static
    # analysis never sees them.
    "win32com",
    "win32com.client",
    "win32com.client.gencache",
    "win32com.client.dynamic",
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32clipboard",
    # uvicorn resolves these by name at runtime.
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # The companion talks to the PlanWise server over httpx.
    "httpx",
    "h11",
    "anyio",
    # TLS against the Windows cert store — the corporate proxy's root CA is
    # there and not in certifi, so a hosted (https) PlanWise is unreachable
    # without this. Imported inside a try/except, which PyInstaller's static
    # analysis does not follow, hence the explicit entry.
    "truststore",
    "_ssl",
] + collect_submodules("fastapi")

a = Analysis(
    ["companion/launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # None of the app's own weight belongs here. The companion never reads
        # the Vista workbook, renders a PDF, or touches the database — it is a
        # bridge to Outlook and nothing else.
        "openpyxl",
        "pypdf",
        "sqlite3",
        "tkinter",
        "matplotlib",
        "numpy",
        "PIL",
        "pytest",
        "_pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PlanWiseCompanion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon="packaging/companion.ico",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
