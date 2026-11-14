"""Help assistant: a tool-calling loop on the same LLM endpoint. Answers only from tool results; any action is a
confirmation card the owner must press (the button then calls the normal execution-service endpoints)."""
import json
import re

from backend import store
from backend.assistant import tools
from backend.config import settings
from backend.db.lakebase import q
from backend.llm.client import llm
from backend.tracing import tag_incident, traced

SYSTEM = """You are Crumbly's help assistant for a small bakery owner who may not be confident with technology.
Rules:
- Plain, warm, calm British English. Short sentences. No jargon: say "flour on its way", not "stock on order".
- At most three short paragraphs. Always end with one clear next step.
- Every number must come from a tool result. If you don't know, say so and offer to show the right screen (navigate_to).
- You can never place orders, change rules or send emails. To act, call prepare_feedback or prepare_approval, which only
  shows the owner a confirmation button. Read back what you understood before they confirm.
The owner is on screen: {page}. Incident in view: {incident}."""
MAX_STEPS = 5


@traced("assistant.chat", span_type="AGENT")
def chat(text: str, page: str = "home", incident_id: str | None = None, owner_id: str | None = None) -> dict:
    """One owner message -> reply text + any cards (links / confirmation buttons)."""
    owner = owner_id or settings.owner_id
    tag_incident(incident_id)
    history = q("SELECT role, content FROM (SELECT * FROM assistant_messages WHERE owner_id = %s ORDER BY id DESC LIMIT 8) h ORDER BY id", [owner])
    messages = [{"role": "system", "content": SYSTEM.format(page=page, incident=incident_id or "none")},
                *[{"role": h["role"], "content": h["content"]} for h in history], {"role": "user", "content": text}]
    ctx, cards = {"incident_id": incident_id, "page": page}, []
    reply = ""
    for _ in range(MAX_STEPS):
        out = llm.complete(messages, tools=tools.SPECS)
        if not out["tool_calls"]:
            reply = out["content"]
            break
        messages.append({"role": "assistant", "content": out["content"] or "", "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in out["tool_calls"]]})
        for c in out["tool_calls"]:
            result, card = tools.run_json(c["name"], c["arguments"], ctx)
            if card:
                cards.append(card)
            messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"], "content": result})
    reply = reply or "Sorry, I'm not sure about that one. I can show you the right screen instead."
    if not cards:
        cards.append({"type": "link", "label": "Show me the screen", "href": tools.SCREENS["home"]})
    q("INSERT INTO assistant_messages (owner_id, role, content) VALUES (%s, 'user', %s)", [owner, text])
    q("INSERT INTO assistant_messages (owner_id, role, content, card) VALUES (%s, 'assistant', %s, %s)", [owner, reply, cards])
    return {"reply": reply, "cards": cards}


# ---------------------------------------------------------------- deterministic router for LLM_PROVIDER=stub

INTENTS = [  # (pattern on the owner's words, tool, args)
    (r"too expensive|too dear|costs? too much", "prepare_feedback", {"reason": "too_expensive"}),
    (r"don'?t trust|do not trust", "prepare_feedback", {"reason": "dont_trust_supplier"}),
    (r"later is fine|can wait", "prepare_feedback", {"reason": "later_is_fine"}),
    (r"which option|should i pick|recommend|what happens if i do nothing|order it|approve", "get_pending_decision", {}),
    (r"\bwhy\b|picked|choose|chose", "get_quotes", {}),
    (r"alder|juniper|corner shop|customer|orders?\b", "get_affected_orders", {}),
    (r"limit|rule", "get_rules", {}),
    (r"how .*doing|metric|so far", "get_metrics", {}),
    (r"what does|what is|mean", "explain_term", None),
    (r".*", "get_incident_summary", {}),
]


def _call(name: str, args: dict) -> dict:
    return {"content": "", "tool_calls": [{"id": f"stub-{name}", "name": name, "arguments": json.dumps(args)}]}


def stub_router(messages: list[dict], _tools: list) -> dict:
    """Pick a tool from keywords, then phrase the answer from the tool's JSON (never inventing numbers)."""
    user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    results = {m["name"]: json.loads(m["content"]) for m in messages[messages.index(next(m for m in reversed(messages) if m["role"] == "user")):]
               if m["role"] == "tool"}
    if not results:
        for pat, name, args in INTENTS:
            if re.search(pat, user, re.I):
                if args is None:  # explain_term: the words after "mean"/"is"
                    m = re.search(r"(?:does|is)\s+['\"]?([\w\- ]+?)['\"]?\s*(?:mean)?\??$", user, re.I)
                    args = {"term": m.group(1) if m else user}
                return _call(name, args)
    if "get_pending_decision" in results and "prepare_approval" not in results and results["get_pending_decision"].get("options"):
        rec = next((o for o in results["get_pending_decision"]["options"] if o.get("recommended")), None)
        if rec:
            return _call("prepare_approval", {"option_id": rec["id"]})
    return {"content": _phrase(results, user), "tool_calls": []}


def _phrase(r: dict, user: str) -> str:
    """Turn tool results into short, plain sentences."""
    if "prepare_feedback" in r:
        reason = {"too_expensive": "too expensive", "dont_trust_supplier": "not someone you trust", "later_is_fine": "fine to arrive later"}
        why = next((v for k, v in reason.items() if re.search(k.split("_")[0], json.dumps(r)) or k in user), "not right")
        return (f"Just to check: you'd like me to tell Crumbly that {r['prepare_feedback'].get('supplier') or 'this offer'} is {why}?\n\n"
                "Press “Yes, that's right” and we'll look again straight away.")
    if "prepare_approval" in r and "get_pending_decision" in r:
        d = r["get_pending_decision"]
        rec = next(o for o in d["options"] if o.get("recommended"))
        extra = f" The new total would be £{float(rec['new_total']):.0f}." if rec.get("new_total") else ""
        return f"There's one thing waiting for you: {d['title']}\n\nI'd pick “{rec['label']}”. It passes all your rules.{extra}\n\nPress the button below if you're happy."
    if "get_pending_decision" in r:
        return "Nothing is waiting for you right now. Crumbly will ask if anything falls outside your rules.\n\nYou don't need to do anything."
    if "get_incident_summary" in r:
        s = r["get_incident_summary"]
        if s.get("error"):
            return "There's nothing to worry about at the moment. No deliveries have gone wrong.\n\nYou don't need to do anything."
        st, sh = s["stock"], s["shortage"] or {}
        slots = s.get("coverage_now") or []
        ok = sum(x["covered"] for x in slots)
        if s["status"] in ("resolved", "resolved_partial") or (slots and ok == len(slots)):
            return (f"Yes, tomorrow looks fine. {st['on_order_kg']:g} kg of {s['ingredient']} is on its way"
                    f"{', arriving ' + st['on_order_arrival'][11:16] if st.get('on_order_arrival') else ''}. "
                    f"With the {st['on_hand_kg']:g} kg you have, that's {st['available_kg']:g} kg for the {st['needed_kg']:g} kg you need.\n\n"
                    f"{ok} of {len(slots)} bakes are covered. You don't need to do anything.")
        return (f"Not yet. You need {sh.get('needed_kg', 0):g} kg of {s['ingredient']} tomorrow and have {sh.get('on_hand_kg', 0):g} kg, "
                f"so you're {sh.get('shortage_kg', 0):g} kg short. Right now {ok} of {len(slots)} bakes are covered.\n\n"
                f"Crumbly is already asking suppliers. Next step: I'll let you know if anything needs your OK.")
    if "get_affected_orders" in r:
        lines = [f"{o['customer']} ({o['bake_time']}): {'covered' if o['covered_now'] else 'not covered yet'}" for o in r["get_affected_orders"].get("orders", [])]
        return "Here's where each order stands:\n" + "\n".join(lines) + "\n\nNext step: nothing for now, we'll tell you if that changes."
    if "get_quotes" in r:
        qd = r["get_quotes"]
        if not qd["qualifying"]:
            return "No offer passes all your rules yet. " + "; ".join(f"{p['suppliers'][0]}: {', '.join(p['reasons']).lower()}" for p in qd["disqualified"]) + ".\n\nWe'll keep looking."
        best = qd["qualifying"][0]
        others = "; ".join(f"{p['suppliers'][0]} was {', '.join(p['reasons']).lower()}" for p in qd["disqualified"])
        return (f"We picked {' + '.join(best['suppliers'])} at £{float(best['total']):.0f}. We put reliability first, then cost — a cheap order that turns up late doesn't help."
                + (f"\n\nThe others: {others}." if others else "") + "\n\nNext step: nothing, unless you'd rather not use them.")
    if "get_rules" in r:
        x = r["get_rules"]
        return (f"Crumbly can spend up to £{float(x['spending_limit_per_incident']):.0f} on one problem without asking. "
                f"Automatic ordering is {'on' if x['auto_order_enabled'] else 'off'}.\n\nTo change it, open the Rules page and press “Edit limit”.")
    if "get_metrics" in r:
        m = r["get_metrics"]
        return (f"On average Crumbly sorts a problem in {m['avg_time_to_recover_min']} minutes. "
                f"It has protected {m['orders_protected']} customer orders worth £{float(m['orders_value']):.0f}.\n\nNext step: nothing needed.")
    if "explain_term" in r:
        e = r["explain_term"]
        return (e["meaning"] + "\n\nAnything else you'd like explained?") if e["meaning"] else "I'm not sure about that word. I can show you the screen it's on."
    return "Sorry, I'm not sure about that one. I can show you the right screen instead."
