"""Sourcing agent: email approved suppliers, research new ones with Linkup, parse replies, follow up, chase and drop."""
from decimal import Decimal as D

from psycopg.types.json import Jsonb

from backend import store
from backend.agents import tools
from backend.db.lakebase import one, q
from backend.dbx import sql
from backend.dbx.pipeline import parse
from backend.dbx.seed.seed import supplier_email
from backend.demo import clock
from backend.email import outbox
from backend.email.transport import Mail
from backend.execution.quotes import QUESTIONS, merge, normalise
from backend.llm.schemas import QuoteExtract
from backend.research.linkup import Linkup, domain
from backend.tracing import traced

AWAITING = ("contacted", "incomplete", "chased")  # threads we're still waiting on


def _enquiry_fields(inc: dict, rules: dict) -> dict:
    """Template fields describing what we need (no customer data, ever)."""
    st = inc["state"]
    return {"packs": st["packs"], "pack_size": f"{st['pack_size_kg']:g}", "ingredient": inc["ingredient"],
            "area": rules["postcode_area"], "window_start": rules["delivery_window_start"], "window_end": rules["delivery_window_end"]}


def _open_thread(inc: dict, supplier: str, email: str, rules: dict, is_new: bool = False) -> None:
    """Send the enquiry and start the chase/drop timers (business minutes, compressed by the demo scale)."""
    mail = outbox.send(inc["id"], supplier, email, "enquiry", "enquiry", **_enquiry_fields(inc, rules))
    now = clock.now()
    q("INSERT INTO supplier_threads (incident_id, supplier, thread_id, email, is_new, status, last_contact_at, chase_due_at, drop_due_at) "
      "VALUES (%s,%s,%s,%s,%s,'contacted',%s,%s,%s) ON CONFLICT DO NOTHING",
      [inc["id"], supplier, mail.message_id, email, is_new, now, now + clock.business(rules["chase_after_min"]),
       now + clock.business(rules["drop_after_min"])])


@traced("sourcing_agent.contact_approved", span_type="AGENT")
def contact_approved(inc: dict) -> list[str]:
    """Enquire with every approved supplier except the one that let us down (recorded as excluded)."""
    rules, sent, seen = store.rules(), [], set()
    for alt in tools.approved_alternatives(inc["ingredient"]):
        if alt["supplier"] in seen:
            continue
        seen.add(alt["supplier"])
        if alt["supplier"] == inc["state"]["original_supplier"]:
            q("INSERT INTO supplier_threads (incident_id, supplier, email, status, note) VALUES (%s,%s,%s,'excluded',%s) ON CONFLICT DO NOTHING",
              [inc["id"], alt["supplier"], alt["email"], "Cancelled this delivery, so not asked again for this incident"])
            continue
        _open_thread(inc, alt["supplier"], alt["email"], rules)
        sent.append(alt["supplier"])
    store.log_event(inc["id"], "investigate", "sourcing_agent", "enquiries_sent",
                    f"Enquiries sent to {', '.join(sent[:-1]) + ' and ' + sent[-1] if len(sent) > 1 else ''.join(sent)}",
                    {"suppliers": sent, "refs": [f"{len(sent)} outbound emails", "thread IDs stored"]})
    return sent


@traced("sourcing_agent.research", span_type="AGENT")
def research(inc: dict, lock) -> None:
    """Linkup discovery + verification (runs in the background, outside the engine lock until it writes)."""
    rules, st = store.rules(), inc["state"]
    lk = Linkup()
    try:
        found, sources, at = lk.discover(inc["ingredient"], st["pack_size_kg"], rules["postcode_area"])
        known = {r["supplier"].lower() for r in sql.query(f"SELECT supplier FROM {sql.T('suppliers')}")}
        new = [f for f in found if f.supplier_name.lower() not in known][:2]
        checked = [(f, lk.verify(f, inc["ingredient"], st["pack_size_kg"], rules["postcode_area"])) for f in new]
    except Exception as e:  # research is additive: failure never blocks the approved-supplier path
        with lock:
            store.log_event(inc["id"], "investigate", "sourcing_agent", "research_failed", f"Supplier research unavailable: {e}", {})
            store.update_incident(inc["id"], state={"research_done": True})
        return
    with lock:
        store.log_event(inc["id"], "investigate", "sourcing_agent", "research_discovery",
                        f"Linkup search found {len(found)} suppliers, {len(new)} not on your list",
                        {"queries": lk.queries, "sources": sources, "retrieved_at": at, "refs": ["Linkup research"]})
        cards = []
        for f, claims in checked:
            slug = "".join(ch for ch in f.supplier_name.lower() if ch.isalnum())[:20]
            # Demo safety: new suppliers are emailed at a supplier-bot plus-address, never at a real business.
            email = supplier_email(slug)
            for c in claims:
                q("INSERT INTO research (incident_id, supplier, claim, value, status, source_urls) VALUES (%s,%s,%s,%s,%s,%s)",
                  [inc["id"], f.supplier_name, c["claim"], c["value"], c["status"], Jsonb(c["source_urls"])])
            sql.insert("supplier_research", [{
                "research_id": f"{inc['id']}:{slug}:{i}", "incident_id": inc["id"], "supplier": f.supplier_name, "claim": c["claim"],
                "value": c["value"], "status": c["status"], "source_urls": ",".join(c["source_urls"]), "retrieved_at": clock.now()}
                for i, c in enumerate(claims)])
            sql.insert("suppliers", [{"supplier": f.supplier_name, "email": email, "status": "new", "preference_rank": 99,
                                      "delivery_area": ",".join(f.delivery_areas), "website": domain(f.website)}])
            urls = sorted({u for c in claims for u in c["source_urls"]})
            cards.append({"supplier": f.supplier_name, "location": f.location, "website": f.website, "claims": claims,
                          "published": f.model_dump(), "sources": [{"url": u, "retrieved_at": at} for u in urls]})
            n_sources = len(urls)
            store.log_event(inc["id"], "investigate", "sourcing_agent", "new_supplier_found",
                            f"{f.supplier_name} found; key claims cross-checked against {n_sources} sources",
                            {"supplier": f.supplier_name, "claims": claims, "sources": urls, "refs": ["Linkup research", f"{n_sources} source URLs"]})
            _open_thread(store.incident(inc["id"]), f.supplier_name, email, rules, is_new=True)
        store.update_incident(inc["id"], state={"research_done": True, "new_suppliers": cards, "linkup_queries": lk.queries})


def _plain(fields: list[str]) -> str:
    """['delivery_charge', 'arrival_at'] -> 'delivery charge and arrival time'."""
    names = [f.replace("_at", " time").replace("_", " ") for f in fields]
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def _vat_default(ingredient: str) -> D | None:
    """Catalogue VAT for the ingredient (flour is zero-rated), used only when the supplier doesn't state VAT."""
    rates = {a["vat_rate"] for a in tools.approved_alternatives(ingredient)}
    return rates.pop() if len(rates) == 1 else None


def _published_conflict(incident_id: str, supplier: str, arrival_hhmm: str) -> str | None:
    """Reply verification: does the emailed arrival beat the supplier's own published earliest delivery?"""
    r = one("SELECT value FROM research WHERE incident_id = %s AND supplier = %s AND claim = 'Next-day delivery from'",
            [incident_id, supplier])
    published = (r or {}).get("value") or ""
    times = [t for t in published.replace(" vs ", " ").split() if ":" in t]
    return f"emailed {arrival_hhmm} but published earliest delivery is {published}" if times and arrival_hhmm < min(times) else None


@traced("sourcing_agent.handle_quote", span_type="AGENT")
def handle_quote(inc: dict, thread: dict, mail: Mail) -> str:
    """Parse a reply (bronze -> silver), merge with earlier replies, detect missing fields by code, follow up once.
    Returns the new thread status."""
    rules, day, now = store.rules(), inc["production_date"], clock.now()
    parsed, path = parse(QuoteExtract, mail.body, "This is a supplier replying to a bakery's request for a flour quote.")
    sup = thread["supplier"]
    if parsed and parsed.declined:
        q("UPDATE supplier_threads SET status = 'declined', last_contact_at = %s WHERE incident_id = %s AND supplier = %s", [now, inc["id"], sup])
        store.log_event(inc["id"], "coordinate", "sourcing_agent", "supplier_declined", f"{sup} can't supply this time",
                        {"message_id": mail.message_id, "parse_path": path})
        return "declined"
    offers = [o.model_dump() for o in parsed.offers] if parsed and parsed.offers else [{}]  # unparseable -> all missing
    previous = {(p["label"] or ""): p for p in q("SELECT * FROM quotes WHERE incident_id = %s AND supplier = %s AND NOT superseded",
                                                 [inc["id"], sup])}
    q("UPDATE quotes SET superseded = true WHERE incident_id = %s AND supplier = %s", [inc["id"], sup])
    vat, quotes = _vat_default(inc["ingredient"]), []
    for i, offer in enumerate(offers):
        # Same-label offer from an earlier reply (a follow-up answer usually has no label: it completes the first offer).
        prev = previous.get(offer.get("label") or "") or (next(iter(previous.values())) if i == 0 and previous else None)
        raw = merge(prev["raw"] if prev else None, offer)
        n = normalise(raw, day, vat, inc["state"]["pack_size_kg"])
        row = one("INSERT INTO quotes (incident_id, supplier, label, packs, max_packs, pack_size_kg, unit_price, goods_price, delivery_charge, "
                  "vat_rate, total, arrival_at, arrival_text, missing_fields, raw, source_message_id, parse_path) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                  [inc["id"], sup, n["label"], n["packs"], n["max_packs"], n["pack_size_kg"], n["unit_price"], n["goods_price"],
                   n["delivery_charge"], n["vat_rate"], n["total"], n["arrival_at"], n["arrival_text"], Jsonb(n["missing_fields"]),
                   store.jsonable(raw), mail.message_id, path])
        sql.insert("silver_quotes", [{
            "quote_id": str(row["quote_id"]), "incident_id": inc["id"], "supplier": sup, "sku": None, "packs": n["packs"] or n["max_packs"],
            "pack_size_kg": float(n["pack_size_kg"]), "goods_price": n["goods_price"], "delivery_charge": n["delivery_charge"],
            "vat_rate": n["vat_rate"], "total": n["total"], "arrival_at": n["arrival_at"], "missing_fields": ",".join(n["missing_fields"]),
            "source_message_id": mail.message_id, "parse_path": path, "parsed_at": now}])
        quotes.append(row)
    main = quotes[0]
    missing = main["missing_fields"]
    # Re-run time-phased coverage for this offer and log it (rule: every quote change).
    kg = (main["packs"] or main["max_packs"] or 0) * float(main["pack_size_kg"])
    slots = tools.coverage(inc["ingredient"], day, rules["arrival_buffer_min"], kg, main["arrival_at"])
    saved = sum(s["covered"] for s in slots)
    total = f"£{main['total']:.0f}" if main["total"] is not None else f"£{main['goods_price']:.0f}" if main["goods_price"] else "a price"
    when = f"arriving {clock.hhmm(main['arrival_at'])}" if main["arrival_at"] else "arrival time not specific"
    late = main["arrival_at"] and saved == 0
    summary = f"{sup} quoted {total}, {when}" + (" — too late" if late else "") + (f" · {_plain(missing)} missing" if missing else "")
    store.log_event(inc["id"], "coordinate", "sourcing_agent", "quote_parsed", summary,
                    {"quote_ids": [x["quote_id"] for x in quotes], "parse_path": path, "missing": missing, "message_id": mail.message_id,
                     "coverage": slots, "bakes_saved": saved, "refs": ["reply parsed into quote fields", "coverage_by_slot"]})
    if main["arrival_at"] and (why := _published_conflict(inc["id"], sup, clock.hhmm(main["arrival_at"]))):
        store.log_event(inc["id"], "coordinate", "sourcing_agent", "claim_conflict", f"Check {sup}: {why}",
                        {"supplier": sup, "refs": ["Linkup research", "reply verification"]})
    if missing and thread["followups"] == 0:
        window = f"{rules['delivery_window_start']} and {rules['delivery_window_end']}"
        questions = "\n".join(QUESTIONS[m].format(window=window) for m in missing)
        outbox.send(inc["id"], sup, thread["email"], "followup", "followup", thread_id=thread["thread_id"], reply_to=mail,
                    subject=mail.subject.removeprefix("Re: "), questions=questions)
        q("UPDATE supplier_threads SET status = 'incomplete', followups = followups + 1, last_contact_at = %s, chase_due_at = %s, "
          "drop_due_at = GREATEST(drop_due_at, %s) WHERE incident_id = %s AND supplier = %s",
          [now, now + clock.business(rules["chase_after_min"]), now + clock.business(rules["chase_after_min"]), inc["id"], sup])
        store.log_event(inc["id"], "coordinate", "sourcing_agent", "followup_sent",
                        f"Follow-up sent asking for {_plain(missing)}",
                        {"missing": missing, "questions": questions, "refs": ["templated follow-up", "missing fields"]})
        return "incomplete"
    status = "incomplete" if missing else "quoted"
    q("UPDATE supplier_threads SET status = %s, last_contact_at = %s WHERE incident_id = %s AND supplier = %s", [status, now, inc["id"], sup])
    return status


@traced("sourcing_agent.timers", span_type="AGENT")
def run_timers() -> list[str]:
    """Chase once after chase_after_min; drop after drop_after_min. Returns incident ids whose options changed."""
    now, changed = clock.now(), []
    due = q("SELECT t.*, i.status AS inc_status FROM supplier_threads t JOIN incidents i ON i.id = t.incident_id "
            "WHERE t.status = ANY(%s) AND (t.chase_due_at <= %s OR t.drop_due_at <= %s)", [list(AWAITING), now, now])
    for t in due:
        inc = store.incident(t["incident_id"])
        if t["drop_due_at"] <= now:
            q("UPDATE supplier_threads SET status = 'dropped' WHERE incident_id = %s AND supplier = %s", [t["incident_id"], t["supplier"]])
            store.log_event(t["incident_id"], "coordinate", "sourcing_agent", "supplier_dropped",
                            f"{t['supplier']} dropped after no reply", {"supplier": t["supplier"], "refs": ["drop timer"]})
            changed.append(t["incident_id"])
        elif t["status"] != "chased" and t["inc_status"] not in ("resolved", "resolved_partial"):
            rules = store.rules()
            outbox.send(inc["id"], t["supplier"], t["email"], "chase", "chase", thread_id=t["thread_id"],
                        reply_to=store.last_inbound(inc["id"], t["supplier"]), subject=f"Quote request: {inc['state']['packs']} × "
                        f"{inc['state']['pack_size_kg']:g} kg {inc['ingredient']} for tomorrow", **_enquiry_fields(inc, rules))
            q("UPDATE supplier_threads SET status = 'chased', last_contact_at = %s WHERE incident_id = %s AND supplier = %s",
              [now, t["incident_id"], t["supplier"]])
            store.log_event(t["incident_id"], "coordinate", "sourcing_agent", "supplier_chased",
                            f"{t['supplier']} chased once; dropped at {clock.hhmm(t['drop_due_at'])} if still quiet",
                            {"supplier": t["supplier"], "drop_due_at": t["drop_due_at"], "refs": ["chase timer"]})
    return changed
