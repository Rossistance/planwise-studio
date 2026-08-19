"""The weekly briefing — one row, two audiences, seeded from the registers.

Doctrine 5 pinned as a sentence: a customer copy never carries an internal
block. And the seed rule: every proposed line traces to a register row —
an empty job seeds an empty briefing, never invented narrative.
"""
from __future__ import annotations

import pytest

from backend import briefing, db, records, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANWISE_VISTA_WORKBOOK", "")
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def test_an_empty_job_seeds_an_empty_briefing():
    b = briefing.get_or_create("24-003", "2026-08-16", actor="pm")
    assert all(b["blocks"][k] == [] for k in briefing.BLOCK_KEYS), \
        "no register rows means no proposed lines — nothing is invented"


def test_the_seed_traces_to_real_rows():
    store.add_co("24-003", {"kind": "customer", "co_number": "04",
                            "description": "Anchor revision",
                            "amount_submitted": 186400, "status": "Sent"}, actor="pm")
    records.add_record("24-003", "rfi", {"title": "Bus spacing", "status": "Draft",
                                         "due_date": "2026-08-21"}, actor="pm")
    b = briefing.get_or_create("24-003", "2026-08-16", actor="pm")
    asks = " ".join(x["text"] for x in b["blocks"]["asks"])
    risks = " ".join(x["text"] for x in b["blocks"]["risks"])
    assert "CO-04" in asks and "$186,400" in asks
    assert "Bus spacing" in risks


def test_get_or_create_is_stable_and_editable():
    b1 = briefing.get_or_create("24-003", "2026-08-16", actor="pm")
    b2 = briefing.get_or_create("24-003", "2026-08-16", actor="pm")
    assert b1["id"] == b2["id"], "one row per job per week"

    edited = briefing.patch(b1["id"], {"blocks": {
        "progress": [{"text": "Bay 4 columns set Thursday.", "tag": "Schedule"}],
        "risks": [], "asks": [], "signature": []}}, actor="pm")
    assert edited["blocks"]["progress"][0]["text"] == "Bay 4 columns set Thursday."
    again = briefing.get_or_create("24-003", "2026-08-16", actor="pm")
    assert again["blocks"]["progress"][0]["text"] == "Bay 4 columns set Thursday.", \
        "a PM's edits survive the next read — seeding happens once"


def test_a_customer_copy_never_carries_an_internal_block():
    store.add_co("24-003", {"kind": "subcontractor", "co_number": "S1",
                            "amount_approved": 96800}, actor="pm")
    b = briefing.get_or_create("24-003", "2026-08-16", actor="pm")
    assert any("exposure" in (r.get("tag") or "").lower()
               for r in b["blocks"]["signature"])

    job = {"job_name": "Sage Draw", "current_contract": 6482910,
           "actual_billed": 4196540, "actual_cost": 3884215}
    cust = briefing.render_html(b, job, "customer")
    team = briefing.render_html(b, job, "team")
    assert "Financial position" not in cust and "$6,482,910" not in cust
    assert "exposure" not in cust.lower()
    assert "Financial position" in team and "$6,482,910" in team


def test_sending_stamps_the_row_and_is_reversible():
    b = briefing.get_or_create("24-003", "2026-08-16", actor="pm")
    sent = briefing.patch(b["id"], {"status": "Sent"}, actor="pm")
    assert sent["status"] == "Sent" and sent["sent_at"]

    from backend import reversal
    out = reversal.apply(sent["activity_id"], actor="pm", is_admin=True)
    assert out["ok"] is True, out
    back = briefing.get_or_create("24-003", "2026-08-16", actor="pm")
    assert back["status"] == "Draft" and not back["sent_at"], \
        "undoing a send restores the row's state; the email itself is Outlook's"
