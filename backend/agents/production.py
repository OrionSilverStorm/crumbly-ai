"""Production agent: match a supplier email to an outstanding PO (Detect) and work out the damage (Understand)."""
import re
from datetime import date

from backend.agents import tools
from backend.agents.tools import AgentResult
from backend.dbx import sql
from backend.demo import clock
from backend.email.transport import Mail
from backend.execution.quotes import packs_needed
from backend.llm.client import llm
from backend.llm.schemas import TriggerExtract
from backend.tracing import traced


def _po_ref(text: str | None) -> str | None:
    """Normalise 'PO–0079' / 'po 0079' / 'PO-0079' to 'PO-0079'."""
    m = re.search(r"PO\W*(\d{3,})", text or "", re.I)
    return f"PO-{m.group(1)}" if m else None


@traced("production_agent.detect", span_type="AGENT")
def detect(mail: Mail) -> AgentResult | None:
    """LLM reads the email; code confirms the match against incoming_deliveries. None if it isn't a supply problem."""
    ext = llm.extract(TriggerExtract, f"Subject: {mail.subject}\n\n{mail.body}",
                      "This may be a supplier telling a bakery about a problem with an order.")
    if not ext or not ext.is_supply_problem:
        return None
    po = _po_ref(ext.po_reference) or _po_ref(mail.subject)
    rows = sql.query(f"SELECT * FROM {sql.T('incoming_deliveries')} WHERE po_id = :po AND status = 'scheduled'", {"po": po}) if po else []
    if not rows:
        return AgentResult(facts={"matched": False, "po_reference": po}, uncertainties=[f"No scheduled delivery matches {po or 'this email'}"],
                           evidence_refs=[f"email:{mail.message_id}"])
    d = rows[0]
    doubts = []
    if ext.supplier_name and ext.supplier_name.lower().split()[0] not in d["supplier"].lower():
        doubts.append(f"Email signed '{ext.supplier_name}' but {po} is with {d['supplier']}")
    if ext.ingredient and ext.ingredient.lower() not in d["ingredient"].lower():
        doubts.append(f"Email mentions '{ext.ingredient}' but {po} is {d['ingredient']}")
    # A cancellation loses the whole delivery; a short delivery loses what the email says (never more than ordered).
    lost = d["quantity_kg"] if ext.kind != "shortened" or not ext.quantity_kg_lost else min(ext.quantity_kg_lost, d["quantity_kg"])
    return AgentResult(
        facts={"matched": True, "po_id": po, "supplier": d["supplier"], "ingredient": d["ingredient"], "kind": ext.kind or "cancelled",
               "kg_lost": lost, "kg_ordered": d["quantity_kg"], "expected_arrival": clock.local(d["expected_arrival"]),
               "po_cost": d["total_cost"]},
        uncertainties=doubts, evidence_refs=[f"email:{mail.message_id}", f"incoming_deliveries:{po}"])


@traced("production_agent.understand", span_type="AGENT")
def understand(ingredient: str, day: date, buffer_min: int) -> AgentResult:
    """Shortage, affected orders and time-phased coverage, all from UC functions; packs rounded up by code."""
    s = tools.calculate_shortage(ingredient, day)
    orders = tools.affected_orders(ingredient, day)
    slots = tools.coverage(ingredient, day, buffer_min)
    alts = tools.approved_alternatives(ingredient)
    pack = alts[0]["pack_size_kg"] if alts else 25.0
    uncovered = {sl["bake_time"] for sl in slots if not sl["covered"]}
    at_risk = [o for o in orders if o["bake_time"] in uncovered]
    return AgentResult(
        facts={**s, "pack_size_kg": pack, "packs": packs_needed(s["shortage_kg"], pack),
               "orders": orders, "at_risk": at_risk, "coverage": slots,
               "production_start": orders[0]["bake_time"] if orders else None, "refreshed_at": clock.now()},
        uncertainties=[] if alts else [f"No approved alternatives on file for {ingredient}"],
        evidence_refs=["uc:calculate_shortage", "uc:get_affected_orders", "uc:coverage_by_slot", "uc:get_approved_alternatives"])
