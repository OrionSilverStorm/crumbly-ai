"""Linkup privacy rule, help-assistant guardrails, and crash-resume."""
from backend.agents import orchestrator, sourcing
from backend.assistant import chat
from backend.db.lakebase import one, q
from backend.dbx.seed.seed import ORDERS, RECIPES
from backend.research import linkup
from backend.tests.conftest import incident, trigger


def test_linkup_queries_never_contain_customer_or_recipe_data(scenario, monkeypatch):
    drive = scenario("happy")
    sent = []
    real = linkup.Linkup._call
    monkeypatch.setattr(linkup.Linkup, "_call", lambda self, op, **kw: sent.append(kw.get("query") or kw.get("url")) or real(self, op, **kw))
    trigger()
    assert drive(lambda: (i := incident()) is not None and i["state"].get("research_done"), timeout=30)
    assert sent, "research should have queried Linkup"
    forbidden = [o[0] for o in ORDERS] + [o[1] for o in ORDERS] + [o[2] for o in ORDERS] + [r[0] for r in RECIPES] + [o[6] for o in ORDERS]
    for query in sent:
        for word in forbidden:
            assert word.lower() not in query.lower(), f"{word!r} leaked into Linkup query {query!r}"
    assert linkup.build_query("strong white flour", 25, "SE1") == "wholesale strong white flour 25 kg bags next-day delivery SE1 London"


def test_assistant_answers_from_tools(scenario):
    drive = scenario("happy")
    trigger()
    assert drive(lambda: incident() is not None and incident()["status"] == "resolved", timeout=150)
    r = chat.chat("Is tomorrow OK?", incident_id=incident()["id"])
    assert "Yes" in r["reply"] and "175 kg" in r["reply"] and "05:00" in r["reply"] and "3 of 3" in r["reply"]


def test_assistant_too_expensive_prepares_card_and_never_orders(scenario):
    drive = scenario("owner_rejects")
    trigger()
    assert drive(lambda: one("SELECT 1 AS x FROM pending_decisions WHERE kind = 'approve_order' AND status = 'open'") is not None, timeout=150)
    iid = incident()["id"]
    r = chat.chat("That's too expensive", page="decide", incident_id=iid)
    card = next(c for c in r["cards"] if c["type"] == "confirm_feedback")
    assert card["reason"] == "too_expensive" and card["supplier"] == "Borough Mill"
    assert one("SELECT COUNT(*) AS n FROM owner_feedback WHERE incident_id = %s", [iid])["n"] == 0  # nothing until the click
    r = chat.chat("Which option should I pick? Order it", page="decide", incident_id=iid)
    assert any(c["type"] == "confirm_decision" for c in r["cards"])
    assert one("SELECT COUNT(*) AS n FROM purchase_orders")["n"] == 0  # the assistant cannot send a PO by itself
    assert one("SELECT COUNT(*) AS n FROM email_messages WHERE kind = 'po'")["n"] == 0


def test_crash_resume_continues_instead_of_restarting(scenario):
    drive = scenario("happy")
    trigger()
    assert drive(lambda: one("SELECT 1 AS x FROM quotes") is not None, timeout=60)
    iid = incident()["id"]
    enquiries = one("SELECT COUNT(*) AS n FROM email_messages WHERE kind = 'enquiry'")["n"]
    orchestrator.resume()  # what startup does after a crash
    assert one("SELECT COUNT(*) AS n FROM incidents WHERE NOT (state ? 'history')")["n"] == 1
    assert one("SELECT COUNT(*) AS n FROM email_messages WHERE kind = 'enquiry'")["n"] == enquiries  # no re-sends
    assert drive(lambda: incident()["status"] == "resolved", timeout=150)
    assert incident()["id"] == iid
