"""Predecessor and duration parsing — the two places a schedule silently loses data.

Both of these were real defects. A dropped predecessor doesn't look like an
error; it looks like a task with no dependencies, which reschedules wrongly and
quietly. Same for a milestone whose duration reads as "missing" rather than
zero: it acquires a length of one day from the fallback and pushes everything
downstream of it a day late.
"""
from __future__ import annotations

import pytest

from backend import db, schedule


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


# --- durations ----------------------------------------------------------------

def test_a_zero_duration_is_zero_not_missing():
    """A milestone is 'PT0H'. Reporting that as None sent it down the
    start/finish fallback, which gives a milestone a length of one day."""
    assert schedule._duration_days("PT0H0M0S") == 0.0
    assert schedule._duration_days("P0D") == 0.0
    # Genuinely absent stays absent — that distinction is the whole point.
    assert schedule._duration_days(None) is None
    assert schedule._duration_days("") is None
    assert schedule._duration_days("garbage") is None


def test_durations_convert_on_an_eight_hour_day():
    assert schedule._duration_days("PT80H0M0S") == 10.0
    assert schedule._duration_days("P5D") == 5.0
    assert schedule._duration_days("PT4H0M0S") == 0.5


def test_a_milestone_keeps_its_zero_duration_through_import():
    from tests.test_schedule import mspdi, task
    data = mspdi(task(1, "Handover", "2026-03-02", "2026-03-02", hours=0, ms=1))
    tasks = schedule.parse_mspdi(data)
    assert tasks[0]["duration_days"] == 0.0
    assert tasks[0]["is_milestone"] == 1


# --- predecessors -------------------------------------------------------------

def preds(raw):
    return schedule._parse_preds(raw)


def test_a_plain_id_is_finish_to_start_with_no_lag():
    assert preds("12") == [("12", "FS", 0.0)]
    assert preds("12,13") == [("12", "FS", 0.0), ("13", "FS", 0.0)]
    assert preds("12; 13") == [("12", "FS", 0.0), ("13", "FS", 0.0)]
    assert preds("") == []
    assert preds(None) == []


def test_link_types_survive_instead_of_being_swallowed():
    """'12SS+2d' used to fail the pattern entirely and become a predecessor
    literally named '12SS+2d', which resolved to nothing — the dependency
    vanished without a word."""
    assert preds("12SS") == [("12", "SS", 0.0)]
    assert preds("12FF") == [("12", "FF", 0.0)]
    assert preds("12SF") == [("12", "SF", 0.0)]
    assert preds("12SS+2d") == [("12", "SS", 2.0)]
    assert preds("12FF-1 day") == [("12", "FF", -1.0)]


def test_lag_units_convert_to_working_days():
    assert preds("12FS+2 days") == [("12", "FS", 2.0)]
    assert preds("12SS-1wk") == [("12", "SS", -5.0)]
    assert preds("12FS+2 weeks") == [("12", "FS", 10.0)]
    assert preds("12FS+1 mon") == [("12", "FS", 20.0)]
    assert preds("12FS+4 hrs") == [("12", "FS", 0.5)]


def test_an_id_containing_a_hyphen_is_not_read_as_a_lag():
    """'A-100' is an ordinary activity id. The old pattern split it into id 'A'
    with a lag of -100 days, so the real predecessor was never found."""
    assert preds("A-100") == [("A-100", "FS", 0.0)]
    assert preds("A-100FS+2d") == [("A-100", "FS", 2.0)]
    assert preds("A-100SS") == [("A-100", "SS", 0.0)]
    assert preds("CIV-01,ELE-02") == [("CIV-01", "FS", 0.0), ("ELE-02", "FS", 0.0)]


def test_a_numeric_id_may_carry_a_unitless_lag():
    """Unambiguous because the id is all digits — that is what separates
    '12-2' (two days of lead) from 'A-100' (an id)."""
    assert preds("12+2") == [("12", "FS", 2.0)]
    assert preds("12-2") == [("12", "FS", -2.0)]


def test_unrecognisable_text_is_kept_as_an_id_rather_than_guessed_at():
    assert preds("what is this") == [("what is this", "FS", 0.0)]


def test_parsed_lag_still_drives_the_current_engine():
    """End to end: the parser feeds analyze(), so a lag typed in the grid moves
    the successor."""
    schedule.import_tasks("24-003", [
        {"external_id": "1", "name": "A", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 0},
        {"external_id": "2", "name": "B", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 1,
         "predecessors": "1FS+3 days"},
    ], source="test")
    out = schedule.analyze("24-003")
    b = next(t for t in out["tasks"] if t["name"] == "B")
    # A is 5 working days from Mon 2 Mar, then 3 days of lag: 8 working days
    # after the start, which is Thu 12 Mar. Without the parser fix the lag was
    # dropped and B started on the 9th.
    assert b["early_start"] == "2026-03-12"

    schedule.import_tasks("24-003", [
        {"external_id": "1", "name": "A", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 0},
        {"external_id": "2", "name": "B", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 1,
         "predecessors": "1"},
    ], source="test")
    plain = next(t for t in schedule.analyze("24-003")["tasks"] if t["name"] == "B")
    assert plain["early_start"] == "2026-03-09"          # no lag, for contrast
