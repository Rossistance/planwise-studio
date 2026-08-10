"""Per-user accounts and sessions (Phase 5a)."""
from __future__ import annotations

import pytest

from backend import auth, db


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


# --- password hashing ---------------------------------------------------------

def test_hashes_are_salted_and_verify_both_ways():
    a = auth.hash_password("correct horse battery")
    b = auth.hash_password("correct horse battery")
    assert a != b                                   # per-user salt, not a lookup table
    assert a.startswith("pbkdf2_sha256$")
    assert "correct horse battery" not in a         # never the plaintext
    assert auth.verify_password("correct horse battery", a)
    assert auth.verify_password("correct horse battery", b)
    assert not auth.verify_password("Correct Horse Battery", a)
    assert not auth.verify_password("", a)


def test_a_user_with_no_password_can_never_match():
    """The pre-Phase-5 rows have no hash. They must not become open doors."""
    assert not auth.verify_password("anything", None)
    assert not auth.verify_password("anything", "")
    assert not auth.verify_password("", None)


def test_garbage_hashes_are_rejected_not_crashed_on():
    for junk in ("plaintext", "a$b$c", "pbkdf2_sha256$notanint$x$y", "$$$", "bcrypt$1$a$b"):
        assert not auth.verify_password("x", junk)


def test_short_passwords_are_refused():
    with pytest.raises(auth.AuthError, match="8 characters"):
        auth.hash_password("short")


# --- bootstrap ----------------------------------------------------------------

def test_first_admin_needs_the_setup_token_from_the_server():
    """Whoever finds the URL first must not be able to claim the instance."""
    token = auth.setup_token()
    assert token and len(token) > 20
    assert auth.setup_token() == token              # stable until used
    assert not auth.admin_exists()

    with pytest.raises(auth.AuthError, match="not valid"):
        auth.bootstrap_admin("wrong-token", "Ross Hixon", "a-good-password")
    assert not auth.admin_exists()

    acct = auth.bootstrap_admin(token, "Ross Hixon", "a-good-password")
    assert acct["is_admin"] is True
    assert auth.admin_exists()

    # the token is spent, and a second claim is refused
    assert auth.setup_token() is None
    with pytest.raises(auth.AuthError, match="already has an administrator"):
        auth.bootstrap_admin(token, "Someone Else", "another-password")


def test_bootstrap_adopts_an_existing_named_user():
    """Names already exist from the header-identity era; claiming one must
    keep its id so the activity trail stays attached."""
    db.connect().execute("INSERT INTO users (id, name, created_at) VALUES (?,?,?)",
                         ("u1", "Ross Hixon", db.now()))
    db.connect().commit()
    auth.bootstrap_admin(auth.setup_token(), "Ross Hixon", "a-good-password")
    user = auth.get_user("Ross Hixon")
    assert user["id"] == "u1"                       # same row, not a duplicate
    assert user["is_admin"] == 1
    assert len(auth.list_accounts()) == 1


# --- login / sessions ---------------------------------------------------------

def signed_in(name="Ross Hixon", password="a-good-password"):
    if not auth.admin_exists():
        auth.bootstrap_admin(auth.setup_token(), name, password)
    return auth.login(name, password)


def test_login_returns_a_session_that_resolves_back_to_the_user():
    token, user = signed_in()
    assert user["name"] == "Ross Hixon"
    assert len(token) > 30
    assert auth.session_user(token)["name"] == "Ross Hixon"


def test_login_failure_does_not_say_which_half_was_wrong():
    signed_in()
    for name, pw in [("Ross Hixon", "wrong"), ("Nobody At All", "a-good-password")]:
        with pytest.raises(auth.AuthError) as exc:
            auth.login(name, pw)
        assert "don't match" in str(exc.value)      # same message either way


def test_unknown_expired_and_missing_tokens_resolve_to_nobody():
    from datetime import datetime, timedelta, timezone

    token, _ = signed_in()
    assert auth.session_user(None) is None
    assert auth.session_user("") is None
    assert auth.session_user("not-a-real-token") is None

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    db.connect().execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (past, token))
    db.connect().commit()
    assert auth.session_user(token) is None
    # and the dead row is cleaned up rather than left to accumulate
    assert db.connect().execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"] == 0


def test_logout_kills_only_that_session():
    signed_in()
    a, _ = auth.login("Ross Hixon", "a-good-password")
    b, _ = auth.login("Ross Hixon", "a-good-password")
    auth.logout(a)
    assert auth.session_user(a) is None
    assert auth.session_user(b) is not None         # the other device stays signed in


def test_changing_a_password_signs_every_device_out():
    """You change a password because you think someone else has it."""
    signed_in()
    a, _ = auth.login("Ross Hixon", "a-good-password")
    b, _ = auth.login("Ross Hixon", "a-good-password")

    with pytest.raises(auth.AuthError, match="not correct"):
        auth.change_password("Ross Hixon", "wrong-current", "brand-new-password")

    auth.change_password("Ross Hixon", "a-good-password", "brand-new-password")
    assert auth.session_user(a) is None
    assert auth.session_user(b) is None
    with pytest.raises(auth.AuthError):
        auth.login("Ross Hixon", "a-good-password")
    assert auth.login("Ross Hixon", "brand-new-password")[1]["name"] == "Ross Hixon"


# --- account management -------------------------------------------------------

def test_admin_created_accounts_must_change_their_temporary_password():
    signed_in()
    acct = auth.create_account("Field Leader", "temp-password-1", actor="Ross Hixon")
    assert acct["must_change_password"] is True
    assert "password_hash" not in acct              # never handed back

    _tok, user = auth.login("Field Leader", "temp-password-1")
    assert user["must_change_password"] is True
    assert user["is_admin"] is False

    auth.change_password("Field Leader", "temp-password-1", "their-own-password")
    assert auth.login("Field Leader", "their-own-password")[1]["must_change_password"] is False


def test_duplicate_accounts_are_refused():
    signed_in()
    auth.create_account("Field Leader", "temp-password-1")
    with pytest.raises(auth.AuthError, match="already has an account"):
        auth.create_account("field leader", "temp-password-2")   # case-insensitive


def test_disabling_an_account_revokes_its_live_sessions():
    """Someone walking out of the building must not keep a working cookie."""
    signed_in()
    auth.create_account("Field Leader", "temp-password-1")
    token, _ = auth.login("Field Leader", "temp-password-1")
    assert auth.session_user(token) is not None

    assert auth.set_disabled("Field Leader", True, actor="Ross Hixon") is True
    assert auth.session_user(token) is None
    with pytest.raises(auth.AuthError):
        auth.login("Field Leader", "temp-password-1")

    auth.set_disabled("Field Leader", False)
    assert auth.login("Field Leader", "temp-password-1")[1]["name"] == "Field Leader"


def test_listing_accounts_never_exposes_a_hash():
    signed_in()
    auth.create_account("Field Leader", "temp-password-1")
    rows = auth.list_accounts()
    assert {r["name"] for r in rows} == {"Ross Hixon", "Field Leader"}
    for r in rows:
        assert "password_hash" not in r
        assert r["has_password"] is True


def test_purge_expired_clears_only_dead_sessions():
    from datetime import datetime, timedelta, timezone

    signed_in()
    live, _ = auth.login("Ross Hixon", "a-good-password")
    dead, _ = auth.login("Ross Hixon", "a-good-password")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    db.connect().execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (past, dead))
    db.connect().commit()

    assert auth.purge_expired() == 1
    assert auth.session_user(live) is not None
