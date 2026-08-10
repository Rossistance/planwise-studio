"""AI layer (Phase 3b, decision D13).

Dual-provider — all Anthropic and all OpenAI models, selectable in Settings —
behind one shared company key per provider, a monthly team spend gate, and a
deterministic template fallback so the pipeline works (and is testable) with
no key and no spend at all.

Direct REST via httpx; no provider SDKs to keep the dependency surface flat.
"""
from __future__ import annotations

import calendar
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from . import db

DEFAULTS = {
    "ai_provider": "anthropic",
    "ai_model_anthropic": "claude-sonnet-5",
    "ai_model_openai": "gpt-5.5",
    "ai_spend_cap_monthly": "100",   # USD; conservative until Ross sets one
    "anthropic_api_key": "",
    "openai_api_key": "",
    # Background reply polling, run by each user's companion.
    "reply_poll_enabled": "1",
    # Seconds, not minutes: since the companion watches Outlook events
    # directly (D35) this sweep is only a backstop, and a cheap one —
    # already-filed messages are skipped rather than rebuilt.
    "reply_poll_seconds": "15",
}
SECRET_KEYS = {"anthropic_api_key", "openai_api_key", "companion_token"}

# Rough blended $/M-token used for the gate. The gate is a budget backstop,
# not an invoice — costs are labeled estimates everywhere they surface.
EST_IN_PER_M = 3.0
EST_OUT_PER_M = 15.0


class AIError(RuntimeError):
    pass


class SpendCapReached(AIError):
    pass


# --- settings ---------------------------------------------------------------

def get_settings(mask: bool = True) -> dict[str, str]:
    conn = db.connect()
    vals = dict(DEFAULTS)
    for row in conn.execute("SELECT key, value FROM settings"):
        vals[row["key"]] = row["value"] or ""
    if mask:
        for k in SECRET_KEYS & vals.keys():
            v = vals[k]
            vals[k] = (v[:6] + "…" + v[-4:]) if len(v) > 12 else ("set" if v else "")
    return vals


def patch_settings(fields: dict[str, Any], actor: str | None = None) -> dict[str, str]:
    conn = db.connect()
    for k, v in fields.items():
        if k not in DEFAULTS:
            continue
        # a masked value round-tripped from the UI must not clobber the secret
        if k in SECRET_KEYS and ("…" in str(v) or str(v) == "set"):
            continue
        conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (k, str(v)))
    conn.commit()
    db.log_activity(actor, None, "settings.update",
                    ", ".join(k for k in fields if k in DEFAULTS))
    return get_settings()


def companion_token() -> str:
    """Shared secret between the web app and each user's local companion.
    Generated once; foreign browser origins can't read it (CORS), so a
    drive-by page can't puppet the user's Outlook through the companion."""
    conn = db.connect()
    row = conn.execute("SELECT value FROM settings WHERE key = 'companion_token'").fetchone()
    if row and row["value"]:
        return row["value"]
    token = secrets.token_urlsafe(24)
    conn.execute("INSERT INTO settings (key, value) VALUES ('companion_token', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (token,))
    conn.commit()
    # Convenience pairing for the machine hosting the server (today: Ross's
    # PC): drop the token where the local companion reads it. MUST go through
    # data_dir() — writing to Path.home() directly let the test suite (which
    # redirects data_dir to a tmp dir but not home) clobber the real pairing
    # file with a throwaway token on every pytest run. Other users copy the
    # token from Settings into their own ~/.planwise/companion_token.txt.
    try:
        from . import config
        f = config.data_dir() / "companion_token.txt"
        f.write_text(token, encoding="utf-8")
    except OSError:
        pass
    return token


# --- spend gate -------------------------------------------------------------

def month_spend() -> float:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    conn = db.connect()
    row = conn.execute("SELECT COALESCE(SUM(cost_est), 0) c FROM ai_spend WHERE ts >= ?",
                       (start.isoformat(),)).fetchone()
    return float(row["c"])


def spend_status() -> dict[str, Any]:
    cap = float(get_settings()["ai_spend_cap_monthly"] or 0)
    spent = month_spend()
    now = datetime.now(timezone.utc)
    return {"cap": cap, "spent_est": round(spent, 4),
            "remaining_est": round(max(0.0, cap - spent), 4),
            "month": f"{now.year}-{now.month:02d}",
            "days_left": calendar.monthrange(now.year, now.month)[1] - now.day}


def _check_gate() -> None:
    s = spend_status()
    if s["cap"] > 0 and s["spent_est"] >= s["cap"]:
        raise SpendCapReached(
            f"The team's monthly AI budget (${s['cap']:.2f}) is spent "
            f"(~${s['spent_est']:.2f} this month). Drafting falls back to "
            "templates until the cap is raised in Settings or the month rolls.")


def _record_spend(provider: str, model: str, tokens_in: int, tokens_out: int,
                  purpose: str) -> None:
    cost = tokens_in / 1e6 * EST_IN_PER_M + tokens_out / 1e6 * EST_OUT_PER_M
    conn = db.connect()
    conn.execute("INSERT INTO ai_spend (ts, provider, model, tokens_in, tokens_out, cost_est, purpose) "
                 "VALUES (?,?,?,?,?,?,?)",
                 (db.now(), provider, model, tokens_in, tokens_out, round(cost, 6), purpose))
    conn.commit()


# --- providers --------------------------------------------------------------

_ssl_ctx = None


def _ssl_context():
    """Trust the OS certificate store, not certifi's bundle.

    On a managed Windows machine TLS inspection re-signs outbound HTTPS with a
    corporate root that lives in the Windows store — certifi has never heard of
    it, so every provider call died with CERTIFICATE_VERIFY_FAILED. truststore
    hands verification to the OS, which does know that root.
    """
    global _ssl_ctx
    if _ssl_ctx is None:
        import ssl
        try:
            import truststore
            _ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            _ssl_ctx = True  # httpx default verification
    return _ssl_ctx


def _complete(prompt: str, purpose: str, max_tokens: int = 1500) -> str:
    """One completion through the configured provider.

    Every failure — no key, HTTP error, TLS, timeout, malformed response —
    surfaces as AIError so callers have exactly one thing to catch and can
    fall back deterministically.
    """
    try:
        return _complete_inner(prompt, purpose, max_tokens)
    except (AIError, SpendCapReached):
        raise
    except Exception as exc:  # noqa: BLE001 — provider/network faults are expected
        raise AIError(f"{type(exc).__name__}: {exc}") from exc


def _complete_inner(prompt: str, purpose: str, max_tokens: int) -> str:
    _check_gate()
    s = get_settings(mask=False)
    provider = s["ai_provider"]
    import httpx

    if provider == "anthropic":
        key = s["anthropic_api_key"]
        if not key:
            raise AIError("No Anthropic API key configured.")
        model = s["ai_model_anthropic"]
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                       json={"model": model, "max_tokens": max_tokens,
                             "messages": [{"role": "user", "content": prompt}]},
                       timeout=90, verify=_ssl_context())
        if r.status_code != 200:
            raise AIError(f"Anthropic {r.status_code}: {r.text[:300]}")
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        usage = data.get("usage", {})
        _record_spend("anthropic", model, usage.get("input_tokens", 0),
                      usage.get("output_tokens", 0), purpose)
        return text

    key = s["openai_api_key"]
    if not key:
        raise AIError("No OpenAI API key configured.")
    model = s["ai_model_openai"]
    r = httpx.post("https://api.openai.com/v1/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "max_completion_tokens": max_tokens,
                         "messages": [{"role": "user", "content": prompt}]},
                   timeout=90, verify=_ssl_context())
    if r.status_code != 200:
        raise AIError(f"OpenAI {r.status_code}: {r.text[:300]}")
    data = r.json()
    text = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage", {})
    _record_spend("openai", model, usage.get("prompt_tokens", 0),
                  usage.get("completion_tokens", 0), purpose)
    return text


# --- drafting ---------------------------------------------------------------

def draft_email(rec: dict[str, Any], job: dict[str, Any],
                markups: list[dict[str, Any]]) -> dict[str, str]:
    """Subject + body for the outbound email. AI when configured and funded;
    an honest deterministic template otherwise. Never raises for a missing
    key — the pipeline must work without spend."""
    label = "RFI" if rec["kind"] == "rfi" else "Submittal"
    subject = f"{label} {rec.get('number') or ''} — {job.get('job_name') or rec['job_number']}".strip()

    try:
        notes = [s.get("text") for a in markups
                 if (s := a.get("shape", {})).get("type") == "text" and s.get("text")]
        prompt = f"""Draft a short, professional construction {label} email for the customer.
Job: {job.get('job_name')} (#{rec['job_number']})
{label} number: {rec.get('number')} — {rec.get('title')}
Recipient: {rec.get('to_name') or 'the reviewing party'}
Respond-by date: {rec.get('due_date') or 'not set'}
{"Question: " + (rec.get('question') or '') if rec['kind'] == 'rfi' else "Spec section: " + (rec.get('spec_section') or '')}
Markup notes on the attached pages: {json.dumps(notes) if notes else 'none'}

The marked-up drawing pages are attached as a PDF. Ask for review and a written
response{"" if rec['kind'] == 'rfi' else " with a disposition (Approved / Approved as Noted / Revise & Resubmit / Rejected)"}.
Plain text only, under 180 words, no subject line, sign off as the sender."""
        body = _complete(prompt, f"{rec['kind']}.draft").strip()
        if body:
            return {"subject": subject, "body": body, "source": "ai"}
    except Exception:  # noqa: BLE001 — any provider failure falls back to the template
        pass

    if rec["kind"] == "rfi":
        body = (f"Please find attached {label} {rec.get('number') or ''} for "
                f"{job.get('job_name') or rec['job_number']}.\n\n"
                f"Subject: {rec.get('title') or '—'}\n\n"
                f"Question:\n{rec.get('question') or '(see attached pages)'}\n\n"
                f"The relevant drawing pages are attached with our markups. "
                f"Please review and respond in writing"
                + (f" by {rec['due_date']}" if rec.get("due_date") else "") + ".\n\nThank you,")
    else:
        body = (f"Please find attached Submittal {rec.get('number') or ''} for "
                f"{job.get('job_name') or rec['job_number']}"
                + (f" (spec section {rec['spec_section']})" if rec.get("spec_section") else "") + ".\n\n"
                f"Subject: {rec.get('title') or '—'}\n\n"
                f"Please review the attached pages and respond with a disposition — "
                f"Approved, Approved as Noted, Revise & Resubmit, or Rejected"
                + (f" — by {rec['due_date']}" if rec.get("due_date") else "") + ".\n\nThank you,")
    return {"subject": subject, "body": body, "source": "template"}


# --- reply analysis ---------------------------------------------------------

_DISPOSITIONS = [
    (r"revise\s*(and|&)\s*resubmit", "Revise & Resubmit"),
    (r"approved\s+as\s+noted|approved\s+with\s+(comments|notes|exceptions)", "Approved as Noted"),
    (r"\b(rejected|not\s+approved|disapproved)\b", "Rejected"),
    (r"\bapproved\b", "Approved"),
]


def analyze_reply(rec: dict[str, Any], body: str) -> dict[str, Any]:
    """Propose a status (and, for RFIs, an answer) from a reply body.

    Deterministic heuristics always run; AI refines when configured. Either
    way the result is a PROPOSAL — records change only on PM confirmation.
    """
    low = (body or "").lower()
    proposal: dict[str, Any] = {"proposed_status": None, "proposed_answer": None,
                                "proposal_source": "heuristic"}
    if rec["kind"] == "submittal":
        for pat, status in _DISPOSITIONS:
            if re.search(pat, low):
                proposal["proposed_status"] = status
                break
    else:
        proposal["proposed_status"] = "Answered" if body and body.strip() else None
        proposal["proposed_answer"] = (body or "").strip()[:4000] or None

    try:
        want = ("the disposition (exactly one of: Approved, Approved as Noted, "
                "Revise & Resubmit, Rejected, Unclear)"
                if rec["kind"] == "submittal"
                else "the direct answer to the question, quoted or tightly paraphrased")
        prompt = f"""A construction {rec['kind'].upper()} reply arrived. Extract {want}.
{"Question that was asked: " + (rec.get('question') or '') if rec['kind'] == 'rfi' else ''}
Reply email body:
---
{(body or '')[:6000]}
---
Respond with JSON only: {{"status": "...", "answer": "..."}} (answer empty for submittals)."""
        raw = _complete(prompt, f"{rec['kind']}.analyze", max_tokens=500)
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            parsed = json.loads(m.group(0))
            status = (parsed.get("status") or "").strip()
            valid = (["Answered"] if rec["kind"] == "rfi"
                     else [s for _, s in _DISPOSITIONS])
            if status in valid:
                proposal["proposed_status"] = status
            if rec["kind"] == "rfi" and parsed.get("answer"):
                proposal["proposed_answer"] = str(parsed["answer"])[:4000]
            proposal["proposal_source"] = "ai"
    except Exception:  # noqa: BLE001
        # AI refinement is a bonus, never a gate. A provider outage, a TLS
        # failure, a spend cap, a garbled response — the reply still gets
        # captured and staged with the heuristic proposal. (A narrower catch
        # here let an SSL error 500 the whole capture on 2026-08-08.)
        pass

    return proposal
