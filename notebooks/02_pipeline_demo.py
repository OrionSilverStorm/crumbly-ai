# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Bronze → silver with `ai_query`
# MAGIC Every email Crumbly sends or receives lands in `bronze_emails` as raw text. Supplier replies are parsed into structured
# MAGIC quotes with SQL `ai_query` and a JSON response format. The live app does this per message (falling back to the LLM
# MAGIC client if `ai_query` is slow or unavailable, and recording which path ran); this notebook runs it in batch for judges.

# COMMAND ----------

dbutils.widgets.text("catalog", "crumbly")
dbutils.widgets.text("schema", "bakery")
S = f"{dbutils.widgets.get('catalog')}.{dbutils.widgets.get('schema')}"

# COMMAND ----------

# MAGIC %md ### Bronze: raw emails for the latest incident

# COMMAND ----------

display(spark.sql(f"""SELECT received_at, direction, from_addr, subject, body FROM {S}.bronze_emails
                     WHERE incident_id = (SELECT MAX(incident_id) FROM {S}.bronze_emails) ORDER BY received_at"""))

# COMMAND ----------

# MAGIC %md ### Silver (batch): `ai_query` over every inbound reply

# COMMAND ----------

display(spark.sql(f"""SELECT received_at, parsed.quote.declined, explode_outer(parsed.quote.offers) AS offer
                     FROM {S}.silver_quotes_batch ORDER BY received_at"""))

# COMMAND ----------

# MAGIC %md ### Silver (live): what the app stored, including the parse path and code-detected missing fields

# COMMAND ----------

display(spark.sql(f"""SELECT parsed_at, supplier, packs, goods_price, delivery_charge, vat_rate, total, arrival_at,
                            missing_fields, parse_path FROM {S}.silver_quotes ORDER BY parsed_at"""))

# COMMAND ----------

# MAGIC %md ### Share of quotes that needed a follow-up

# COMMAND ----------

display(spark.sql(f"SELECT * FROM {S}.v_quote_followup_share"))
