"""Read models for the UI and the help assistant. Everything the screens show comes from here (nothing hard-coded)."""
import time
from decimal import Decimal as D

from backend import store, tracing
from backend.agents import tools
from backend.config import settings
from backend.db.lakebase import one, q
from backend.dbx import sql
from backend.demo import clock

_rel_cache: dict[str, tuple[float, dict]] = {}


def reliability(supplier: str) -> dict:
    """supplier_reliability with a 60 s cache (UI refreshes often; warehouse calls are not free)."""
    hit = _rel_cache.get(supplier)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    r = tools.reliability(supplier)
    _rel_cache[supplier] = (time.time(), r)
    return r


def config() -> dict:
    """Demo badge, modes and footer for the shell."""
    warehouse = "Databricks warehouse" if settings.warehouse_mode == "databricks" else "local Databricks-schema mirror"
    email = "Gmail transport" if settings.email_mode == "gmail" else "controlled demo inbox"
    model = "Databricks model" if settings.llm_provider == "databricks" else "deterministic extraction" if settings.llm_provider == "stub" else "external model"
    linkup = "live Linkup research" if settings.linkup_mode == "live" else "controlled Linkup fixture"
    return {"scenario": store.demo_state("scenario", settings.scenario), "time_scale": settings.time_scale,
            "modes": {"db": settings.db_mode, "warehouse": settings.warehouse_mode, "llm": settings.llm_provider,
                      "email": settings.email_mode, "linkup": settings.linkup_mode, "tracing": tracing.status()},
            "scenario_availability": {
                "new_supplier_wins": {
                    "enabled": settings.linkup_mode == "fixture",
                    "reason": "This controlled scenario needs the bundled Linkup fixture and scripted Thames Grain reply."
                }
            },
            "footer": f"{linkup} · {warehouse} · {email} · {model} · fictional bakery data",
            "rules": rules_summary()}


def rules_summary() -> dict:
    r = store.rules() or {}
    return store.jsonable(r)


def incidents() -> list[dict]:
    """All incidents, newest first, with a one-line 'what happened'."""
    rows = q("SELECT id, ingredient, status, stage, opened_at, resolved_at, shortage_kg, summary, state->>'kind' AS kind, state ? 'history' AS history, "
             "(SELECT COUNT(*) FROM pending_decisions d WHERE d.incident_id = i.id AND d.status = 'open') AS open_decisions "
             "FROM incidents i ORDER BY opened_at DESC")
    for r in rows:
        if not r["summary"]:
            r["summary"] = f"Delivery {r['kind'] or 'cancelled'} · {r['shortage_kg']:g} kg short" if r["shortage_kg"] else "Checking"
    return store.jsonable(rows)


def snapshot(incident_id: str) -> dict | None:
    """Everything one incident page needs, in one call."""
    inc = store.incident(incident_id)
    if not inc:
        return None
    threads = q("SELECT * FROM supplier_threads WHERE incident_id = %s ORDER BY is_new, supplier", [incident_id])
    for t in threads:
        t["reliability"] = reliability(t["supplier"]) if not t["is_new"] else {"on_time_rate": None, "deliveries": 0}
        t["replied_at"] = (one("SELECT MIN(sent_or_received_at) AS at FROM email_messages WHERE incident_id = %s AND supplier = %s "
                               "AND direction = 'inbound'", [incident_id, t["supplier"]]) or {}).get("at")
    events = q("SELECT * FROM incident_events WHERE incident_id = %s ORDER BY id", [incident_id])
    for e in events:
        e["trace_url"] = tracing.trace_url(e["evidence"].get("trace_id"))
    emails = q("SELECT message_id, supplier, direction, kind, subject, body, sent_or_received_at FROM email_messages "
               "WHERE incident_id = %s ORDER BY sent_or_received_at", [incident_id])
    return store.jsonable({
        "incident": inc, "events": events, "threads": threads, "emails": emails,
        "quotes": q("SELECT * FROM quotes WHERE incident_id = %s ORDER BY quote_id", [incident_id]),
        "research": q("SELECT * FROM research WHERE incident_id = %s ORDER BY research_id", [incident_id]),
        "purchase_orders": q("SELECT * FROM purchase_orders WHERE incident_id = %s ORDER BY sent_at NULLS LAST", [incident_id]),
        "decisions": q("SELECT * FROM pending_decisions WHERE incident_id = %s ORDER BY id DESC", [incident_id]),
        "rules": store.rules(), "now": clock.now(),
        "stats": {"emails_sent": sum(e["direction"] == "outbound" for e in emails),
                  "replies": sum(e["direction"] == "inbound" and e["kind"] != "trigger" for e in emails),
                  "owner_decisions": sum(e["actor"] == "owner" for e in events)},
        "stock": stock(inc),
    })


def stock(inc: dict) -> dict:
    """On hand vs on order vs needed (flour on its way is tracked separately from flour on the shelf)."""
    s = (inc["state"] or {}).get("shortage") or {}
    on_order = sql.query(f"SELECT COALESCE(SUM(quantity_kg), 0) AS kg, MAX(expected_arrival) AS last FROM {sql.T('incoming_deliveries')} "
                         "WHERE ingredient = :i AND status = 'confirmed'", {"i": inc["ingredient"]})[0]
    # Live shelf stock, not the snapshot taken when the incident opened: a delivery the owner marks as received leaves
    # "on order" and lands here, so reading the snapshot would make received flour vanish from the totals.
    inv = sql.query(f"SELECT COALESCE(SUM(quantity_kg), 0) AS kg, COALESCE(SUM(reserved_kg), 0) AS reserved FROM {sql.T('inventory')} "
                    "WHERE ingredient = :i", {"i": inc["ingredient"]})[0]
    on_hand = float(inv["kg"] or 0) - float(inv["reserved"] or 0)
    available = on_hand + (on_order["kg"] or 0)
    return {"on_hand_kg": on_hand, "on_order_kg": on_order["kg"] or 0, "on_order_arrival": clock.local(on_order["last"]),  # everything is in by the latest delivery
            "available_kg": available, "needed_kg": s.get("needed_kg", 0), "spare_kg": available - s.get("needed_kg", 0)}


def metrics() -> dict:
    """Headline metrics computed with SQL over Lakebase (incidents, events, POs) and Delta (order values)."""
    agg = one("""
        SELECT COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved,
               COUNT(*) AS total,
               AVG(EXTRACT(EPOCH FROM resolved_at - opened_at) / 60) FILTER (WHERE resolved_at IS NOT NULL) AS avg_recover_min,
               COUNT(*) FILTER (WHERE resolved_at IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM incident_events e WHERE e.incident_id = i.id AND e.actor = 'owner')) AS without_owner
        FROM incidents i""")
    live = q("SELECT i.id, i.ingredient, i.production_date, i.state, "
             "(SELECT SUM(total) FROM purchase_orders p WHERE p.incident_id = i.id AND p.status IN ('confirmed','accepted_adjusted','received')) AS spent "
             "FROM incidents i WHERE i.resolved_at IS NOT NULL")
    protected, value, extra = 0, D("0"), D("0")
    for r in live:
        st = r["state"]
        if st.get("history"):
            protected += st["orders_protected"]
            value += D(st["orders_value"])
            extra += D(st["replacement_total"]) - D(st["po_cost"])
            continue
        covered = {s["bake_time"] for s in st.get("coverage_now", []) if s["covered"]}
        at_risk = set(st.get("at_risk", []))
        orders = [o for o in tools.affected_orders(r["ingredient"], r["production_date"]) if o["order_id"] in at_risk]
        saved = [o for o in orders if o["bake_time"].isoformat() in covered]
        protected += len(saved)
        value += sum((D(str(o["order_value"])) for o in saved), D("0"))
        extra += (r["spent"] or D("0")) - D(str(st.get("po_cost") or 0))
    return store.jsonable({
        "avg_time_to_recover_min": round(float(agg["avg_recover_min"] or 0)),
        "orders_protected": protected, "orders_value": value,
        "handled_without_owner": agg["without_owner"], "incidents_resolved": agg["resolved"], "incidents_total": agg["total"],
        "extra_cost": extra, "tracing": tracing.status(),
    })


def suppliers() -> list[dict]:
    """Supplier list with reliability from delivery_history."""
    rows = sql.query(f"SELECT supplier, email, status, preference_rank, delivery_area, website FROM {sql.T('suppliers')} ORDER BY status, preference_rank")
    return store.jsonable([{**r, **reliability(r["supplier"])} for r in rows])


def table(name: str) -> list[dict]:
    """Read-only operational tables for the Production / Inventory screens."""
    order = {"production_orders": "bake_time", "inventory": "ingredient", "incoming_deliveries": "expected_arrival",
             "approved_products": "ingredient, sku"}[name]
    return store.jsonable(sql.query(f"SELECT * FROM {sql.T(name)} ORDER BY {order}"))
