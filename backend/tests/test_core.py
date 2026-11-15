"""UC function semantics, pack rounding, execution-service checks and confirmation matching."""
from datetime import timedelta
from decimal import Decimal as D

from backend.agents import tools
from backend.config import ROOT, load
from backend.demo import clock
from backend.demo.reset import reset
from backend.execution import service as ex
from backend.execution.quotes import normalise, packs_needed
from backend.research.linkup import FoundSupplier, Linkup

FLOUR = "strong white flour"


def test_blank_optional_environment_values_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("PGDATA_DIR", "")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "")
    configured = load()
    assert configured.pgdata == str(ROOT / ".pgdata")
    assert configured.mlflow_tracking_uri == f"sqlite:///{(ROOT / '.mlflow' / 'mlflow.db').as_posix()}"


def _cancel_po():
    """Simulate the cancellation's effect on incoming stock."""
    from backend.dbx import sql

    sql.query(f"UPDATE {sql.T('incoming_deliveries')} SET status = 'cancelled' WHERE po_id = 'PO-0079'")


def test_calculate_shortage_is_160_after_cancellation():
    reset("happy")
    assert tools.calculate_shortage(FLOUR, clock.tomorrow())["shortage_kg"] == 0  # PO-0079 still expected
    _cancel_po()
    s = tools.calculate_shortage(FLOUR, clock.tomorrow())
    assert (s["needed_kg"], s["on_hand_kg"], s["shortage_kg"]) == (200, 40, 160)


def test_coverage_by_slot_respects_arrival_buffer():
    reset("happy")
    _cancel_po()
    day = clock.tomorrow()
    early = tools.coverage(FLOUR, day, 60, 175, clock.at(day, "05:00"))
    late = tools.coverage(FLOUR, day, 60, 175, clock.at(day, "07:00"))
    assert [s["covered"] for s in early] == [True, True, True]
    assert [s["covered"] for s in late] == [False, False, False]  # 07:00 is inside the 60-min buffer for every slot
    assert [clock.hhmm(s["bake_time"]) for s in early] == ["06:00", "06:30", "07:00"]


def test_affected_orders_and_reliability_come_from_sql():
    reset("happy")
    orders = tools.affected_orders(FLOUR, clock.tomorrow())
    assert [(o["customer"], o["kg_required"]) for o in orders] == [("Café Juniper", 48), ("The Corner Shop", 72), ("Alder Hotel", 80)]
    bm, hs = tools.reliability("Borough Mill"), tools.reliability("Harrow & Sons")
    assert (round(bm["on_time_rate"] * 100), round(bm["quantity_accuracy"] * 100), bm["deliveries"]) == (96, 100, 42)
    assert (round(hs["on_time_rate"] * 100), round(hs["quantity_accuracy"] * 100), hs["deliveries"]) == (91, 98, 23)


def test_pack_rounding():
    assert packs_needed(160, 25) == 7
    assert packs_needed(150, 25) == 6
    assert packs_needed(151, 25) == 7
    assert packs_needed(0, 25) == 0


def test_linkup_verification_fetches_discovered_supplier_page(monkeypatch):
    supplier = FoundSupplier(supplier_name="Example Mill", website="https://mill.example/products/flour")
    calls = []

    def fake_call(self, op, **kw):
        calls.append((op, kw))
        url = kw["url"] if op == "fetch" else "https://independent.example"
        return {"data": {"sells_pack_size": True}, "sources": [{"url": url}]}

    monkeypatch.setattr(Linkup, "_call", fake_call)
    claims = Linkup().verify(supplier, "flour", 25, "E1")

    assert calls[0][1]["url"] == supplier.website
    assert next(c for c in claims if c["field"] == "sells_pack_size")["status"] == "confirmed"


def test_missing_fields_detected_by_code():
    day = clock.tomorrow()
    n = normalise({"packs": 7, "goods_price": 147, "arrival_text": "tomorrow"}, day, D("0"), 25)
    assert n["missing_fields"] == ["delivery_charge", "arrival_at"]
    n = normalise({"packs": 7, "goods_price": 147, "delivery_charge": 18, "total": 165, "arrival_time": "05:00"}, day, D("0"), 25)
    assert n["missing_fields"] == [] and n["total"] == D("165.00") and n["unit_price"] == D("21.00")
    n = normalise({"packs": 7, "goods_price": 147, "delivery_charge": 18, "total": 170, "arrival_time": "05:00"}, day, D("0"), 25)
    assert n["missing_fields"] == ["total"]  # stated total doesn't add up -> ask, never guess


def _ctx(shortage=160, committed=D("0")):
    """A check context for the seeded incident without running the agents."""
    day = clock.tomorrow()
    slots = [{"bake_time": clock.at(day, t).isoformat(), "covered": False} for t in ("06:00", "06:30", "07:00")]
    inc = {"id": "INC-TEST", "ingredient": FLOUR, "production_date": day, "shortage_kg": shortage,
           "deadline": clock.at(day, "06:00"), "state": {"baseline_coverage": slots}}
    return ex.context(inc, committed=committed)


def _line(supplier="Borough Mill", sku="BM-SWF-25", packs=7, goods="147", delivery="18", arrival="05:00", approved=True):
    return ex.Line(1, supplier, "x@y", None, sku, packs, D("25"), D(goods) / packs, D(goods), D(delivery), D("0"),
                   clock.at(clock.tomorrow(), arrival), approved, True, {"on_time_rate": 0.96})


def _status(plan):
    return {c["id"]: c["status"] for c in plan.checks}


def test_execution_checks_pass_for_borough():
    reset("happy")
    p = ex.validate(ex.Plan([_line()]), _ctx())
    assert all(s == "pass" for s in _status(p).values())
    assert ex.auto_allowed(p, _ctx())[0]
    assert next(c for c in p.checks if c["id"] == "in_time")["detail"] == "05:00, an hour before 06:00"


def test_execution_checks_fail_reasons():
    reset("happy")
    assert _status(ex.validate(ex.Plan([_line(arrival="09:00")]), _ctx()))["in_time"] == "fail"
    assert _status(ex.validate(ex.Plan([_line(arrival="05:30")]), _ctx()))["in_time"] == "fail"  # outside 04:00-05:00 window
    assert _status(ex.validate(ex.Plan([_line(packs=6, goods="126")]), _ctx()))["enough"] == "fail"
    assert _status(ex.validate(ex.Plan([_line(goods="240")]), _ctx()))["within_limit"] == "fail"
    assert _status(ex.validate(ex.Plan([_line()]), _ctx(committed=D("100"))))["within_limit"] == "fail"  # limit is per incident
    new = ex.validate(ex.Plan([_line("Thames Grain Co.", None, approved=False)]), _ctx())
    assert _status(new)["approved_supplier"] == "approval" and new.qualifies and not ex.auto_allowed(new, _ctx())[0]


def test_confirmation_matching_never_accepts_a_mismatch():
    po = {"po_id": "PO-0087", "lines": [{"product": FLOUR, "pack_size_kg": "25", "packs": 7, "unit_price": "21.00",
                                          "delivery": "18.00", "total": "165.00", "arrival": "05:00"}]}
    good = {"po_reference": "PO-0087", "product": FLOUR, "pack_size_kg": 25, "packs": 7, "unit_price": 21, "delivery_charge": 18,
            "total": 165, "arrival_time": "05:00"}
    assert ex.match(po, good)["all_ok"]
    short = ex.match(po, {**good, "packs": 6, "total": 144})
    assert not short["all_ok"] and {f["field"] for f in short["fields"] if not f["ok"]} == {"Quantity", "Total"}
    assert not ex.match(po, {**good, "unit_price": None})["all_ok"]  # unstated counts as a mismatch
