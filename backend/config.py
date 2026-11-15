"""Central configuration. Every setting (and every secret) comes from environment variables; see .env.example."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Repo root, used for local data dirs (.pgdata, caches) and the built frontend.
ROOT = Path(__file__).resolve().parent.parent
# A local .env is optional; real deployments (Databricks Apps) inject env vars directly.
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    """Read a string env var, treating an unset or blank value as the documented default."""
    value = os.getenv(name)
    return default if value is None or not value.strip() else value


def _flag(name: str, default: str = "0") -> bool:
    """Read a boolean env var ('1', 'true', 'yes', 'on' count as true)."""
    return _env(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    """Snapshot of all settings, built once per process by load()."""

    tz: str
    # Live app state: 'embedded' (pgserver, no install), 'postgres' (DATABASE_URL) or 'lakebase'.
    db_mode: str
    database_url: str
    pgdata: str  # embedded Postgres data directory
    lakebase_endpoint: str  # Lakebase Autoscaling endpoint path (projects/.../endpoints/...)
    lakebase_instance: str  # Lakebase Provisioned instance name (used if no endpoint is set)
    # Operational data: 'local' (Postgres mirror of the Delta tables) or 'databricks' (SQL warehouse).
    warehouse_mode: str
    warehouse_id: str
    uc_catalog: str
    uc_schema: str
    # LLM: 'databricks' (serving endpoint), 'openai' (any OpenAI-compatible API) or 'stub' (tests only).
    llm_provider: str
    llm_endpoint: str
    openai_base_url: str
    openai_api_key: str
    ai_query_enabled: bool
    ai_query_timeout_s: float
    # Email: 'gmail' (IMAP/SMTP, two accounts) or 'memory' (in-process mailboxes for tests/offline).
    email_mode: str
    bakery_address: str
    bakery_password: str
    suppliers_address: str
    suppliers_password: str
    imap_host: str
    smtp_host: str
    poll_seconds: float
    # Linkup research: 'live' (real API) or 'fixture' (bundled fictional responses for the scripted demo).
    linkup_api_key: str
    linkup_mode: str
    linkup_cache: bool
    # MLflow tracing.
    tracing_enabled: bool
    mlflow_tracking_uri: str
    mlflow_experiment: str
    mlflow_uc_traces: bool
    # Demo controls.
    scenario: str
    time_scale: float
    bot_inprocess: bool
    owner_id: str


def load() -> Settings:
    """Build Settings from the current environment."""
    return Settings(
        tz=_env("APP_TZ", "Europe/London"),
        db_mode=_env("DB_MODE", "embedded"),
        database_url=_env("DATABASE_URL"),
        pgdata=_env("PGDATA_DIR", str(ROOT / ".pgdata")),
        lakebase_endpoint=_env("LAKEBASE_ENDPOINT"),
        lakebase_instance=_env("LAKEBASE_INSTANCE"),
        warehouse_mode=_env("WAREHOUSE_MODE", "local"),
        warehouse_id=_env("DATABRICKS_WAREHOUSE_ID"),
        uc_catalog=_env("UC_CATALOG", "crumbly"),
        uc_schema=_env("UC_SCHEMA", "bakery"),
        llm_provider=_env("LLM_PROVIDER", "stub"),
        llm_endpoint=_env("LLM_ENDPOINT", "databricks-claude-sonnet-4-5"),
        openai_base_url=_env("OPENAI_BASE_URL"),
        openai_api_key=_env("OPENAI_API_KEY"),
        ai_query_enabled=_flag("AI_QUERY_ENABLED", "1"),
        ai_query_timeout_s=float(_env("AI_QUERY_TIMEOUT_S", "8")),
        email_mode=_env("EMAIL_MODE", "memory"),
        bakery_address=_env("EMAIL_BAKERY_ADDRESS", "bakery@crumbly.test"),
        bakery_password=_env("EMAIL_BAKERY_PASSWORD"),
        suppliers_address=_env("EMAIL_SUPPLIERS_ADDRESS", "suppliers@crumbly.test"),
        suppliers_password=_env("EMAIL_SUPPLIERS_PASSWORD"),
        imap_host=_env("EMAIL_IMAP_HOST", "imap.gmail.com"),
        smtp_host=_env("EMAIL_SMTP_HOST", "smtp.gmail.com"),
        poll_seconds=float(_env("EMAIL_POLL_SECONDS", "10")),
        linkup_api_key=_env("LINKUP_API_KEY"),
        linkup_mode=_env("LINKUP_MODE", "live"),
        linkup_cache=_flag("LINKUP_CACHE"),
        tracing_enabled=_flag("TRACING_ENABLED", "1"),
        mlflow_tracking_uri=_env("MLFLOW_TRACKING_URI", f"sqlite:///{(ROOT / '.mlflow' / 'mlflow.db').as_posix()}"),
        mlflow_experiment=_env("MLFLOW_EXPERIMENT_NAME", "crumbly"),
        mlflow_uc_traces=_flag("MLFLOW_UC_TRACES"),
        scenario=_env("SCENARIO", "happy"),
        time_scale=float(_env("DEMO_TIME_SCALE", "1")),
        bot_inprocess=_flag("SUPPLIER_BOT_INPROCESS", "1"),
        owner_id=_env("OWNER_ID", "owner"),
    )


# Process-wide settings; tests set env vars before importing backend modules.
settings = load()
