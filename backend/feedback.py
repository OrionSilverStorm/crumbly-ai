"""Owner feedback ("Not this one"): store it, log it to MLflow, re-plan immediately, and maybe suggest a rule.
The model never changes hard rules; a suggestion only takes effect when the owner accepts it."""
import math
from decimal import Decimal as D

from backend import store, tracing
from backend.agents import recovery
from backend.config import settings
from backend.db.lakebase import one, q

LABELS = {"too_expensive": "Too expensive", "dont_trust_supplier": "Don't trust this supplier",
          "later_is_fine": "Later is fine for this bake", "other": "Other"}
SUGGEST_AFTER = 2  # same reason this many times -> suggest a rule


def submit(incident_id: str, reason: str, note: str | None = None, quote_id: int | None = None, supplier: str | None = None) -> dict:
    """Record a rejection and re-plan. Returns what happened."""
    inc = store.incident(incident_id)
    quote = one("SELECT * FROM quotes WHERE quote_id = %s", [quote_id]) if quote_id else None
    supplier = supplier or (quote or {}).get("supplier")
    amount = (quote or {}).get("total") or (inc["state"].get("proposal") or {}).get("total")
    fb = one("INSERT INTO owner_feedback (incident_id, quote_id, supplier, ingredient, amount, reason, note) "
             "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *", [incident_id, quote_id, supplier, inc["ingredient"], amount, reason, note])
    decided = one("SELECT evidence FROM incident_events WHERE incident_id = %s AND type = 'offer_selected' ORDER BY id DESC LIMIT 1", [incident_id])
    logged = tracing.log_feedback((decided or {}).get("evidence", {}).get("trace_id"), reason, note, settings.owner_id)
    store.log_event(incident_id, "decide", "owner", "owner_feedback", f"You said “{LABELS[reason]}” about {supplier}",
                    {"feedback_id": fb["id"], "reason": reason, "note": note, "mlflow_feedback": logged})
    # Any open order proposal is withdrawn while we re-plan.
    q("UPDATE pending_decisions SET status = 'superseded' WHERE incident_id = %s AND kind = 'approve_order' AND status = 'open'", [incident_id])
    store.update_incident(incident_id, status="open", state={"last_decided": None})
    if reason == "later_is_fine":
        return {"feedback": fb, "next": _ask_relax(inc, supplier)}
    who = "quote_id = %s" if quote_id and reason in ("too_expensive", "other") else "supplier = %s"
    q(f"UPDATE quotes SET excluded_reason = %s WHERE incident_id = %s AND {who} AND NOT superseded",
      [LABELS[reason], incident_id, quote_id if "quote_id" in who else supplier])
    if reason == "dont_trust_supplier":
        q("UPDATE supplier_threads SET status = 'excluded', note = 'You said you don''t trust them' WHERE incident_id = %s AND supplier = %s",
          [incident_id, supplier])
        old = one("SELECT value FROM preferences WHERE key = %s", [f"avoid:{supplier}"])
        penalty = int((old or {}).get("value", {}).get("penalty", 0)) + 1
        q("INSERT INTO preferences (key, value, source, confirmed) VALUES (%s, %s, 'owner', true) "
          "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", [f"avoid:{supplier}", {"supplier": supplier, "penalty": penalty}])
    suggestion = maybe_suggest_rule(inc["ingredient"]) if reason == "too_expensive" else None
    return {"feedback": fb, "next": recovery.decide(incident_id), "suggestion": suggestion}


def _ask_relax(inc: dict, supplier: str | None) -> str:
    """'Later is fine' only relaxes one specific bake, and only after the owner confirms which."""
    slots = [s for s in inc["state"].get("baseline_coverage", []) if not s["covered"]]
    orders = inc["state"].get("orders", [])
    options = [{"id": f"relax:{s['bake_time']}", "label": f"Yes, the {s['bake_time'][11:16]} bake can wait",
                "customers": [o["customer"] for o in orders if o["bake_time"] == s["bake_time"]], "bake_time": s["bake_time"]}
               for s in slots] + [{"id": "keep", "label": "No, keep every bake on time", "recommended": True}]
    recovery.open_decision(inc["id"], "relax_slot", "Which bake can wait?", options, {"supplier": supplier})
    return "asked_owner"


def maybe_suggest_rule(ingredient: str) -> dict | None:
    """Same reason recurring (e.g. two 'too expensive' rejections over £150 for flour) -> suggest, never apply."""
    key = f"ask_over:{ingredient}"
    if one("SELECT 1 FROM preferences WHERE key = %s", [key]):
        return None
    rows = q("SELECT amount FROM owner_feedback WHERE reason = 'too_expensive' AND ingredient = %s AND amount IS NOT NULL", [ingredient])
    if len(rows) < SUGGEST_AFTER:
        return None
    cap = int(math.floor(min(D(str(r["amount"])) for r in rows) / 50) * 50)  # e.g. £158 and £165 -> £150
    value = {"ingredient": ingredient, "amount": cap, "text": f"Ask me before ordering {ingredient} over £{cap}"}
    q("INSERT INTO preferences (key, value, source, confirmed) VALUES (%s, %s, 'suggested', false)", [key, value])
    d = recovery.open_decision(None, "rule_suggestion", value["text"] + "?", [
        {"id": "accept", "label": "Yes, make it a rule", "recommended": False},
        {"id": "decline", "label": "No thanks", "recommended": False}], {"key": key, "value": value, "times": len(rows)})
    return {"decision_id": d["id"], **value}
