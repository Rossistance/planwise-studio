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
