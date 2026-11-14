"""Recovery agent: ask the execution service to validate and rank offers, act or ask the owner, then match confirmations."""
from decimal import Decimal as D

from backend import store
from backend.agents import tools
from backend.agents.sourcing import AWAITING
from backend.db.lakebase import one, q
from backend.dbx.pipeline import parse
from backend.demo import clock
from backend.email.transport import Mail
from backend.execution import service as ex
from backend.llm.schemas import ConfirmationExtract
from backend.tracing import traced

RESOLVED = ("resolved", "resolved_partial")


def open_decision(incident_id: str, kind: str, title: str, options: list[dict], context: dict | None = None) -> dict:
    """Create a pending decision (superseding older open ones of the same kind) and flag the incident."""
    q("UPDATE pending_decisions SET status = 'superseded' WHERE incident_id = %s AND kind = %s AND status = 'open'", [incident_id, kind])
    d = one("INSERT INTO pending_decisions (incident_id, kind, title, context, options) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            [incident_id, kind, title, store.jsonable(context or {}), store.jsonable(options)])
    store.update_incident(incident_id, status="needs_owner")
    return d


def plan_from(inc: dict, plan: dict, ctx: ex.Ctx) -> ex.Plan:
    """Rebuild a stored plan from live quotes and re-validate it (state may have changed since it was proposed)."""
    info = ex._supplier_info(inc["ingredient"])
    lines = []
    for l in plan["lines"]:
        quote = one("SELECT * FROM quotes WHERE quote_id = %s", [l["quote_id"]])
        lines.append(ex.line_from(quote, info, tools.reliability(quote["supplier"]), l["packs"]))
    return ex.validate(ex.Plan(lines, kind=plan["kind"]), ctx)


def _ranking(ev: dict) -> dict:
    """Ranking for the UI: qualifying (in order) and disqualified (with reasons)."""
    return {"qualifying": [p.as_dict() for p in ev["qualifying"]], "disqualified": [p.as_dict() for p in ev["disqualified"]],
            "checked_at": clock.now()}


@traced("recovery_agent.decide", span_type="AGENT")
def decide(incident_id: str) -> str:
    """Re-plan after any change. Act as soon as no supplier still pending could outrank the best qualifying offer."""
    inc = store.incident(incident_id)
    if inc["status"] in RESOLVED or one("SELECT 1 FROM purchase_orders WHERE incident_id = %s AND status = ANY(%s)",
                                        [incident_id, list(ex.OPEN_PO)]):
        return "nothing_to_decide"
    if one("SELECT 1 FROM purchase_orders WHERE incident_id = %s AND status IN ('confirmed','accepted_adjusted')", [incident_id]):
        return "nothing_to_decide"  # already covered by a confirmed order
    ev = ex.evaluate(inc)
    store.update_incident(incident_id, state={"ranking": _ranking(ev)})
    waiting = q("SELECT supplier FROM supplier_threads WHERE incident_id = %s AND status = ANY(%s)", [incident_id, list(AWAITING)])
    best = ev["qualifying"][0] if ev["qualifying"] else None
    if best:
        best_rel = best.lines[0].reliability.get("on_time_rate") or -1
        rivals = [w["supplier"] for w in waiting if (tools.reliability(w["supplier"])["on_time_rate"] or -1) > best_rel]
        if rivals:
            return "waiting_for_better"
        plan = best
    elif waiting:
        return "waiting_for_replies"
    else:
        plan = ex.best_combination(inc, ev["ctx"])
        if not plan:
            return _no_option(inc, ev["ctx"])
    return act(inc, plan, ev["ctx"])


def act(inc: dict, plan: ex.Plan, ctx: ex.Ctx) -> str:
    """Order automatically when every rule allows it; otherwise ask the owner with the plan as the recommendation."""
    auto, why = ex.auto_allowed(plan, ctx)
    who = " + ".join(f"{l.supplier} ({l.packs} bags)" if len(plan.lines) > 1 else l.supplier for l in plan.lines)
    passed = sum(c["status"] == "pass" for c in plan.checks)
    if inc["state"].get("last_decided") != plan.signature:
        store.log_event(inc["id"], "decide", "recovery_agent", "offer_selected",
                        f"{who} at £{plan.total:.0f} — passed {passed} of {len(plan.checks)} checks",
                        {"plan": plan.as_dict(), "auto": auto, "why_owner": why, "refs": ["offer validation", "spending policy"]})
        store.update_incident(inc["id"], state={"last_decided": plan.signature, "proposal": plan.as_dict()})
    if auto:
        store.set_stage(inc["id"], "execute", "open")
        ex.place(inc["id"], plan, "auto")
        return "ordered"
    open_ = one("SELECT * FROM pending_decisions WHERE incident_id = %s AND kind = 'approve_order' AND status = 'open'", [inc["id"]])
    if not (open_ and open_["context"].get("signature") == plan.signature):
        open_decision(inc["id"], "approve_order", f"Order from {who}?", [
            {"id": "approve", "label": "Approve order", "recommended": True, "plan": plan.as_dict()},
            {"id": "not_this", "label": "Not this one"},
        ], {"signature": plan.signature, "why": why})
        store.log_event(inc["id"], "decide", "recovery_agent", "owner_needed", f"Needs your OK: {'; '.join(why)}", {"why": why})
    store.set_stage(inc["id"], "decide")
    return "asked_owner"


def _no_option(inc: dict, ctx: ex.Ctx) -> str:
    """Nobody qualifies: offer the best partial plan (showing which bakes it saves) or keep looking."""
    partial = ex.best_combination(inc, ctx, allow_partial=True)
    options = []
    if partial:
        last = max(l.arrival_at for l in partial.lines)
        slots = tools.coverage(inc["ingredient"], inc["production_date"], ctx.rules["arrival_buffer_min"], float(partial.kg), last)
        options.append({"id": "order_partial", "label": f"Order the {partial.kg:g} kg we can get", "recommended": True,
                        "plan": partial.as_dict(), "coverage": store.jsonable(slots)})
    options.append({"id": "keep_looking", "label": "Keep looking", "recommended": not partial})
    open_decision(inc["id"], "no_qualifying", "No offer covers everything in time", options)
    store.log_event(inc["id"], "decide", "recovery_agent", "no_qualifying", "No supplier qualifies — your decision needed",
                    {"partial": partial.as_dict() if partial else None})
    store.set_stage(inc["id"], "decide")
    return "no_option"


# ---------------------------------------------------------------- confirmations

@traced("recovery_agent.confirmation", span_type="AGENT")
def on_confirmation(inc: dict, thread: dict, mail: Mail) -> str:
    """Match a supplier's confirmation field by field. Any mismatch becomes a decision, never an acceptance."""
    po = one("SELECT * FROM purchase_orders WHERE incident_id = %s AND supplier = %s AND status IN ('sent','correction_requested') "
             "ORDER BY sent_at DESC LIMIT 1", [inc["id"], thread["supplier"]])
    if not po:
        return "no_open_po"
    conf, path = parse(ConfirmationExtract, mail.body, "This is a supplier confirming a purchase order.")
    c = conf.model_dump() if conf else {}
    m = ex.match(po, c)
    q("UPDATE purchase_orders SET confirmation = %s, match_result = %s, status = %s WHERE po_id = %s",
      [store.jsonable(c), m, "confirmed" if m["all_ok"] else "mismatch", po["po_id"]])
    if m["all_ok"]:
        a = po["lines"][0]
        ex.add_on_order(inc, po, a["packs"], clock.local(po["arrival_at"]), po["total"])
        q("UPDATE pending_decisions SET status = 'superseded' WHERE incident_id = %s AND kind = 'confirmation_mismatch' AND status = 'open'", [inc["id"]])
        store.log_event(inc["id"], "update", "recovery_agent", "confirmation_matched",
                        f"Confirmation matched; {a['packs'] * D(a['pack_size_kg']):g} kg added to stock on order",
                        {"po_id": po["po_id"], "match": m, "parse_path": path, "refs": ["field-by-field match", "coverage_by_slot"]})
        store.set_stage(inc["id"], "update")
        check_resolution(inc["id"])
        return "matched"
    return _mismatch(store.incident(inc["id"]), po, c, m)


def _mismatch(inc: dict, po: dict, conf: dict, m: dict) -> str:
    """Build the three options; the recommended top-up must itself pass every rule."""
    a, rules = po["lines"][0], store.rules()
    pack = D(a["pack_size_kg"])
    conf_packs = conf.get("packs") or 0
    conf_total = ex.money(conf.get("total")) if conf.get("total") is not None else po["total"]
    others = q("SELECT * FROM purchase_orders WHERE incident_id = %s AND po_id <> %s AND status IN ('confirmed','accepted_adjusted')",
               [inc["id"], po["po_id"]])
    have_kg = sum((D(str(o["lines"][0]["packs"])) * D(o["lines"][0]["pack_size_kg"]) for o in others), D("0"))
    shortfall = max(D(str(inc["shortage_kg"])) - have_kg - conf_packs * pack, D("0"))
    committed = sum((o["total"] for o in others), D("0")) + conf_total
    arrival = clock.at(inc["production_date"], conf["arrival_time"]) if conf.get("arrival_time") else clock.local(po["arrival_at"])
    slots = tools.coverage(inc["ingredient"], inc["production_date"], rules["arrival_buffer_min"], float(conf_packs * pack), arrival)
    orders = tools.affected_orders(inc["ingredient"], inc["production_date"])
    short = [{"bake_time": s["bake_time"], "short_kg": s["cumulative_required"] - s["cumulative_available"],
              "customers": [{"customer": o["customer"], "description": o["description"],
                             "units": round((s["cumulative_required"] - s["cumulative_available"]) / (o["kg_required"] / o["quantity"])),
                             "product": o["product"]} for o in orders if o["bake_time"] == s["bake_time"]]}
             for s in slots if not s["covered"]]
    options = []
    if shortfall > 0:
        ctx = ex.context(inc, need_kg=shortfall, committed=committed)
        top = ex.best_combination(inc, ctx, exclude_suppliers={po["supplier"]}, kind="top_up")
        if top:
            options.append({"id": "top_up", "label": f"Top up from {top.lines[0].supplier}", "recommended": True,
                            "plan": top.as_dict(), "new_total": store.jsonable(committed + top.total)})
    options.append({"id": "ask_correct", "label": f"Ask {po['supplier']} to correct it", "recommended": not options,
                    "differences": [f for f in m["fields"] if not f["ok"]]})
    options.append({"id": "accept_adjust", "label": "Accept and adjust", "recommended": False,
                    "shortfall_kg": store.jsonable(shortfall), "slots": store.jsonable(short)})
    wrong = ", ".join(f["field"].lower() for f in m["fields"] if not f["ok"])
    open_decision(inc["id"], "confirmation_mismatch", f"{po['supplier']} confirmed something different", options,
                  {"po_id": po["po_id"], "match": m, "confirmation": conf, "shortfall_kg": shortfall})
    store.log_event(inc["id"], "execute", "execution_service", "confirmation_mismatch",
                    f"{po['supplier']}'s confirmation doesn't match ({wrong}) — not accepted",
                    {"po_id": po["po_id"], "match": m, "refs": ["field-by-field match"]})
    store.set_stage(inc["id"], "execute")
    return "mismatch"


def accept_confirmed(inc: dict, po: dict) -> None:
    """Owner accepted the supplier's confirmed (different) terms: record those as stock on order."""
    c = po["confirmation"] or {}
    total = ex.money(c.get("total")) if c.get("total") is not None else po["total"]
    arrival = clock.at(inc["production_date"], c["arrival_time"]) if c.get("arrival_time") else clock.local(po["arrival_at"])
    q("UPDATE purchase_orders SET status = 'accepted_adjusted', total = %s WHERE po_id = %s", [total, po["po_id"]])
    po = one("SELECT * FROM purchase_orders WHERE po_id = %s", [po["po_id"]])
    ex.add_on_order(inc, po, c.get("packs") or 0, arrival, total)


def check_resolution(incident_id: str, accept_shortfall: bool = False) -> bool:
    """Recalculate coverage with confirmed deliveries; resolve when every (non-relaxed) bake is covered."""
    inc = store.incident(incident_id)
    if one("SELECT 1 FROM purchase_orders WHERE incident_id = %s AND status = ANY(%s)", [incident_id, list(ex.OPEN_PO)]):
        return False
    rules = store.rules()
    slots = tools.coverage(inc["ingredient"], inc["production_date"], rules["arrival_buffer_min"])
    relaxed = set(inc["state"].get("relaxed_slots", []))
    covered = all(s["covered"] or s["bake_time"].isoformat() in relaxed for s in slots)
    store.update_incident(incident_id, state={"coverage_now": slots})
    store.log_event(incident_id, "update", "recovery_agent", "coverage_recalculated",
                    f"Coverage recalculated: {sum(s['covered'] for s in slots)} of {len(slots)} bakes covered",
                    {"coverage": slots, "refs": ["coverage_by_slot"]})
    if not (covered or accept_shortfall):
        return False
    status = "resolved" if covered else "resolved_partial"
    store.update_incident(incident_id, status=status, stage="update", resolved_at=clock.now())
    store.log_event(incident_id, "update", "recovery_agent", "resolved",
                    "All orders are covered again" if covered else "Resolved with a shortfall you accepted", {"coverage": slots})
    return True
