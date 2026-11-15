"""Help-assistant tools. All READ-ONLY; the two `prepare_*` tools only build a confirmation card for the UI.
Nothing here can place orders, change rules or send emails."""
import json

from backend import store, views
from backend.assistant.glossary import explain
from backend.db.lakebase import one, q

SCREENS = {"home": "#/", "understand": "#/incident/{id}/understand", "investigate": "#/incident/{id}/investigate",
           "coordinate": "#/incident/{id}/coordinate", "decide": "#/incident/{id}/decide", "execute": "#/incident/{id}/execute",
           "decision": "#/incident/{id}/needs-you", "summary": "#/incident/{id}/summary", "log": "#/incident/{id}/log",
           "rules": "#/rules", "suppliers": "#/suppliers", "inventory": "#/inventory", "production": "#/production"}


def _fn(name: str, desc: str, props: dict | None = None, required: list | None = None) -> dict:
    """OpenAI-style function tool definition."""
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


SPECS = [
    _fn("get_incident_summary", "Current incident: what happened, shortage, stage, coverage per bake and what's on order."),
    _fn("get_affected_orders", "Customer orders affected, with bake times and whether each is covered now."),
    _fn("get_quotes", "Supplier offers: which qualify (ranked) and which don't, with reasons."),
    _fn("get_pending_decision", "Any decision waiting for the owner, with the options and which one is recommended."),
    _fn("get_rules", "The owner's purchasing rules (limit, auto-ordering, delivery window, timers)."),
    _fn("get_metrics", "How Crumbly has been doing (time to recover, orders protected, cost)."),
    _fn("get_capabilities", "What the help assistant can and cannot do, including its safety boundary."),
    _fn("explain_term", "Explain a word used in the app in plain English.", {"term": {"type": "string"}}, ["term"]),
    _fn("navigate_to", "Offer a link to a screen.", {"screen": {"type": "string", "enum": list(SCREENS)}}, ["screen"]),
    _fn("prepare_feedback", "Prepare (NOT send) a 'Not this one' card the owner must confirm.",
        {"reason": {"type": "string", "enum": ["too_expensive", "dont_trust_supplier", "later_is_fine", "other"]},
         "supplier": {"type": "string"}, "note": {"type": "string"}}, ["reason"]),
    _fn("prepare_approval", "Prepare (NOT carry out) an approval card for an open decision option the owner must confirm.",
        {"option_id": {"type": "string"}}, ["option_id"]),
]


def _incident(incident_id: str | None) -> dict | None:
    """The incident in context, else the most recent open one, else the most recent."""
    if incident_id:
        return store.incident(incident_id)
    return one("SELECT * FROM incidents WHERE NOT (state ? 'history') ORDER BY (status IN ('resolved','resolved_partial')), opened_at DESC LIMIT 1")


def run(name: str, args: dict, ctx: dict) -> tuple[dict, dict | None]:
    """Execute a tool. Returns (result for the model, optional UI card)."""
    inc = _incident(ctx.get("incident_id"))
    iid = inc["id"] if inc else None
    if name == "explain_term":
        return explain(args.get("term", "")), None
    if name == "get_rules":
        return views.rules_summary(), None
    if name == "get_metrics":
        return views.metrics(), None
    if name == "get_capabilities":
        return {
            "can": ["explain the live incident", "compare offers", "prepare a decision for the owner"],
            "cannot": ["place an order from chat", "send an email from chat", "change a purchasing rule from chat"],
            "safety": "Any action needs an explicit owner click on a confirmation card.",
        }, None
    if name == "navigate_to":
        screen = args.get("screen", "home")
        return {"ok": True}, {"type": "link", "label": "Show me the screen", "href": SCREENS.get(screen, "#/").format(id=iid)}
    if not inc:
        return {"error": "There is no incident right now."}, None
    st = inc["state"]
    if name == "get_incident_summary":
        return store.jsonable({"incident": iid, "ingredient": inc["ingredient"], "status": inc["status"], "stage": inc["stage"],
                               "shortage": st.get("shortage"), "packs_needed": st.get("packs"), "coverage_now": st.get("coverage_now"),
                               "stock": views.stock(inc), "original_supplier": st.get("original_supplier")}), None
    if name == "get_affected_orders":
        covered = {s["bake_time"]: s["covered"] for s in st.get("coverage_now", [])}
        return {"orders": [{"customer": o["customer"], "what": o["description"], "kg": o["kg_required"], "bake_time": o["bake_time"][11:16],
                            "covered_now": covered.get(o["bake_time"])} for o in st.get("orders", [])]}, None
    if name == "get_quotes":
        r = st.get("ranking") or {}
        brief = lambda p: {"suppliers": p["suppliers"], "total": p["total"], "reasons": p["reasons"], "reliability": p.get("reliability")}  # noqa: E731
        return {"qualifying": [brief(p) for p in r.get("qualifying", [])], "disqualified": [brief(p) for p in r.get("disqualified", [])],
                "rule": "Reliability first, then cost."}, None
    if name == "get_pending_decision":
        d = one("SELECT * FROM pending_decisions WHERE status = 'open' AND (incident_id = %s OR incident_id IS NULL) ORDER BY id DESC LIMIT 1", [iid])
        return (store.jsonable({"decision_id": d["id"], "kind": d["kind"], "title": d["title"],
                                "options": [{k: o.get(k) for k in ("id", "label", "recommended", "new_total", "shortfall_kg")} for o in d["options"]]})
                if d else {"decision": None}), None
    if name == "prepare_feedback":
        proposal = st.get("proposal") or {}
        supplier = args.get("supplier") or (proposal.get("suppliers") or [None])[0]
        quote_id = (proposal.get("lines") or [{}])[0].get("quote_id") if supplier in proposal.get("suppliers", []) else None
        card = {"type": "confirm_feedback", "incident_id": iid, "reason": args["reason"], "supplier": supplier, "quote_id": quote_id,
                "note": args.get("note"), "yes": "Yes, that's right", "no": "No"}
        return {"prepared": True, "needs_owner_click": True, "supplier": supplier}, card
    if name == "prepare_approval":
        d = one("SELECT * FROM pending_decisions WHERE status = 'open' AND incident_id = %s ORDER BY id DESC LIMIT 1", [iid])
        opt = next((o for o in (d or {}).get("options", []) if o["id"] == args.get("option_id")), None)
        if not opt:
            return {"error": "No open decision with that option."}, None
        return {"prepared": True, "needs_owner_click": True}, {
            "type": "confirm_decision", "decision_id": d["id"], "option_id": opt["id"], "label": opt["label"],
            "yes": "Yes, order it" if d["kind"] == "approve_order" or opt["id"] == "top_up" else "Yes, do that", "no": "No"}
    return {"error": f"unknown tool {name}"}, None


def run_json(name: str, raw_args: str, ctx: dict) -> tuple[str, dict | None]:
    """Tool call with JSON-string args (as returned by the model)."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        args = {}
    result, card = run(name, args, ctx)
    return json.dumps(result, default=str), card
