-- Local Postgres mirror of dbx/uc_functions.sql. Same names, parameters and semantics; only the dialect differs.
-- (In SQL functions a column wins over a same-named parameter, so parameters are qualified with the function name.)

CREATE OR REPLACE FUNCTION wh.calculate_shortage(ingredient TEXT, production_date DATE)
RETURNS TABLE (needed_kg DOUBLE PRECISION, on_hand_kg DOUBLE PRECISION, reserved_kg DOUBLE PRECISION, incoming_kg DOUBLE PRECISION, shortage_kg DOUBLE PRECISION)
LANGUAGE sql STABLE AS $$
  WITH need AS (
    SELECT COALESCE(SUM(o.quantity * r.kg_per_unit), 0)::float8 AS needed_kg
    FROM wh.production_orders o JOIN wh.recipes r ON r.product = o.product
    WHERE r.ingredient = calculate_shortage.ingredient AND o.production_date = calculate_shortage.production_date),
  inv AS (
    SELECT COALESCE(SUM(i.quantity_kg), 0)::float8 AS on_hand_kg, COALESCE(SUM(i.reserved_kg), 0)::float8 AS reserved_kg
    FROM wh.inventory i WHERE i.ingredient = calculate_shortage.ingredient),
  inc AS (
    SELECT COALESCE(SUM(d.quantity_kg), 0)::float8 AS incoming_kg
    FROM wh.incoming_deliveries d
    WHERE d.ingredient = calculate_shortage.ingredient AND d.status IN ('scheduled', 'confirmed')
      AND d.expected_arrival <= (SELECT MAX(o.bake_time) FROM wh.production_orders o WHERE o.production_date = calculate_shortage.production_date))
  SELECT need.needed_kg, inv.on_hand_kg, inv.reserved_kg, inc.incoming_kg,
         GREATEST(need.needed_kg - (inv.on_hand_kg - inv.reserved_kg) - inc.incoming_kg, 0)
  FROM need CROSS JOIN inv CROSS JOIN inc
$$;

CREATE OR REPLACE FUNCTION wh.get_affected_orders(ingredient TEXT, production_date DATE)
RETURNS TABLE (order_id TEXT, customer TEXT, product TEXT, quantity INT, description TEXT, order_value NUMERIC(10,2), kg_required DOUBLE PRECISION, bake_time TIMESTAMPTZ)
LANGUAGE sql STABLE AS $$
  SELECT o.order_id, o.customer, o.product, o.quantity, o.description, o.order_value, o.quantity * r.kg_per_unit, o.bake_time
  FROM wh.production_orders o JOIN wh.recipes r ON r.product = o.product
  WHERE r.ingredient = get_affected_orders.ingredient AND o.production_date = get_affected_orders.production_date
  ORDER BY o.bake_time, o.order_id
$$;

CREATE OR REPLACE FUNCTION wh.get_approved_alternatives(ingredient TEXT)
RETURNS TABLE (sku TEXT, supplier TEXT, email TEXT, pack_size_kg DOUBLE PRECISION, unit_price NUMERIC(10,2), vat_rate NUMERIC(5,4), auto_order_allowed BOOLEAN, preference_rank INT)
LANGUAGE sql STABLE AS $$
  SELECT p.sku, p.supplier, s.email, p.pack_size_kg, p.unit_price, p.vat_rate, p.auto_order_allowed, s.preference_rank
  FROM wh.approved_products p JOIN wh.suppliers s ON s.supplier = p.supplier
  WHERE p.ingredient = get_approved_alternatives.ingredient AND s.status = 'approved'
  ORDER BY s.preference_rank
$$;

CREATE OR REPLACE FUNCTION wh.coverage_by_slot(ingredient TEXT, production_date DATE, extra_kg DOUBLE PRECISION, extra_arrival TIMESTAMPTZ, buffer_min INT DEFAULT 60)
RETURNS TABLE (bake_time TIMESTAMPTZ, required_kg DOUBLE PRECISION, cumulative_required DOUBLE PRECISION, cumulative_available DOUBLE PRECISION, covered BOOLEAN)
LANGUAGE sql STABLE AS $$
  WITH slots AS (
    SELECT o.bake_time, SUM(o.quantity * r.kg_per_unit)::float8 AS required_kg
    FROM wh.production_orders o JOIN wh.recipes r ON r.product = o.product
    WHERE r.ingredient = coverage_by_slot.ingredient AND o.production_date = coverage_by_slot.production_date
    GROUP BY o.bake_time),
  stock AS (
    SELECT COALESCE(SUM(i.quantity_kg - i.reserved_kg), 0)::float8 AS kg
    FROM wh.inventory i WHERE i.ingredient = coverage_by_slot.ingredient),
  arriving AS (
    SELECT s.bake_time, COALESCE(SUM(d.quantity_kg), 0)::float8 AS kg
    FROM slots s LEFT JOIN wh.incoming_deliveries d
      ON d.ingredient = coverage_by_slot.ingredient AND d.status IN ('scheduled', 'confirmed')
     AND d.expected_arrival <= s.bake_time - make_interval(mins => coverage_by_slot.buffer_min)
    GROUP BY s.bake_time),
  phased AS (
    SELECT s.bake_time, s.required_kg,
           SUM(s.required_kg) OVER (ORDER BY s.bake_time) AS cumulative_required,
           stock.kg + a.kg + CASE WHEN coverage_by_slot.extra_arrival IS NOT NULL
             AND coverage_by_slot.extra_arrival <= s.bake_time - make_interval(mins => coverage_by_slot.buffer_min)
             THEN coverage_by_slot.extra_kg ELSE 0 END AS cumulative_available
    FROM slots s JOIN arriving a ON a.bake_time = s.bake_time CROSS JOIN stock)
  SELECT p.bake_time, p.required_kg, p.cumulative_required, p.cumulative_available,
         p.cumulative_available >= p.cumulative_required
  FROM phased p ORDER BY p.bake_time
$$;

CREATE OR REPLACE FUNCTION wh.supplier_reliability(supplier TEXT)
RETURNS TABLE (on_time_rate DOUBLE PRECISION, quantity_accuracy DOUBLE PRECISION, deliveries BIGINT)
LANGUAGE sql STABLE AS $$
  SELECT AVG(CASE WHEN h.arrived_at <= h.promised_at THEN 1.0
                  WHEN h.arrived_at <= h.promised_at + interval '15 minutes' THEN 0.5 ELSE 0.0 END)::float8,
         AVG(LEAST(h.qty_received / h.qty_ordered, 1.0))::float8,
         COUNT(*)
  FROM wh.delivery_history h WHERE h.supplier = supplier_reliability.supplier
$$;
