# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PlanWise.exe — the desktop app window.

Tiny by design. It opens a chromeless window onto the hosted PlanWise and
starts the Outlook companion; it does not embed a browser or a copy of the
server, so there is nothing here but stdlib. That keeps the installer small
enough to email and free of the runtime dependencies corporate TLS inspection
makes painful to install (A2, D37).

Same three build decisions as the companion, for the same reasons:
  * onefile  — one artifact survives "just send it to me".
  * upx=False — UPX packing is a known antivirus false-positive trigger.
  * console=False — it is a GUI launcher; a console would flash a black
    rectangle on every launch.
"""

a = Analysis(
    ["desktop/planwise_desktop.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Nothing here needs the heavy standard-library corners, and leaving
        # them out keeps the launcher small.
        "tkinter", "unittest", "pydoc_data", "sqlite3", "email", "xml",
        "http.server", "distutils", "lib2to3",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PlanWise",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="packaging/planwise.ico",
)
