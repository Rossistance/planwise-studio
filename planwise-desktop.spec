# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PlanWise.exe — the desktop app window.

It hosts WebView2 in ITS OWN process rather than launching Edge, so the window
belongs to PlanWise: the taskbar icon is this exe's icon, alt-tab says
PlanWise, and it can be pinned as itself. Shelling out to `msedge --app=` gave
Edge's taskbar icon no matter what the page's favicon said, because the window
was Edge's.

It still embeds no browser and no copy of the server — WebView2 ships with
Windows 11 and the data stays hosted (D9/D27) — so what grew is the pywebview
and pythonnet glue, not a bundled Chromium.

Same three build decisions as the companion, for the same reasons:
  * onefile  — one artifact survives "just send it to me".
  * upx=False — UPX packing is a known antivirus false-positive trigger.
  * console=False — it is a GUI app; a console would flash a black rectangle
    on every launch.
"""

from PyInstaller.utils.hooks import collect_submodules

hidden = [
    # pywebview picks its backend at runtime by name, so static analysis never
    # sees the Windows one or the .NET bridge underneath it.
    "webview",
    "webview.platforms",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr_loader",
    "pythonnet",
] + collect_submodules("webview")

a = Analysis(
    ["desktop/planwise_desktop.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Lean, but note what is NOT excluded: distutils, which clr_loader
        # pulls in to locate the .NET runtime. Excluding it fails the build
        # outright rather than at launch, which is the good kind of failure.
        "tkinter", "unittest", "pydoc_data", "lib2to3",
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
