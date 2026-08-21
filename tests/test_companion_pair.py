"""The companion's pairing endpoint — where a PC decides whose mail it drafts.

This endpoint writes the credential that lets a background process file into
shared records and drive a mailbox, so its guards matter more than its size
suggests. It is also the upgrade path: a PC still holding the old company-wide
token must land on the sign-in page, not on "already paired".
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from companion import companion as c


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Never touch the real ~/.planwise — it holds this machine's live pairing."""
    monkeypatch.setattr(c, "PAIR_DIR", tmp_path)
    monkeypatch.setattr(c, "AUTH_FILE", tmp_path / "companion_auth.json")
    monkeypatch.setattr(c, "TOKEN_FILE", tmp_path / "companion_token.txt")
    monkeypatch.setattr(c, "SERVER_FILE", tmp_path / "server_url.txt")
    yield


@pytest.fixture
def client():
    return TestClient(c.app)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def planwise(monkeypatch):
    """Stand in for the PlanWise server the companion signs in against."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "body": json})
        if json.get("password") == "the-right-password":
            return FakeResponse(200, {"token": "issued-token-abc", "user_name": "Dana Wallace"})
        return FakeResponse(401, {"detail": "That email and password don't match."})

    monkeypatch.setattr(c.httpx, "post", fake_post)
    return calls


def pair(client, **kw):
    body = {"server": "https://planwise.example", "email": "dana@wecc.com",
            "password": "the-right-password"}
    body.update(kw)
    return client.post("/pair", json=body)


# --- the upgrade path ---------------------------------------------------------

def test_a_leftover_company_wide_token_reads_as_unpaired(client):
    """The old shared token is not a pairing. Treating it as one would make
    the 409 guard a dead end: an upgraded PC would refuse to re-pair and the
    user would have to find and delete a hidden file."""
    c.TOKEN_FILE.write_text("the-old-company-wide-token", encoding="utf-8")
    assert client.get("/health").json()["paired"] is False
    assert "Work email" in client.get("/pair").text


def test_pairing_removes_the_legacy_token_file(client, planwise):
    c.TOKEN_FILE.write_text("the-old-company-wide-token", encoding="utf-8")
    assert pair(client).status_code == 200
    assert not c.TOKEN_FILE.exists()


# --- signing in ---------------------------------------------------------------

def test_a_successful_sign_in_stores_the_token_but_never_the_password(client, planwise):
    r = pair(client)
    assert r.status_code == 200
    assert r.json() == {"paired": True, "server": "https://planwise.example",
                        "user_name": "Dana Wallace"}

    raw = c.AUTH_FILE.read_text(encoding="utf-8")
    assert json.loads(raw) == {"token": "issued-token-abc",
                               "server": "https://planwise.example",
                               "user_name": "Dana Wallace"}
    assert "the-right-password" not in raw
    # The device name is sent so the sign-in is identifiable in the trail.
    assert planwise[0]["body"]["device"]


def test_a_wrong_password_is_refused_and_writes_nothing(client, planwise):
    r = pair(client, password="not-the-password")
    assert r.status_code == 401
    assert r.json()["detail"] == "That email and password don't match."
    assert not c.AUTH_FILE.exists()
    assert client.get("/health").json()["paired"] is False


def test_an_unreachable_server_says_so_rather_than_half_pairing(client, monkeypatch):
    def boom(*_a, **_kw):
        raise c.httpx.ConnectError("nope")
    monkeypatch.setattr(c.httpx, "post", boom)

    r = pair(client)
    assert r.status_code == 502
    assert "Couldn't reach PlanWise" in r.json()["detail"]
    assert not c.AUTH_FILE.exists()


def test_obvious_nonsense_is_rejected_before_any_network_call(client, planwise):
    assert pair(client, server="planwise.example").status_code == 422   # no scheme
    assert pair(client, email="").status_code == 422
    assert pair(client, password="").status_code == 422
    assert planwise == []                                              # never called


# --- the guards ---------------------------------------------------------------

def test_an_already_connected_pc_refuses_and_names_who_it_belongs_to(client, planwise):
    pair(client)
    r = pair(client, email="someone@else.com")
    assert r.status_code == 409
    assert "already connected as Dana Wallace" in r.json()["detail"]


def test_a_cross_origin_page_cannot_re_point_the_companion(client, planwise):
    """A site you happen to visit must not be able to aim this companion at a
    server of its choosing — it would receive every reply captured here."""
    r = client.post("/pair", json={"server": "https://evil.example",
                                   "email": "a@b.c", "password": "the-right-password"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert not c.AUTH_FILE.exists()


def test_the_wrong_persons_token_is_refused_with_a_message_that_explains(client, planwise):
    """Two people at one desk is the ordinary cause. Drafting anyway would put
    this person's mail in the other person's Sent Items (D10)."""
    pair(client)
    r = client.post("/draft", json={"token": "not-hers", "subject": "x", "to": "a@b.c"})
    assert r.status_code == 401
    assert "paired to Dana Wallace" in r.json()["detail"]


def test_an_unpaired_companion_points_at_its_own_sign_in_page(client):
    r = client.post("/draft", json={"token": "anything", "subject": "x"})
    assert r.status_code == 503
    assert "/pair" in r.json()["detail"]


def test_health_reports_the_paired_user(client, planwise):
    assert client.get("/health").json()["paired_user"] is None
    pair(client)
    h = client.get("/health").json()
    assert h["paired"] is True and h["paired_user"] == "Dana Wallace"
    assert h["server"] == "https://planwise.example"


# --- reachable from a hosted PlanWise ------------------------------------------

def test_the_companion_answers_a_private_network_preflight(client):
    """Hosting PlanWise made every browser call to this companion a public
    HTTPS origin reaching a loopback address, which Chrome and Edge gate behind
    Private Network Access. Refusing that preflight blocks the request before
    it is made, and looks exactly like the companion not running — which is
    what it looked like."""
    r = client.options("/draft", headers={
        "Origin": "https://planwise-rahj.onrender.com",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
        "Access-Control-Request-Private-Network": "true",
    })
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-private-network") == "true"


def test_an_ordinary_preflight_still_works(client):
    r = client.options("/draft", headers={
        "Origin": "http://127.0.0.1:8771",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.status_code == 200


# --- the backstop sweep covers SENDS, not just replies -------------------------

def test_the_sweep_checks_sent_items_even_with_no_reply_threads(client, planwise, monkeypatch):
    """The bug: the sweep scanned the Inbox only, and returned early when the
    thread list was empty. A record that is drafted but not yet sent HAS no
    reply thread — so the sweep did nothing for it, and Draft -> Sent rested
    entirely on Outlook's ItemAdd on Sent Items, which Exchange cached mode
    routinely never fires. A missed event was permanent, and because a record
    only joins the reply watch list once Sent, the reply was then invisible
    too. One missed event killed the whole chain silently.
    """
    import asyncio

    pair(client)
    scanned = {}

    monkeypatch.setattr(c, "_fetch_manifest", lambda force=False: {
        "threads": [], "drafts": [{"record_id": "rec-1", "subject": "RFI 001 — X"}]})

    def fake_scan_sent(queries):
        scanned["queries"] = queries
        return [{"record_id": "rec-1", "sent_on": "2026-08-12T06:16:00", "to": "gc@x.com"}]

    def fake_scan_inbox(queries):          # must not be needed to reach sends
        scanned["inbox"] = True
        return {"replies": [], "scanned": 0}

    monkeypatch.setattr(c, "_scan_sent", fake_scan_sent)
    monkeypatch.setattr(c, "_scan_inbox", fake_scan_inbox)
    # Outlook open is now a precondition of scanning anything, because asking
    # for Outlook must never start it (see test_companion_outlook.py). The
    # machine running the tests usually has Outlook closed.
    monkeypatch.setattr(c, "outlook_is_open", lambda: True)

    posted = []

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            return FakeAsyncResponse(200, {
                "enabled": True, "interval_seconds": 15,
                "threads": [], "drafts": [{"record_id": "rec-1", "subject": "RFI 001 — X"}]})
        async def post(self, url, json=None, headers=None):
            posted.append((url, json))
            return FakeAsyncResponse(200, {})

    monkeypatch.setattr(c.httpx, "AsyncClient", lambda **kw: FakeClient())
    asyncio.run(c._poll_once())

    assert scanned.get("queries"), "Sent Items was never scanned"
    assert any(u.endswith("/api/records/rec-1/sent") for u, _ in posted), \
        f"the send was never reported to the server; posted={posted}"


def test_the_sweep_waits_quietly_when_outlook_is_closed(client, planwise, monkeypatch):
    """A closed Outlook is a state, not a failure.

    It must produce neither a scan (there is nothing to scan, and reaching for
    Outlook would START one) nor an error every fifteen seconds — an hour at
    the pub would otherwise leave 240 logged failures and a red chip waiting on
    Monday.
    """
    import asyncio

    pair(client)
    touched = {}

    monkeypatch.setattr(c, "outlook_is_open", lambda: False)
    monkeypatch.setattr(c, "_scan_sent",
                        lambda q: touched.setdefault("sent", True) or [])
    monkeypatch.setattr(c, "_scan_inbox",
                        lambda q: touched.setdefault("inbox", True) or {"replies": [], "scanned": 0})

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            return FakeAsyncResponse(200, {
                "enabled": True, "interval_seconds": 15,
                "threads": [{"record_id": "rec-1", "subject": "RFI 001 — X"}],
                "drafts": [{"record_id": "rec-2", "subject": "RFI 002 — X"}]})
        async def post(self, url, json=None, headers=None):
            raise AssertionError("nothing should be reported with Outlook closed")

    monkeypatch.setattr(c.httpx, "AsyncClient", lambda **kw: FakeClient())
    asyncio.run(c._poll_once())

    assert not touched, f"Outlook was reached for while closed: {touched}"
    assert c.poll_state["outlook"] == "not open"
    assert c.poll_state["last_error"] is None, "a closed Outlook is not an error"


class FakeAsyncResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_new_outlook_detection_reads_the_toggle_and_the_process(monkeypatch):
    """UseNewOutlook=1 or a running olk.exe — either means the person lives
    in new Outlook and drafting must go the hidden-save-and-sync way."""
    from companion import companion as comp

    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import types
    fake_winreg = types.SimpleNamespace(
        HKEY_CURRENT_USER=0,
        OpenKey=lambda *a, **k: FakeKey(),
        QueryValueEx=lambda k, name: (1, 4))
    import sys
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert comp.new_outlook_preferred() is True

    fake_winreg.QueryValueEx = lambda k, name: (0, 4)
    import subprocess as sp
    monkeypatch.setattr(sp, "run", lambda *a, **k: types.SimpleNamespace(stdout="INFO: No tasks"))
    assert comp.new_outlook_preferred() is False

    monkeypatch.setattr(sp, "run", lambda *a, **k: types.SimpleNamespace(stdout="olk.exe  1234 Console"))
    assert comp.new_outlook_preferred() is True


# --- the vista trigger (2.0.3) -----------------------------------------------
# The companion re-fires the scheduled pull; these pin the decision logic, not
# the subprocess. A capable-machine stub stands in for schtasks.

def _reset_vista(monkeypatch, capable=True):
    monkeypatch.setattr(c, "vista_state",
                        {"capable": capable, "last_trigger": None,
                         "last_result": None, "reason": None})
    fired = []
    monkeypatch.setattr(c, "_trigger_vista_pull",
                        lambda reason: (fired.append(reason),
                                        c.vista_state.__setitem__(
                                            "last_trigger",
                                            c.datetime.now().isoformat(timespec="seconds"))))
    return fired


def test_a_settings_request_fires_the_pull_once_not_every_sweep(monkeypatch):
    import asyncio
    fired = _reset_vista(monkeypatch)
    manifest = {"vista": {"wanted": True, "as_of": None}}
    asyncio.run(c._maybe_refresh_vista(manifest))
    asyncio.run(c._maybe_refresh_vista(manifest))   # 15s later in real life
    assert fired == ["asked from Settings"]         # throttled while in flight


def test_fresh_data_triggers_nothing_on_the_daily_path(monkeypatch):
    import asyncio
    from datetime import datetime
    fired = _reset_vista(monkeypatch)
    manifest = {"vista": {"wanted": False,
                          "as_of": datetime.now().isoformat(timespec="seconds")}}
    asyncio.run(c._maybe_refresh_vista(manifest))
    assert fired == []


def test_an_incapable_machine_never_fires(monkeypatch):
    import asyncio
    fired = _reset_vista(monkeypatch, capable=False)
    asyncio.run(c._maybe_refresh_vista({"vista": {"wanted": True, "as_of": None}}))
    assert fired == []


def test_a_timezone_stamped_as_of_is_read_as_fresh(monkeypatch):
    """The server stamps as_of with an offset. Comparing it against a naive
    now() raises, and swallowing that read minutes-old data as infinitely
    stale — re-pulling Power BI every two hours, all day (2026-08-21)."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    fired = _reset_vista(monkeypatch)
    fresh = datetime.now(timezone(timedelta(hours=-4))).isoformat(timespec="seconds")
    asyncio.run(c._maybe_refresh_vista({"vista": {"wanted": False, "as_of": fresh}}))
    assert fired == [], "fresh, timezone-stamped data must not trigger a pull"


def test_genuinely_old_data_still_triggers_the_backstop(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone

    fired = _reset_vista(monkeypatch)
    old = (datetime.now(timezone(timedelta(hours=-4))) - timedelta(days=2)).isoformat(timespec="seconds")
    asyncio.run(c._maybe_refresh_vista({"vista": {"wanted": False, "as_of": old}}))
    # The backstop only runs after 7am; before then the day hasn't started.
    if datetime.now().hour >= 7:
        assert fired and "backstop" in fired[0]
    else:
        assert fired == []


def test_an_unreadable_stamp_is_reported_not_treated_as_stale(monkeypatch):
    import asyncio
    fired = _reset_vista(monkeypatch)
    asyncio.run(c._maybe_refresh_vista({"vista": {"wanted": False, "as_of": "not-a-date"}}))
    assert fired == [], "a broken stamp must not masquerade as stale data"


def test_health_never_touches_outlooks_object_model(monkeypatch):
    """Reading Namespace.Accounts to name the mailbox is address-book access,
    and it popped Outlook's own security guard every time Settings opened."""
    import inspect
    # Comments explain the history; only the CODE is under test.
    code = "\n".join(line.split("#", 1)[0]
                     for line in inspect.getsource(c.health).splitlines())
    assert "Accounts" not in code, "health reads the address book again"
    assert "_outlook(" not in code, "health opens a COM connection again"
    assert "outlook_is_open()" in code
