"""Web push subscriptions and sending (Phase 5e)."""
from __future__ import annotations

import pytest

from backend import db, push


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def sub(endpoint="https://push.example/abc", p256dh="pub-key", auth="auth-secret"):
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


# --- keys ---------------------------------------------------------------------

def test_the_vapid_keypair_is_generated_once_and_then_reused():
    """Every browser subscription is bound to the key it was made with, so a
    regenerated keypair would silently orphan every subscribed device."""
    first = push.public_key()
    assert first and len(first) > 40
    assert push.public_key() == first
    assert (push.config.data_dir() / push.KEY_FILE).is_file()
    assert push.available() is True


def test_the_private_key_never_leaves_the_server():
    import json
    push.public_key()
    stored = json.loads((push.config.data_dir() / push.KEY_FILE).read_text())
    assert "private" in stored and "public" in stored
    assert push.public_key() == stored["public"]
    assert stored["private"] != stored["public"]


# --- subscriptions ------------------------------------------------------------

def test_subscribing_records_the_device_against_the_user():
    push.subscribe("Ross Hixon", sub())
    rows = push.list_subscriptions()
    assert len(rows) == 1
    assert rows[0]["user_name"] == "Ross Hixon"
    assert rows[0]["endpoint"] == "https://push.example/abc"


def test_resubscribing_the_same_device_updates_rather_than_duplicating():
    """Otherwise one phone would get one copy of every notification per
    re-subscribe, which is how users learn to ignore notifications."""
    push.subscribe("Ross Hixon", sub(auth="first"))
    push.subscribe("Ross Hixon", sub(auth="second"))
    rows = push.list_subscriptions()
    assert len(rows) == 1
    assert rows[0]["auth"] == "second"


def test_two_devices_for_one_person_are_both_kept():
    push.subscribe("Ross Hixon", sub(endpoint="https://push.example/phone"))
    push.subscribe("Ross Hixon", sub(endpoint="https://push.example/desktop"))
    assert len(push.list_subscriptions("Ross Hixon")) == 2


def test_subscriptions_can_be_listed_per_user():
    push.subscribe("Ross Hixon", sub(endpoint="https://push.example/a"))
    push.subscribe("Field Leader", sub(endpoint="https://push.example/b"))
    assert len(push.list_subscriptions()) == 2
    assert [r["endpoint"] for r in push.list_subscriptions("Field Leader")] == \
        ["https://push.example/b"]


def test_a_malformed_subscription_is_refused():
    for bad in [{}, {"endpoint": "x"}, {"endpoint": "x", "keys": {}},
                {"endpoint": "x", "keys": {"p256dh": "p"}}, {"keys": {"p256dh": "p", "auth": "a"}}]:
        with pytest.raises(ValueError, match="usable push subscription"):
            push.subscribe("Ross Hixon", bad)
    assert push.list_subscriptions() == []


def test_unsubscribe_removes_only_that_device():
    push.subscribe("Ross Hixon", sub(endpoint="https://push.example/phone"))
    push.subscribe("Ross Hixon", sub(endpoint="https://push.example/desktop"))
    assert push.unsubscribe("https://push.example/phone") is True
    assert [r["endpoint"] for r in push.list_subscriptions()] == ["https://push.example/desktop"]
    assert push.unsubscribe("https://push.example/phone") is False


# --- sending ------------------------------------------------------------------

def test_sending_with_no_subscribers_is_a_no_op():
    assert push.send("t", "b") == {"sent": 0, "failed": 0, "pruned": 0}


def test_a_push_service_failure_never_raises(monkeypatch):
    """Sending happens on the back of work that already succeeded — a captured
    reply must not become an error because a push endpoint had a bad day."""
    push.subscribe("Ross Hixon", sub())

    import pywebpush
    monkeypatch.setattr(pywebpush, "webpush",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    out = push.send("t", "b")
    assert out == {"sent": 0, "failed": 1, "pruned": 0}
    assert len(push.list_subscriptions()) == 1        # kept: it may just be transient


def test_a_gone_subscription_is_pruned(monkeypatch):
    """404/410 is how a push service says the device uninstalled the app."""
    push.subscribe("Ross Hixon", sub(endpoint="https://push.example/dead"))
    push.subscribe("Ross Hixon", sub(endpoint="https://push.example/live"))

    import pywebpush

    class Resp:
        def __init__(self, code): self.status_code = code

    def fake(**kw):
        if "dead" in kw["subscription_info"]["endpoint"]:
            raise pywebpush.WebPushException("gone", response=Resp(410))
        return None

    monkeypatch.setattr(pywebpush, "webpush", fake)
    out = push.send("t", "b")
    assert out == {"sent": 1, "failed": 0, "pruned": 1}
    assert [r["endpoint"] for r in push.list_subscriptions()] == ["https://push.example/live"]


def test_sending_can_target_one_person(monkeypatch):
    push.subscribe("Ross Hixon", sub(endpoint="https://push.example/ross"))
    push.subscribe("Field Leader", sub(endpoint="https://push.example/field"))

    seen = []
    import pywebpush
    monkeypatch.setattr(pywebpush, "webpush",
                        lambda **kw: seen.append(kw["subscription_info"]["endpoint"]))

    assert push.send("t", "b", user="Field Leader")["sent"] == 1
    assert seen == ["https://push.example/field"]


def test_the_payload_carries_what_the_worker_needs(monkeypatch):
    import json

    import pywebpush
    push.subscribe("Ross Hixon", sub())
    captured = {}
    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: captured.update(kw))

    push.send("RFI 004 — reply received", "From customer@x.com. Approved.",
              url="/#/job/24-003/rfis/abc", tag="reply:abc")
    body = json.loads(captured["data"])
    assert body["title"] == "RFI 004 — reply received"
    assert body["url"] == "/#/job/24-003/rfis/abc"
    assert body["tag"] == "reply:abc"
    assert captured["vapid_claims"]["sub"].startswith("mailto:")
