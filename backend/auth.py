"""Per-user authentication (Phase 5a).

Until now identity was a name in a header — decision D9 said so plainly:
*"not authentication; an internal-LAN accountability tool."* That was correct
for a LAN. PlanWise is moving to a public URL, where the same design would put
Vista financials for 9,298 jobs, customer drawings and RFI correspondence
behind nothing but an unguessable address.

So: real accounts, on top of the named identity that already drives the
activity trail. Passwords are PBKDF2-HMAC-SHA256 (stdlib — no new dependency
to break behind corporate TLS inspection) at the OWASP-recommended iteration
count, with a per-user salt. Sessions are opaque random tokens in an HttpOnly
cookie, so no credential is readable from JavaScript and XSS cannot lift one.

Entra SSO would be stronger still, but it needs a tenant app registration —
the exact dependency D10 was designed to avoid. This keeps PlanWise
self-contained.

**Bootstrap.** A fresh instance has no accounts, and whoever reaches the URL
first must not simply be able to claim it. On startup, if no admin exists, a
one-time setup token is written to the data directory — the same pattern as
the companion pairing token, which the team already knows. Creating the first
admin requires that token, so it requires filesystem access to the server.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config, db

COOKIE = "planwise_session"
SESSION_DAYS = 30
SETUP_TOKEN_FILE = "setup_token.txt"

# Deliberately loose: the point is catching typos ("ross@wecc"), not policing
# RFC 5322. With no server-side mail there is no verification step — the
# admin's approval screen, which leads with the address, IS the verification.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Registration is open to the internet by design (that's what self-service
# means), so it gets a bound: with this many strangers already waiting, new
# requests are turned away before any CPU is spent hashing their passwords.
MAX_PENDING = 20

# OWASP's 2023 floor for PBKDF2-HMAC-SHA256. Costs ~0.2s per login here,
# which is invisible to a human and expensive for a guesser.
_ITERATIONS = 600_000
_ALGO = "pbkdf2_sha256"


class AuthError(Exception):
    """Raised for anything the caller is allowed to hear about verbatim."""


# --- passwords ---------------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str, *, iterations: int = _ITERATIONS) -> str:
    """`pbkdf2_sha256$<iterations>$<salt>$<hash>` — self-describing, so the
    iteration count can be raised later without invalidating old hashes."""
    if not password or len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{_ALGO}${iterations}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. A user with no password set can never match."""
    if not stored:
        return False
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode(),
                                 _unb64(salt_b64), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, _unb64(hash_b64))


# --- accounts ----------------------------------------------------------------

def _public(row: dict[str, Any]) -> dict[str, Any]:
    """The over-the-API shape: booleans not 1/0, and never a hash or a
    companion token."""
    return {"id": row["id"], "name": row["name"],
            "email": row.get("email"),
            "is_admin": bool(row.get("is_admin")),
            "disabled": bool(row.get("disabled")),
            "pending": bool(row.get("pending")),
            "must_change_password": bool(row.get("must_change_password"))}


def get_user(name: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE name = ? COLLATE NOCASE",
                       (name.strip(),)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    # NOCASE in the query, not just the index: the index expression governs
    # uniqueness, but a lookup only ignores case if it says so itself.
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE",
                       ((email or "").strip(),)).fetchone()
    return dict(row) if row else None


def resolve_user(identifier: str) -> dict[str, Any] | None:
    """One sign-in field for two eras: email is the identity now, but the
    accounts that predate it (the bootstrap admin) still match by name."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    return (get_user_by_email(identifier) if "@" in identifier else None) \
        or get_user(identifier)


def list_accounts() -> list[dict[str, Any]]:
    """Never leaks a hash — the API layer has no business seeing one."""
    conn = db.connect()
    return [{"id": r["id"], "name": r["name"], "email": r["email"],
             "first_name": r["first_name"], "last_name": r["last_name"],
             "is_admin": bool(r["is_admin"]), "disabled": bool(r["disabled"]),
             "pending": bool(r["pending"]),
             "has_password": bool(r["password_hash"]),
             "must_change_password": bool(r["must_change_password"]),
             "created_at": r["created_at"]}
            for r in conn.execute(
                "SELECT * FROM users ORDER BY pending DESC, name")]


def set_password(name: str, password: str, *, must_change: bool = False) -> None:
    conn = db.connect()
    cur = conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = ? "
        "WHERE name = ? COLLATE NOCASE",
        (hash_password(password), 1 if must_change else 0, name.strip()))
    conn.commit()
    if cur.rowcount == 0:
        raise AuthError(f"No such user: {name}")


def create_account(name: str, password: str, *, is_admin: bool = False,
                   must_change: bool = True, actor: str | None = None) -> dict[str, Any]:
    """Admin-created accounts start with a temporary password the person is
    made to change on first sign-in, so the admin never knows it afterwards."""
    name = (name or "").strip()
    if not name:
        raise AuthError("A name is required.")
    if get_user(name):
        raise AuthError(f"{name} already has an account.")
    rec = {"id": db.new_id(), "name": name, "created_at": db.now(),
           "password_hash": hash_password(password),
           "is_admin": 1 if is_admin else 0, "disabled": 0,
           "must_change_password": 1 if must_change else 0}
    conn = db.connect()
    cols = ", ".join(rec)
    conn.execute(f"INSERT INTO users ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                 tuple(rec.values()))
    conn.commit()
    db.log_activity(actor, None, "auth.account.create", name)
    # Booleans, not SQLite's 1/0 — this shape goes straight out over the API.
    return {"id": rec["id"], "name": rec["name"], "created_at": rec["created_at"],
            "is_admin": bool(rec["is_admin"]), "disabled": False,
            "must_change_password": bool(rec["must_change_password"])}


def set_disabled(name: str, disabled: bool, actor: str | None = None) -> bool:
    """Disabling kills the account's live sessions too — otherwise someone
    walked out of the building still holding a valid cookie."""
    conn = db.connect()
    cur = conn.execute("UPDATE users SET disabled = ? WHERE name = ? COLLATE NOCASE",
                       (1 if disabled else 0, name.strip()))
    if disabled:
        user = get_user(name)
        if user:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    conn.commit()
    db.log_activity(actor, None, "auth.account.disable" if disabled else
                    "auth.account.enable", name)
    return cur.rowcount > 0


# --- self-service registration (zero-token access, 2026-08-10) -----------------

def pending_count() -> int:
    conn = db.connect()
    return conn.execute("SELECT COUNT(*) c FROM users WHERE pending = 1 "
                        "AND disabled = 0").fetchone()["c"]


def register(email: str, first_name: str, last_name: str,
             password: str) -> dict[str, Any]:
    """Create your own account. It works immediately — but pending, so the
    waiting screen is what you see until an admin approves you.

    Display name is "First Last" — the attribution string used everywhere.
    users.name is UNIQUE (binary), so a second John Smith gets a visible
    numeral rather than a refusal; the admin judges identity by the email at
    approval time anyway. The insert retries on IntegrityError rather than
    trusting a pre-check — two simultaneous John Smiths must both land.
    """
    email = (email or "").strip()
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if not _EMAIL_RE.match(email):
        raise AuthError("That doesn't look like an email address.")
    if not first or not last:
        raise AuthError("First and last name are both required.")

    # Bounds before the expensive hash: a flood of strangers must not become
    # a CPU bill, and 500 bot sign-ups collapse into "ask your administrator".
    if pending_count() >= MAX_PENDING:
        raise AuthError("Too many access requests are already waiting. "
                        "Ask your administrator to review them first.")
    if get_user_by_email(email):
        raise AuthError("That email already has an account. Try signing in.")

    pw_hash = hash_password(password)
    base = f"{first} {last}"
    conn = db.connect()
    for attempt in range(50):
        name = base if attempt == 0 else f"{base} {attempt + 1}"
        rec = {"id": db.new_id(), "name": name, "created_at": db.now(),
               "password_hash": pw_hash, "is_admin": 0, "disabled": 0,
               "must_change_password": 0, "email": email,
               "first_name": first, "last_name": last, "pending": 1}
        try:
            cols = ", ".join(rec)
            conn.execute(f"INSERT INTO users ({cols}) VALUES ({','.join('?' * len(rec))})",  # noqa: S608
                         tuple(rec.values()))
            conn.commit()
            break
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            if "users.name" in str(exc):
                continue                    # display-name taken: add a numeral
            # The only other unique thing is the email index — a racing twin
            # registration got there first.
            raise AuthError("That email already has an account. Try signing in.") from exc
    else:
        raise AuthError("Couldn't find a free display name — ask your administrator.")

    db.log_activity(name, None, "auth.account.register", f"{name} <{email}>")
    return _public(rec)


def approve_account(name: str, actor: str | None = None) -> dict[str, Any] | None:
    conn = db.connect()
    cur = conn.execute("UPDATE users SET pending = 0 WHERE name = ? COLLATE NOCASE",
                       (name.strip(),))
    conn.commit()
    if cur.rowcount == 0:
        return None
    user = get_user(name)
    db.log_activity(actor, None, "auth.account.approve",
                    f"{user['name']} <{user.get('email') or 'no email'}>")
    return _public(user)


def _last_enabled_admin(user: dict[str, Any]) -> bool:
    """Would removing/demoting/disabling this account leave no working admin?"""
    if not user.get("is_admin") or user.get("disabled"):
        return False
    conn = db.connect()
    others = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE is_admin = 1 AND disabled = 0 "
        "AND pending IS NOT 1 AND id != ?", (user["id"],)).fetchone()["c"]
    return others == 0


def delete_account(name: str, actor: str | None = None) -> bool:
    """Deny a request, or remove an account outright.

    Everything that answers to the account dies with it — sessions (no FK, so
    by hand), push subscriptions, and its undrafted outbox items (invisible
    forever otherwise: pending() scopes by author). The historical activity
    trail keeps its name strings deliberately — the record outlives the
    account.
    """
    user = get_user(name)
    if user is None:
        return False
    if _last_enabled_admin(user):
        raise AuthError("That is the only administrator. Make someone else "
                        "an admin first.")
    conn = db.connect()
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    conn.execute("DELETE FROM push_subscriptions WHERE user_name = ?", (user["name"],))
    conn.execute("DELETE FROM outbox WHERE queued_by = ? AND drafted_at IS NULL",
                 (user["name"],))
    conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    conn.commit()
    db.log_activity(actor, None, "auth.account.delete",
                    f"{user['name']} <{user.get('email') or 'no email'}>")
    return True


def set_admin(name: str, is_admin: bool, actor: str | None = None) -> bool:
    user = get_user(name)
    if user is None:
        return False
    if not is_admin and _last_enabled_admin(user):
        raise AuthError("That is the only administrator. Make someone else "
                        "an admin first.")
    conn = db.connect()
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?",
                 (1 if is_admin else 0, user["id"]))
    conn.commit()
    db.log_activity(actor, None,
                    "auth.account.admin" if is_admin else "auth.account.unadmin",
                    user["name"])
    return True


def set_email(name: str, email: str, actor: str | None = None) -> dict[str, Any]:
    """Backfill or correct an address — how the bootstrap account, which
    predates email sign-in, gets one."""
    email = (email or "").strip()
    if not _EMAIL_RE.match(email):
        raise AuthError("That doesn't look like an email address.")
    user = get_user(name)
    if user is None:
        raise AuthError(f"No such user: {name}")
    other = get_user_by_email(email)
    if other and other["id"] != user["id"]:
        raise AuthError("That email already belongs to another account.")
    conn = db.connect()
    conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, user["id"]))
    conn.commit()
    db.log_activity(actor, None, "auth.account.email", f"{user['name']} <{email}>")
    return _public({**user, "email": email})


def admin_exists() -> bool:
    conn = db.connect()
    row = conn.execute("SELECT 1 FROM users WHERE is_admin = 1 "
                       "AND password_hash IS NOT NULL LIMIT 1").fetchone()
    return row is not None


# --- first-admin bootstrap ---------------------------------------------------

def setup_token() -> str | None:
    """The token that authorises creating the first admin, or None once one
    exists. Written to the data directory, so claiming a fresh instance needs
    access to the server rather than merely knowing its URL."""
    if admin_exists():
        return None
    path = config.data_dir() / SETUP_TOKEN_FILE
    if not path.exists():
        path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def bootstrap_admin(token: str, name: str, password: str) -> dict[str, Any]:
    expected = setup_token()
    if expected is None:
        raise AuthError("This instance already has an administrator.")
    if not hmac.compare_digest((token or "").strip(), expected):
        raise AuthError("That setup token is not valid.")

    existing = get_user(name)
    if existing:
        set_password(name, password)
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin = 1, disabled = 0, "
                     "must_change_password = 0 WHERE id = ?", (existing["id"],))
        conn.commit()
        account = {"id": existing["id"], "name": existing["name"], "is_admin": True}
    else:
        account = create_account(name, password, is_admin=True, must_change=False)

    (config.data_dir() / SETUP_TOKEN_FILE).unlink(missing_ok=True)
    db.log_activity(name, None, "auth.bootstrap", name)
    return account


# --- sessions ----------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue_session(user: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(32)
    conn = db.connect()
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, last_seen, expires_at) "
        "VALUES (?,?,?,?,?)",
        (token, user["id"], db.now(), db.now(),
         (_now() + timedelta(days=SESSION_DAYS)).isoformat()))
    conn.commit()
    return token


def _verify_credentials(identifier: str, password: str) -> dict[str, Any]:
    """Email-or-name plus password, or the one deliberately vague refusal.

    Shared by sign-in and companion pairing so there is exactly one oracle,
    saying exactly one thing. A pending account still verifies — what a
    pending session may DO is the middleware's decision, not this one's.
    """
    user = resolve_user(identifier)
    if user is None or user.get("disabled") \
            or not verify_password(password, user.get("password_hash")):
        raise AuthError("That email and password don't match.")
    return user


def login(name: str, password: str) -> tuple[str, dict[str, Any]]:
    """Returns (session token, user). Failure is deliberately vague: naming
    which half was wrong tells an attacker which accounts exist."""
    user = _verify_credentials(name, password)
    token = issue_session(user)
    db.log_activity(user["name"], None, "auth.login", user["name"])
    return token, _public(user)


def session_user(token: str | None) -> dict[str, Any] | None:
    """Resolve a cookie to a live user, sliding the expiry forward. Returns
    None for anything expired, unknown, or belonging to a disabled account."""
    if not token:
        return None
    conn = db.connect()
    row = conn.execute(
        "SELECT s.token, s.expires_at, u.* FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token = ?", (token,)).fetchone()
    if row is None or row["disabled"]:
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) < _now():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
    except (TypeError, ValueError):
        return None

    conn.execute("UPDATE sessions SET last_seen = ?, expires_at = ? WHERE token = ?",
                 (db.now(), (_now() + timedelta(days=SESSION_DAYS)).isoformat(), token))
    conn.commit()
    return _public(dict(row))


def logout(token: str | None) -> None:
    if not token:
        return
    conn = db.connect()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def change_password(name: str, current: str, new: str) -> None:
    user = get_user(name)
    if user is None or not verify_password(current, user.get("password_hash")):
        raise AuthError("Your current password is not correct.")
    set_password(name, new, must_change=False)
    # Every other session for this account dies — changing a password is what
    # you do when you think someone else has it.
    conn = db.connect()
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    conn.commit()
    db.log_activity(name, None, "auth.password.change", name)


def purge_expired() -> int:
    conn = db.connect()
    cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))
    conn.commit()
    return cur.rowcount


# --- companion pairing (zero-token access, 2026-08-10) -------------------------
# The global pairing token is gone. Each user has at most ONE companion token,
# minted on demand and never rotated by pairing: it is per-user, not
# per-device, so pairing a second PC returns the same token rather than
# silently killing the first PC's pairing. Revocation = clearing the column.

def companion_token_for(user_id: str) -> str:
    conn = db.connect()
    row = conn.execute("SELECT companion_token FROM users WHERE id = ?",
                       (user_id,)).fetchone()
    if row is None:
        raise AuthError("No such user.")
    if row["companion_token"]:
        return row["companion_token"]
    token = secrets.token_urlsafe(24)
    conn.execute("UPDATE users SET companion_token = ? WHERE id = ? "
                 "AND companion_token IS NULL", (token, user_id))
    conn.commit()
    # Mint-once even under a race: whoever's UPDATE landed first wins.
    return conn.execute("SELECT companion_token FROM users WHERE id = ?",
                        (user_id,)).fetchone()["companion_token"]


def user_by_companion_token(token: str | None) -> dict[str, Any] | None:
    """The user a presented companion token belongs to — or None.

    Disabled and pending accounts resolve to None: a token minted while an
    account was in good standing must die the moment the account isn't.
    """
    if not token:
        return None
    conn = db.connect()
    row = conn.execute(
        "SELECT * FROM users WHERE companion_token = ? AND disabled = 0 "
        "AND pending IS NOT 1", (token,)).fetchone()
    if row is None:
        return None
    # The indexed lookup found the row; compare again in constant time so the
    # equality the security rests on is never the index's.
    if not hmac.compare_digest(row["companion_token"], token):
        return None
    return dict(row)


def reset_companion_token(name: str, actor: str | None = None) -> bool:
    """Un-pair every PC this account's companion runs on. The next pairing
    mints a fresh token."""
    user = get_user(name)
    if user is None:
        return False
    conn = db.connect()
    conn.execute("UPDATE users SET companion_token = NULL WHERE id = ?", (user["id"],))
    conn.commit()
    db.log_activity(actor, None, "auth.companion.reset", user["name"])
    return True


def companion_pair(identifier: str, password: str,
                   device: str | None = None) -> dict[str, Any]:
    """Exchange sign-in credentials for the companion token — what the
    companion's pairing page calls instead of asking anyone to paste a secret.

    Pending accounts are refused here even though they can sign IN: an
    unapproved stranger must not acquire the credential that files mail into
    the shared records.
    """
    user = _verify_credentials(identifier, password)
    if user.get("pending"):
        raise AuthError("This account is still waiting for approval — "
                        "pair the companion once you're in.")
    token = companion_token_for(user["id"])
    db.log_activity(user["name"], None, "auth.companion.pair",
                    f"{user['name']} on {device or 'unnamed PC'}")
    return {"token": token, "user_name": user["name"]}
