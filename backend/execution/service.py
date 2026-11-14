"""Execution service: the ONLY component that can act. Plain code, no model calls.

- validates purchase plans against the owner's rules (7 checks)
- ranks offers: reliability, then cost, then confirmed soft preferences (documented tie-breaker)
- builds split / top-up plans when no single offer covers the shortage
- sends POs idempotently (idempotency key = incident_id:supplier:attempt)
- matches confirmations field by field (a mismatch is never accepted)
- tracks stock on order separately from physical stock (physical changes only on receipt)
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal as D
from itertools import combinations

from backend import store
from backend.agents import tools
from backend.db.lakebase import one, q
from backend.dbx import sql
from backend.demo import clock
from backend.email import outbox
from backend.execution.quotes import CENT, money, packs_needed
from backend.tracing import traced

# Owner-facing short reason for each failed check.
FAIL_REASON = {"approved_product": "Not an approved product", "enough": "Not enough flour", "in_time": "Too late",
               "cost_known": "Cost not known yet", "within_limit": "Over your limit", "no_duplicate": "Already ordered"}
OPEN_PO = ("sending", "sent", "mismatch", "correction_requested")


@dataclass
class Line:
    """One purchase line drawn from a quote."""

    quote_id: int
    supplier: str
    email: str
    label: str | None
    sku: str | None
    packs: int
    pack_size_kg: D
    unit_price: D | None
    goods: D | None
    delivery: D | None
    vat_rate: D | None
    arrival_at: datetime | None
    approved: bool          # supplier status == approved
    auto_ok: bool           # product allows automatic ordering
    reliability: dict

    @property
    def kg(self) -> D:
        return self.packs * self.pack_size_kg

    @property
    def total(self) -> D | None:
        if None in (self.goods, self.delivery, self.vat_rate):
            return None
        return money((self.goods + self.delivery) * (1 + self.vat_rate))


@dataclass
class Plan:
    """One or more lines that together replace the shortage; checks are filled in by validate()."""

    lines: list[Line]
    kind: str = "single"    # single | split | top_up | partial
    checks: list[dict] = field(default_factory=list)

    @property
    def total(self) -> D | None:
        ts = [l.total for l in self.lines]
        return None if None in ts else sum(ts, D("0"))

    @property
    def kg(self) -> D:
        return sum((l.kg for l in self.lines), D("0"))

    @property
    def qualifies(self) -> bool:
        return all(c["status"] != "fail" for c in self.checks)

    @property
    def needs_owner(self) -> list[str]:
        return [c["detail"] for c in self.checks if c["status"] == "approval"]

    @property
    def signature(self) -> str:
        """Stable identity of what would be ordered (used for idempotent placement)."""
        return "|".join(sorted(f"{l.quote_id}x{l.packs}" for l in self.lines))

    def as_dict(self) -> dict:
        """JSON form for decisions, events and the UI."""
        rel = self.lines[0].reliability if len(self.lines) == 1 else {}
        return store.jsonable({
            "kind": self.kind, "signature": self.signature, "total": self.total, "kg": self.kg,
            "suppliers": [l.supplier for l in self.lines], "qualifies": self.qualifies, "needs_owner": self.needs_owner,
            "reasons": [FAIL_REASON[c["id"]] for c in self.checks if c["status"] == "fail"],
            "checks": self.checks, "reliability": rel,
            "lines": [{**l.__dict__, "kg": l.kg, "total": l.total} for l in self.lines],
        })


@dataclass
class Ctx:
    """Everything the checks need, loaded once per evaluation."""

    inc: dict
    rules: dict
    need_kg: D
    committed: D            # spend already committed in this incident
    deadline: datetime      # earliest affected bake still requiring flour
    approved_skus: set
    open_po_suppliers: set
    prefs: dict


def context(inc: dict, need_kg: D | None = None, committed: D | None = None) -> Ctx:
    """Build the check context from live state (rules, POs, preferences, relaxed bake slots)."""
    pos = q("SELECT * FROM purchase_orders WHERE incident_id = %s", [inc["id"]])
    active = [p for p in pos if p["status"] not in ("rejected",)]
    # Deadline = earliest bake that was uncovered at the start and that the owner hasn't said "later is fine" for.
    relaxed = set(inc["state"].get("relaxed_slots", []))
    slots = [s for s in inc["state"].get("baseline_coverage", []) if not s["covered"] and s["bake_time"] not in relaxed]
    deadline = datetime.fromisoformat(slots[0]["bake_time"]) if slots else inc["deadline"]
    prefs = {r["key"]: r["value"] for r in q("SELECT key, value FROM preferences WHERE confirmed")}
    return Ctx(
        inc=inc, rules=store.rules(), need_kg=D(str(need_kg if need_kg is not None else inc["shortage_kg"])),
        committed=committed if committed is not None else sum((p["total"] for p in active), D("0")),
        deadline=clock.local(deadline),
        approved_skus={a["sku"] for a in tools.approved_alternatives(inc["ingredient"])},
        open_po_suppliers={p["supplier"] for p in pos if p["status"] in OPEN_PO}, prefs=prefs,
    )


def status_of(plan: Plan, check_id: str) -> str | None:
    """Status of one named check on a validated plan."""
    return next((c["status"] for c in plan.checks if c["id"] == check_id), None)


def _check(id_: str, label: str, status: bool | str, detail: str) -> dict:
    """status: True -> pass, False -> fail, 'approval' -> allowed only with the owner's OK."""
    return {"id": id_, "label": label, "status": {True: "pass", False: "fail"}.get(status, status), "detail": detail}


def _gap(minutes: int) -> str:
    """60 -> 'an hour', 45 -> '45 min'."""
    return "an hour" if minutes == 60 else f"{minutes // 60} h {minutes % 60} min" if minutes > 60 else f"{minutes} min"


def validate(plan: Plan, ctx: Ctx) -> Plan:
    """Run the seven checks. Fills plan.checks and returns the plan."""
    r, day = ctx.rules, ctx.inc["production_date"]
    latest = ctx.deadline - timedelta(minutes=r["arrival_buffer_min"])
    w0, w1 = clock.at(day, r["delivery_window_start"]), clock.at(day, r["delivery_window_end"])
    ingredient = ctx.inc["ingredient"].capitalize()
    new = [l for l in plan.lines if not l.approved]
    late = [l for l in plan.lines if not (l.arrival_at and w0 <= l.arrival_at <= w1 and l.arrival_at <= latest)]
    total, spend = plan.total, (plan.total or D("0")) + ctx.committed
    first = plan.lines[0]
    a = first.arrival_at
    unapproved_sku = [l for l in plan.lines if l.approved and l.sku not in ctx.approved_skus]
    plan.checks = [
        # Approved suppliers must quote an approved SKU; a new supplier's product can only be bought with the owner's OK.
        _check("approved_product", "Approved product", False if unapproved_sku else "approval" if new else True,
               " + ".join(f"{ingredient} · {l.sku}" if l.sku else f"{l.supplier}: not on your approved list yet" for l in plan.lines)),
        _check("enough", "Enough flour", plan.kg >= ctx.need_kg,
               f"{' + '.join(f'{l.packs} × {l.pack_size_kg:g} kg' for l in plan.lines)} = {plan.kg:g} kg "
               f"{'≥' if plan.kg >= ctx.need_kg else '<'} {ctx.need_kg:g} kg"),
        _check("in_time", "Arrives in time", not late,
               (f"{clock.hhmm(a)}, {_gap(int((ctx.deadline - a).total_seconds() // 60))} before {clock.hhmm(ctx.deadline)}"
                if a and not late and len(plan.lines) == 1 else
                ", ".join(f"{l.supplier} {clock.hhmm(l.arrival_at) or 'time not given'}" for l in plan.lines)
                + (f" · needs {r['delivery_window_start']}–{min(r['delivery_window_end'], clock.hhmm(latest))}" if late else ""))),
        _check("cost_known", "Full cost known", total is not None,
               " + ".join(f"£{l.goods:.0f} + £{l.delivery:.0f} delivery" if l.total is not None else f"{l.supplier}: incomplete"
                          for l in plan.lines) + (f" · VAT {first.vat_rate * 100:.0f}%" if total is not None else "")),
        _check("within_limit", "Within your limit", total is not None and spend <= r["spending_limit_per_incident"],
               f"£{spend:.0f} of £{r['spending_limit_per_incident']:.0f} per incident"),
        _check("approved_supplier", "Approved supplier", "approval" if new else True,
               "New supplier, buying needs your OK" if new else
               "Automatic ordering allowed" if r["auto_order_enabled"] and all(l.auto_ok for l in plan.lines)
               else "Approved · ordering needs your OK"),
        _check("no_duplicate", "No duplicate order", not any(l.supplier in ctx.open_po_suppliers for l in plan.lines),
               f"First order for {ctx.inc['id']}" if not ctx.open_po_suppliers else "No other open order with this supplier"),
    ]
    return plan


def auto_allowed(plan: Plan, ctx: Ctx) -> tuple[bool, list[str]]:
    """May the service order without asking? Returns (allowed, reasons it must ask)."""
    why = list(plan.needs_owner)
    if not ctx.rules["auto_order_enabled"]:
        why.append("Automatic ordering is off")
    if not all(l.auto_ok for l in plan.lines):
        why.append("Product is set to 'ask me first'")
    cap = ctx.prefs.get(f"ask_over:{ctx.inc['ingredient']}")
    if cap and plan.total is not None and plan.total > D(str(cap["amount"])):
        why.append(f"You asked to approve {ctx.inc['ingredient']} orders over £{cap['amount']}")
    return plan.qualifies and not why, why


# ---------------------------------------------------------------- offers, ranking and plans

def _supplier_info(ingredient: str) -> dict:
    """supplier -> {status, email, sku, auto_ok} from the warehouse."""
    sups = sql.query(f"SELECT supplier, email, status FROM {sql.T('suppliers')}")
    prods = {p["supplier"]: p for p in tools.approved_alternatives(ingredient)}
    return {s["supplier"]: {**s, "sku": prods.get(s["supplier"], {}).get("sku"),
                            "auto_ok": bool(prods.get(s["supplier"], {}).get("auto_order_allowed"))} for s in sups}


def active_quotes(incident_id: str) -> list[dict]:
    """Latest, non-excluded quotes from suppliers still in play."""
    return q("SELECT qt.* FROM quotes qt JOIN supplier_threads t ON t.incident_id = qt.incident_id AND t.supplier = qt.supplier "
             "WHERE qt.incident_id = %s AND NOT qt.superseded AND qt.excluded_reason IS NULL "
             "AND t.status NOT IN ('excluded', 'declined') ORDER BY qt.quote_id", [incident_id])


def line_from(quote: dict, info: dict, rel: dict, packs: int | None = None) -> Line:
    """Turn a quote into a purchase line, optionally for fewer packs (priced per pack)."""
    avail = quote["packs"] or quote["max_packs"] or 0
    n = min(packs or avail, avail)
    goods = quote["goods_price"] if n == quote["packs"] and quote["goods_price"] is not None else (
        quote["unit_price"] * n if quote["unit_price"] is not None else None)
    s = info.get(quote["supplier"], {})
    return Line(quote["quote_id"], quote["supplier"], s.get("email", ""), quote["label"], s.get("sku") if s.get("status") == "approved" else None,
                n, D(str(quote["pack_size_kg"])), quote["unit_price"], goods, quote["delivery_charge"], quote["vat_rate"],
                clock.local(quote["arrival_at"]), s.get("status") == "approved", s.get("auto_ok", False), rel)


def _sort_key(plan: Plan, prefs: dict):
    """Reliability first, then cost, then confirmed soft preferences (documented tie-breaker)."""
    rel = plan.lines[0].reliability.get("on_time_rate") if len(plan.lines) == 1 else None
    soft = sum(D(str(prefs.get(f"avoid:{l.supplier}", {}).get("penalty", 0))) for l in plan.lines)
    return (-(rel if rel is not None else -1), plan.total if plan.total is not None else D("1e9"), soft)


@traced("execution.evaluate", span_type="CHAIN")
def evaluate(inc: dict) -> dict:
    """Validate every single offer; split into qualifying (ranked) and disqualified (with reasons)."""
    ctx = context(inc)
    info = _supplier_info(inc["ingredient"])
    rels = {}
    plans = []
    for quote in active_quotes(inc["id"]):
        rel = rels.setdefault(quote["supplier"], tools.reliability(quote["supplier"]))
        plans.append(validate(Plan([line_from(quote, info, rel)]), ctx))
    qualifying = sorted([p for p in plans if p.qualifies], key=lambda p: _sort_key(p, ctx.prefs))
    return {"ctx": ctx, "qualifying": qualifying, "disqualified": [p for p in plans if not p.qualifies]}


def best_combination(inc: dict, ctx: Ctx, exclude_suppliers: set = frozenset(), kind: str = "split",
                     allow_partial: bool = False) -> Plan | None:
    """Cheapest plan of one or two in-time offers (distinct suppliers) that covers ctx.need_kg and passes every check.
    With allow_partial, returns the in-time combination saving the most kg instead (no full cover possible)."""
    info = _supplier_info(inc["ingredient"])
    pool_ = []  # (quote, full line) for offers that arrive in time and are fully priced
    for quote in active_quotes(inc["id"]):
        if quote["supplier"] in exclude_suppliers:
            continue
        line = line_from(quote, info, tools.reliability(quote["supplier"]))
        if line.packs and line.total is not None and status_of(validate(Plan([line]), ctx), "in_time") == "pass":
            pool_.append((quote, line))
    best: Plan | None = None
    for size in (1, 2):
        for combo in combinations(pool_, size):
            if len({l.supplier for _, l in combo}) < size:
                continue
            need, lines = packs_needed(ctx.need_kg, combo[0][1].pack_size_kg), []
            for quote, line in sorted(combo, key=lambda c: c[1].total / c[1].packs):  # cheapest per pack first
                take = min(line.packs, need)
                if take > 0:
                    lines.append(line_from(quote, info, line.reliability, take))
                    need -= take
            if len(lines) < size:
                continue  # the second offer wasn't needed; the single-offer pass already covers that
            plan = validate(Plan(lines, kind=kind if (len(lines) > 1 or kind == "top_up") else "single"), ctx)
            if allow_partial:  # everything but quantity must pass; prefer more kg saved, then lower cost
                ok = all(c["status"] != "fail" for c in plan.checks if c["id"] != "enough")
                better = best is None or (plan.kg, -plan.total) > (best.kg, -best.total)
            else:
                ok, better = plan.qualifies, best is None or plan.total < best.total
            if ok and better:
                best = plan
    if best and allow_partial:
        best.kind = "partial"
    return best


# ---------------------------------------------------------------- placing orders (idempotent)

@traced("execution.place_order", span_type="TOOL")
def place(incident_id: str, plan: Plan, approved_by: str = "auto") -> list[dict]:
    """Send one PO per line. Safe to re-run: the attempt number is persisted per plan signature before sending,
    and the UNIQUE idempotency key stops a second PO for the same supplier and attempt."""
    inc = store.incident(incident_id)
    st = inc["state"]
    if plan.signature in st.get("placed", []):
        return q("SELECT * FROM purchase_orders WHERE incident_id = %s", [incident_id])  # already done
    attempts = st.get("attempts", {})
    attempt = attempts.get(plan.signature) or len(attempts) + 1
    store.update_incident(incident_id, state={"attempts": {**attempts, plan.signature: attempt}})
    rules = store.rules()
    out = []
    for l in plan.lines:
        key = f"{incident_id}:{l.supplier}:{attempt}"
        line = store.jsonable({"quote_id": l.quote_id, "sku": l.sku, "product": inc["ingredient"], "packs": l.packs,
                               "pack_size_kg": l.pack_size_kg, "unit_price": (l.goods / l.packs).quantize(CENT),
                               "goods": l.goods, "delivery": l.delivery, "vat_rate": l.vat_rate, "total": l.total,
                               "arrival": clock.hhmm(l.arrival_at)})
        po = one("INSERT INTO purchase_orders (po_id, incident_id, supplier, lines, total, arrival_at, idempotency_key, status, approved_by) "
                 "VALUES ('PO-' || lpad(nextval('po_seq')::text, 4, '0'), %s, %s, %s, %s, %s, %s, 'sending', %s) "
                 "ON CONFLICT (idempotency_key) DO NOTHING RETURNING *",
                 [incident_id, l.supplier, [line], l.total, l.arrival_at, key, approved_by]) \
            or one("SELECT * FROM purchase_orders WHERE idempotency_key = %s", [key])
        if po["status"] == "sending":  # not sent yet (first run, or a crash before the send completed)
            thread = one("SELECT * FROM supplier_threads WHERE incident_id = %s AND supplier = %s", [incident_id, l.supplier])
            mail = outbox.send(incident_id, l.supplier, l.email, "po", "purchase_order", thread_id=thread["thread_id"],
                               reply_to=store.last_inbound(incident_id, l.supplier), po_id=po["po_id"], packs=l.packs,
                               pack_size=f"{l.pack_size_kg:g}", ingredient=inc["ingredient"], sku=l.sku or "new supplier",
                               kg=f"{l.kg:g}", unit_price=line["unit_price"], delivery=f"{l.delivery:.2f}",
                               total=f"{l.total:.2f}", arrival=line["arrival"], area=rules["postcode_area"])
            po = one("UPDATE purchase_orders SET status = 'sent', sent_at = %s, message_id = %s WHERE po_id = %s RETURNING *",
                     [clock.now(), mail.message_id, po["po_id"]])
            q("UPDATE supplier_threads SET status = 'ordered', last_contact_at = %s WHERE incident_id = %s AND supplier = %s",
              [clock.now(), incident_id, l.supplier])
            store.log_event(incident_id, "execute", "execution_service", "po_sent",
                            f"{po['po_id']} sent to {l.supplier}, approved {'automatically' if approved_by == 'auto' else 'by you'}",
                            {"po_id": po["po_id"], "idempotency_key": key, "total": l.total, "message_id": mail.message_id,
                             "refs": ["purchase order", "duplicate-order guard"]})
        out.append(po)
    store.update_incident(incident_id, state={"placed": st.get("placed", []) + [plan.signature]})
    return out


# ---------------------------------------------------------------- confirmations and stock

def match(po: dict, conf: dict) -> dict:
    """Compare a confirmation with the agreed PO, field by field. Missing confirmed values count as mismatches."""
    a = po["lines"][0]
    eq_money = lambda x, y: y is not None and money(x) == money(y)  # noqa: E731
    ref = (conf.get("po_reference") or "").replace("–", "-").replace(" ", "-").upper()
    rows = [
        ("Product", f"{a['product'].capitalize()}, {D(a['pack_size_kg']):g} kg",
         f"{(conf.get('product') or '?').capitalize()}, {conf.get('pack_size_kg') or '?':g} kg" if conf.get("pack_size_kg") else conf.get("product"),
         bool(conf.get("product")) and a["product"] in conf["product"].lower() and D(str(conf.get("pack_size_kg") or 0)) == D(a["pack_size_kg"])),
        ("Quantity", f"{a['packs']} bags · {a['packs'] * D(a['pack_size_kg']):g} kg",
         f"{conf.get('packs')} bags · {(conf.get('packs') or 0) * D(a['pack_size_kg']):g} kg" if conf.get("packs") else None,
         conf.get("packs") == a["packs"]),
        ("Unit price", f"£{D(a['unit_price']):.2f}", f"£{conf['unit_price']:.2f}" if conf.get("unit_price") is not None else None,
         eq_money(a["unit_price"], conf.get("unit_price"))),
        ("Delivery", f"£{D(a['delivery']):.2f}", f"£{conf['delivery_charge']:.2f}" if conf.get("delivery_charge") is not None else None,
         eq_money(a["delivery"], conf.get("delivery_charge"))),
        ("Total", f"£{D(a['total']):.2f}", f"£{conf['total']:.2f}" if conf.get("total") is not None else None,
         eq_money(a["total"], conf.get("total"))),
        ("Arrival", f"Tomorrow, {a['arrival']}", f"Tomorrow, {conf['arrival_time']}" if conf.get("arrival_time") else None,
         conf.get("arrival_time") == a["arrival"]),
        ("Reference", po["po_id"], ref or None, ref == po["po_id"]),
    ]
    fields = [{"field": f, "agreed": ag, "confirmed": c if c is not None else "Not stated", "ok": bool(ok)} for f, ag, c, ok in rows]
    return {"fields": fields, "all_ok": all(f["ok"] for f in fields), "matched": sum(f["ok"] for f in fields), "of": len(fields)}


def add_on_order(inc: dict, po: dict, packs: int, arrival_at: datetime, total: D) -> None:
    """Record stock ON ORDER (an incoming delivery). Physical inventory is untouched until receipt."""
    a = po["lines"][0]
    sql.query(f"DELETE FROM {sql.T('incoming_deliveries')} WHERE po_id = :po", {"po": po["po_id"]})  # idempotent
    sql.insert("incoming_deliveries", [{
        "po_id": po["po_id"], "supplier": po["supplier"], "ingredient": inc["ingredient"],
        "quantity_kg": float(packs * D(a["pack_size_kg"])), "expected_arrival": arrival_at, "status": "confirmed", "total_cost": total}])


def mark_received(po_id: str) -> dict:
    """Owner checked the delivery in: only now does physical stock change."""
    d = sql.query(f"SELECT * FROM {sql.T('incoming_deliveries')} WHERE po_id = :po AND status = 'confirmed'", {"po": po_id})
    if not d:
        return {"ok": False, "reason": "No confirmed delivery for this PO"}
    sql.query(f"UPDATE {sql.T('inventory')} SET quantity_kg = quantity_kg + :kg, last_updated = :now WHERE ingredient = :ing",
              {"kg": d[0]["quantity_kg"], "now": clock.now(), "ing": d[0]["ingredient"]})
    sql.query(f"UPDATE {sql.T('incoming_deliveries')} SET status = 'received' WHERE po_id = :po", {"po": po_id})
    q("UPDATE purchase_orders SET status = 'received' WHERE po_id = %s", [po_id])
    return {"ok": True, "kg": d[0]["quantity_kg"]}
