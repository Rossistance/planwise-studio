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
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config, db

COOKIE = "planwise_session"
SESSION_DAYS = 30
SETUP_TOKEN_FILE = "setup_token.txt"

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

def get_user(name: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE name = ? COLLATE NOCASE",
                       (name.strip(),)).fetchone()
    return dict(row) if row else None


def list_accounts() -> list[dict[str, Any]]:
    """Never leaks a hash — the API layer has no business seeing one."""
    conn = db.connect()
    return [{"id": r["id"], "name": r["name"],
             "is_admin": bool(r["is_admin"]), "disabled": bool(r["disabled"]),
             "has_password": bool(r["password_hash"]),
             "must_change_password": bool(r["must_change_password"]),
             "created_at": r["created_at"]}
            for r in conn.execute("SELECT * FROM users ORDER BY name")]


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


def login(name: str, password: str) -> tuple[str, dict[str, Any]]:
    """Returns (session token, user). Failure is deliberately vague: naming
    which half was wrong tells an attacker which accounts exist."""
    user = get_user(name)
    if user is None or user.get("disabled") or not verify_password(password, user.get("password_hash")):
        raise AuthError("That name and password don't match.")

    token = secrets.token_urlsafe(32)
    conn = db.connect()
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, last_seen, expires_at) "
        "VALUES (?,?,?,?,?)",
        (token, user["id"], db.now(), db.now(),
         (_now() + timedelta(days=SESSION_DAYS)).isoformat()))
    conn.commit()
    db.log_activity(user["name"], None, "auth.login", user["name"])
    return token, {"id": user["id"], "name": user["name"],
                   "is_admin": bool(user.get("is_admin")),
                   "must_change_password": bool(user.get("must_change_password"))}


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
    return {"id": row["id"], "name": row["name"],
            "is_admin": bool(row["is_admin"]),
            "must_change_password": bool(row["must_change_password"])}


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
