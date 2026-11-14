-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 03 · Trace analysis (MLflow traces stored in Unity Catalog)
-- MAGIC With `MLFLOW_UC_TRACES=1`, traces land in `<catalog>.<schema>.<prefix>_otel_spans` (prefix defaults to the
-- MAGIC experiment id). Each agent step is a trace tagged with `incident_id`, with child spans per UC function / Linkup /
-- MAGIC LLM call. Set the widgets, then run `DESCRIBE` first: the OTel column layout can differ between MLflow versions.

-- COMMAND ----------

CREATE WIDGET TEXT spans_table DEFAULT 'crumbly.bakery.<experiment_id>_otel_spans';
CREATE WIDGET TEXT schema DEFAULT 'crumbly.bakery';

-- COMMAND ----------

DESCRIBE TABLE IDENTIFIER(:spans_table);

-- COMMAND ----------

-- Tool calls per incident (incident_id is a trace tag; tool spans are named uc.* / linkup.* / llm.*)
WITH spans AS (
  SELECT trace_id, name, attributes,
         (end_time_unix_nano - start_time_unix_nano) / 1e6 AS ms
  FROM IDENTIFIER(:spans_table)
),
incident_of AS (
  SELECT trace_id, MAX(attributes['incident_id']) AS incident_id FROM spans GROUP BY trace_id
)
SELECT i.incident_id, split(s.name, '\.')[0] AS tool_family, COUNT(*) AS calls, ROUND(AVG(s.ms)) AS avg_ms
FROM spans s JOIN incident_of i USING (trace_id)
WHERE s.name RLIKE '^(uc|linkup|llm|pipeline)\.'
GROUP BY ALL ORDER BY i.incident_id, calls DESC;

-- COMMAND ----------

-- Latency per agent stage (root spans named <agent>.<step>)
SELECT name AS step, COUNT(*) AS runs,
       ROUND(PERCENTILE((end_time_unix_nano - start_time_unix_nano) / 1e6, 0.5)) AS p50_ms,
       ROUND(PERCENTILE((end_time_unix_nano - start_time_unix_nano) / 1e6, 0.95)) AS p95_ms
FROM IDENTIFIER(:spans_table)
WHERE name RLIKE '^(production_agent|sourcing_agent|recovery_agent|execution|crumbly)\.'
GROUP BY name ORDER BY p50_ms DESC;

-- COMMAND ----------

-- Share of quotes needing a follow-up, and stage timings from the Delta copy of the event log
SELECT * FROM IDENTIFIER(:schema || '.v_quote_followup_share');

-- COMMAND ----------

SELECT incident_id, stage, MIN(ts) AS entered, COUNT(*) AS events
FROM IDENTIFIER(:schema || '.incident_events_history')
GROUP BY ALL ORDER BY incident_id, entered;
