"""End-to-end scenarios over (in-memory) email with the scripted supplier bot, at 600x demo time."""
import time
from decimal import Decimal as D

from backend import feedback
from backend.agents import orchestrator, recovery
from backend.db.lakebase import one, q
from backend.execution import service as ex
from backend.tests.conftest import incident, trigger


def _resolved():
    inc = incident()
    return inc is not None and inc["status"] in ("resolved", "resolved_partial")


def _open_decision(kind):
    return lambda: one("SELECT * FROM pending_decisions WHERE kind = %s AND status = 'open'", [kind]) is not None


def _decision(kind):
    return one("SELECT * FROM pending_decisions WHERE kind = %s AND status = 'open' ORDER BY id DESC LIMIT 1", [kind])


def test_happy_path_end_to_end(scenario):
    drive = scenario("happy")
    t0 = time.time()
    trigger()
    assert drive(lambda: incident() is not None, timeout=20)
    inc = incident()
    assert float(inc["shortage_kg"]) == 160 and len(inc["state"]["at_risk"]) == 3 and inc["state"]["packs"] == 7
    assert drive(_resolved, timeout=170), "happy path did not resolve"
    assert time.time() - t0 < 180
    inc = incident()
    pos = q("SELECT * FROM purchase_orders WHERE incident_id = %s", [inc["id"]])
    assert [(p["po_id"], p["supplier"], p["total"], p["status"]) for p in pos] == [("PO-0087", "Borough Mill", D("165.00"), "confirmed")]
    assert one("SELECT COUNT(*) AS n FROM email_messages WHERE incident_id = %s AND kind = 'followup'", [inc["id"]])["n"] == 1
    assert all(s["covered"] for s in inc["state"]["coverage_now"])
    # Linkup research ran in parallel and Thames Grain was contacted as a new supplier.
    assert one("SELECT * FROM supplier_threads WHERE incident_id = %s AND supplier = 'Thames Grain Co.'", [inc["id"]])["is_new"]
    # Wheatfield never replies: chased, then dropped on schedule.
    assert drive(lambda: one("SELECT status FROM supplier_threads WHERE supplier = 'Wheatfield Direct'")["status"] == "dropped", timeout=20)
    assert one("SELECT 1 AS x FROM incident_events WHERE type = 'supplier_chased'") is not None


def test_rerunning_steps_never_sends_a_second_po(scenario):
    drive = scenario("happy")
    trigger()
    assert drive(lambda: one("SELECT 1 AS x FROM purchase_orders") is not None, timeout=120)
    inc = incident()
    plan = recovery.plan_from(inc, inc["state"]["proposal"], ex.context(inc))
    before = one("SELECT COUNT(*) AS n FROM email_messages WHERE kind = 'po'")["n"]
    ex.place(inc["id"], plan, "auto")              # same step again
    recovery.decide(inc["id"])                      # and the decision step again
    # Even with the 'placed' marker lost (e.g. a crash just after sending), the idempotency key holds.
    from backend import store
    store.update_incident(inc["id"], state={"placed": []})
    ex.place(inc["id"], plan, "auto")
    assert one("SELECT COUNT(*) AS n FROM email_messages WHERE kind = 'po'")["n"] == before == 1
    assert one("SELECT COUNT(*) AS n FROM purchase_orders")["n"] == 1


def test_short_confirm_creates_decision_and_top_up_passes_every_rule(scenario):
    drive = scenario("short_confirm")
    trigger()
    assert drive(_open_decision("confirmation_mismatch"), timeout=150)
    po = one("SELECT * FROM purchase_orders WHERE supplier = 'Borough Mill'")
    assert po["status"] == "mismatch"  # never accepted
    d = _decision("confirmation_mismatch")
    top = next(o for o in d["options"] if o["id"] == "top_up")
    assert top["recommended"] and D(top["new_total"]) == D("170.00")
    assert all(c["status"] == "pass" for c in top["plan"]["checks"])
    assert top["plan"]["lines"][0]["supplier"] == "Harrow & Sons" and top["plan"]["lines"][0]["packs"] == 1
    adjust = next(o for o in d["options"] if o["id"] == "accept_adjust")
    assert D(adjust["shortfall_kg"]) == 10 and adjust["slots"][0]["customers"][0]["customer"] == "Alder Hotel"
    assert orchestrator.resolve_decision(d["id"], "top_up")["ok"]
    assert drive(_resolved, timeout=60)
    totals = {p["supplier"]: p["total"] for p in q("SELECT * FROM purchase_orders")}
    assert totals == {"Borough Mill": D("144.00"), "Harrow & Sons": D("26.00")}


def test_new_supplier_wins_needs_owner_approval(scenario):
    drive = scenario("new_supplier_wins")
    trigger()
    assert drive(_open_decision("approve_order"), timeout=150)
    inc = incident()
    claims = {r["claim"]: r["status"] for r in q("SELECT * FROM research WHERE incident_id = %s", [inc["id"]])}
    assert claims == {"Delivers to SE1": "confirmed", "Sells 25 kg strong white flour": "confirmed",
                      "Next-day delivery from": "conflicting", "Trade minimum": "unverified"}
    assert all(r["source_urls"] for r in q("SELECT * FROM research"))
    assert one("SELECT 1 AS x FROM incident_events WHERE type = 'claim_conflict'")  # emailed 04:30 vs published 07:00
    assert one("SELECT COUNT(*) AS n FROM purchase_orders")["n"] == 0  # nothing bought without the owner
    d = _decision("approve_order")
    assert d["options"][0]["plan"]["suppliers"] == ["Thames Grain Co."]
    assert orchestrator.resolve_decision(d["id"], "approve")["ok"]
    assert drive(_resolved, timeout=60)
    assert one("SELECT approved_by FROM purchase_orders")["approved_by"] == "owner"


def test_owner_rejects_replans_with_split_and_suggests_rule(scenario):
    drive = scenario("owner_rejects")
    trigger()
    assert drive(lambda: (d := _decision("approve_order")) is not None and d["options"][0]["plan"]["suppliers"] == ["Borough Mill"], timeout=150)
    inc = incident()
    quote_id = inc["state"]["proposal"]["lines"][0]["quote_id"]
    with orchestrator.lock:
        out = feedback.submit(inc["id"], "too_expensive", "Bit steep", quote_id=quote_id)
    assert out["suggestion"]["amount"] == 150  # two flour rejections over £150
    assert _decision("rule_suggestion") is not None
    plan = _decision("approve_order")["options"][0]["plan"]
    assert plan["kind"] == "split" and sorted(plan["suppliers"]) == ["Harrow & Sons", "Wheatfield Direct"]
    assert D(plan["total"]) == D("162.00") and plan["qualifies"]
    assert orchestrator.resolve_decision(_decision("approve_order")["id"], "approve")["ok"]
    assert drive(_resolved, timeout=60)
    assert one("SELECT COUNT(*) AS n FROM purchase_orders WHERE status = 'confirmed'")["n"] == 2
