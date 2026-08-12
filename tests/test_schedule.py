"""Schedule import, CPM, and the two-week look ahead."""
from __future__ import annotations

import pytest

from backend import db, lookahead, schedule


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def mspdi(tasks_xml: str) -> bytes:
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Project xmlns="http://schemas.microsoft.com/project">'
            f'<Tasks>{tasks_xml}</Tasks></Project>').encode()


TASK_TPL = """
<Task><UID>{uid}</UID><Name>{name}</Name><Start>{start}T08:00:00</Start>
<Finish>{finish}T17:00:00</Finish><Duration>PT{hours}H0M0S</Duration>
<PercentComplete>{pct}</PercentComplete><OutlineLevel>{lvl}</OutlineLevel>
<Milestone>{ms}</Milestone><Summary>{summ}</Summary>{preds}</Task>"""


def task(uid, name, start, finish, hours=40, pct=0, lvl=1, ms=0, summ=0, preds=()):
    links = "".join(f"<PredecessorLink><PredecessorUID>{p}</PredecessorUID>"
                    f"</PredecessorLink>" for p in preds)
    return TASK_TPL.format(uid=uid, name=name, start=start, finish=finish, hours=hours,
                           pct=pct, lvl=lvl, ms=ms, summ=summ, preds=links)


# --- MSPDI parsing ------------------------------------------------------------

def test_parses_mspdi_tasks_dates_durations_and_links():
    data = mspdi(
        task(0, "Project Summary", "2026-08-10", "2026-09-04", summ=1)
        + task(1, "Mobilize", "2026-08-10", "2026-08-14")
        + task(2, "Underground", "2026-08-17", "2026-08-28", hours=80, pct=25, preds=[1])
        + task(3, "Energize", "2026-08-31", "2026-08-31", hours=0, ms=1, preds=[2]))
    tasks = schedule.parse_mspdi(data)

    assert [t["name"] for t in tasks] == ["Mobilize", "Underground", "Energize"]  # UID 0 dropped
    t2 = tasks[1]
    assert (t2["start"], t2["finish"]) == ("2026-08-17", "2026-08-28")
    assert t2["duration_days"] == 10          # 80h / 8h day
    assert t2["percent_complete"] == 25
    assert t2["predecessors"] == "1"
    assert tasks[2]["is_milestone"] == 1


def test_mspdi_rejects_non_project_xml_and_garbage():
    with pytest.raises(schedule.ScheduleError, match="not valid XML|Not valid XML"):
        schedule.parse_mspdi(b"<<< not xml")
    with pytest.raises(schedule.ScheduleError, match="does not look like"):
        schedule.parse_mspdi(b'<?xml version="1.0"?><Other><Nope/></Other>')


def test_file_routing_by_extension_and_content():
    data = mspdi(task(1, "A", "2026-08-10", "2026-08-14"))
    _, source = schedule.parse_schedule("plan.xml", data)
    assert source == "mspdi"
    _, source = schedule.parse_schedule("no-extension", data)   # sniffed
    assert source == "mspdi"
    with pytest.raises(schedule.ScheduleError, match="Unsupported"):
        schedule.parse_schedule("notes.txt", b"just text")


def test_mpp_without_a_jvm_fails_with_guidance():
    """This machine has no JRE (probed 2026-08-08). The failure must tell the
    user what to do — export XML — not just error out."""
    ok, detail = schedule.mpp_available()
    if ok:
        pytest.skip("a JVM is present on this machine")
    with pytest.raises(schedule.ScheduleError, match="XML"):
        schedule.parse_mpp(b"\xd0\xcf\x11\xe0fake mpp")


# --- import modes -------------------------------------------------------------

def test_replace_and_merge_modes():
    v1 = schedule.parse_mspdi(mspdi(
        task(1, "Mobilize", "2026-08-10", "2026-08-14")
        + task(2, "Underground", "2026-08-17", "2026-08-28", preds=[1])))
    assert schedule.import_tasks("24-003", v1, "mspdi")["added"] == 2

    schedule.add_task("24-003", {"name": "PM-added punch walk", "start": "2026-09-01",
                                 "finish": "2026-09-02"})

    # merge: updates known tasks, leaves the hand-added one alone
    v2 = schedule.parse_mspdi(mspdi(
        task(1, "Mobilize (revised)", "2026-08-11", "2026-08-15")
        + task(2, "Underground", "2026-08-18", "2026-08-29", preds=[1])
        + task(3, "Energize", "2026-09-04", "2026-09-04", ms=1)))
    res = schedule.import_tasks("24-003", v2, "mspdi", mode="merge")
    assert (res["added"], res["updated"]) == (1, 2)

    names = [t["name"] for t in schedule.list_tasks("24-003")]
    assert "Mobilize (revised)" in names
    assert "PM-added punch walk" in names       # survives a re-import
    assert len(names) == 4

    # Replace reconciles rather than wiping. It used to DELETE every row for
    # the job, which threw away the ids the look ahead points at
    # (lookahead_items.task_id) and now the ids dependencies hang off — a
    # re-import silently orphaned every seeded look-ahead item. So: imported
    # rows the file still knows about are updated in place, imported rows it
    # has dropped are removed, and the PM's hand-added row survives, which is
    # the promise that made two modes worth having.
    ids_before = {t["external_id"]: t["id"] for t in schedule.list_tasks("24-003")
                  if t["external_id"]}
    res = schedule.import_tasks("24-003", v2, "mspdi", mode="replace")
    after = schedule.list_tasks("24-003")
    assert len(after) == 4
    assert "PM-added punch walk" in [t["name"] for t in after]
    assert res["removed"] == 0                      # nothing was dropped by v2
    assert {t["external_id"]: t["id"] for t in after if t["external_id"]} == ids_before

    # A file that drops a task removes exactly that task, and only because it
    # came from a file in the first place.
    v3 = schedule.parse_mspdi(mspdi(task(1, "Mobilize (revised)", "2026-08-11", "2026-08-15")))
    res = schedule.import_tasks("24-003", v3, "mspdi", mode="replace")
    assert res["removed"] == 2
    names = [t["name"] for t in schedule.list_tasks("24-003")]
    assert names == ["Mobilize (revised)", "PM-added punch walk"]

    with pytest.raises(schedule.ScheduleError, match="mode"):
        schedule.import_tasks("24-003", v2, "mspdi", mode="sideways")


# --- CPM ----------------------------------------------------------------------

def test_critical_path_float_and_project_span():
    """Two chains from one start: the long one is critical, the short one
    carries float equal to the difference."""
    data = mspdi(
        task(1, "Start", "2026-08-10", "2026-08-14", hours=40)
        + task(2, "Long chain", "2026-08-17", "2026-08-28", hours=80, preds=[1])
        + task(3, "Short chain", "2026-08-17", "2026-08-21", hours=40, preds=[1])
        + task(4, "Finish", "2026-08-31", "2026-09-04", hours=40, preds=[2, 3]))
    schedule.import_tasks("24-003", schedule.parse_mspdi(data), "mspdi")
    result = schedule.analyze("24-003")
    by_name = {t["name"]: t for t in result["tasks"]}

    assert by_name["Start"]["is_critical"] == 1
    assert by_name["Long chain"]["is_critical"] == 1
    assert by_name["Finish"]["is_critical"] == 1
    assert by_name["Short chain"]["is_critical"] == 0
    assert by_name["Short chain"]["total_float"] == pytest.approx(5)   # 10d - 5d
    assert result["critical_count"] == 3
    assert result["project_start"] == "2026-08-10"


def test_summary_rows_are_excluded_from_the_network():
    data = mspdi(task(1, "Phase 1", "2026-08-10", "2026-08-28", summ=1, hours=120)
                 + task(2, "Work", "2026-08-10", "2026-08-14", hours=40))
    schedule.import_tasks("24-003", schedule.parse_mspdi(data), "mspdi")
    by_name = {t["name"]: t for t in schedule.analyze("24-003")["tasks"]}
    assert by_name["Phase 1"]["total_float"] is None      # roll-up, not work
    assert by_name["Work"]["is_critical"] == 1


def test_analyze_handles_a_dependency_cycle_without_hanging():
    data = mspdi(task(1, "A", "2026-08-10", "2026-08-14", preds=[2])
                 + task(2, "B", "2026-08-17", "2026-08-21", preds=[1]))
    schedule.import_tasks("24-003", schedule.parse_mspdi(data), "mspdi")
    assert len(schedule.analyze("24-003")["tasks"]) == 2   # degrades, doesn't raise


def test_empty_schedule_analyzes_to_nothing():
    assert schedule.analyze("no-such-job")["tasks"] == []


# --- look ahead ---------------------------------------------------------------

def seed_schedule():
    data = mspdi(
        task(1, "Mobilize", "2026-08-10", "2026-08-14", pct=100)
        + task(2, "Underground", "2026-08-17", "2026-08-28", pct=40)
        + task(3, "Way later", "2026-11-02", "2026-11-06")
        + task(4, "Phase", "2026-08-10", "2026-08-28", summ=1))
    schedule.import_tasks("24-003", schedule.parse_mspdi(data), "mspdi")


SUNDAY = "2026-08-09"          # the field sheet runs Sun -> Sat


def test_week_starts_on_sunday_like_the_field_sheet():
    from datetime import date
    assert lookahead._week_start(date(2026, 8, 9)) == date(2026, 8, 9)    # Sun -> itself
    assert lookahead._week_start(date(2026, 8, 12)) == date(2026, 8, 9)   # Wed -> that Sun
    assert lookahead._week_start(date(2026, 8, 15)) == date(2026, 8, 9)   # Sat -> that Sun
    assert lookahead._week_start(date(2026, 8, 16)) == date(2026, 8, 16)  # next Sun


def test_day_headers_span_the_chosen_weeks_and_flag_weekends():
    days = lookahead.day_headers(SUNDAY)
    assert len(days) == 14                       # two weeks by default
    assert (days[0]["dow"], days[0]["day"], days[0]["weekend"]) == ("Sun", 9, True)
    assert (days[1]["dow"], days[1]["weekend"]) == ("Mon", False)
    assert (days[6]["dow"], days[6]["weekend"]) == ("Sat", True)
    assert days[13]["date"] == "2026-08-22"
    assert [d["index"] for d in days if d["weekend"]] == [0, 6, 7, 13]

    three = lookahead.day_headers(SUNDAY, 3)
    assert len(three) == 21
    assert three[20]["date"] == "2026-08-29"
    assert [d["index"] for d in three if d["weekend"]] == [0, 6, 7, 13, 14, 20]
    assert lookahead.day_headers(SUNDAY, 9) == three      # clamped to three


def test_normalize_days_always_stores_the_full_three_weeks():
    """21 wide whatever the sheet shows, so switching 3 -> 2 -> 3 weeks never
    loses week three."""
    assert lookahead.normalize_days(None) == "0" * 21
    assert lookahead.normalize_days("11") == "11" + "0" * 19          # padded
    assert lookahead.normalize_days("1" * 30) == "1" * 21             # clipped
    assert lookahead.normalize_days([True, False, True]) == "101" + "0" * 18


def test_seed_ticks_the_days_a_task_actually_spans():
    seed_schedule()
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    res = lookahead.seed_from_schedule(period["id"])
    assert res["seeded"] == 2                # not the November task, not the summary

    items = lookahead.list_items(period["id"])
    assert [i["description"] for i in items] == ["Mobilize", "Underground"]
    assert [i["status"] for i in items] == ["Complete", "In Progress"]

    # Seeding fills the full three weeks (Sun 8/9 .. Sat 8/29) even though the
    # sheet shows two, so switching to 3 weeks reveals real data, not blanks.
    # Mobilize runs Mon 8/10 - Fri 8/14: index 0 (Sunday) off, week one on.
    assert items[0]["days"] == "01111100000000" + "0" * 7
    # Underground runs 8/17 - 8/28: both work weeks ticked, weekends skipped.
    assert items[1]["days"] == "00000000" + "11111" + "00" + "11111" + "0"


def test_seeding_never_ticks_a_weekend():
    data = mspdi(task(1, "Straight through", "2026-08-09", "2026-08-22"))
    schedule.import_tasks("24-003", schedule.parse_mspdi(data), "mspdi")
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.seed_from_schedule(period["id"])
    days = lookahead.list_items(period["id"])[0]["days"]
    assert days == "01111100111110" + "0" * 7
    assert [i for i, c in enumerate(days) if c == "1"] == [1, 2, 3, 4, 5, 8, 9, 10, 11, 12]


def test_reseeding_is_idempotent_and_preserves_manual_work():
    seed_schedule()
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.seed_from_schedule(period["id"])
    manual = lookahead.add_item(period["id"], {"description": "Crane pick - not in schedule"})
    edited = lookahead.list_items(period["id"])[0]
    lookahead.update_item(edited["id"], {"notes": "weather permitting",
                                         "days": "1" * 21})

    again = lookahead.seed_from_schedule(period["id"])
    assert again["seeded"] == 0
    items = lookahead.list_items(period["id"])
    assert len(items) == 3
    assert any(i["id"] == manual["id"] for i in items)
    kept = next(i for i in items if i["id"] == edited["id"])
    assert kept["notes"] == "weather permitting"
    assert kept["days"] == "1" * 21      # hand edits survive re-seeding


def test_toggle_day_flips_one_column():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    item = lookahead.add_item(period["id"], {"description": "Pull wire"})
    assert item["days"] == "0" * 21

    assert lookahead.toggle_day(item["id"], 3)["days"] == "0001" + "0" * 17
    assert lookahead.toggle_day(item["id"], 3)["days"] == "0" * 21       # toggles back
    assert lookahead.toggle_day(item["id"], 5, on=True)["days"] == "000001" + "0" * 15
    assert lookahead.toggle_day(item["id"], 5, on=True)["days"] == "000001" + "0" * 15  # idempotent
    assert lookahead.toggle_day(item["id"], 5, on=False)["days"] == "0" * 21

    assert lookahead.toggle_day(item["id"], 21) is None      # out of range
    assert lookahead.toggle_day(item["id"], -1) is None
    assert lookahead.toggle_day("nope", 0) is None


def test_period_fields_are_editable():
    period = lookahead.get_or_create_period("24-003", SUNDAY, actor="Ross")
    assert period["prepared_by"] == "Ross"       # defaults to whoever opened it
    out = lookahead.update_period(period["id"], {"prepared_by": "Field Leader",
                                                 "notes": "rain expected Thu"})
    assert out["prepared_by"] == "Field Leader"
    assert out["notes"] == "rain expected Thu"
    assert lookahead.update_period(period["id"], {"bogus": "x"}) is None


def test_switching_between_two_and_three_weeks_never_loses_week_three():
    """The whole point of storing 21 days: a PM can run a rolling three-week
    plan, drop to two to look at the near term, and go back with everything
    intact."""
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    assert period.get("weeks") in (None, 2)
    assert lookahead.get_period(period["id"])["weeks"] == 2
    assert len(lookahead.get_period(period["id"])["days"]) == 14

    three = lookahead.update_period(period["id"], {"weeks": 3})
    assert three["weeks"] == 3
    assert len(three["days"]) == 21
    assert three["end_date"] == "2026-08-29"

    item = lookahead.add_item(period["id"], {"description": "Backfill"})
    lookahead.toggle_day(item["id"], 17, on=True)              # a week-three day
    assert lookahead.list_items(period["id"])[0]["days"][17] == "1"

    back = lookahead.update_period(period["id"], {"weeks": 2})
    assert (back["weeks"], len(back["days"]), back["end_date"]) == (2, 14, "2026-08-22")
    assert lookahead.list_items(period["id"])[0]["days"][17] == "1"   # still there

    assert lookahead.update_period(period["id"], {"weeks": 7})["weeks"] == 3   # clamped
    assert lookahead.update_period(period["id"], {"weeks": "junk"})["weeks"] == 2


def test_a_three_week_sheet_can_be_shared_as_two():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.update_period(period["id"], {"weeks": 3})
    lookahead.add_item(period["id"], {"description": "Backfill", "days": "1" * 21})
    full = lookahead.get_period(period["id"])

    assert lookahead.share_weeks(full, None) == 3      # defaults to what's held
    assert lookahead.share_weeks(full, 2) == 2
    assert lookahead.share_weeks(full, 9) == 3         # never more than held

    two = lookahead.share_html(period["id"], "Siemens", "24-003", weeks=2)
    assert two["subject"].startswith("Two-Week")
    assert "2026-08-22" in two["html"] and "2026-08-29" not in two["html"]
    assert two["html"].count("&#10003;") == 14

    three = lookahead.share_html(period["id"], "Siemens", "24-003")
    assert three["subject"].startswith("Three-Week")
    assert "2026-08-29" in three["html"]
    assert three["html"].count("&#10003;") == 21

    assert "Three-Week" in pdf_text(period["id"])[1]
    assert "Two-Week" in pdf_text(period["id"], weeks=2)[1]


def test_a_two_week_sheet_cannot_be_shared_as_three():
    """Otherwise the customer gets a week of blank columns."""
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.add_item(period["id"], {"description": "Pull wire", "days": "1" * 21})
    out = lookahead.share_html(period["id"], "Siemens", "24-003", weeks=3)
    assert out["subject"].startswith("Two-Week")
    assert out["html"].count("&#10003;") == 14


# --- work areas (optional colour coding) --------------------------------------

def test_each_work_area_gets_its_own_colour_and_can_be_taken_out_of_use():
    a = lookahead.add_area("24-003", "Parking Lot East", actor="Ross")
    b = lookahead.add_area("24-003", "Cable Tray Install")
    assert a["color"] != b["color"]
    assert a["color"] in lookahead.AREA_COLORS
    assert [x["name"] for x in lookahead.list_areas("24-003")] == [
        "Parking Lot East", "Cable Tray Install"]

    # "in use" is a tick, not a delete — the area stays on the job, ready to
    # tick back on, but drops out of the picker while it's off.
    lookahead.update_area(b["id"], {"active": False})
    assert [x["name"] for x in lookahead.list_areas("24-003", active_only=True)] == [
        "Parking Lot East"]
    assert [x["name"] for x in lookahead.list_areas("24-003")] == [
        "Parking Lot East", "Cable Tray Install"]

    with pytest.raises(lookahead.LookaheadError, match="name"):
        lookahead.add_area("24-003", "   ")
    assert lookahead.update_area("nope", {"name": "x"}) is None
    assert lookahead.delete_area("nope") is False


def test_taking_an_area_out_of_use_releases_the_rows_that_were_on_it():
    """Un-ticking "in use" has to reach the grid — otherwise rows keep a colour
    from an area the PM just switched off."""
    area = lookahead.add_area("24-003", "Inside West Side")
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    kept = lookahead.add_item(period["id"], {"description": "Set transformer pad",
                                             "work_area_id": area["id"]})
    assert lookahead.list_items(period["id"])[0]["work_area_id"] == area["id"]

    lookahead.update_area(area["id"], {"active": False})
    rows = lookahead.list_items(period["id"])
    assert [r["id"] for r in rows] == [kept["id"]]     # the work is untouched
    assert rows[0]["work_area_id"] is None            # it just went back to no area
    assert lookahead.list_areas("24-003", active_only=True) == []

    # ticking it back on makes it selectable again; rows stay released
    lookahead.update_area(area["id"], {"active": True})
    assert len(lookahead.list_areas("24-003", active_only=True)) == 1
    assert lookahead.list_items(period["id"])[0]["work_area_id"] is None


def test_removing_an_area_unassigns_its_rows_rather_than_deleting_them():
    area = lookahead.add_area("24-003", "Tree Cutting")
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    item = lookahead.add_item(period["id"], {"description": "Clear trees",
                                             "work_area_id": area["id"]})
    assert lookahead.list_items(period["id"])[0]["work_area_id"] == area["id"]

    assert lookahead.delete_area(area["id"]) is True
    rows = lookahead.list_items(period["id"])
    assert [r["id"] for r in rows] == [item["id"]]       # the work is still planned
    assert rows[0]["work_area_id"] is None               # it just lost its colour


def test_rows_carry_their_own_requirements_notes_tools_and_materials():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    item = lookahead.add_item(period["id"], {
        "description": "Pull wire", "requirements": "Escort to roof",
        "notes": "Two-man crew", "tools": "Trencher", "materials": "4in PVC"})
    row = lookahead.list_items(period["id"])[0]
    assert row["requirements"] == "Escort to roof"
    assert row["notes"] == "Two-man crew"
    assert (row["tools"], row["materials"]) == ("Trencher", "4in PVC")
    assert lookahead.update_item(item["id"], {"tools": "Bender"})["tools"] == "Bender"


def test_period_is_reused_per_start_date():
    a = lookahead.get_or_create_period("24-003", SUNDAY)
    b = lookahead.get_or_create_period("24-003", SUNDAY)
    c = lookahead.get_or_create_period("24-003", "2026-08-23")
    assert a["id"] == b["id"] != c["id"]
    assert lookahead.get_period(a["id"])["end_date"] == "2026-08-22"


def test_item_crud():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    item = lookahead.add_item(period["id"], {"description": "Pull wire", "status": "Planned"})
    assert lookahead.update_item(item["id"], {"status": "Blocked"})["status"] == "Blocked"
    assert lookahead.update_item(item["id"], {"bogus": "x"}) is None
    assert lookahead.delete_item(item["id"]) is True
    assert lookahead.list_items(period["id"]) == []


def populate(period_id):
    lookahead.add_item(period_id, {
        "description": "Pull <wire> & terminate", "days": "01100000000000",
        "requirements": "Escort", "notes": "west side",
        "tools": "Trencher", "materials": "PVC90s"})


def test_hand_typed_tasks_land_on_top_but_seeding_keeps_schedule_order():
    seed_schedule()
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.seed_from_schedule(period["id"])
    assert [i["description"] for i in lookahead.list_items(period["id"])] == [
        "Mobilize", "Underground"]

    lookahead.add_item(period["id"], {"description": "Crane pick"}, at_top=True)
    lookahead.add_item(period["id"], {"description": "Switchgear delivery"}, at_top=True)
    assert [i["description"] for i in lookahead.list_items(period["id"])] == [
        "Switchgear delivery", "Crane pick", "Mobilize", "Underground"]

    # re-seeding still appends below, so schedule rows stay in schedule order
    schedule.import_tasks("24-003", schedule.parse_mspdi(
        mspdi(task(9, "Backfill", "2026-08-19", "2026-08-21"))), "mspdi")
    lookahead.seed_from_schedule(period["id"])
    assert lookahead.list_items(period["id"])[-1]["description"] == "Backfill"


def test_share_html_renders_the_day_grid_and_escapes_input():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.update_period(period["id"], {"prepared_by": "Ross Hixon"})
    populate(period["id"])
    out = lookahead.share_html(period["id"], "Siemens - Wendell", "24-003")
    assert "Two-Week Look Ahead" in out["subject"]
    assert SUNDAY in out["subject"]
    assert "Pull &lt;wire&gt; &amp; terminate" in out["html"]   # escaped, not injected
    assert out["html"].count("&#10003;") == 2                   # exactly two ticked days
    assert "Prepared by Ross Hixon" in out["html"]
    assert "Sun" in out["html"] and "Sat" in out["html"]


def test_customer_html_drops_the_internal_columns_and_team_html_keeps_them():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    populate(period["id"])

    customer = lookahead.share_html(period["id"], "Siemens", "24-003", "customer")
    assert "Requirements for Customer" in customer["html"]
    assert "Operation Notes" in customer["html"] and "west side" in customer["html"]
    for leak in ("Tools Needed", "Material Needed", "Trencher", "PVC90s"):
        assert leak not in customer["html"]
    assert not customer["subject"].startswith("[Internal]")

    team = lookahead.share_html(period["id"], "Siemens", "24-003", "team")
    assert "Tools Needed" in team["html"] and "Trencher" in team["html"]
    assert "Material Needed" in team["html"] and "PVC90s" in team["html"]
    assert team["subject"].startswith("[Internal]")


def test_ticked_days_wear_their_row_s_work_area_colour():
    """A row in a work area ticks in that area's colour, in the UI and on
    paper alike; a row with no area falls back to the accent."""
    area = lookahead.add_area("24-003", "Cable Tray Install")
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.add_item(period["id"], {"description": "Hang tray", "days": "01000000000000",
                                      "work_area_id": area["id"]})
    lookahead.add_item(period["id"], {"description": "Unassigned work", "days": "00100000000000"})

    html = lookahead.share_html(period["id"], "Siemens", "24-003")["html"]
    assert f"background:{area['color']};color:#fff" in html          # the area row
    assert f"background:{lookahead.ACCENT};color:#fff" in html       # the arealess row

    pdf = lookahead.share_pdf(period["id"], "Siemens", "24-003").decode("latin-1")
    r, g, b = lookahead._hex_rgb(area["color"])
    assert f"{r:.3f} {g:.3f} {b:.3f} rg" in pdf
    assert "%.3f %.3f %.3f rg" % lookahead._hex_rgb(lookahead.ACCENT) in pdf


def test_work_area_is_a_column_naming_the_area_on_each_row():
    used = lookahead.add_area("24-003", "Cable Tray Install")
    lookahead.add_area("24-003", "Tree Cutting")            # defined but unassigned
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.add_item(period["id"], {"description": "Hang tray",
                                      "work_area_id": used["id"]})
    html = lookahead.share_html(period["id"], "Siemens", "24-003")["html"]
    assert "Work Area" in html
    assert "Cable Tray Install" in html      # named on its row, not in a footer key
    assert "Tree Cutting" not in html        # nothing uses it, so it isn't shown
    assert used["color"] in html             # colour band + chip


def test_the_work_area_column_is_absent_when_no_row_uses_one():
    """It's optional — an unused feature costs no width on the sheet."""
    lookahead.add_area("24-003", "Tree Cutting")            # exists, unassigned
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.add_item(period["id"], {"description": "Hang tray"})
    assert "Work Area" not in lookahead.share_html(period["id"], "Siemens", "24-003")["html"]
    assert "Work Area" not in pdf_text(period["id"])[1]


def pdf_text(period_id, audience="customer", job="Siemens - Wendell", weeks=None):
    import io

    from pypdf import PdfReader

    data = lookahead.share_pdf(period_id, job, "24-003", audience, weeks)
    reader = PdfReader(io.BytesIO(data))
    return reader, "\n".join(pg.extract_text() for pg in reader.pages)


def test_share_pdf_is_a_real_readable_pdf():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    for n in range(3):
        lookahead.add_item(period["id"], {"description": f"Activity {n} - pull wire",
                                          "days": "01111100000000",
                                          "requirements": "Escort", "notes": "note"})
    reader, text = pdf_text(period["id"])
    assert len(reader.pages) == 1
    assert "Two-Week Look Ahead" in text
    assert "Siemens - Wendell" in text
    assert "Activity 0" in text
    assert "Requirements" in text and "Escort" in text


def test_customer_pdf_has_no_tools_or_materials_and_the_team_pdf_does():
    """The guarantee is structural — the customer layout has no such columns,
    so there is no filter to forget."""
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    populate(period["id"])

    _, customer = pdf_text(period["id"], "customer")
    assert "Escort" in customer and "west side" in customer     # customer columns stay
    for leak in ("Tools", "Material", "Trencher", "PVC90s"):
        assert leak not in customer
    assert "(Internal)" not in customer

    _, team = pdf_text(period["id"], "team")
    assert "Tools" in team and "Trencher" in team
    assert "Material" in team and "PVC90s" in team
    assert "(Internal)" in team


def test_the_pdf_carries_the_work_area_column():
    area = lookahead.add_area("24-003", "Cable Tray Install")
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.add_item(period["id"], {"description": "Hang tray",
                                      "work_area_id": area["id"]})
    _, text = pdf_text(period["id"])
    assert "Work Area" in text
    assert "Cable Tray" in text            # the name wraps inside the column


def test_pdf_cells_wrap_in_full_and_grow_their_row():
    """Character-count clipping used to cut a requirement off mid-sentence.
    Cells wrap on real metrics now and the row grows to the tallest cell."""
    import re

    long_text = ("Badged escort to switchgear. need trailers moved on east side "
                 "immediately before tue 8/22")
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.add_item(period["id"], {"description": "Mobilize", "requirements": long_text,
                                      "tools": "Trencher, hydraulic bender"})
    lookahead.add_item(period["id"], {"description": "Short one"})

    _, text = pdf_text(period["id"], "team")
    assert long_text in " ".join(text.split())          # nothing lost
    assert "Trencher, hydraulic bender" in " ".join(text.split())

    # the wrapped row is visibly taller than the one-liner beneath it
    raw = lookahead.share_pdf(period["id"], "Job", "24-003", "team").decode("latin-1")
    # full-width horizontal rules, top down: the strap line under the title,
    # the table top, the header bottom, then one per row boundary
    rules = sorted({float(m.group(1)) for m in
                    re.finditer(r"40\.0 ([\d.]+) m 752\.0 [\d.]+ l S", raw)}, reverse=True)
    rows = [a - b for a, b in zip(rules[2:], rules[3:])]
    assert rows[0] > rows[1]                       # the wrapped row is taller
    assert rows[1] >= lookahead._MIN_ROW_H - 0.5   # and the plain one is the floor


@pytest.mark.parametrize("weeks", [2, 3])
@pytest.mark.parametrize("audience", ["customer", "team"])
def test_pdf_day_headers_fit_their_column(weeks, audience):
    """The dates used to crush together and run through their own borders on
    a three-week sheet. Every header must measure inside its column, and the
    day name must stay unambiguous — two letters minimum, never a bare "T"
    that could be Tuesday or Thursday."""
    import re

    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.update_period(period["id"], {"weeks": weeks})
    area = lookahead.add_area("24-003", "Cable Tray Install")
    lookahead.add_item(period["id"], {"description": "Hang tray", "days": "1" * 21,
                                      "work_area_id": area["id"]})

    _, _, day_w, _box, _cols = lookahead._layout(
        lookahead.is_internal(audience), True, weeks)
    raw = lookahead.share_pdf(period["id"], "Job", "24-003", audience, weeks).decode("latin-1")

    dow = re.findall(r"/F2 ([\d.]+) Tf [\d.]+ 518\.0 Td \(([^)]*)\) Tj", raw)
    # a wrapped column heading has a second line on the same baseline as the
    # day numbers, so keep only the runs that actually are numbers
    nums = [(s, t) for s, t in
            re.findall(r"/F2 ([\d.]+) Tf [\d.]+ 508\.0 Td \(([^)]*)\) Tj", raw)
            if t.isdigit()]
    assert len(dow) == len(nums) == weeks * 7
    for size, label in dow:
        assert len(label) >= 2
        assert lookahead.text_width(label, float(size), True) <= day_w - 1
    for size, label in nums:
        assert lookahead.text_width(label, float(size), True) <= day_w - 1


def test_share_pdf_paginates_long_look_aheads():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    for n in range(25):                       # > one page of rows
        lookahead.add_item(period["id"], {"description": f"Task {n}"})
    reader, _ = pdf_text(period["id"], job="Job")
    assert len(reader.pages) == 2
    assert "page 2 of 2" in reader.pages[1].extract_text()


def test_share_pdf_survives_non_latin1_text():
    """Em dashes and smart quotes come from real typing; Helvetica is
    latin-1, so they must be transliterated rather than crash the writer."""
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    lookahead.add_item(period["id"], {"description": "Pull wire \u2014 \u201ceast\u201d run"})
    _, text = pdf_text(period["id"], job="Job \u2014 A")
    assert "Pull wire - " in text


def test_share_refuses_an_empty_look_ahead():
    period = lookahead.get_or_create_period("24-003", SUNDAY)
    with pytest.raises(lookahead.LookaheadError, match="no line items"):
        lookahead.share_html(period["id"], "Job", "24-003")
    with pytest.raises(lookahead.LookaheadError, match="no line items"):
        lookahead.share_pdf(period["id"], "Job", "24-003")


def test_clearing_a_schedule_removes_tasks_and_links_but_keeps_the_calendar():
    """The way back from a bad import. Links go with the tasks, a staged
    import waiting for review goes too (it would otherwise offer to commit
    rows against a schedule that no longer exists), and the working calendar
    survives — workdays and holidays belong to the job, not to the tasks."""
    schedule.import_tasks("24-003", [
        {"external_id": "1", "name": "A", "start": "2026-03-02",
         "finish": "2026-03-06", "duration_days": 5, "sort_order": 0},
        {"external_id": "2", "name": "B", "start": "2026-03-09",
         "finish": "2026-03-13", "duration_days": 5, "sort_order": 1,
         "predecessors": "1"},
    ], source="test")
    schedule.set_calendar("24-003", workdays="1111110", holidays=["2026-07-03"])
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) c FROM schedule_links").fetchone()["c"] > 0

    assert schedule.clear_tasks("24-003", actor="Ross Hixon") == 2
    assert schedule.list_tasks("24-003") == []
    assert conn.execute("SELECT COUNT(*) c FROM schedule_links").fetchone()["c"] == 0

    from datetime import date
    cal = schedule.get_calendar("24-003")
    assert cal.workdays == "1111110"
    assert date(2026, 7, 3) in cal.holidays

    # Clearing an already-empty schedule is a no-op, not an error.
    assert schedule.clear_tasks("24-003") == 0
