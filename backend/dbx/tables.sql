-- Delta tables in Unity Catalog ({S} = catalog.schema). Mirrored for local dev in dbx/local/tables_pg.sql.

-- ---------- Operational data the bakery already has ----------
CREATE TABLE IF NOT EXISTS {S}.inventory (
  ingredient STRING, quantity_kg DOUBLE, reserved_kg DOUBLE, unit STRING, last_updated TIMESTAMP
);

CREATE TABLE IF NOT EXISTS {S}.production_orders (
  order_id STRING, customer STRING, product STRING, quantity INT, bake_time TIMESTAMP,
  production_date DATE, order_value DECIMAL(10,2), description STRING
);

CREATE TABLE IF NOT EXISTS {S}.recipes (product STRING, ingredient STRING, kg_per_unit DOUBLE);

-- status: scheduled | confirmed (stock on order) | cancelled | received
CREATE TABLE IF NOT EXISTS {S}.incoming_deliveries (
  po_id STRING, supplier STRING, ingredient STRING, quantity_kg DOUBLE, expected_arrival TIMESTAMP,
  status STRING, total_cost DECIMAL(10,2)
);

CREATE TABLE IF NOT EXISTS {S}.approved_products (
  sku STRING, supplier STRING, ingredient STRING, pack_size_kg DOUBLE, unit_price DECIMAL(10,2),
  vat_rate DECIMAL(5,4), auto_order_allowed BOOLEAN
);

-- status: approved | new (found by research; buying needs the owner's OK)
CREATE TABLE IF NOT EXISTS {S}.suppliers (
  supplier STRING, email STRING, status STRING, preference_rank INT, delivery_area STRING, website STRING
);

CREATE TABLE IF NOT EXISTS {S}.delivery_history (
  po_id STRING, supplier STRING, ingredient STRING, promised_at TIMESTAMP, arrived_at TIMESTAMP,
  qty_ordered DOUBLE, qty_received DOUBLE
);

-- ---------- Pipeline and audit ----------
-- Raw email text, inbound and outbound.
CREATE TABLE IF NOT EXISTS {S}.bronze_emails (
  message_id STRING, thread_id STRING, incident_id STRING, direction STRING, from_addr STRING,
  to_addr STRING, subject STRING, body STRING, received_at TIMESTAMP
);

-- Structured quotes parsed from bronze (ai_query, or the LLM client fallback).
CREATE TABLE IF NOT EXISTS {S}.silver_quotes (
  quote_id STRING, incident_id STRING, supplier STRING, sku STRING, packs INT, pack_size_kg DOUBLE,
  goods_price DECIMAL(10,2), delivery_charge DECIMAL(10,2), vat_rate DECIMAL(5,4), total DECIMAL(10,2),
  arrival_at TIMESTAMP, missing_fields STRING, source_message_id STRING, parse_path STRING, parsed_at TIMESTAMP
);

-- Linkup research claims with sources.
CREATE TABLE IF NOT EXISTS {S}.supplier_research (
  research_id STRING, incident_id STRING, supplier STRING, claim STRING, value STRING, status STRING,
  source_urls STRING, retrieved_at TIMESTAMP
);

-- Periodic copy of the Lakebase event log for analytics.
CREATE TABLE IF NOT EXISTS {S}.incident_events_history (
  id BIGINT, incident_id STRING, ts TIMESTAMP, stage STRING, actor STRING, type STRING, summary STRING, evidence STRING
);
