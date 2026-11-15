"""Regressions found while rehearsing the demo video: each one would have been visible on camera."""
from fastapi.testclient import TestClient

from backend import views
from backend.assistant import chat
from backend.assistant.glossary import explain
from backend.execution import service as ex
from backend.main import app
from backend.tests.conftest import incident, trigger


def _resolved():
    inc = incident()
    return inc is not None and inc["status"] in ("resolved", "resolved_partial")


def test_marking_delivery_received_moves_flour_from_on_order_to_on_hand(scenario):
    """'Mark as received' must not make 175 kg vanish (it used to show 'Short 135 kg' in red after receipt)."""
    drive = scenario("happy")
    trigger()
    assert drive(_resolved, timeout=150)
    inc = incident()
    before = views.stock(inc)
    assert (before["on_hand_kg"], before["on_order_kg"], before["available_kg"]) == (40, 175, 215)

    assert ex.mark_received("PO-0087")["ok"]
    after = views.stock(incident())
    assert (after["on_hand_kg"], after["on_order_kg"], after["available_kg"], after["spare_kg"]) == (215, 0, 215, 15)
    assert not ex.mark_received("PO-0087")["ok"]  # checking in twice never double-counts stock
    assert views.stock(incident())["on_hand_kg"] == 215


def test_assistant_handles_the_words_used_in_the_demo(scenario):
    drive = scenario("happy")
    trigger()
    assert drive(_resolved, timeout=150)
    iid = incident()["id"]

    for question in ("What's happening?", "What is happening?", "What is the status?"):
        reply = chat.chat(question, incident_id=iid)["reply"]
        assert "160 kg short" in reply or "tomorrow looks fine" in reply, (question, reply)

    assert "extra order" in chat.chat("What is a top-up?", incident_id=iid)["reply"]
    assert "never quietly accepts" in chat.chat("What does confirmation mismatch mean?", incident_id=iid)["reply"]
    assert "Borough Mill at £165. We put" in chat.chat("Why did you pick this supplier?", incident_id=iid)["reply"]


def test_glossary_prefers_the_specific_term():
    assert explain("top up")["term"] == "top-up"
    assert explain("confirmation mismatch")["term"] == "mismatch"
    assert explain("a split order")["term"] == "split order"
    assert explain("croissants")["meaning"] is None


def test_supplier_names_ending_in_a_full_stop_are_not_doubled():
    """'Thames Grain Co.' used to read 'Thames Grain Co..' in the assistant's answer."""
    quotes = {"qualifying": [{"suppliers": ["Thames Grain Co."], "total": "164"}], "disqualified": []}
    assert "Co.." not in chat._phrase({"get_quotes": quotes}, "How much will it cost?")
    assert "Co.." not in chat._phrase({"get_quotes": quotes}, "Why this one?")


def test_unknown_incident_export_is_404_not_500():
    client = TestClient(app)  # no `with`: the lifespan (poller, timers, bot) is not started
    assert client.get("/api/incidents/INC-9999/export").status_code == 404
    assert client.get("/api/incidents/INC-9999").status_code == 404
