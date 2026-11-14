"""Email transport behind one interface: Gmail IMAP/SMTP (real mail) or in-process mailboxes (tests/offline).

Threads are tracked by Message-ID / In-Reply-To / References. Suppliers are identified from the thread, never from
the From address, so plus-addressing (one supplier-bot inbox for every supplier) works.
"""
import imaplib
import smtplib
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr, parsedate_to_datetime

from backend.config import settings
from backend.demo import clock


@dataclass
class Mail:
    """A sent or received email in transport-neutral form."""

    message_id: str
    from_addr: str
    to_addr: str
    subject: str
    body: str
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    date: datetime | None = None


def canonical(addr: str) -> str:
    """Strip display name and +tag: 'Bot <a+x@b.com>' -> 'a@b.com' (the mailbox that actually receives it)."""
    local, _, domain = parseaddr(addr)[1].lower().partition("@")
    return f"{local.split('+')[0]}@{domain}"


def plus_tag(addr: str) -> str | None:
    """'a+boroughmill@b.com' -> 'boroughmill' (used only by the supplier bot to know who it plays)."""
    local = parseaddr(addr)[1].split("@")[0]
    return local.split("+", 1)[1] if "+" in local else None


def _build(sender: str, name: str, to: str, subject: str, body: str, reply_to: Mail | None) -> tuple[EmailMessage, Mail]:
    """Compose a MIME message (threaded onto `reply_to` if given) and its Mail record."""
    msg = EmailMessage()
    mid = make_msgid(domain=sender.split("@")[1])
    refs = (reply_to.references + [reply_to.message_id]) if reply_to else []
    msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = formataddr((name, sender)), to, subject, mid
    if reply_to:
        msg["In-Reply-To"], msg["References"] = reply_to.message_id, " ".join(refs)
    msg.set_content(body)
    return msg, Mail(mid, sender, to, subject, body, reply_to.message_id if reply_to else None, refs, clock.now())


class EmailTransport(ABC):
    """One mailbox: send mail, fetch unprocessed inbound mail, acknowledge processed mail."""

    def __init__(self, address: str, name: str):
        self.address, self.name = address, name

    @abstractmethod
    def send(self, to: str, subject: str, body: str, reply_to: Mail | None = None, from_addr: str | None = None, name: str | None = None) -> Mail: ...

    @abstractmethod
    def fetch_new(self) -> list[Mail]: ...

    @abstractmethod
    def ack(self, mail: Mail) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...


class MemoryTransport(EmailTransport):
    """In-process mailboxes keyed by canonical address. Shared across instances, like a tiny mail server."""

    _boxes: dict[str, list[Mail]] = {}
    _lock = threading.Lock()

    def send(self, to, subject, body, reply_to=None, from_addr=None, name=None):
        _, mail = _build(from_addr or self.address, name or self.name, to, subject, body, reply_to)
        with self._lock:
            self._boxes.setdefault(canonical(to), []).append(mail)
        return mail

    def fetch_new(self):
        with self._lock:
            return list(self._boxes.get(canonical(self.address), []))

    def ack(self, mail):
        with self._lock:
            box = self._boxes.get(canonical(self.address), [])
            self._boxes[canonical(self.address)] = [m for m in box if m.message_id != mail.message_id]

    def clear(self):
        with self._lock:
            self._boxes[canonical(self.address)] = []


class GmailTransport(EmailTransport):
    """Gmail via app password: SMTP to send, IMAP UNSEEN to receive, \\Seen flag to acknowledge."""

    def __init__(self, address: str, name: str, password: str):
        super().__init__(address, name)
        self.password = password
        self._uids: dict[str, bytes] = {}  # message_id -> IMAP uid, for ack()

    def _imap(self) -> imaplib.IMAP4_SSL:
        imap = imaplib.IMAP4_SSL(settings.imap_host)
        imap.login(self.address, self.password)
        imap.select("INBOX")
        return imap

    def send(self, to, subject, body, reply_to=None, from_addr=None, name=None):
        msg, mail = _build(from_addr or self.address, name or self.name, to, subject, body, reply_to)
        with smtplib.SMTP_SSL(settings.smtp_host, 465) as s:
            s.login(self.address, self.password)
            s.send_message(msg)
        return mail

    def fetch_new(self):
        imap, out = self._imap(), []
        try:
            _, data = imap.uid("search", None, "UNSEEN")
            for uid in data[0].split():
                _, parts = imap.uid("fetch", uid, "(BODY.PEEK[])")  # PEEK: stay unseen until processed
                msg = message_from_bytes(parts[0][1], policy=policy.default)
                body = msg.get_body(preferencelist=("plain", "html"))
                mail = Mail(
                    message_id=(msg["Message-ID"] or f"<uid-{uid.decode()}@imap>").strip(),
                    from_addr=parseaddr(msg["From"] or "")[1], to_addr=msg["To"] or "", subject=str(msg["Subject"] or ""),
                    body=body.get_content() if body else "", in_reply_to=(msg["In-Reply-To"] or "").strip() or None,
                    references=(msg["References"] or "").split(),
                    date=parsedate_to_datetime(msg["Date"]) if msg["Date"] else clock.now(),
                )
                self._uids[mail.message_id] = uid
                out.append(mail)
        finally:
            imap.logout()
        return out

    def ack(self, mail):
        uid = self._uids.pop(mail.message_id, None)
        if uid:
            imap = self._imap()
            try:
                imap.uid("store", uid, "+FLAGS", "(\\Seen)")
            finally:
                imap.logout()

    def clear(self):
        imap = self._imap()
        try:
            imap.uid("store", "1:*", "+FLAGS", "(\\Seen)")  # mark everything processed; mail stays archived
        finally:
            imap.logout()


def make(role: str) -> EmailTransport:
    """Transport for 'bakery' (Crumbly) or 'suppliers' (the demo supplier bot)."""
    addr, pw, name = (
        (settings.bakery_address, settings.bakery_password, "Morning Loaf (Crumbly)") if role == "bakery"
        else (settings.suppliers_address, settings.suppliers_password, "Supplier")
    )
    return GmailTransport(addr, name, pw) if settings.email_mode == "gmail" else MemoryTransport(addr, name)
