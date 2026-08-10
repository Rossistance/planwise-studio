"""Web push notifications (Phase 5e).

The point of a phone in the field is being told something happened without
having to go and look. "Your RFI got a reply" is the highest-value thing
PlanWise can say, so that's what this carries.

iOS has supported Web Push for **home-screen** PWAs since 16.4 — Safari will
not even offer permission until the app has been added to the Home Screen,
which is worth knowing before concluding it's broken.

Keys: a VAPID keypair identifies this server to Apple's and Google's push
services. It's generated once and kept in the data directory beside the other
secrets, so it survives restarts — regenerating it would silently invalidate
every existing subscription.

Failure is never allowed to matter. Sending happens on the back of real work
(a reply landing), and a push service being slow, or a subscription being
stale, must not break the thing that actually mattered.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from . import config, db

log = logging.getLogger("planwise.push")

KEY_FILE = "vapid_key.json"

# Identifies the sender to the push service. A mailto: is what the spec asks
# for so an operator can get in touch about misbehaviour.
CONTACT = "mailto:planwise@1910legacy.com"


class PushUnavailable(RuntimeError):
    """No keypair, or the crypto dependency isn't installed."""


# --- keys --------------------------------------------------------------------

def _keypair() -> dict[str, str]:
    """The server's VAPID keypair, generated on first use and then reused.

    Stored rather than derived: every browser subscription is bound to the
    public key it was created with, so a new keypair would quietly orphan
    every device that had already subscribed.
    """
    path = config.data_dir() / KEY_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        from py_vapid import Vapid01
    except ImportError as exc:                     # pragma: no cover
        raise PushUnavailable(
            "pywebpush is not installed, so notifications are unavailable.") from exc

    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    v = Vapid01()
    v.generate_keys()
    raw_pub = v.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint)
    raw_priv = v.private_key.private_numbers().private_value.to_bytes(32, "big")

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    keys = {"public": b64(raw_pub), "private": b64(raw_priv)}
    path.write_text(json.dumps(keys), encoding="utf-8")
    log.info("generated a new VAPID keypair at %s", path)
    assert ec  # keeps the import meaningful to linters
    return keys


def public_key() -> str | None:
    """What the browser needs to subscribe. None when push can't work here."""
    try:
        return _keypair()["public"]
    except PushUnavailable:
        return None


def available() -> bool:
    return public_key() is not None


# --- subscriptions -----------------------------------------------------------

def subscribe(user: str, subscription: dict[str, Any]) -> dict[str, Any]:
    """Record a device. Keyed on the endpoint, so re-subscribing the same
    device updates it rather than accumulating duplicates that would each
    fire their own copy of every notification."""
    endpoint = (subscription or {}).get("endpoint")
    keys = (subscription or {}).get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("That is not a usable push subscription.")

    conn = db.connect()
    conn.execute(
        "INSERT INTO push_subscriptions (endpoint, user_name, p256dh, auth, created_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(endpoint) DO UPDATE SET user_name = excluded.user_name, "
        "p256dh = excluded.p256dh, auth = excluded.auth",
        (endpoint, user, keys["p256dh"], keys["auth"], db.now()))
    conn.commit()
    return {"endpoint": endpoint, "user": user}


def unsubscribe(endpoint: str) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
    return cur.rowcount > 0


def list_subscriptions(user: str | None = None) -> list[dict[str, Any]]:
    conn = db.connect()
    if user:
        rows = conn.execute("SELECT * FROM push_subscriptions WHERE user_name = ?", (user,))
    else:
        rows = conn.execute("SELECT * FROM push_subscriptions")
    return [dict(r) for r in rows]


# --- sending -----------------------------------------------------------------

def send(title: str, body: str, *, url: str = "/", tag: str | None = None,
         user: str | None = None) -> dict[str, int]:
    """Notify every subscribed device (or one user's devices).

    Returns counts rather than raising: this is always called on the back of
    something that already succeeded, and a push service having a bad day must
    not turn a captured reply into an error. Subscriptions the service reports
    as gone (404/410) are deleted — that's how a browser tells you the device
    uninstalled the app or cleared its data.
    """
    subs = list_subscriptions(user)
    if not subs:
        return {"sent": 0, "failed": 0, "pruned": 0}

    try:
        from pywebpush import WebPushException, webpush
        keys = _keypair()
    except (ImportError, PushUnavailable):
        log.info("push unavailable; %d subscription(s) not notified", len(subs))
        return {"sent": 0, "failed": len(subs), "pruned": 0}

    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    sent = failed = pruned = 0
    for s in subs:
        try:
            webpush(
                subscription_info={"endpoint": s["endpoint"],
                                   "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                data=payload,
                vapid_private_key=keys["private"],
                vapid_claims={"sub": CONTACT},
                timeout=10)
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                unsubscribe(s["endpoint"])
                pruned += 1
            else:
                failed += 1
                log.warning("push to %s failed (%s)", s["endpoint"][:40], status or exc)
        except Exception as exc:                   # noqa: BLE001 - never fatal
            failed += 1
            log.warning("push error: %s", exc)
    return {"sent": sent, "failed": failed, "pruned": pruned}
