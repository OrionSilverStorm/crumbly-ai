"""Live app state in Postgres: Lakebase in Databricks, or a local Postgres / embedded pgserver fallback."""
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from backend.config import settings

MIGRATIONS = Path(__file__).parent / "migrations"


def _lakebase_token() -> str:
    """Short-lived (60 min) OAuth database credential from the Databricks SDK, used as the Postgres password."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    if settings.lakebase_endpoint:  # Lakebase Autoscaling (projects/branches/endpoints)
        return w.postgres.generate_database_credential(endpoint=settings.lakebase_endpoint).token
    # Lakebase Provisioned (database instances)
    return w.database.generate_database_credential(
        request_id=str(uuid.uuid4()), instance_names=[settings.lakebase_instance]
    ).token


class _LakebaseConnection(psycopg.Connection):
    """Connection class that fetches a fresh token for every new pooled connection (the documented pattern)."""

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs):
        kwargs["password"] = _lakebase_token()
        return super().connect(conninfo, **kwargs)


def _conninfo() -> tuple[str, type[psycopg.Connection], float]:
    """Connection string, connection class and max connection lifetime for the configured mode."""
    if settings.db_mode == "lakebase":
        # Databricks Apps inject PGHOST/PGUSER/PGDATABASE/PGPORT/PGSSLMODE for a database resource; libpq reads them.
        return "", _LakebaseConnection, 45 * 60  # recycle before the 60-minute token expires
    if settings.db_mode == "postgres":
        return settings.database_url, psycopg.Connection, 3600
    import pgserver  # embedded Postgres binaries, no Docker needed

    # Keep running across restarts. After an unclean stop, crash recovery on Windows can outlast pgserver's 10 s
    # start timeout, so retry while the server finishes recovering.
    for attempt in range(6):
        try:
            server = pgserver.get_server(settings.pgdata, cleanup_mode=None)
            return server.get_uri(), psycopg.Connection, 3600
        except Exception:
            if attempt == 5:
                raise


@lru_cache
def pool() -> ConnectionPool:
    """Process-wide connection pool (created lazily on first use)."""
    conninfo, cls, lifetime = _conninfo()
    # All timestamps are timestamptz (absolute instants), so no session timezone is needed.
    kwargs = {"row_factory": dict_row, "autocommit": True}
    return ConnectionPool(
        conninfo, connection_class=cls, kwargs=kwargs,
        min_size=1, max_size=10, max_lifetime=lifetime, open=True,
    )


def _json(v) -> bool:
    """Dicts and lists of dicts are JSONB; lists of scalars stay Postgres arrays (for = ANY(...)). Wrap a JSONB list of
    scalars explicitly with Jsonb()."""
    return isinstance(v, dict) or (isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v))


def _adapt(params):
    """Wrap JSON-shaped values as JSONB so JSON columns can be passed as plain Python values."""
    if params is None:
        return None
    fix = lambda v: Jsonb(v) if _json(v) else v  # noqa: E731
    return {k: fix(v) for k, v in params.items()} if isinstance(params, dict) else [fix(v) for v in params]


def q(sql: str, params=None) -> list[dict]:
    """Run a query and return all rows as dicts."""
    with pool().connection() as c:
        cur = c.execute(sql, _adapt(params))
        return cur.fetchall() if cur.description else []


def one(sql: str, params=None) -> dict | None:
    """Run a query and return the first row (or None)."""
    rows = q(sql, params)
    return rows[0] if rows else None


@contextmanager
def tx():
    """Transaction block yielding a cursor-like connection; commits on success, rolls back on error."""
    with pool().connection() as c, c.transaction():
        yield c


def migrate() -> None:
    """Apply plain-SQL migrations in filename order, once each."""
    q("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())")
    done = {r["name"] for r in q("SELECT name FROM schema_migrations")}
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.name not in done:
            with tx() as c:
                c.execute(f.read_text(encoding="utf-8"))
                c.execute("INSERT INTO schema_migrations (name) VALUES (%s)", [f.name])
