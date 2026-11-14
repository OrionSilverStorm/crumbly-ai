-- Local Postgres mirror of the Delta tables in dbx/tables.sql (schema `wh`), for offline dev and tests.
CREATE SCHEMA IF NOT EXISTS wh;

CREATE TABLE IF NOT EXISTS wh.inventory (ingredient TEXT, quantity_kg DOUBLE PRECISION, reserved_kg DOUBLE PRECISION, unit TEXT, last_updated TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS wh.production_orders (order_id TEXT, customer TEXT, product TEXT, quantity INT, bake_time TIMESTAMPTZ, production_date DATE, order_value NUMERIC(10,2), description TEXT);
CREATE TABLE IF NOT EXISTS wh.recipes (product TEXT, ingredient TEXT, kg_per_unit DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS wh.incoming_deliveries (po_id TEXT, supplier TEXT, ingredient TEXT, quantity_kg DOUBLE PRECISION, expected_arrival TIMESTAMPTZ, status TEXT, total_cost NUMERIC(10,2));
CREATE TABLE IF NOT EXISTS wh.approved_products (sku TEXT, supplier TEXT, ingredient TEXT, pack_size_kg DOUBLE PRECISION, unit_price NUMERIC(10,2), vat_rate NUMERIC(5,4), auto_order_allowed BOOLEAN);
CREATE TABLE IF NOT EXISTS wh.suppliers (supplier TEXT, email TEXT, status TEXT, preference_rank INT, delivery_area TEXT, website TEXT);
CREATE TABLE IF NOT EXISTS wh.delivery_history (po_id TEXT, supplier TEXT, ingredient TEXT, promised_at TIMESTAMPTZ, arrived_at TIMESTAMPTZ, qty_ordered DOUBLE PRECISION, qty_received DOUBLE PRECISION);

CREATE TABLE IF NOT EXISTS wh.bronze_emails (message_id TEXT, thread_id TEXT, incident_id TEXT, direction TEXT, from_addr TEXT, to_addr TEXT, subject TEXT, body TEXT, received_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS wh.silver_quotes (quote_id TEXT, incident_id TEXT, supplier TEXT, sku TEXT, packs INT, pack_size_kg DOUBLE PRECISION, goods_price NUMERIC(10,2), delivery_charge NUMERIC(10,2), vat_rate NUMERIC(5,4), total NUMERIC(10,2), arrival_at TIMESTAMPTZ, missing_fields TEXT, source_message_id TEXT, parse_path TEXT, parsed_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS wh.supplier_research (research_id TEXT, incident_id TEXT, supplier TEXT, claim TEXT, value TEXT, status TEXT, source_urls TEXT, retrieved_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS wh.incident_events_history (id BIGINT, incident_id TEXT, ts TIMESTAMPTZ, stage TEXT, actor TEXT, type TEXT, summary TEXT, evidence TEXT);
