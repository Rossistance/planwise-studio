"""Paths and settings for PlanWise.

Two locations matter:

* the **Vista workbook** — read-only, refreshed daily by a Power Automate flow
  and delivered to every workstation through OneDrive sync. PlanWise never
  writes to it.
* the **data directory** — everything PlanWise itself owns (projects, change
  orders, POs, schedule, field records). Local, writable, one directory.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "PlanWise"

# The shared Vista extract. OneDrive names a synced library
# "<tenant display name>/<site> - <library>", so the path is the same shape on
# every workstation that syncs Company Share — but the tenant folder is named
# by the user's OneDrive client, so we discover it rather than hardcode it.
_LIBRARY_TAIL = Path("Company Share - Documents") / "Vista Model 2026- RH"
_WORKBOOK_NAME = "Vista Model 2026 - Data.xlsx"

# How long after the flow's as_of stamp the data is still considered current.
# Matches the freshness contract the Financial Studio already uses.
STALE_AFTER_HOURS = 26


def data_dir() -> Path:
    """Everything PlanWise owns. Override with PLANWISE_DATA_DIR (tests do)."""
    override = os.environ.get("PLANWISE_DATA_DIR")
    root = Path(override) if override else Path.home() / ".planwise"
    root.mkdir(parents=True, exist_ok=True)
    return root


def pushed_workbook() -> Path:
    """Where a workbook delivered over the API lands (Phase 5b).

    A hosted PlanWise has no OneDrive, so the daily `vista_pull.py` run on
    Ross's PC pushes the extract here instead of relying on a synced folder.
    """
    return data_dir() / "vista" / _WORKBOOK_NAME


# Both of these keep the .xlsx extension deliberately: openpyxl refuses to
# open a file by any other name, so a ".incoming" temp could never be
# validated and a ".prev" backup could never be recovered from.
def pushed_workbook_incoming() -> Path:
    p = pushed_workbook()
    return p.with_name(f"{p.stem}.incoming.xlsx")


def pushed_workbook_previous() -> Path:
    p = pushed_workbook()
    return p.with_name(f"{p.stem} (previous).xlsx")


def vista_workbook() -> Path | None:
    """Locate the Vista workbook, or None if this machine has not synced it.

    Resolution order:
      1. PLANWISE_VISTA_WORKBOOK — an explicit path. An empty string means
         "don't go hunting my home directory", which is what test isolation
         needs; it does not disable step 3, because a pushed copy is the
         app's own data rather than a machine-dependent discovery.
      2. Any OneDrive tenant folder under the user's home that contains the
         Company Share library path.
      3. A copy pushed over the API. Last, so a workstation that syncs
         OneDrive keeps using the canonical file; first and only resort on a
         hosted instance, which has no OneDrive to sync.

    Returns None rather than raising: a machine mid-sync is a normal state and
    the UI says so honestly instead of crashing.
    """
    override = os.environ.get("PLANWISE_VISTA_WORKBOOK")
    if override:
        p = Path(override)
        return p if p.is_file() else None

    home = Path.home() if override is None else None
    # "OneDrive - 1910 Legacy Enterprises" today, but don't assume the tenant
    # display name — match any OneDrive-style folder, then the exact library.
    if home is not None:
        candidates = sorted(home.glob("OneDrive*")) + sorted(home.glob("1910 Legacy*"))
        for base in candidates:
            p = base / _LIBRARY_TAIL / _WORKBOOK_NAME
            if p.is_file():
                return p

    pushed = pushed_workbook()
    return pushed if pushed.is_file() else None


def ingest_token() -> str | None:
    """Shared secret for the workbook push. Unset means the endpoint is off —
    fail closed, so a misconfigured instance refuses uploads rather than
    accepting anonymous ones."""
    return (os.environ.get("PLANWISE_INGEST_TOKEN") or "").strip() or None
