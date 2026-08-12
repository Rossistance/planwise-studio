"""The scheduling engine: typed links, lags, working time, float.

The property under test throughout is that the network only ever pushes work
LATER. An imported schedule carries dates that no dependency in the file
explains — procurement holds, weather, constraints someone applied in Project
years ago — and a schedule imported from a printed PDF has no links at all
until a human confirms them. If a recompute is allowed to pull tasks earlier,
all 392 rows of a real schedule collapse onto the project start date and the
tool has invented a plan nobody agreed to.
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


JOB = "24-003"


def build(*rows):
    """rows: (ext, name, start, finish, duration) — all Mondays-friendly."""
    schedule.import_tasks(JOB, [
        {"external_id": e, "name": n, "start": s, "finish": f,
         "duration_days": d, "sort_order": i}
        for i, (e, n, s, f, d) in enumerate(rows)], source="test")
    return {t["external_id"]: t["id"] for t in schedule.list_tasks(JOB)}


def link(ids, pred, succ, ltype="FS", lag=0.0):
    schedule.add_link(JOB, ids[pred], ids[succ], link_type=ltype, lag_days=lag,
                      source="test")


def es(out, name):
    return next(t["early_start"] for t in out["tasks"] if t["name"] == name)


def ef(out, name):
    return next(t["early_finish"] for t in out["tasks"] if t["name"] == name)


# --- link types ---------------------------------------------------------------
# A and B both 5 working days, both stored starting Mon 2 Mar 2026, so the
# only thing that moves B is the link.

def two_tasks():
    return build(("1", "A", "2026-03-02", "2026-03-06", 5),
                 ("2", "B", "2026-03-02", "2026-03-06", 5))


def test_finish_to_start_puts_the_successor_after_the_predecessor():
    ids = two_tasks()
    link(ids, "1", "2")
    assert es(schedule.analyze(JOB), "B") == "2026-03-09"


def test_start_to_start_lines_the_starts_up():
    ids = two_tasks()
    link(ids, "1", "2", "SS")
    # A starts on the 2nd, so SS puts B no earlier than the 2nd — which is
    # already its stored start, so it does not move.
    assert es(schedule.analyze(JOB), "B") == "2026-03-02"


def test_start_to_start_with_lag_offsets_the_successor():
    ids = two_tasks()
    link(ids, "1", "2", "SS", 2)
    assert es(schedule.analyze(JOB), "B") == "2026-03-04"


def test_finish_to_finish_aligns_the_finishes():
    ids = two_tasks()
    link(ids, "1", "2", "FF")
    out = schedule.analyze(JOB)
    # Both are 5 days; FF means B can't finish before A does, and they are the
    # same length, so B lands on A's dates rather than being pushed past them.
    assert ef(out, "B") == ef(out, "A")


def test_finish_to_finish_with_a_longer_successor_pulls_nothing_earlier():
    ids = build(("1", "A", "2026-03-02", "2026-03-06", 5),
                ("2", "B", "2026-03-02", "2026-03-13", 10))
    link(ids, "1", "2", "FF")
    # B is longer and would have to START before the project to finish with A.
    # The floor forbids that: it stays where the source put it.
    assert es(schedule.analyze(JOB), "B") == "2026-03-02"


def test_start_to_finish_is_honoured():
    ids = build(("1", "A", "2026-03-16", "2026-03-20", 5),
                ("2", "B", "2026-03-02", "2026-03-06", 5))
    link(ids, "1", "2", "SF")
    out = schedule.analyze(JOB)
    # B must finish before A starts. A starts Mon 16 Mar, so B's last working
    # day is Fri 13 Mar — finish dates are inclusive (the last day worked),
    # which is how Project and Smartsheet both show them.
    assert ef(out, "B") == "2026-03-13"
    assert es(out, "B") == "2026-03-09"


def test_lag_pushes_the_successor_out():
    ids = two_tasks()
    link(ids, "1", "2", "FS", 3)
    assert es(schedule.analyze(JOB), "B") == "2026-03-12"


def test_a_lead_shortens_the_push_but_the_floor_still_holds():
    ids = two_tasks()
    link(ids, "1", "2", "FS", -3)
    # A ends after 5 days; a 3-day lead pulls B back to 2 days after the start
    # — still later than its own stored date, so that is where it lands.
    assert es(schedule.analyze(JOB), "B") == "2026-03-04"

    schedule.delete_link(JOB, schedule.list_links(JOB)[0]["id"])
    link(ids, "1", "2", "FS", -10)
    # A lead big enough to place B before its stored start is clamped: the
    # source's date is a floor, not a suggestion.
    assert es(schedule.analyze(JOB), "B") == "2026-03-02"


# --- the floor ----------------------------------------------------------------

def test_a_schedule_with_no_links_keeps_every_stored_date():
    """The PDF-import case: 392 tasks, no confirmed dependencies. Nothing may
    move, and nothing may stack up on the project start."""
    build(("1", "A", "2026-03-02", "2026-03-06", 5),
          ("2", "B", "2026-06-01", "2026-06-05", 5),
          ("3", "C", "2026-09-07", "2026-09-11", 5))
    out = schedule.analyze(JOB)
    assert es(out, "A") == "2026-03-02"
    assert es(out, "B") == "2026-06-01"
    assert es(out, "C") == "2026-09-07"


def test_a_link_can_push_a_task_later_but_never_earlier():
    ids = build(("1", "A", "2026-03-02", "2026-03-27", 20),
                ("2", "B", "2026-03-09", "2026-03-13", 5))
    link(ids, "1", "2")
    # A runs 20 days, so B is pushed well past its stored start of the 9th.
    assert es(schedule.analyze(JOB), "B") == "2026-03-30"


# --- working time -------------------------------------------------------------

def test_the_default_calendar_skips_weekends():
    build(("1", "A", "2026-03-06", "2026-03-06", 1),      # a Friday
          ("2", "B", "2026-03-06", "2026-03-06", 1))
    ids = {t["external_id"]: t["id"] for t in schedule.list_tasks(JOB)}
    link(ids, "1", "2")
    assert es(schedule.analyze(JOB), "B") == "2026-03-09"   # Monday, not Saturday


def test_a_six_day_week_shortens_the_chain():
    ids = two_tasks()
    link(ids, "1", "2")
    assert es(schedule.analyze(JOB), "B") == "2026-03-09"
    schedule.set_calendar(JOB, workdays="1111110")          # Saturdays worked
    assert es(schedule.analyze(JOB), "B") == "2026-03-07"


def test_holidays_push_work_out():
    ids = two_tasks()
    link(ids, "1", "2")
    schedule.set_calendar(JOB, holidays=["2026-03-09", "2026-03-10"])
    assert es(schedule.analyze(JOB), "B") == "2026-03-11"


def test_a_calendar_with_no_working_days_falls_back_rather_than_hanging():
    cal = schedule.Calendar("0000000")
    assert cal.workdays == schedule.DEFAULT_WORKDAYS


def test_the_calendar_round_trips():
    schedule.set_calendar(JOB, workdays="1111100", holidays=["2026-07-03"])
    out = schedule.analyze(JOB)
    assert out["calendar"] == {"workdays": "1111100", "holidays": ["2026-07-03"]}


# --- float --------------------------------------------------------------------

def test_total_and_free_float_differ_where_a_chain_converges():
    ids = build(("1", "Start", "2026-03-02", "2026-03-06", 5),
                ("2", "Long", "2026-03-09", "2026-03-20", 10),
                ("3", "Short", "2026-03-09", "2026-03-13", 5),
                ("4", "End", "2026-03-23", "2026-03-27", 5))
    for p, s in (("1", "2"), ("1", "3"), ("2", "4"), ("3", "4")):
        link(ids, p, s)
    out = schedule.analyze(JOB)
    by = {t["name"]: t for t in out["tasks"]}
    # The long leg is critical; the short leg has a week of slack either way.
    assert by["Long"]["total_float"] == 0
    assert by["Long"]["is_critical"] == 1
    assert by["Short"]["total_float"] == pytest.approx(5)
    assert by["Short"]["free_float"] == pytest.approx(5)
    assert out["critical_count"] == 3


def test_free_float_is_zero_when_a_successor_starts_immediately():
    ids = two_tasks()
    link(ids, "1", "2")
    out = schedule.analyze(JOB)
    assert next(t["free_float"] for t in out["tasks"] if t["name"] == "A") == 0


# --- robustness ---------------------------------------------------------------

def test_a_cycle_does_not_hang_the_engine():
    ids = two_tasks()
    link(ids, "1", "2")
    link(ids, "2", "1")
    out = schedule.analyze(JOB)          # bounded relaxation, no exception
    assert len(out["tasks"]) == 2


def test_a_task_cannot_depend_on_itself():
    ids = two_tasks()
    assert schedule.add_link(JOB, ids["1"], ids["1"]) is None


def test_the_same_link_is_never_stored_twice():
    ids = two_tasks()
    assert schedule.add_link(JOB, ids["1"], ids["2"], source="test") is not None
    assert schedule.add_link(JOB, ids["1"], ids["2"], source="test") is None
    assert len(schedule.list_links(JOB)) == 1


def test_deleting_a_task_takes_its_links_with_it():
    ids = two_tasks()
    link(ids, "1", "2")
    assert len(schedule.list_links(JOB)) == 1
    schedule.delete_task(JOB, ids["1"])
    assert schedule.list_links(JOB) == []          # ON DELETE CASCADE


def test_summary_rows_stay_out_of_the_network():
    schedule.import_tasks(JOB, [
        {"external_id": "1", "name": "Phase", "start": "2026-03-02",
         "finish": "2026-03-27", "duration_days": 20, "is_summary": 1, "sort_order": 0},
        {"external_id": "2", "name": "Work", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 1},
    ], source="test")
    out = schedule.analyze(JOB)
    phase = next(t for t in out["tasks"] if t["name"] == "Phase")
    assert phase["total_float"] is None and phase["is_critical"] == 0


def test_an_invalid_link_type_is_refused():
    ids = two_tasks()
    with pytest.raises(schedule.ScheduleError, match="Link type"):
        schedule.add_link(JOB, ids["1"], ids["2"], link_type="XY")


# --- text predecessors are an input format, not a second source of truth ------

def test_predecessor_text_becomes_real_links():
    schedule.import_tasks(JOB, [
        {"external_id": "1", "name": "A", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 0},
        {"external_id": "2", "name": "B", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 1,
         "predecessors": "1SS+2d"},
    ], source="test")
    links = schedule.list_links(JOB)
    assert len(links) == 1
    assert links[0]["link_type"] == "SS" and links[0]["lag_days"] == 2


def test_re_importing_drops_dependencies_the_new_file_removed():
    rows = [{"external_id": "1", "name": "A", "start": "2026-03-02",
             "finish": "2026-03-06", "duration_days": 5, "sort_order": 0},
            {"external_id": "2", "name": "B", "start": "2026-03-02",
             "finish": "2026-03-06", "duration_days": 5, "sort_order": 1,
             "predecessors": "1"}]
    schedule.import_tasks(JOB, rows, source="test")
    assert len(schedule.list_links(JOB)) == 1

    rows[1]["predecessors"] = None
    schedule.import_tasks(JOB, rows, source="test")
    assert schedule.list_links(JOB) == []


def test_a_hand_drawn_link_survives_a_re_import():
    ids = build(("1", "A", "2026-03-02", "2026-03-06", 5),
                ("2", "B", "2026-03-02", "2026-03-06", 5))
    schedule.add_link(JOB, ids["1"], ids["2"], source="manual")
    schedule.import_tasks(JOB, [
        {"external_id": "1", "name": "A", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 0},
        {"external_id": "2", "name": "B", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 1},
    ], source="test")
    assert len(schedule.list_links(JOB)) == 1


def test_a_manual_task_can_finally_be_a_predecessor():
    """Hand-added rows have no external_id, so they could never be referenced.
    They can now be named instead."""
    schedule.add_task(JOB, {"name": "Punch walk", "start": "2026-03-02",
                            "finish": "2026-03-06", "duration_days": 5})
    schedule.add_task(JOB, {"name": "Closeout", "start": "2026-03-02",
                            "finish": "2026-03-06", "duration_days": 5,
                            "predecessors": "Punch walk"})
    assert len(schedule.list_links(JOB)) == 1
    assert es(schedule.analyze(JOB), "Closeout") == "2026-03-09"
