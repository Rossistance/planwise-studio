"""Importing schedules: spreadsheets, printed PDFs, and the staging gate.

The requirement these tests exist to hold: **never invent**. An importer that
quietly produces a task nobody scheduled, a date nobody set, or a dependency
nobody drew is worse than one that imports nothing, because the result looks
like a plan and gets worked to.
"""
from __future__ import annotations

import csv
import io
import json
import os
import zlib
from pathlib import Path

import pytest

from backend import db, schedule, schedule_tab

# The real customer schedule. Outside the repo on purpose — it is customer data
# and must never be committed — so the test that uses it skips when it is absent.
SIEMENS = Path(
    r"C:\Users\rhixon\1910 Legacy Enterprises\Axis Share - Documents"
    r"\1. Axis Active Project Files\24-003 - Siemens Wendell\003 - Schedule"
    r"\2024-10-15 S RE - US, Wendell-NC - Siemens Rd - Solar-BESS 44OP-362593.pdf")


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


JOB = "24-003"


# --- spreadsheets -------------------------------------------------------------

def csv_bytes(rows) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


PROJECT_EXPORT = [
    ["ID", "Task Name", "Duration", "Start", "Finish", "% Complete", "Predecessors"],
    ["1", "Mobilize", "5 days", "Mon 3/2/26", "Fri 3/6/26", "100%", ""],
    ["2", "Underground", "10 days", "Mon 3/9/26", "Fri 3/20/26", "50%", "1"],
    ["3", "Energize", "0 days", "Mon 3/23/26", "Mon 3/23/26", "0%", "2FS+2 days"],
]

SMARTSHEET_EXPORT = [
    ["Row ID", "Primary Column", "Start Date", "End Date", "Duration",
     "% Complete", "Predecessors", "Assigned To"],
    ["1", "Design", "2026-03-02", "2026-03-06", "5d", "1", "", "AH"],
    ["2", "Build", "2026-03-09", "2026-03-20", "10d", "0.5", "1FS", "DW"],
]


def test_a_project_style_csv_imports_with_its_dependencies():
    out = schedule.parse_any("schedule.csv", csv_bytes(PROJECT_EXPORT))
    assert out["source"] == "csv"
    t = out["tasks"]
    assert [x["name"] for x in t] == ["Mobilize", "Underground", "Energize"]
    assert t[0]["start"] == "2026-03-02" and t[0]["finish"] == "2026-03-06"
    assert t[0]["duration_days"] == 5 and t[0]["percent_complete"] == 100
    assert t[2]["is_milestone"] == 1                    # 0 days
    assert t[2]["predecessors"] == "2FS+2 days"

    schedule.import_tasks(JOB, t, "csv")
    links = schedule.list_links(JOB)
    assert len(links) == 2
    lagged = next(l for l in links if l["lag_days"])
    assert lagged["lag_days"] == 2 and lagged["link_type"] == "FS"


def test_smartsheet_column_names_are_recognised():
    out = schedule.parse_any("sheet.csv", csv_bytes(SMARTSHEET_EXPORT))
    t = out["tasks"]
    assert [x["name"] for x in t] == ["Design", "Build"]
    assert t[0]["start"] == "2026-03-02" and t[1]["finish"] == "2026-03-20"
    # "Assigned To" has nowhere to go yet — say so rather than dropping it mutely.
    assert any("Assigned To" in w for w in out["warnings"])


def test_a_title_row_above_the_header_does_not_become_the_columns():
    rows = [["Project: Siemens Wendell", "", "", ""], [], *PROJECT_EXPORT]
    out = schedule.parse_any("schedule.csv", csv_bytes(rows))
    assert len(out["tasks"]) == 3


def test_a_percentage_stored_as_a_fraction_is_scaled():
    out = schedule.parse_any("sheet.csv", csv_bytes(SMARTSHEET_EXPORT))
    assert out["tasks"][0]["percent_complete"] == 1        # text "1" stays 1%


def test_an_unreadable_date_is_left_empty_and_reported():
    rows = [PROJECT_EXPORT[0],
            ["1", "Mobilize", "5 days", "sometime next spring", "Fri 3/6/26", "0%", ""]]
    out = schedule.parse_any("schedule.csv", csv_bytes(rows))
    assert out["tasks"][0]["start"] is None               # never guessed
    assert any("could not be read" in w for w in out["warnings"])


def test_a_file_with_no_recognisable_columns_is_refused_with_a_reason():
    with pytest.raises(schedule.ScheduleError, match="No schedule columns"):
        schedule.parse_any("notes.csv", csv_bytes([["alpha", "beta"], ["1", "2"]]))


def test_elapsed_durations_keep_their_unit():
    rows = [PROJECT_EXPORT[0],
            ["1", "Panel delivery", "60 edays", "Mon 3/2/26", "Fri 5/1/26", "0%", ""]]
    out = schedule.parse_any("s.csv", csv_bytes(rows))
    # 60 elapsed days is not 60 working days; the unit rides along so the
    # difference can never be silently lost.
    assert out["tasks"][0]["duration_unit"] == "ed"
    assert out["tasks"][0]["duration_days"] == 60


def test_an_xlsx_export_reads_the_same_as_a_csv():
    import openpyxl
    wb = openpyxl.Workbook()
    for r in PROJECT_EXPORT:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    out = schedule.parse_any("schedule.xlsx", buf.getvalue())
    assert out["source"] == "xlsx"
    assert [x["name"] for x in out["tasks"]] == ["Mobilize", "Underground", "Energize"]


def test_header_mapping_handles_synonyms_and_reports_leftovers():
    mapping, leftover = schedule_tab.map_headers(
        ["Task ID", "Title", "Begin", "Due Date", "Progress", "Cost"])
    assert mapping["name"] == 1 and mapping["start"] == 2
    assert mapping["finish"] == 3 and mapping["percent_complete"] == 4
    assert leftover == ["Cost"]


# --- staging ------------------------------------------------------------------

def test_a_clean_import_applies_immediately_but_a_staged_one_waits():
    """Nothing to decide -> no ceremony. Something to decide -> it waits."""
    staged = schedule.stage_import(JOB, "schedule.csv", csv_bytes(PROJECT_EXPORT))
    assert staged["counts"]["tasks"] == 3
    assert schedule.list_tasks(JOB) == []            # staging touches nothing

    schedule.commit_import(staged["id"], mode="replace")
    assert len(schedule.list_tasks(JOB)) == 3


def test_discarding_leaves_the_schedule_untouched():
    staged = schedule.stage_import(JOB, "schedule.csv", csv_bytes(PROJECT_EXPORT))
    assert schedule.discard_import(staged["id"]) is True
    assert schedule.list_tasks(JOB) == []
    with pytest.raises(schedule.ScheduleError, match="already discarded"):
        schedule.commit_import(staged["id"])


def test_an_import_cannot_be_committed_twice():
    staged = schedule.stage_import(JOB, "schedule.csv", csv_bytes(PROJECT_EXPORT))
    schedule.commit_import(staged["id"])
    with pytest.raises(schedule.ScheduleError, match="already committed"):
        schedule.commit_import(staged["id"])


def test_only_accepted_links_are_written():
    """The heart of it: a proposal is not a dependency until somebody says so."""
    payload = {
        "tasks": [
            {"external_id": "1", "name": "A", "start": "2026-03-02",
             "finish": "2026-03-06", "duration_days": 5, "sort_order": 0},
            {"external_id": "2", "name": "B", "start": "2026-03-02",
             "finish": "2026-03-06", "duration_days": 5, "sort_order": 1},
            {"external_id": "3", "name": "C", "start": "2026-03-02",
             "finish": "2026-03-06", "duration_days": 5, "sort_order": 2},
        ],
        "links": [
            {"pred_external_id": "1", "succ_external_id": "2", "link_type": "FS",
             "lag_days": 0, "inferred": True, "confidence": 0.9},
            {"pred_external_id": "2", "succ_external_id": "3", "link_type": "FS",
             "lag_days": 0, "inferred": True, "confidence": 0.3},
        ],
        "warnings": [],
    }
    conn = db.connect()
    rec_id = db.new_id()
    conn.execute("INSERT INTO schedule_imports (id, job_number, filename, source, "
                 "payload, status, created_at) VALUES (?,?,?,?,?,?,?)",
                 (rec_id, JOB, "x.pdf", "pdf", json.dumps(payload), "staged", db.now()))
    conn.commit()

    res = schedule.commit_import(rec_id, accepted_link_ids=["1>2"])
    assert res["links_accepted"] == 1 and res["links_rejected"] == 1
    links = schedule.list_links(JOB)
    assert len(links) == 1
    assert links[0]["inferred"] == 1 and links[0]["confidence"] == 0.9
    # Accepted means confirmed: provenance is kept, but it is real now.
    assert links[0]["confirmed_at"]


def test_rejecting_every_link_still_imports_the_tasks():
    staged = schedule.stage_import(JOB, "schedule.csv", csv_bytes(PROJECT_EXPORT))
    schedule.commit_import(staged["id"], accepted_link_ids=[])
    assert len(schedule.list_tasks(JOB)) == 3


# --- the real thing -----------------------------------------------------------

@pytest.mark.skipif(not SIEMENS.exists(), reason="customer schedule not on this machine")
def test_the_siemens_printed_schedule_imports_faithfully():
    """Against the actual customer PDF: a flattened MS Project print.

    Asserted against what the document visibly says, so a regression in row
    clustering or column assignment fails here rather than in front of a PM.
    """
    out = schedule.parse_any(SIEMENS.name, SIEMENS.read_bytes())
    tasks = out["tasks"]
    assert out["source"] == "pdf"

    # Every printed row, and not one more. The printed view is outline-filtered,
    # so the ids run to 393 while only 106 rows are actually on the paper.
    assert len(tasks) == 106
    assert all(t["name"] and t["external_id"] for t in tasks)
    assert all(t["start"] and t["finish"] for t in tasks)

    by_id = {t["external_id"]: t for t in tasks}

    top = by_id["0"]
    assert top["name"].startswith("2024-10-15 S RE - US, Wendell-NC")
    assert (top["start"], top["finish"]) == ("2022-12-06", "2027-02-17")
    assert top["duration_days"] == 1067 and top["percent_complete"] == 44

    supply = by_id["296"]
    assert supply["name"] == "FIM01 Equipment Supply"
    assert supply["wbs"] == "70.101.050"
    assert (supply["start"], supply["finish"]) == ("2024-07-17", "2026-01-12")
    assert supply["duration_days"] == 375 and supply["percent_complete"] == 28
    assert supply["outline_level"] == 3

    # A row printed with no WBS still lands at the right depth, from its indent.
    hanwha = by_id["302"]
    assert hanwha["name"] == "Hanwha Panels SRE"
    assert hanwha["wbs"] is None
    assert hanwha["outline_level"] >= 4
    assert hanwha["duration_days"] == 25        # "5 wks" -> 25 working days
    assert hanwha["duration_unit"] == "w"

    # Zero-duration rows are milestones, and they are not summaries.
    started = by_id["295"]
    assert started["duration_days"] == 0 and started["is_milestone"] == 1
    assert started["is_summary"] == 0
    assert sum(t["is_milestone"] for t in tasks) == 25

    # Deepest WBS seen on the sheet is four levels (70.101.050.010).
    assert max(t["outline_level"] for t in tasks) >= 4

    # Dependencies exist only where an arrow was actually drawn, and each one
    # arrives as a proposal rather than a fact.
    assert all(l["inferred"] and 0 < l["confidence"] <= 1 for l in out["links"])
    assert len(out["links"]) < len(tasks)       # nothing like a link per row
    ids = {t["external_id"] for t in tasks}
    assert all(l["pred_external_id"] in ids and l["succ_external_id"] in ids
               for l in out["links"])
    assert any("different pages" in w for w in out["warnings"])


@pytest.mark.skipif(not SIEMENS.exists(), reason="customer schedule not on this machine")
def test_the_siemens_schedule_survives_staging_and_scheduling():
    staged = schedule.stage_import(JOB, SIEMENS.name, SIEMENS.read_bytes(),
                                   actor="Ross Hixon")
    assert staged["counts"]["tasks"] == 106
    assert staged["counts"]["inferred_links"] == len(staged["links"])

    accept = [l["id"] for l in staged["links"] if l["confidence"] >= 0.45]
    schedule.commit_import(staged["id"], mode="replace",
                           accepted_link_ids=accept, actor="Ross Hixon")

    out = schedule.analyze(JOB)
    assert len(out["tasks"]) == 106
    assert len(out["links"]) == len(accept)
    assert out["project_start"] == "2022-12-06"
    assert out["project_finish"] == "2027-02-17"
    # With almost no links, every stored date must survive the schedule pass —
    # this is the floor rule doing its job on a real 106-row import.
    for t in out["tasks"]:
        if t["start"] and not t["is_summary"]:
            assert t["early_start"] >= out["project_start"]
    kept = {t["external_id"]: t["start"] for t in schedule.list_tasks(JOB)}
    assert kept["296"] == "2024-07-17"
