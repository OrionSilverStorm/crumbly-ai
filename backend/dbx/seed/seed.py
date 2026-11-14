"""Demo bakery data (Morning Loaf, SE1). Dates are relative to 'now' so tomorrow's production is always tomorrow."""
from datetime import timedelta
from decimal import Decimal as D

from backend.config import settings
from backend.dbx import sql
from backend.demo import clock

FLOUR = "strong white flour"

# (name, slug for the plus-address, status, preference rank, website)
SUPPLIERS = [
    ("Borough Mill", "boroughmill", "approved", 1, "boroughmill.example"),
    ("Harrow & Sons", "harrowsons", "approved", 2, "harrowandsons.example"),
    ("Wheatfield Direct", "wheatfield", "approved", 3, "wheatfielddirect.example"),
    ("Millers Supply", "millerssupply", "approved", 4, "millerssupply.example"),
    ("Dairy Lane", "dairylane", "approved", 1, "dairylane.example"),
    ("Pantry Co.", "pantryco", "approved", 1, "pantryco.example"),
]

# (sku, supplier, ingredient, pack kg, unit price, vat rate, auto-order allowed). Flour is zero-rated in the UK.
PRODUCTS = [
    ("BM-SWF-25", "Borough Mill", FLOUR, 25, D("21.00"), D("0"), True),
    ("HS-SWF-25", "Harrow & Sons", FLOUR, 25, D("19.00"), D("0"), True),
    ("WD-SWF-25", "Wheatfield Direct", FLOUR, 25, D("20.00"), D("0"), True),
    ("MS-SWF-25", "Millers Supply", FLOUR, 25, D("20.00"), D("0"), True),
    ("BM-WM-25", "Borough Mill", "wholemeal flour", 25, D("22.00"), D("0"), True),
    ("HS-WM-25", "Harrow & Sons", "wholemeal flour", 25, D("20.50"), D("0"), True),
    ("DL-UB-10", "Dairy Lane", "unsalted butter", 10, D("68.00"), D("0"), True),
    ("PC-FY-1", "Pantry Co.", "fresh yeast", 1, D("4.20"), D("0"), False),
]

# (product, ingredient, kg per unit)
RECIPES = [
    ("Sourdough loaf", FLOUR, 0.8),
    ("Loaves & rolls", FLOUR, 0.6),
    ("Breakfast pastry", FLOUR, 0.5),
]

# Tomorrow's flour orders: 48 + 72 + 80 = 200 kg. (order id, customer, product, qty, bake, value, description)
ORDERS = [
    ("ORD-1041", "Café Juniper", "Sourdough loaf", 60, "06:00", D("180.00"), "60 sourdough loaves"),
    ("ORD-1042", "The Corner Shop", "Loaves & rolls", 120, "06:30", D("168.00"), "120 loaves & rolls"),
    ("ORD-1043", "Alder Hotel", "Breakfast pastry", 160, "07:00", D("320.00"), "160 breakfast pastries"),
]

# History that produces the reliability figures through SQL: (supplier, on time, <=15 min late, late, short deliveries).
# Borough: (39 + 3*0.5)/42 = 96%; Harrow: 21/23 = 91% and (22 + 0.5)/23 = 98% right quantity.
HISTORY = [
    ("Borough Mill", 39, 3, 0, 0),
    ("Harrow & Sons", 21, 0, 2, 1),
    ("Wheatfield Direct", 12, 1, 2, 0),
    ("Millers Supply", 27, 0, 3, 0),
]


def supplier_email(slug: str) -> str:
    """Every supplier is a plus-address of the supplier-bot mailbox, so all supplier mail lands in one inbox."""
    local_part, domain = settings.suppliers_address.split("@")
    return f"{local_part}+{slug}@{domain}"


def _history_rows() -> list[dict]:
    """Deterministic delivery history, one delivery every 2 days going back from yesterday."""
    rows, n = [], 0
    for supplier, on_time, slightly_late, late, short in HISTORY:
        kinds = ["on"] * on_time + ["slight"] * slightly_late + ["late"] * late
        for i, kind in enumerate(kinds):
            promised = clock.at(clock.now().date() - timedelta(days=2 * i + 1), "04:30")
            delay = {"on": -10, "slight": 10, "late": 75}[kind]  # minutes relative to the promised time
            n += 1
            rows.append({
                "po_id": f"PO-H{n:03d}", "supplier": supplier, "ingredient": FLOUR,
                "promised_at": promised, "arrived_at": promised + timedelta(minutes=delay),
                "qty_ordered": 200.0, "qty_received": 100.0 if i < short else 200.0,
            })
    return rows


def seed_warehouse() -> None:
    """Delete and re-insert all operational seed rows (Delta tables or the local mirror)."""
    day = clock.tomorrow()
    for t in ("inventory", "production_orders", "recipes", "incoming_deliveries", "approved_products",
              "suppliers", "delivery_history", "bronze_emails", "silver_quotes", "supplier_research", "incident_events_history"):
        sql.query(f"DELETE FROM {sql.T(t)}")
    now = clock.now()
    sql.insert("suppliers", [
        {"supplier": n, "email": supplier_email(s), "status": st, "preference_rank": r, "delivery_area": "SE1", "website": w}
        for n, s, st, r, w in SUPPLIERS])
    sql.insert("approved_products", [
        {"sku": a, "supplier": b, "ingredient": c, "pack_size_kg": float(d), "unit_price": e, "vat_rate": f, "auto_order_allowed": g}
        for a, b, c, d, e, f, g in PRODUCTS])
    sql.insert("recipes", [{"product": p, "ingredient": i, "kg_per_unit": k} for p, i, k in RECIPES])
    sql.insert("inventory", [
        {"ingredient": i, "quantity_kg": q, "reserved_kg": 0.0, "unit": "kg", "last_updated": now}
        for i, q in ((FLOUR, 40.0), ("wholemeal flour", 60.0), ("unsalted butter", 30.0), ("fresh yeast", 5.0), ("caster sugar", 50.0))])
    sql.insert("production_orders", [
        {"order_id": o, "customer": c, "product": p, "quantity": q, "bake_time": clock.at(day, b),
         "production_date": day, "order_value": v, "description": d}
        for o, c, p, q, b, v, d in ORDERS])
    # PO-0079: 8 x 25 kg from Millers Supply, due tomorrow 04:30 (inside the 04:00-05:00 window).
    sql.insert("incoming_deliveries", [{
        "po_id": "PO-0079", "supplier": "Millers Supply", "ingredient": FLOUR, "quantity_kg": 200.0,
        "expected_arrival": clock.at(day, "04:30"), "status": "scheduled", "total_cost": D("160.00")}])
    sql.insert("delivery_history", _history_rows())
