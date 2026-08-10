"""The mobile -> desk handoff for Outlook drafting (Phase 5g).

The property that matters most: mail leaves from the account of the person
who asked for it (D10/D11). Moving the *moment* of drafting must not quietly
move the *mailbox*.
"""
from __future__ import annotations

import pytest

from backend import db, outbox, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def queued(actor="Ross Hixon", **kw):
    args = {"job_number": "24-003", "kind": "lookahead", "target_id": "period-1",
            "audience": "customer", "weeks": 2}
    args.update(kw)
    return outbox.queue(actor=actor, **args)


# --- queueing -----------------------------------------------------------------

def test_queueing_records_what_to_send_and_who_asked():
    item = queued(note="sent from the van")
    assert item["kind"] == "lookahead"
    assert item["audience"] == "customer"
    assert item["weeks"] == 2
    assert item["note"] == "sent from the van"
    assert item["queued_by"] == "Ross Hixon"
    assert item["drafted_at"] is None


def test_an_unknown_kind_or_empty_target_is_refused():
    with pytest.raises(outbox.OutboxError, match="Don't know how"):
        queued(kind="carrier-pigeon")
    with pytest.raises(outbox.OutboxError, match="Nothing to send"):
        queued(target_id="")
    assert outbox.pending() == []


def test_a_blank_note_is_stored_as_nothing_rather_than_empty_text():
    assert queued(note="   ")["note"] is None


# --- what's waiting -----------------------------------------------------------

def test_pending_is_scoped_to_one_person_by_default():
    """You are only ever offered your own — see the mailbox rule below."""
    queued(actor="Ross Hixon")
    queued(actor="Field Leader", target_id="period-2")
    assert len(outbox.pending()) == 2                       # everything
    assert [i["target_id"] for i in outbox.pending("Ross Hixon")] == ["period-1"]
    assert [i["target_id"] for i in outbox.pending("Field Leader")] == ["period-2"]


def test_pending_can_be_narrowed_to_a_job():
    queued(target_id="a")
    queued(job_number="25-001", target_id="b")
    assert len(outbox.pending("Ross Hixon")) == 2
    assert [i["target_id"] for i in outbox.pending("Ross Hixon", "25-001")] == ["b"]


def test_drafted_items_drop_out_of_pending():
    item = queued()
    assert outbox.mark_drafted(item["id"], actor="Ross Hixon") is not None
    assert outbox.pending("Ross Hixon") == []


# --- the mailbox rule ---------------------------------------------------------

def test_only_the_person_who_queued_it_can_draft_it():
    """D10 is 'mine through my email, someone else's through their own'. Two
    people signed in on one machine must not be able to send each other's mail
    from the wrong mailbox."""
    item = queued(actor="Ross Hixon")
    with pytest.raises(outbox.OutboxError, match="Only Ross Hixon"):
        outbox.claim(item["id"], "Field Leader")
    assert outbox.claim(item["id"], "Ross Hixon")["id"] == item["id"]


def test_only_the_person_who_queued_it_can_cancel_it():
    item = queued(actor="Ross Hixon")
    with pytest.raises(outbox.OutboxError, match="isn't yours"):
        outbox.cancel(item["id"], "Field Leader")
    assert outbox.cancel(item["id"], "Ross Hixon") is True
    assert outbox.pending() == []


def test_claiming_something_already_drafted_or_gone_is_refused():
    item = queued()
    outbox.mark_drafted(item["id"], actor="Ross Hixon")
    with pytest.raises(outbox.OutboxError, match="already been drafted"):
        outbox.claim(item["id"], "Ross Hixon")
    with pytest.raises(outbox.OutboxError, match="no longer queued"):
        outbox.claim("does-not-exist", "Ross Hixon")


def test_marking_drafted_twice_is_refused_so_a_double_click_cannot_double_send():
    item = queued()
    assert outbox.mark_drafted(item["id"], actor="Ross Hixon") is not None
    assert outbox.mark_drafted(item["id"], actor="Ross Hixon") is None


def test_cancelling_something_gone_or_already_drafted_reports_false():
    item = queued()
    outbox.mark_drafted(item["id"], actor="Ross Hixon")
    assert outbox.cancel(item["id"], "Ross Hixon") is False
    assert outbox.cancel("nope", "Ross Hixon") is False


def test_the_queue_and_the_draft_both_land_in_the_activity_trail():
    item = queued()
    outbox.mark_drafted(item["id"], actor="Ross Hixon")
    kinds = [a["action"] for a in store.list_activity("24-003", 20)]
    assert "outbox.queue" in kinds
    assert "outbox.drafted" in kinds
