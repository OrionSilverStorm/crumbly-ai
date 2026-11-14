"""The agents' data tools: each wraps exactly one UC function call in an MLflow TOOL span. No raw SQL here."""
from datetime import date, datetime

from pydantic import BaseModel, Field

from backend.dbx.sql import fn
from backend.demo import clock
from backend.tracing import traced

# Stand-in for "no extra delivery" (avoids untyped NULL parameters on the warehouse).
NEVER = datetime(2100, 1, 1, tzinfo=clock.TZ)


class AgentResult(BaseModel):
    """What every agent step returns: structured facts, explicit uncertainties and evidence references."""

    facts: dict = Field(default_factory=dict)
    uncertainties: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


@traced("uc.calculate_shortage", span_type="TOOL")
def calculate_shortage(ingredient: str, day: date) -> dict:
    """needed / on hand / reserved / incoming / shortage kg."""
    return fn("calculate_shortage", ingredient=ingredient, production_date=day)[0]


@traced("uc.get_affected_orders", span_type="TOOL")
def affected_orders(ingredient: str, day: date) -> list[dict]:
    """Orders using the ingredient that day, in bake order."""
    return [{**r, "bake_time": clock.local(r["bake_time"])} for r in fn("get_affected_orders", ingredient=ingredient, production_date=day)]


@traced("uc.get_approved_alternatives", span_type="TOOL")
def approved_alternatives(ingredient: str) -> list[dict]:
    """Approved SKUs from approved suppliers, in preference order."""
    return fn("get_approved_alternatives", ingredient=ingredient)


@traced("uc.coverage_by_slot", span_type="TOOL")
def coverage(ingredient: str, day: date, buffer_min: int, extra_kg: float = 0.0, extra_arrival: datetime | None = None) -> list[dict]:
    """Time-phased coverage per bake slot, optionally with a candidate delivery."""
    rows = fn("coverage_by_slot", ingredient=ingredient, production_date=day, extra_kg=float(extra_kg),
              extra_arrival=extra_arrival or NEVER, buffer_min=int(buffer_min))
    return [{**r, "bake_time": clock.local(r["bake_time"])} for r in rows]


@traced("uc.supplier_reliability", span_type="TOOL")
def reliability(supplier: str) -> dict:
    """On-time rate, quantity accuracy and delivery count from delivery_history (None rates if no history)."""
    rows = fn("supplier_reliability", supplier=supplier)
    r = rows[0] if rows else {}
    return {"on_time_rate": r.get("on_time_rate"), "quantity_accuracy": r.get("quantity_accuracy"), "deliveries": int(r.get("deliveries") or 0)}
