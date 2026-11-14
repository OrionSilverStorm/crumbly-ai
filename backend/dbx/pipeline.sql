-- Batch version of the bronze -> silver pipeline, for judges and notebooks/02_pipeline_demo.py.
-- Parses every inbound supplier reply in bronze_emails with ai_query (JSON response format) into a view.
-- The live app runs the same ai_query per message (backend/dbx/pipeline.py) and writes silver_quotes.
-- ${endpoint} is the serving endpoint name (LLM_ENDPOINT).

CREATE OR REPLACE VIEW {S}.silver_quotes_batch AS
SELECT
  b.message_id,
  b.incident_id,
  b.received_at,
  from_json(
    ai_query(
      '${endpoint}',
      concat('Extract only facts stated in this supplier email; null if not stated. Email:\n', b.body),
      responseFormat => 'STRUCT<quote:STRUCT<declined:BOOLEAN, offers:ARRAY<STRUCT<label:STRING, packs:INT, max_packs:INT, pack_size_kg:DOUBLE, unit_price:DOUBLE, goods_price:DOUBLE, delivery_charge:DOUBLE, delivery_included:BOOLEAN, vat_rate:DOUBLE, total:DOUBLE, arrival_time:STRING, arrival_text:STRING>>>>'
    ),
    'STRUCT<quote:STRUCT<declined:BOOLEAN, offers:ARRAY<STRUCT<label:STRING, packs:INT, max_packs:INT, pack_size_kg:DOUBLE, unit_price:DOUBLE, goods_price:DOUBLE, delivery_charge:DOUBLE, delivery_included:BOOLEAN, vat_rate:DOUBLE, total:DOUBLE, arrival_time:STRING, arrival_text:STRING>>>>'
  ) AS parsed
FROM {S}.bronze_emails b
WHERE b.direction = 'inbound' AND b.incident_id IS NOT NULL;

-- ---------- Metrics views (Delta side) ----------
-- Sales value of tomorrow's orders per ingredient (used for "orders protected").
CREATE OR REPLACE VIEW {S}.v_order_value_by_ingredient AS
SELECT r.ingredient, o.production_date, COUNT(*) AS orders, SUM(o.order_value) AS order_value
FROM {S}.production_orders o JOIN {S}.recipes r ON r.product = o.product
GROUP BY r.ingredient, o.production_date;

-- Share of quotes that needed a follow-up (missing fields at first parse).
CREATE OR REPLACE VIEW {S}.v_quote_followup_share AS
SELECT incident_id, COUNT(*) AS quotes,
       AVG(CASE WHEN missing_fields <> '[]' THEN 1.0 ELSE 0.0 END) AS share_missing
FROM {S}.silver_quotes GROUP BY incident_id;
