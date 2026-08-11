"""Self-service accounts, the approval gate, and per-user companion pairing.

The shape being protected: PlanWise sits on a public URL carrying Vista
financials for 9,298 jobs. Anyone may ASK for access — that's what removes the
sharing friction — but nobody sees a number until an administrator says so.
And the credential that lets a companion file mail into shared records is per
person, so a reply finally has an author.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import auth, db, push, records, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANWISE_VISTA_WORKBOOK", "")
    db.reset_for_tests()
    yield
    db.reset_for_tests()


@pytest.fixture
def admin():
    """A signed-in administrator — the bootstrap account, which has no email,
    exactly like the real live instance."""
    c = TestClient(app_module.app)
    auth.bootstrap_admin(auth.setup_token(), "Ross Hixon", "a-good-password")
    assert c.post("/api/auth/login",
                  json={"name": "Ross Hixon", "password": "a-good-password"}).status_code == 200
    return c


def register(client, email="jane@wecc.com", first="Jane", last="Smith",
             password="another-good-password"):
    return client.post("/api/auth/register", json={
        "email": email, "first_name": first, "last_name": last, "password": password})


# --- registering --------------------------------------------------------------

def test_registering_signs_you_in_but_holds_you_pending(admin):
    c = TestClient(app_module.app)
    r = register(c)
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["name"] == "Jane Smith"          # attribution string
    assert user["email"] == "jane@wecc.com"
    assert user["pending"] is True
    assert "password_hash" not in user and "companion_token" not in user

    # A real session exists — the cookie was set...
    status = c.get("/api/auth/status").json()
    assert status["signed_in"] is True
    assert status["pending"] is True

    # ...but it opens no doors at all.
    for path in ["/api/jobs", "/api/users", "/api/outbox", "/api/companion/token"]:
        r = c.get(path)
        assert r.status_code == 403, f"{path} was reachable while pending"
        assert r.json()["pending"] is True


def test_a_pending_user_can_still_change_their_own_password(admin):
    """An admin resetting a pending account's password sets must_change; if
    the change endpoint were gated too, that screen would deadlock."""
    c = TestClient(app_module.app)
    register(c)
    r = c.post("/api/auth/password", json={"current": "another-good-password",
                                           "new": "a-third-good-password"})
    assert r.status_code == 200, r.text


def test_bad_registrations_are_refused_with_a_reason(admin):
    c = TestClient(app_module.app)
    assert register(c, email="not-an-email").status_code == 422
    assert register(c, first="  ").status_code == 422
    assert register(c, password="short").status_code == 422
    assert auth.list_accounts() == [a for a in auth.list_accounts() if a["name"] == "Ross Hixon"]


def test_the_same_email_cannot_register_twice_in_any_case(admin):
    c = TestClient(app_module.app)
    assert register(c, email="jane@wecc.com").status_code == 200
    r = register(TestClient(app_module.app), email="JANE@WECC.COM")
    assert r.status_code == 422
    assert "already has an account" in r.json()["detail"]


def test_two_people_with_the_same_name_both_get_in(admin):
    """users.name is UNIQUE and is the attribution string, so a second Jane
    Smith gets a visible numeral rather than a refusal. The admin tells them
    apart by the email, which is what the approval screen leads with."""
    assert register(TestClient(app_module.app), email="jane1@wecc.com").status_code == 200
    r = register(TestClient(app_module.app), email="jane2@wecc.com")
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "Jane Smith 2"


def test_a_flood_of_requests_is_capped_before_any_password_is_hashed(admin, monkeypatch):
    monkeypatch.setattr(auth, "MAX_PENDING", 3)
    for i in range(3):
        assert register(TestClient(app_module.app), email=f"p{i}@wecc.com").status_code == 200
    r = register(TestClient(app_module.app), email="one-too-many@wecc.com")
    assert r.status_code == 422
    assert "administrator" in r.json()["detail"]


def test_admins_are_pushed_the_email_because_nothing_else_verifies_it(admin, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "send",
                        lambda title, body, **kw: sent.append((title, body, kw)))
    register(TestClient(app_module.app))
    assert len(sent) == 1
    _title, body, kw = sent[0]
    assert "jane@wecc.com" in body                # the identity being approved
    assert kw["user"] == "Ross Hixon"
    assert kw["tag"] == "registrations"           # 500 bots => one notification
    assert kw["url"] == "/#users"


# --- approving and denying ----------------------------------------------------

def test_approval_opens_the_door_without_a_new_sign_in(admin):
    c = TestClient(app_module.app)
    register(c)
    assert c.get("/api/outbox").status_code == 403

    assert admin.post("/api/users/Jane Smith/approved").status_code == 200
    # Same cookie, same session — the gate simply stops refusing.
    assert c.get("/api/auth/status").json()["pending"] is False
    assert c.get("/api/outbox").status_code == 200


def test_denying_a_request_removes_the_account_and_its_session(admin):
    c = TestClient(app_module.app)
    register(c)
    assert admin.delete("/api/users/Jane Smith").status_code == 200
    # The row is gone, so the server cannot say "denied" — it says signed out,
    # which is what the waiting screen falls back on.
    assert c.get("/api/auth/status").json()["signed_in"] is False
    assert auth.get_user("Jane Smith") is None


def test_denying_cleans_up_what_would_otherwise_be_orphaned(admin):
    c = TestClient(app_module.app)
    register(c)
    admin.post("/api/users/Jane Smith/approved")
    push.subscribe("Jane Smith", {"endpoint": "https://push.example/x",
                                  "keys": {"p256dh": "a", "auth": "b"}})
    from backend import outbox
    outbox.queue(job_number="24-003", kind="lookahead", target_id="p1",
                 actor="Jane Smith")

    admin.delete("/api/users/Jane Smith")
    assert push.list_subscriptions("Jane Smith") == []
    assert outbox.pending("Jane Smith") == []
    # The activity trail keeps her name — the record outlives the account.
    assert any("Jane Smith" in (a["detail"] or "")
               for a in store.list_activity(None, 50))


# --- administrators -----------------------------------------------------------

def test_the_last_administrator_cannot_be_removed_or_demoted(admin):
    r = admin.delete("/api/users/Ross Hixon")
    assert r.status_code == 422 and "own account" in r.json()["detail"]

    c = TestClient(app_module.app)
    register(c)
    admin.post("/api/users/Jane Smith/approved")
    admin.post("/api/users/Jane Smith/admin", json={"is_admin": True})
    # Now there are two, so demoting one is fine...
    assert admin.post("/api/users/Jane Smith/admin", json={"is_admin": False}).status_code == 200
    # ...and Ross, alone again, cannot be demoted into an admin-less instance.
    r = admin.post("/api/users/Ross Hixon/admin", json={"is_admin": False})
    assert r.status_code == 422 and "only administrator" in r.json()["detail"]


def test_the_user_list_and_its_controls_are_administrators_only(admin):
    c = TestClient(app_module.app)
    register(c)
    admin.post("/api/users/Jane Smith/approved")

    # Approved, signed in, ordinary: the review queue is not hers to see.
    assert c.get("/api/users").status_code == 403
    assert c.post("/api/users/Ross Hixon/admin", json={"is_admin": False}).status_code == 403
    assert c.delete("/api/users/Ross Hixon").status_code == 403
    assert admin.get("/api/users").status_code == 200


def test_an_email_can_be_backfilled_onto_the_bootstrap_account(admin):
    """Ross's account predates email sign-in. Giving it one is how he starts
    signing in the same way as everyone else."""
    r = admin.post("/api/users/Ross Hixon/email", json={"email": "rhixon@1910legacy.com"})
    assert r.status_code == 200 and r.json()["email"] == "rhixon@1910legacy.com"

    c = TestClient(app_module.app)
    assert c.post("/api/auth/login", json={"name": "rhixon@1910legacy.com",
                                           "password": "a-good-password"}).status_code == 200
    # And the old way still works — one field, two eras.
    assert TestClient(app_module.app).post(
        "/api/auth/login", json={"name": "Ross Hixon",
                                 "password": "a-good-password"}).status_code == 200


def test_an_email_already_in_use_is_refused(admin):
    register(TestClient(app_module.app))
    r = admin.post("/api/users/Ross Hixon/email", json={"email": "jane@wecc.com"})
    assert r.status_code == 422 and "another account" in r.json()["detail"]


# --- companion pairing --------------------------------------------------------

def approved_user(admin, email="jane@wecc.com"):
    c = TestClient(app_module.app)
    name = register(c, email=email).json()["user"]["name"]
    assert admin.post(f"/api/users/{name}/approved").status_code == 200
    return c, name


def test_pairing_exchanges_a_password_for_this_users_own_token(admin):
    _c, name = approved_user(admin)
    r = TestClient(app_module.app).post("/api/auth/companion-pair", json={
        "email": "jane@wecc.com", "password": "another-good-password",
        "device": "JANE-LAPTOP"})
    assert r.status_code == 200
    assert r.json()["user_name"] == name
    token = r.json()["token"]
    assert len(token) > 20

    # Pairing a SECOND PC returns the same token rather than minting a new one.
    # Rotating would silently kill the first PC's companion.
    again = TestClient(app_module.app).post("/api/auth/companion-pair", json={
        "email": "jane@wecc.com", "password": "another-good-password"})
    assert again.json()["token"] == token


def test_pairing_refuses_wrong_passwords_pending_and_disabled_accounts(admin):
    c = TestClient(app_module.app)
    register(c)                                   # still pending
    pair = lambda **kw: TestClient(app_module.app).post("/api/auth/companion-pair", json=kw)

    r = pair(email="jane@wecc.com", password="wrong-password-here")
    assert r.status_code == 401
    assert r.json()["detail"] == "That email and password don't match."   # vague

    r = pair(email="jane@wecc.com", password="another-good-password")
    assert r.status_code == 401 and "approval" in r.json()["detail"]

    admin.post("/api/users/Jane Smith/approved")
    assert pair(email="jane@wecc.com", password="another-good-password").status_code == 200
    auth.set_disabled("Jane Smith", True)
    assert pair(email="jane@wecc.com", password="another-good-password").status_code == 401


def test_a_companion_token_files_replies_AS_the_person_it_belongs_to(admin):
    """The whole point of per-user tokens: until now the server could not tell
    whose Outlook a background reply came from, so every capture recorded
    actor=NULL."""
    _c, name = approved_user(admin)
    token = TestClient(app_module.app).post("/api/auth/companion-pair", json={
        "email": "jane@wecc.com", "password": "another-good-password"}).json()["token"]

    rec = records.add_record("24-003", "rfi", {"title": "Grid B", "number": "RFI-1"},
                             actor="Ross Hixon")
    c = TestClient(app_module.app)
    r = c.post(f"/api/records/{rec['id']}/replies",
               json={"from_email": "gc@customer.com", "body": "Approved as noted.",
                     "received_at": "2026-08-10T09:00:00", "message_id": "m1"},
               headers={"X-PlanWise-Companion": token})
    assert r.status_code == 200, r.text
    assert any(a["actor"] == name and a["action"].endswith("reply")
               for a in store.list_activity("24-003", 20)), \
        "the reply was filed with no author"


def test_a_companion_token_is_not_a_skeleton_key(admin):
    """It buys the two calls a companion makes, and nothing else. Ported from
    the global-token era — the risk is larger now that the token resolves to a
    real user, because a careless hoist would make it a full session."""
    _c, _name = approved_user(admin)
    token = TestClient(app_module.app).post("/api/auth/companion-pair", json={
        "email": "jane@wecc.com", "password": "another-good-password"}).json()["token"]

    c = TestClient(app_module.app)
    headers = {"X-PlanWise-Companion": token}
    for path in ["/api/users", "/api/jobs", "/api/outbox", "/api/companion/token"]:
        assert c.get(path, headers=headers).status_code == 401, f"{path} was reachable"


def test_a_disabled_users_companion_stops_working_immediately(admin):
    _c, name = approved_user(admin)
    token = TestClient(app_module.app).post("/api/auth/companion-pair", json={
        "email": "jane@wecc.com", "password": "another-good-password"}).json()["token"]
    rec = records.add_record("24-003", "rfi", {"title": "x"}, actor="Ross Hixon")

    c = TestClient(app_module.app)
    assert c.post(f"/api/records/{rec['id']}/sent", json={},
                  headers={"X-PlanWise-Companion": token}).status_code != 401
    auth.set_disabled(name, True)
    assert c.post(f"/api/records/{rec['id']}/sent", json={},
                  headers={"X-PlanWise-Companion": token}).status_code == 401


def test_the_poll_manifest_takes_a_per_user_token_by_header_or_query(admin):
    _c, _name = approved_user(admin)
    token = TestClient(app_module.app).post("/api/auth/companion-pair", json={
        "email": "jane@wecc.com", "password": "another-good-password"}).json()["token"]
    c = TestClient(app_module.app)

    assert c.get("/api/companion/poll", params={"token": token}).status_code == 200
    # Header form keeps the credential out of the server's request logs.
    assert c.get("/api/companion/poll",
                 headers={"X-PlanWise-Companion": token}).status_code == 200
    assert c.get("/api/companion/poll", params={"token": "wrong"}).status_code == 401
    assert c.get("/api/companion/poll").status_code == 401


def test_the_legacy_global_token_still_works_during_the_cutover(admin):
    """Installed companions hold the old shared token. Refusing it the moment
    this deploys would stop reply capture on every PC until someone is
    physically at each one. Removed once everyone has re-paired."""
    from backend import ai
    rec = records.add_record("24-003", "rfi", {"title": "x"}, actor="Ross Hixon")
    c = TestClient(app_module.app)
    r = c.post(f"/api/records/{rec['id']}/sent", json={},
               headers={"X-PlanWise-Companion": ai.companion_token()})
    assert r.status_code != 401
    assert c.get("/api/companion/poll",
                 params={"token": ai.companion_token()}).status_code == 200


def test_each_signed_in_user_gets_their_own_companion_token(admin):
    c, name = approved_user(admin)
    mine = admin.get("/api/companion/token").json()
    hers = c.get("/api/companion/token").json()
    assert mine["user_name"] == "Ross Hixon" and hers["user_name"] == name
    assert mine["token"] != hers["token"]
    assert admin.get("/api/companion/token").json()["token"] == mine["token"]  # stable
