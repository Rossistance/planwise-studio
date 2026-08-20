"""Run PlanWise against the ISOLATED dev data dir (see scripts/seed-dev.py).

launch.json's schema carries no environment variables, so this wrapper sets
the isolation env and starts uvicorn. Everything the 2.0 rebuild touches in
the browser lands here, never in ~/.planwise.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_DIR = os.environ.get("PLANWISE_DEV_DATA") or str(
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) /
    "Temp" / "claude" / "D--New-Product---PlanWise-8-8-2026" /
    "fc8e1591-fe2e-49dd-8b6b-fa78f5db85ab" / "scratchpad" / "devdata")

os.environ["PLANWISE_DATA_DIR"] = DATA_DIR
# Stamped onto the login card and the rail so this instance can never be
# mistaken for the real one (it was, twice, on 2026-08-19).
os.environ["PLANWISE_DEV_BANNER"] = "Sandbox copy — practice data and separate sign-ins. Your real PlanWise is the desktop app."
os.environ["PLANWISE_VISTA_WORKBOOK"] = str(Path(DATA_DIR) / "vista" / "Vista Model DEV - Data.xlsx")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8781)
