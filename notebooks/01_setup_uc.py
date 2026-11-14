# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Set up Unity Catalog for Crumbly
# MAGIC Creates the catalog/schema, the Delta tables (`backend/dbx/tables.sql`), the UC functions the agents use as tools
# MAGIC (`backend/dbx/uc_functions.sql`) and the pipeline/metrics views (`backend/dbx/pipeline.sql`), then seeds demo data.
# MAGIC Run from a Git folder containing this repo.

# COMMAND ----------

dbutils.widgets.text("catalog", "crumbly")
dbutils.widgets.text("schema", "bakery")
dbutils.widgets.text("endpoint", "databricks-claude-sonnet-4-5")
catalog, schema, endpoint = (dbutils.widgets.get(k) for k in ("catalog", "schema", "endpoint"))
spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

# COMMAND ----------

import re, pathlib

root = pathlib.Path("..") / "backend" / "dbx"


def run_file(name: str) -> None:
    """Run every statement in a SQL file ({S} = catalog.schema, ${endpoint} = serving endpoint)."""
    text = (root / name).read_text().replace("{S}", f"{catalog}.{schema}").replace("${endpoint}", endpoint)
    for stmt in (s.strip() for s in re.split(r";\s*\n", text)):
        if any(l.strip() and not l.strip().startswith("--") for l in stmt.splitlines()):
            spark.sql(stmt)


for f in ("tables.sql", "uc_functions.sql", "pipeline.sql"):
    run_file(f)
display(spark.sql(f"SHOW USER FUNCTIONS IN {catalog}.{schema}"))

# COMMAND ----------

# MAGIC %md Seed data and sanity-check the acceptance numbers (expects 160 kg after cancelling PO-0079).

# COMMAND ----------

import os, sys
sys.path.insert(0, str(pathlib.Path("..").resolve()))
os.environ.update(WAREHOUSE_MODE="databricks", UC_CATALOG=catalog, UC_SCHEMA=schema)
# The seed writes through the SQL warehouse client; set DATABRICKS_WAREHOUSE_ID in the cluster env or here.
from backend.dbx.seed.seed import seed_warehouse  # noqa: E402

seed_warehouse()
display(spark.sql(f"""SELECT * FROM {catalog}.{schema}.coverage_by_slot('strong white flour', date_add(current_date(), 1), 175,
                       timestamp(concat(cast(date_add(current_date(), 1) AS STRING), ' 05:00:00')), 60)"""))
