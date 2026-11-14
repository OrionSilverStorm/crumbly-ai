-- Unity Catalog SQL table functions: the agents' only tools for operational data ({S} = catalog.schema).
-- Parameters share names with columns, so the body qualifies them with the function name (e.g. calculate_shortage.ingredient).
-- Local mirror: dbx/local/functions_pg.sql (same semantics, Postgres dialect).

-- Kg short for an ingredient on a production date: needed - (on hand - reserved) - live deliveries arriving before that day's last bake.
-- (Timing per bake slot is coverage_by_slot's job.)
CREATE OR REPLACE FUNCTION {S}.calculate_shortage(ingredient STRING, production_date DATE)
RETURNS TABLE (needed_kg DOUBLE, on_hand_kg DOUBLE, reserved_kg DOUBLE, incoming_kg DOUBLE, shortage_kg DOUBLE)
COMMENT 'Shortage for one ingredient on one production date'
RETURN
  WITH need AS (
    SELECT COALESCE(SUM(o.quantity * r.kg_per_unit), 0) AS needed_kg
    FROM {S}.production_orders o JOIN {S}.recipes r ON r.product = o.product
    WHERE r.ingredient = calculate_shortage.ingredient AND o.production_date = calculate_shortage.production_date),
  inv AS (
    SELECT COALESCE(SUM(i.quantity_kg), 0) AS on_hand_kg, COALESCE(SUM(i.reserved_kg), 0) AS reserved_kg
    FROM {S}.inventory i WHERE i.ingredient = calculate_shortage.ingredient),
  inc AS (
    SELECT COALESCE(SUM(d.quantity_kg), 0) AS incoming_kg
    FROM {S}.incoming_deliveries d
    WHERE d.ingredient = calculate_shortage.ingredient AND d.status IN ('scheduled', 'confirmed')
      AND d.expected_arrival <= (SELECT MAX(o.bake_time) FROM {S}.production_orders o WHERE o.production_date = calculate_shortage.production_date))
  SELECT need.needed_kg, inv.on_hand_kg, inv.reserved_kg, inc.incoming_kg,
         GREATEST(need.needed_kg - (inv.on_hand_kg - inv.reserved_kg) - inc.incoming_kg, 0) AS shortage_kg
  FROM need CROSS JOIN inv CROSS JOIN inc;

-- Customer orders that use the ingredient on the date, in bake order.
CREATE OR REPLACE FUNCTION {S}.get_affected_orders(ingredient STRING, production_date DATE)
RETURNS TABLE (order_id STRING, customer STRING, product STRING, quantity INT, description STRING,
               order_value DECIMAL(10,2), kg_required DOUBLE, bake_time TIMESTAMP)
COMMENT 'Orders needing the ingredient on the production date'
RETURN
  SELECT o.order_id, o.customer, o.product, o.quantity, o.description, o.order_value,
         o.quantity * r.kg_per_unit AS kg_required, o.bake_time
  FROM {S}.production_orders o JOIN {S}.recipes r ON r.product = o.product
  WHERE r.ingredient = get_affected_orders.ingredient AND o.production_date = get_affected_orders.production_date
  ORDER BY o.bake_time, o.order_id;

-- Approved products for the ingredient from approved suppliers, in preference order.
CREATE OR REPLACE FUNCTION {S}.get_approved_alternatives(ingredient STRING)
RETURNS TABLE (sku STRING, supplier STRING, email STRING, pack_size_kg DOUBLE, unit_price DECIMAL(10,2),
               vat_rate DECIMAL(5,4), auto_order_allowed BOOLEAN, preference_rank INT)
COMMENT 'Approved alternatives for an ingredient'
RETURN
  SELECT p.sku, p.supplier, s.email, p.pack_size_kg, p.unit_price, p.vat_rate, p.auto_order_allowed, s.preference_rank
  FROM {S}.approved_products p JOIN {S}.suppliers s ON s.supplier = p.supplier
  WHERE p.ingredient = get_approved_alternatives.ingredient AND s.status = 'approved'
  ORDER BY s.preference_rank;

-- Time-phased coverage: stock only counts for a bake slot if it arrives at least buffer_min before that slot.
-- extra_kg/extra_arrival model a candidate delivery (pass 0/NULL to see current coverage).
CREATE OR REPLACE FUNCTION {S}.coverage_by_slot(ingredient STRING, production_date DATE, extra_kg DOUBLE,
                                                extra_arrival TIMESTAMP, buffer_min INT DEFAULT 60)
RETURNS TABLE (bake_time TIMESTAMP, required_kg DOUBLE, cumulative_required DOUBLE,
               cumulative_available DOUBLE, covered BOOLEAN)
COMMENT 'Per-slot coverage with an arrival buffer'
RETURN
  WITH slots AS (
    SELECT o.bake_time, SUM(o.quantity * r.kg_per_unit) AS required_kg
    FROM {S}.production_orders o JOIN {S}.recipes r ON r.product = o.product
    WHERE r.ingredient = coverage_by_slot.ingredient AND o.production_date = coverage_by_slot.production_date
    GROUP BY o.bake_time),
  stock AS (
    SELECT COALESCE(SUM(i.quantity_kg - i.reserved_kg), 0) AS kg
    FROM {S}.inventory i WHERE i.ingredient = coverage_by_slot.ingredient),
  arriving AS (
    SELECT s.bake_time, COALESCE(SUM(d.quantity_kg), 0) AS kg
    FROM slots s LEFT JOIN {S}.incoming_deliveries d
      ON d.ingredient = coverage_by_slot.ingredient AND d.status IN ('scheduled', 'confirmed')
     AND d.expected_arrival <= timestampadd(MINUTE, -coverage_by_slot.buffer_min, s.bake_time)
    GROUP BY s.bake_time),
  phased AS (
    SELECT s.bake_time, s.required_kg,
           SUM(s.required_kg) OVER (ORDER BY s.bake_time) AS cumulative_required,
           stock.kg + a.kg + CASE WHEN coverage_by_slot.extra_arrival IS NOT NULL
             AND coverage_by_slot.extra_arrival <= timestampadd(MINUTE, -coverage_by_slot.buffer_min, s.bake_time)
             THEN coverage_by_slot.extra_kg ELSE 0 END AS cumulative_available
    FROM slots s JOIN arriving a ON a.bake_time = s.bake_time CROSS JOIN stock)
  SELECT bake_time, required_kg, cumulative_required, cumulative_available,
         cumulative_available >= cumulative_required AS covered
  FROM phased ORDER BY bake_time;

-- Reliability from delivery history. On time = 1, up to 15 min late = half credit, later = 0.
-- Quantity accuracy = average share of the ordered quantity actually received.
CREATE OR REPLACE FUNCTION {S}.supplier_reliability(supplier STRING)
RETURNS TABLE (on_time_rate DOUBLE, quantity_accuracy DOUBLE, deliveries BIGINT)
COMMENT 'Supplier reliability from delivery_history'
RETURN
  SELECT AVG(CASE WHEN h.arrived_at <= h.promised_at THEN 1.0
                  WHEN h.arrived_at <= timestampadd(MINUTE, 15, h.promised_at) THEN 0.5 ELSE 0.0 END) AS on_time_rate,
         AVG(LEAST(h.qty_received / h.qty_ordered, 1.0)) AS quantity_accuracy,
         COUNT(*) AS deliveries
  FROM {S}.delivery_history h WHERE h.supplier = supplier_reliability.supplier;
