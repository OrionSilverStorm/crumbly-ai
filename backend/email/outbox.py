"""Crumbly's outgoing mail: render a template, send from the bakery mailbox, record it (Lakebase + bronze)."""
from functools import lru_cache

from backend.email.templates import render
from backend.email.transport import EmailTransport, Mail, make
from backend.store import record_email


@lru_cache
def bakery() -> EmailTransport:
    """The bakery mailbox Crumbly sends from and polls."""
    return make("bakery")


def send(incident_id: str, supplier: str, to: str, kind: str, template: str,
         thread_id: str | None = None, reply_to: Mail | None = None, **fields) -> Mail:
    """Send a templated email in a supplier thread. A new thread's id is its first Message-ID."""
    subject, body = render(template, incident_id=incident_id, supplier=supplier, **fields)
    mail = bakery().send(to, subject, body, reply_to)
    record_email(mail, "outbound", kind, incident_id, supplier, thread_id or mail.message_id)
    return mail
