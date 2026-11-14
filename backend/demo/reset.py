"""Demo reset: recreate Delta seed rows, truncate Lakebase incident tables, clear both mailboxes, pick a scenario.

    python -m backend.demo.reset [happy|short_confirm|new_supplier_wins|owner_rejects]
"""
import sys
from datetime import timedelta
from decimal import Decimal as D

from backend import store
from backend.config import settings
from backend.db import lakebase
from backend.db.lakebase import q
from backend.dbx import sql
from backend.dbx.seed.seed import seed_warehouse
from backend.demo import clock
from backend.email.transport import make

SCENARIOS = ("happy", "short_confirm", "new_supplier_wins", "owner_rejects")
LIVE_TABLES = ("incidents", "incident_events", "email_messages", "supplier_threads", "quotes", "purchase_orders",
               "owner_feedback", "preferences", "pending_decisions", "research", "assistant_messages")

# Earlier, already-resolved incidents for the home page and metrics: (id, ingredient, what happened, days ago,
# minutes to recover, owner involved, orders protected, their value, replacement total, original PO cost).
HISTORY = [
    ("INC-0039", "unsalted butter", "Short delivery · 18 of 24 kg arrived", 11, 34, False, 2, D("240.00"), D("74.00"), D("68.00")),
    ("INC-0035", "fresh yeast", "Delivery delayed by a day", 24, 52, False, 4, D("410.00"), D("12.60"), D("12.60")),
    ("INC-0031", "caster sugar", "Wrong pack size delivered", 36, 95, True, 1, D("95.00"), D("31.00"), D("28.00")),
]


def _seed_history() -> None:
    """Resolved incidents (with opened/resolved events) so metrics have real rows to compute over."""
    for iid, ing, what, days, mins, owner, n, value, total, cost in HISTORY:
        opened = clock.now().replace(hour=5, minute=10) - timedelta(days=days)
        resolved = opened + timedelta(minutes=mins)
        q("INSERT INTO incidents (id, ingredient, status, stage, opened_at, resolved_at, summary, production_date, state) "
          "VALUES (%s,%s,'resolved','update',%s,%s,%s,%s,%s)",
          [iid, ing, opened, resolved, what, opened.date(), store.jsonable({
              "history": True, "orders_protected": n, "orders_value": value, "replacement_total": total, "po_cost": cost})])
        q("INSERT INTO incident_events (incident_id, ts, stage, actor, type, summary) VALUES (%s,%s,'detect','production_agent','incident_opened',%s)",
          [iid, opened, what])
        q("INSERT INTO incident_events (incident_id, ts, stage, actor, type, summary) VALUES (%s,%s,'update',%s,'resolved',%s)",
          [iid, resolved, "owner" if owner else "recovery_agent", "Resolved by you" if owner else "Resolved"])


def reset(scenario: str | None = None) -> str:
    """Bring everything back to the start of the demo. Safe to run repeatedly."""
    scenario = scenario or settings.scenario
    assert scenario in SCENARIOS, f"unknown scenario {scenario}"
    lakebase.migrate()
    sql.setup()
    q(f"TRUNCATE {', '.join(LIVE_TABLES)} RESTART IDENTITY")
    q("ALTER SEQUENCE incident_seq RESTART WITH 42")
    q("ALTER SEQUENCE po_seq RESTART WITH 87")
    q("DELETE FROM rules")
    q("INSERT INTO rules (spending_limit_per_incident, auto_order_enabled, arrival_buffer_min, delivery_window_start, "
      "delivery_window_end, chase_after_min, drop_after_min, new_supplier_requires_approval, postcode_area, production_start) "
      "VALUES (250, %s, 60, '04:00', '05:00', 30, 60, true, 'SE1', '06:00')", [scenario != "owner_rejects"])
    q("INSERT INTO demo_state (key, value) VALUES ('scenario', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", [scenario])
    # One earlier "too expensive" flour rejection, so a second one triggers the rule suggestion.
    q("INSERT INTO owner_feedback (incident_id, supplier, ingredient, amount, reason, note, created_at) "
      "VALUES (NULL, 'Borough Mill', 'strong white flour', 158, 'too_expensive', 'Earlier this month', %s)", [clock.now() - timedelta(days=12)])
    seed_warehouse()
    _seed_history()
    for role in ("bakery", "suppliers"):
        try:
            make(role).clear()
        except Exception as e:  # mailbox credentials missing locally shouldn't block a reset
            print(f"warning: could not clear {role} mailbox: {e}")
    return scenario


if __name__ == "__main__":
    print("Reset to scenario:", reset(sys.argv[1] if len(sys.argv) > 1 else None))
