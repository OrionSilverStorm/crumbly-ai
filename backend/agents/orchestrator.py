"""Orchestrator: an explicit state machine over Detect -> Understand -> Investigate -> Coordinate -> Decide -> Execute -> Update.

Entry points (inbound email, timer tick, owner decision) run one at a time under a single lock, and every step is
persisted before the next, so restarting the process resumes open incidents instead of starting over.
"""
import logging
import threading

from backend import store, tracing
from backend.agents import production, recovery, sourcing
from backend.db.lakebase import one, q
from backend.dbx import sql
from backend.demo import clock
from backend.email import outbox
from backend.email.transport import Mail
from backend.execution import service as ex

log = logging.getLogger("crumbly.orchestrator")
lock = threading.RLock()  # one step at a time: deterministic, no races between poller, timers and owner actions


def _start_research(incident_id: str) -> None:
    """Linkup research runs in parallel with the approved-supplier enquiries."""
    threading.Thread(target=sourcing.research, args=(store.incident(incident_id), lock), daemon=True, name=f"research-{incident_id}").start()


@tracing.traced("crumbly.inbound_email", span_type="CHAIN")
def on_inbound(mail: Mail) -> str:
    """Route one inbound email: a reply in a known supplier thread, or a possible new incident."""
    with lock:
        seen = one("SELECT processed FROM email_messages WHERE message_id = %s", [mail.message_id])
        if seen and seen["processed"]:
            return "duplicate"
        thread = store.thread_for(mail)
        if thread:
            tracing.tag_incident(thread["incident_id"])
            store.record_email(mail, "inbound", "reply", thread["incident_id"], thread["supplier"], thread["thread_id"])
            result = _on_reply(store.incident(thread["incident_id"]), thread, mail)
        else:
            store.record_email(mail, "inbound", "other")
            result = _on_possible_trigger(mail)
        q("UPDATE email_messages SET processed = true WHERE message_id = %s", [mail.message_id])
        return result


def _on_reply(inc: dict, thread: dict, mail: Mail) -> str:
    """Supplier reply: a confirmation if we've ordered from them, otherwise a quote."""
    if thread["status"] == "ordered":
        return recovery.on_confirmation(inc, thread, mail)
    if inc["stage"] in ("investigate",):
        store.set_stage(inc["id"], "coordinate")
    sourcing.handle_quote(inc, thread, mail)
    return recovery.decide(inc["id"])  # the stage moves to Decide only when we act or ask (see recovery.act)


def _on_possible_trigger(mail: Mail) -> str:
    """Detect: is this a supplier cancelling/shortening a PO we're expecting?"""
    det = production.detect(mail)
    if not det or not det.facts.get("matched"):
        return "ignored"
    return open_incident(mail, det.facts, det.uncertainties)


def open_incident(mail: Mail, f: dict, doubts: list[str]) -> str:
    """Create the incident, then run Understand and Investigate straight away."""
    iid = one("SELECT 'INC-' || lpad(nextval('incident_seq')::text, 4, '0') AS id")["id"]
    tracing.tag_incident(iid)
    rules = store.rules()
    # The cancelled delivery no longer counts as incoming stock (a short delivery keeps the remainder).
    remaining = f["kg_ordered"] - f["kg_lost"]
    sql.query(f"UPDATE {sql.T('incoming_deliveries')} SET status = :s, quantity_kg = :kg WHERE po_id = :po",
              {"s": "cancelled" if remaining <= 0 else "scheduled", "kg": remaining if remaining > 0 else f["kg_ordered"], "po": f["po_id"]})
    q("INSERT INTO incidents (id, ingredient, status, stage, opened_at, trigger_message_id, original_po, production_date, state) "
      "VALUES (%s,%s,'open','detect',%s,%s,%s,%s,%s)",
      [iid, f["ingredient"], clock.now(), mail.message_id, f["po_id"], f["expected_arrival"].date(),
       store.jsonable({"original_supplier": f["supplier"], "kind": f["kind"], "po_cost": f["po_cost"], "uncertainties": doubts,
                       "trigger": {"from": mail.from_addr, "subject": mail.subject, "body": mail.body, "message_id": mail.message_id}})])
    q("UPDATE email_messages SET incident_id = %s, supplier = %s, kind = 'trigger' WHERE message_id = %s", [iid, f["supplier"], mail.message_id])
    store.log_event(iid, "detect", "production_agent", "incident_opened",
                    f"{f['kind'].capitalize()} email from {f['supplier']} matched to {f['po_id']}",
                    {"message_id": mail.message_id, "po_id": f["po_id"], "uncertainties": doubts, "refs": ["email message ID and thread stored"]})
    # Understand
    store.set_stage(iid, "understand")
    u = production.understand(f["ingredient"], f["expected_arrival"].date(), rules["arrival_buffer_min"]).facts
    store.update_incident(iid, shortage_kg=u["shortage_kg"], deadline=u["production_start"], state={
        "packs": u["packs"], "pack_size_kg": u["pack_size_kg"], "shortage": {k: u[k] for k in ("needed_kg", "on_hand_kg", "reserved_kg", "incoming_kg", "shortage_kg")},
        "orders": u["orders"], "at_risk": [o["order_id"] for o in u["at_risk"]], "baseline_coverage": u["coverage"],
        "coverage_now": u["coverage"], "refreshed_at": u["refreshed_at"]})
    store.log_event(iid, "understand", "production_agent", "shortage_calculated",
                    f"Shortage calculated: {u['shortage_kg']:g} kg · {len(u['at_risk'])} customer orders affected",
                    {"shortage": u["shortage_kg"], "packs": u["packs"], "refs": ["calculate_shortage", "get_affected_orders", "coverage_by_slot"]})
    if u["shortage_kg"] <= 0:
        store.update_incident(iid, status="resolved", resolved_at=clock.now())
        return iid
    # Investigate: approved suppliers by email, new suppliers via Linkup in parallel.
    store.set_stage(iid, "investigate")
    sourcing.contact_approved(store.incident(iid))
    _start_research(iid)
    return iid


@tracing.traced("crumbly.timers", span_type="CHAIN")
def tick() -> None:
    """Chase/drop timers; re-plan any incident whose options changed."""
    with lock:
        for iid in set(sourcing.run_timers()):
            tracing.tag_incident(iid)
            recovery.decide(iid)


@tracing.traced("crumbly.owner_decision", span_type="CHAIN")
def resolve_decision(decision_id: int, option_id: str) -> dict:
    """Carry out the owner's choice through the execution service. Re-validates plans before acting."""
    with lock:
        d = one("SELECT * FROM pending_decisions WHERE id = %s", [decision_id])
        if not d or d["status"] != "open":
            return {"ok": False, "reason": "This decision is no longer open"}
        opt = next((o for o in d["options"] if o["id"] == option_id), None)
        if not opt:
            return {"ok": False, "reason": "Unknown option"}
        tracing.tag_incident(d["incident_id"])
        inc = store.incident(d["incident_id"]) if d["incident_id"] else None
        result = _apply(d, opt, inc)
        if result.get("ok", True):
            q("UPDATE pending_decisions SET status = 'resolved', chosen = %s, resolved_at = %s WHERE id = %s", [option_id, clock.now(), decision_id])
            if inc:
                store.log_event(inc["id"], inc["stage"], "owner", "owner_decision", f"You chose: {opt['label']}", {"decision_id": decision_id, "option": option_id})
                if not one("SELECT 1 FROM pending_decisions WHERE incident_id = %s AND status = 'open'", [inc["id"]]) \
                        and store.incident(inc["id"])["status"] == "needs_owner":
                    store.update_incident(inc["id"], status="open")
        return {"ok": True, **result}


def _place_owner_plan(inc: dict, plan: dict, ctx: ex.Ctx | None = None) -> dict:
    """Rebuild, re-validate and place a plan the owner approved (owner approval satisfies 'needs your OK' checks only)."""
    p = recovery.plan_from(inc, plan, ctx or ex.context(inc))
    if not p.qualifies:
        return {"ok": False, "reason": "That option no longer passes your rules: " + ", ".join(p.as_dict()["reasons"])}
    store.set_stage(inc["id"], "execute", "open")
    return {"ok": True, "pos": [x["po_id"] for x in ex.place(inc["id"], p, "owner")]}


def _apply(d: dict, opt: dict, inc: dict | None) -> dict:
    """Option handlers per decision kind."""
    kind, oid = d["kind"], opt["id"]
    if kind == "approve_order" and oid == "approve":
        return _place_owner_plan(inc, opt["plan"])
    if kind == "no_qualifying":
        return _place_owner_plan(inc, opt["plan"], ex.context(inc, need_kg=opt["plan"]["kg"])) if oid == "order_partial" else {"ok": True}
    if kind == "confirmation_mismatch":
        po = one("SELECT * FROM purchase_orders WHERE po_id = %s", [d["context"]["po_id"]])
        if oid == "ask_correct":
            diffs = "\n".join(f"- {f['field']}: agreed {f['agreed']}, you confirmed {f['confirmed']}" for f in opt["differences"])
            thread = one("SELECT * FROM supplier_threads WHERE incident_id = %s AND supplier = %s", [inc["id"], po["supplier"]])
            outbox.send(inc["id"], po["supplier"], thread["email"], "correction", "correction", thread_id=thread["thread_id"],
                        reply_to=store.last_inbound(inc["id"], po["supplier"]), subject=f"Purchase order {po['po_id']}",
                        po_id=po["po_id"], differences=diffs)
            q("UPDATE purchase_orders SET status = 'correction_requested' WHERE po_id = %s", [po["po_id"]])
            store.log_event(inc["id"], "execute", "execution_service", "correction_requested", f"Asked {po['supplier']} to correct {po['po_id']}", {"po_id": po["po_id"]})
            return {"ok": True}
        recovery.accept_confirmed(inc, po)
        if oid == "top_up":
            ctx = ex.context(store.incident(inc["id"]), need_kg=d["context"]["shortfall_kg"])
            ctx.open_po_suppliers.discard(po["supplier"])
            res = _place_owner_plan(inc, opt["plan"], ctx)
            return res
        recovery.check_resolution(inc["id"], accept_shortfall=True)  # accept_adjust
        return {"ok": True}
    if kind == "relax_slot":
        if oid.startswith("relax:"):
            slots = inc["state"].get("relaxed_slots", []) + [opt["bake_time"]]
            store.update_incident(inc["id"], state={"relaxed_slots": slots})
            store.log_event(inc["id"], "decide", "owner", "deadline_relaxed", f"You confirmed the {opt['bake_time'][11:16]} bake can wait", {"bake_time": opt["bake_time"]})
        recovery.decide(inc["id"])
        return {"ok": True}
    if kind == "rule_suggestion":
        key = d["context"]["key"]
        if oid == "accept":
            q("UPDATE preferences SET confirmed = true, source = 'owner' WHERE key = %s", [key])
        else:
            q("DELETE FROM preferences WHERE key = %s", [key])
        return {"ok": True}
    return {"ok": True}


def resume() -> None:
    """On startup: re-process unprocessed inbound mail, finish half-sent POs, restart unfinished research."""
    with lock:
        for row in q("SELECT * FROM email_messages WHERE direction = 'inbound' AND NOT processed ORDER BY sent_or_received_at"):
            # Recording is idempotent (ON CONFLICT DO NOTHING), so on_inbound simply carries on where it stopped.
            on_inbound(Mail(row["message_id"], row["from_addr"], row["to_addr"], row["subject"], row["body"],
                            row["in_reply_to"], [], row["sent_or_received_at"]))
        for inc in q("SELECT * FROM incidents WHERE status NOT IN ('resolved','resolved_partial')"):
            sending = q("SELECT * FROM purchase_orders WHERE incident_id = %s AND status = 'sending'", [inc["id"]])
            if sending:
                plan = recovery.plan_from(inc, {"kind": "single", "lines": [{"quote_id": p["lines"][0]["quote_id"], "packs": p["lines"][0]["packs"]} for p in sending]}, ex.context(inc))
                ex.place(inc["id"], plan, sending[0]["approved_by"])
            if inc["stage"] not in ("detect", "understand") and not inc["state"].get("research_done"):
                _start_research(inc["id"])
            log.info("Resumed %s at stage %s", inc["id"], inc["stage"])
