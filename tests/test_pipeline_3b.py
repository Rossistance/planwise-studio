"""Phase 3b: drafting fallback, disposition heuristics, reply staging, spend
gate, settings masking. No network: no API keys are configured in tests, so
the AI path raises internally and the deterministic path is what's exercised."""
from __future__ import annotations

import pytest

from backend import ai, db, records


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def make_rfi(**kw):
    fields = {"number": "RFI-001", "title": "Slab detail conflict",
              "question": "Which detail governs?", **kw}
    return records.add_record("24-003", "rfi", fields)


def make_sub(**kw):
    return records.add_record("24-003", "submittal", {"number": "SUB-001", **kw})


# --- drafting ----------------------------------------------------------------

def test_draft_falls_back_to_template_without_a_key():
    rec = make_rfi(due_date="2026-08-20")
    d = ai.draft_email(rec, {"job_name": "Siemens - Wendell"}, [])
    assert d["source"] == "template"
    assert "RFI RFI-001" in d["subject"]
    assert "Which detail governs?" in d["body"]
    assert "by 2026-08-20" in d["body"]


def test_submittal_template_asks_for_a_disposition():
    d = ai.draft_email(make_sub(spec_section="03 30 00"),
                       {"job_name": "Siemens - Wendell"}, [])
    assert "Revise & Resubmit" in d["body"]
    assert "03 30 00" in d["body"]


def test_draft_saved_and_editable():
    rec = make_rfi()
    records.save_draft(rec["id"], "Subj", "Body", "template", actor="Ross")
    records.save_draft(rec["id"], "Subj2", "Body2", "edited", actor="Ross")
    d = records.get_draft(rec["id"])
    assert (d["subject"], d["source"]) == ("Subj2", "edited")


# --- reply analysis ----------------------------------------------------------

@pytest.mark.parametrize("body,expected", [
    ("This submittal is APPROVED AS NOTED, see comments.", "Approved as Noted"),
    ("Please revise and resubmit with corrections.", "Revise & Resubmit"),
    ("Revise & resubmit.", "Revise & Resubmit"),
    ("The submittal is rejected.", "Rejected"),
    ("Approved.", "Approved"),
    ("We reviewed it and it is not approved.", "Rejected"),
])
def test_submittal_disposition_heuristics(body, expected):
    assert ai.analyze_reply(make_sub(), body)["proposed_status"] == expected


def test_rfi_reply_proposes_answered_with_answer():
    p = ai.analyze_reply(make_rfi(), "Detail 3/S-201 governs. Proceed accordingly.")
    assert p["proposed_status"] == "Answered"
    assert "S-201" in p["proposed_answer"]
    assert p["proposal_source"] == "heuristic"


# --- reply staging + confirmation --------------------------------------------

def test_reply_is_staged_not_applied():
    rec = make_sub()
    rep = records.add_reply(rec["id"], {"from_email": "pm@siemens.com",
                                        "body": "Approved as noted."}, actor="Ross")
    assert rep["proposed_status"] == "Approved as Noted"
    assert rep["confirmed_at"] is None
    # the record itself has NOT moved
    assert records.get_record(rec["id"])["status"] == "Draft"


def test_confirm_applies_possibly_edited_proposal():
    rec = make_rfi()
    rep = records.add_reply(rec["id"], {"body": "Use detail 3/S-201."})
    out = records.confirm_reply(rep["id"], {"answer": "Detail 3/S-201 governs (edited)."},
                                actor="Ross")
    assert out["confirmed_by"] == "Ross"
    updated = records.get_record(rec["id"])
    assert updated["status"] == "Answered"
    assert updated["answer"] == "Detail 3/S-201 governs (edited)."


def test_reply_attachments_round_trip(tmp_path):
    import base64
    rec = make_sub()
    rep = records.add_reply(rec["id"], {"body": "Rejected."}, attachments=[
        {"filename": "markup.pdf", "content_b64": base64.b64encode(b"%PDF-fake").decode()},
        {"filename": "", "content_b64": ""},  # empty is skipped, not crashed
    ])
    listed = records.list_replies(rec["id"])[0]
    assert [a["filename"] for a in listed["attachments"]] == ["markup.pdf"]


# --- spend gate + settings ---------------------------------------------------

def test_spend_gate_blocks_at_cap():
    ai.patch_settings({"ai_spend_cap_monthly": "0.01", "anthropic_api_key": "sk-test"})
    ai._record_spend("anthropic", "claude-sonnet-5", 10_000, 10_000, "test")
    with pytest.raises(ai.SpendCapReached):
        ai._check_gate()
    # drafting still works — it falls back to the template
    d = ai.draft_email(make_rfi(), {"job_name": "X"}, [])
    assert d["source"] == "template"


def test_settings_mask_secrets_and_masked_writes_do_not_clobber():
    ai.patch_settings({"anthropic_api_key": "sk-ant-actual-key-value-12345"})
    masked = ai.get_settings()["anthropic_api_key"]
    assert "actual-key-value" not in masked
    # a UI round-trip of the masked value must not overwrite the real key
    ai.patch_settings({"anthropic_api_key": masked})
    assert ai.get_settings(mask=False)["anthropic_api_key"] == "sk-ant-actual-key-value-12345"


def test_companion_token_is_stable():
    assert ai.companion_token() == ai.companion_token()
    assert len(ai.companion_token()) > 20


# --- AI failures must never block the pipeline -------------------------------

def test_provider_outage_still_stages_the_reply(monkeypatch):
    """2026-08-08: corporate TLS inspection made every provider call raise
    httpx.ConnectError, which 500'd reply capture outright. The AI is an
    enhancement — a dead provider must degrade to the heuristic, silently."""
    def explode(*a, **kw):
        raise ConnectionError("[SSL: CERTIFICATE_VERIFY_FAILED]")
    monkeypatch.setattr(ai, "_complete_inner", explode)

    rec = make_sub()
    rep = records.add_reply(rec["id"], {"body": "Approved as noted."}, actor="Ross")
    assert rep["proposed_status"] == "Approved as Noted"
    assert rep["proposal_source"] == "heuristic"

    # drafting degrades the same way
    assert ai.draft_email(make_rfi(), {"job_name": "X"}, [])["source"] == "template"


# --- background polling ------------------------------------------------------

def test_replies_are_idempotent_by_message_id():
    """Polling re-sees the same inbox items every cycle; a reply must be
    filed exactly once."""
    rec = make_rfi()
    a = records.add_reply(rec["id"], {"body": "Detail 2 governs.",
                                      "message_id": "OUTLOOK-ENTRY-1"})
    b = records.add_reply(rec["id"], {"body": "Detail 2 governs.",
                                      "message_id": "OUTLOOK-ENTRY-1"})
    assert a["id"] == b["id"]
    assert len(records.list_replies(rec["id"])) == 1

    # a different message on the same thread still files
    records.add_reply(rec["id"], {"body": "Follow-up.", "message_id": "OUTLOOK-ENTRY-2"})
    assert len(records.list_replies(rec["id"])) == 2

    # and the manual path (no message_id) is unaffected
    records.add_reply(rec["id"], {"body": "Typed by hand."})
    assert len(records.list_replies(rec["id"])) == 3


def test_reply_without_message_id_still_dedupes_on_sender_and_time():
    """The real regression: replies captured before message ids were recorded
    had NULL ids, so the first background poll filed second copies of them."""
    rec = make_rfi()
    stamp = "2026-08-08T22:46:31.701000+00:00"
    first = records.add_reply(rec["id"], {"body": "Approved.", "from_email": "a@b.com",
                                          "received_at": stamp})            # legacy row
    again = records.add_reply(rec["id"], {"body": "Approved.", "from_email": "a@b.com",
                                          "received_at": stamp,
                                          "message_id": "ENTRY-9"})         # poller re-sees it
    assert again["id"] == first["id"]
    assert again["deduped"] is True          # so the poller can count honestly
    assert "deduped" not in first
    assert len(records.list_replies(rec["id"])) == 1
    # the row adopts the id, so later cycles match exactly
    assert records.get_reply(first["id"])["message_id"] == "ENTRY-9"

    # a genuinely different email from the same sender still files
    records.add_reply(rec["id"], {"body": "Follow-up.", "from_email": "a@b.com",
                                  "received_at": "2026-08-09T08:00:00+00:00",
                                  "message_id": "ENTRY-10"})
    assert len(records.list_replies(rec["id"])) == 2


def test_open_threads_lists_only_watchable_records():
    sent = make_rfi(number="RFI-010")
    records.save_draft(sent["id"], "RFI RFI-010 — Job", "body", "template")
    records.mark_sent(sent["id"], actor="Ross")

    draft_only = make_rfi(number="RFI-011")          # never sent
    records.save_draft(draft_only["id"], "RFI RFI-011 — Job", "b", "template")

    no_draft = make_rfi(number="RFI-012")            # sent but no email subject
    records.mark_sent(no_draft["id"], actor="Ross")

    closed = make_sub(number="SUB-013")
    records.save_draft(closed["id"], "Submittal SUB-013 — Job", "b", "template")
    records.mark_sent(closed["id"], actor="Ross")
    records.update_record(closed["id"], {"status": "Closed"})

    watched = {t["record_id"] for t in records.open_threads()}
    assert sent["id"] in watched
    assert draft_only["id"] not in watched
    assert no_draft["id"] not in watched
    assert closed["id"] not in watched


def test_mark_sent_records_who_sent_it():
    rec = make_rfi()
    records.mark_sent(rec["id"], actor="Field Leader", sent_at="2026-08-08T21:56:00-04:00")
    conn = db.connect()
    row = conn.execute("SELECT sent_by, sent_at FROM pipeline_records WHERE id = ?",
                       (rec["id"],)).fetchone()
    assert row["sent_by"] == "Field Leader"
    assert row["sent_at"].startswith("2026-08-08")


def test_topic_normalization_matches_this_tenants_external_prefix():
    """The real failure: an [External] transport rule rewrote the reply's
    ConversationTopic, so exact matching found nothing."""
    import sys
    sys.path.insert(0, "companion")
    from companion import _norm_topic

    sent = "RFI 002 — Siemens - Wendell"
    for reply in ["[External] RFI 002 — Siemens - Wendell",
                  "Re: [External] RFI 002 — Siemens - Wendell",
                  "RE: FW: [EXT] RFI 002 —  Siemens - Wendell"]:
        assert _norm_topic(sent) == _norm_topic(reply), reply
    assert _norm_topic(sent) != _norm_topic("Re: [External] RFI 003 — Siemens - Wendell")


def test_any_provider_exception_surfaces_as_aierror(monkeypatch):
    def explode(*a, **kw):
        raise TimeoutError("read timeout")
    monkeypatch.setattr(ai, "_complete_inner", explode)
    with pytest.raises(ai.AIError, match="TimeoutError"):
        ai._complete("hi", "test")


# --- reply capture must not fail after it has succeeded (2026-08-10) ----------

def test_filing_a_reply_returns_200_not_500(tmp_path, monkeypatch):
    """A push-notification trigger added in Phase 5e called records.get(),
    which does not exist. The reply was saved and THEN the endpoint threw, so
    the companion saw a 500 for work that had actually succeeded — the worst
    possible shape of bug: right data, wrong answer."""
    from fastapi.testclient import TestClient

    from backend import ai, app as app_module, db, records

    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    try:
        rec = records.add_record("24-003", "rfi", {"title": "Reply status"})
        records.save_draft(rec["id"], "RFI 001 — Test", "body", "test")
        records.mark_sent(rec["id"])

        client = TestClient(app_module.app)
        headers = {"X-PlanWise-Companion": ai.companion_token()}
        payload = {"message_id": "msg-1", "from_email": "customer@example.com",
                   "body": "Approved as noted.", "received_at": "2026-08-10T10:00:00"}

        first = client.post(f"/api/records/{rec['id']}/replies", json=payload, headers=headers)
        assert first.status_code == 200, first.text
        assert not first.json().get("deduped")

        # and the idempotent re-file, which the poller does on every sweep
        again = client.post(f"/api/records/{rec['id']}/replies", json=payload, headers=headers)
        assert again.status_code == 200, again.text
        assert again.json().get("deduped") is True
        assert len(records.list_replies(rec["id"])) == 1
    finally:
        db.reset_for_tests()
