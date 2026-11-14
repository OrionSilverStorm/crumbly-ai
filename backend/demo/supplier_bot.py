"""Scripted supplier replies over REAL email. Every supplier is a plus-address of one mailbox; the bot reads the To
header's +tag to know who it is playing, and replies in-thread after a (demo-scaled) delay.

Run in-process (SUPPLIER_BOT_INPROCESS=1, default) or standalone: python -m backend.demo.supplier_bot
"""
import logging
import re
import threading
import time

from backend.config import settings
from backend.demo import clock
from backend.email.transport import EmailTransport, Mail, make, plus_tag

log = logging.getLogger("crumbly.bot")
NAMES = {"boroughmill": "Borough Mill", "harrowsons": "Harrow & Sons", "wheatfield": "Wheatfield Direct",
         "millerssupply": "Millers Supply", "thamesgrainco": "Thames Grain Co."}
CONFIRM = "CONFIRM"            # echo the PO exactly
CONFIRM_SHORT = "CONFIRM_SHORT"  # echo the PO one bag short

BOROUGH_FIRST = "Hi,\n\nSeven bags for £147. Delivery tomorrow.\n\nBorough Mill"
BOROUGH_SECOND = "£18 delivery. £165 total. With you by 05:00.\n\nBorough Mill"
HARROW = ("Morning,\n\nWe can do 7 × 25 kg strong white flour for £138 including delivery, arriving 09:00 on our standard van. "
          "Our early van (04:45) has room for up to 2 bags at £26 per bag, delivery included.\n\nHarrow & Sons")
THAMES = "Thanks for getting in touch. We can supply 7 × 25 kg bags for £152 plus £12 delivery, arriving {t} tomorrow.\n\nThames Grain Co."

# scenario -> (supplier slug, message kind) -> (delay in business minutes, reply body or CONFIRM*); missing = no reply.
BASE = {
    ("boroughmill", "enquiry"): (14, BOROUGH_FIRST),
    ("boroughmill", "followup"): (12, BOROUGH_SECOND),
    ("boroughmill", "po"): (6, CONFIRM),
    ("boroughmill", "correction"): (5, CONFIRM),
    ("harrowsons", "enquiry"): (22, HARROW),
    ("harrowsons", "po"): (4, CONFIRM),
    ("thamesgrainco", "enquiry"): (15, THAMES.format(t="07:00")),
    ("thamesgrainco", "po"): (4, CONFIRM),
    ("wheatfield", "po"): (4, CONFIRM),
}
SCRIPTS = {
    "happy": BASE,
    "short_confirm": {**BASE, ("boroughmill", "po"): (6, CONFIRM_SHORT)},
    "new_supplier_wins": {**BASE,
        ("boroughmill", "enquiry"): (14, "Sorry, we're out of strong white flour until Thursday.\n\nBorough Mill"),
        ("harrowsons", "enquiry"): (22, "We can do 7 × 25 kg strong white flour for £138 including delivery, arriving 09:00.\n\nHarrow & Sons"),
        ("thamesgrainco", "enquiry"): (15, THAMES.format(t="04:30"))},
    "owner_rejects": {**BASE,
        ("wheatfield", "enquiry"): (10, "We can send 5 × 25 kg bags at £20 per bag, £10 delivery, arriving 04:30. That's all we have left.\n\nWheatfield Direct")},
}


def _confirm(po_body: str, short: bool, name: str) -> str:
    """Echo the PO's terms (optionally one bag short, priced per bag)."""
    get = lambda k: re.search(rf"^{k}: (.+)$", po_body, re.M).group(1).strip()  # noqa: E731
    po_id, unit = get("Purchase order"), float(get("Unit price").strip("£"))
    delivery, total = float(get("Delivery").strip("£")), float(get("Total").strip("£"))
    packs = int(re.match(r"(\d+)", get("Quantity")).group(1))
    arrival = re.search(r"(\d\d:\d\d)", get("Arrival")).group(1)
    if short:
        packs, total = packs - 1, total - unit
    return (f"Confirming {po_id}: {packs} × 25 kg strong white flour at £{unit:.2f} per bag, delivery £{delivery:.2f}, "
            f"total £{total:.2f}, arriving {arrival} tomorrow.\n\n{name}")


class SupplierBot:
    """Polls the supplier mailbox and answers according to the active scenario."""

    def __init__(self, transport: EmailTransport | None = None):
        self.t = transport or make("suppliers")
        self.pos: dict[str, str] = {}  # supplier slug -> last PO body (to answer correction requests)

    def scenario(self) -> str:
        """Scenario chosen at reset (stored in Lakebase), falling back to the SCENARIO env var."""
        try:
            from backend.store import demo_state

            return demo_state("scenario", settings.scenario)
        except Exception:
            return settings.scenario

    def reply_for(self, mail: Mail) -> tuple[float, str, str] | None:
        """(delay minutes, slug, body) for a message, or None to stay silent."""
        slug = plus_tag(mail.to_addr)
        m = re.search(r"Ref: (INC-\d+)/(\w+)", mail.body)
        if not slug or not m:
            return None
        kind = m.group(2)
        if kind == "po":
            self.pos[slug] = mail.body
        rule = SCRIPTS.get(self.scenario(), BASE).get((slug, kind))
        if not rule:
            return None
        delay, body = rule
        name = NAMES.get(slug, slug)
        if body in (CONFIRM, CONFIRM_SHORT):
            body = _confirm(self.pos.get(slug, mail.body), body == CONFIRM_SHORT, name)
        return delay, slug, body

    def handle(self, mail: Mail) -> None:
        """Schedule a reply (timer thread) for one received message."""
        self.t.ack(mail)
        r = self.reply_for(mail)
        if not r:
            return
        delay, slug, body = r
        send = lambda: self.t.send(mail.from_addr, f"Re: {mail.subject.removeprefix('Re: ')}", body,  # noqa: E731
                                   reply_to=mail, from_addr=mail.to_addr, name=NAMES.get(slug, slug))
        threading.Timer(clock.business(delay).total_seconds(), send).start()

    def poll_once(self) -> None:
        for mail in self.t.fetch_new():
            try:
                self.handle(mail)
            except Exception:
                log.exception("bot failed on %s", mail.message_id)

    def run(self, stop: threading.Event | None = None) -> None:
        """Poll forever (1 s in memory mode, EMAIL_POLL_SECONDS with Gmail)."""
        every = 1.0 if settings.email_mode == "memory" else settings.poll_seconds
        while not (stop and stop.is_set()):
            self.poll_once()
            time.sleep(every)


def send_cancellation(transport: EmailTransport | None = None) -> Mail:
    """The demo trigger: Millers Supply cancels PO-0079 (a real email to the bakery inbox)."""
    t = transport or make("suppliers")
    local, domain = settings.suppliers_address.split("@")
    body = ("Hello,\n\nApologies — due to a breakdown at the mill we're unable to fulfil tomorrow's order of "
            "8 × 25 kg strong white flour (PO-0079). We'll credit your account in full.\n\nMillers Supply")
    return t.send(settings.bakery_address, "Re: PO-0079 · Delivery tomorrow 04:30", body,
                  from_addr=f"{local}+millerssupply@{domain}", name="Millers Supply")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    SupplierBot().run()
