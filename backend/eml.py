"""Build ready-to-send .eml files — the share path that needs nothing installed.

WHY: the companion drives the desktop Outlook *next to the user* over COM, and
that is precisely what makes it impossible on any machine that hasn't installed
it — a coworker's PC, a conference room, a demo. Rather than a dead button,
the server hands over the email itself: a message/rfc822 file with recipients,
subject, body and the PDF already attached. Double-clicked on Windows it opens
in Outlook; the `X-Unsent: 1` header is the documented convention that makes
classic desktop Outlook open it in *compose* mode — editable, with a Send
button — rather than as received mail. The user reviews and presses Send, so
mail still leaves from a person's own mailbox with a human in front of it,
which is the D10 property the companion exists to protect.

Caveats, accepted knowingly (D41): "new" Outlook and OWA may open the file
read-only — the company standard is classic Outlook, which the companion
already requires for COM. And a downloaded .eml sits in the Downloads folder
of whatever machine it touched; internal sheets on shared PCs deserve the same
care as any other downloaded document.

Stdlib only. The project ships no mail library and doesn't need one:
email.message.EmailMessage generates the MIME, exactly the format Outlook
reads. UTF-8 throughout; attachments are application/pdf.
"""
from __future__ import annotations

from email.message import EmailMessage
from email.policy import SMTP


def build_eml(subject: str, to: str = "", *, html: str | None = None,
              text: str | None = None,
              attachments: list[tuple[str, bytes]] | None = None) -> bytes:
    """One outgoing message as .eml bytes.

    `to` uses the companion's own convention — addresses joined by ";" or ","
    — and may be blank (the team sheet deliberately ships unaddressed so the
    PM chooses recipients in Outlook). `html` wins over `text` when both are
    given, with the text carried as the plain alternative.
    """
    msg = EmailMessage(policy=SMTP)
    msg["Subject"] = subject or ""
    recipients = [a.strip() for a in (to or "").replace(";", ",").split(",") if a.strip()]
    if recipients:
        msg["To"] = ", ".join(recipients)
    # The header Outlook keys compose mode on. Unset or 0 would open the file
    # as if it had been received; 1 opens it as a draft being written.
    msg["X-Unsent"] = "1"
    msg["X-Mailer"] = "PlanWise"

    if html:
        msg.set_content(text or _fallback_text(html))
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(text or "")

    for filename, data in attachments or []:
        msg.add_attachment(data, maintype="application", subtype="pdf",
                           filename=filename)
    return msg.as_bytes()


def _fallback_text(html: str) -> str:
    """A crude but honest text/plain alternative for HTML-only bodies.

    Mail clients that render HTML never show this; ones that can't get the
    words without the markup instead of an empty message.
    """
    import re

    text = re.sub(r"<(br|/p|/tr|/table|/div)[^>]*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    import html as _html

    return _html.unescape(text).strip()
