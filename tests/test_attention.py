"""Needs attention — derived from the registers, never stored (2.0).

The doctrine under test: the panel holds only items genuinely waiting on the
user, and an item disappears the moment its cause is resolved — because it is
recomputed from the cause row, not ticked off a list.
"""
from __future__ import annotations

import pytest

from backend import attention, db, records, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANWISE_VISTA_WORKBOOK", "")
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def test_a_drafted_unsent_co_appears_and_clears_when_it_goes_out():
    co = store.add_co("24-003", {"kind": "customer", "co_number": "04",
                                 "description": "Anchor revision",
                                 "amount_submitted": 186400, "status": "Unsent"},
                      actor="pm")
    items = attention.items_for("24-003")
    assert any("CO-04" in i["text"] and "$186,400" in i["text"] for i in items)

    store.update_co("24-003", co["id"], {"status": "Sent"}, actor="pm")
    items = attention.items_for("24-003")
    assert not any("CO-04" in i["text"] for i in items), \
        "the item must disappear the moment the cause row changes"


def test_approved_sub_cos_without_a_po_are_one_exposure_line():
    a = store.add_co("24-003", {"kind": "subcontractor", "co_number": "S1",
                                "amount_approved": 60000}, actor="pm")
    store.add_co("24-003", {"kind": "subcontractor", "co_number": "S2",
                            "amount_approved": 36800}, actor="pm")
    items = attention.items_for("24-003")
    line = next(i for i in items if i["kind"] == "Commitment")
    assert "$96,800" in line["text"] and "2 approved" in line["text"]
    assert line["tone"] == "er"

    # Issuing a PO against one of them halves the exposure…
    store.add_po("24-003", {"po_number": "P-1", "source_co_id": a["id"]}, actor="pm")
    line = next(i for i in attention.items_for("24-003") if i["kind"] == "Commitment")
    assert "$36,800" in line["text"]


def test_draft_records_and_unconfirmed_replies_wait_on_the_pm():
    rec = records.add_record("24-003", "rfi", {"title": "Stub-ups",
                                               "due_date": "2026-08-28"}, actor="pm")
    items = attention.items_for("24-003")
    assert any("still a draft" in i["text"] for i in items)

    records.mark_sent(rec["id"], actor="pm")
    assert not any("still a draft" in i["text"]
                   for i in attention.items_for("24-003"))

    records.add_reply(rec["id"], {"from_name": "Dana", "from_email": "d@wecc.example",
                                  "received_at": "2026-08-19T10:00:00",
                                  "body": "Reroute 18 inches south."})
    items = attention.items_for("24-003")
    assert any("waiting for a project manager to confirm" in i["text"] for i in items)


def test_stale_vista_is_an_item_and_fresh_vista_is_not():
    fresh = attention.items_for("24-003", vista_stale=False)
    assert not any(i["kind"] == "Data" for i in fresh)
    stale = attention.items_for("24-003", vista_stale=True, vista_as_of="2026-08-01")
    item = next(i for i in stale if i["kind"] == "Data")
    assert "2026-08-01" in item["text"]


def test_newest_cause_first():
    store.add_co("24-003", {"kind": "customer", "co_number": "01",
                            "amount_submitted": 100, "status": "Unsent"}, actor="pm")
    records.add_record("24-003", "rfi", {"title": "Newer"}, actor="pm")
    items = attention.items_for("24-003")
    assert "draft" in items[0]["text"], "the newer cause leads the list"
