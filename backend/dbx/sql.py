"""Operational data access (Delta tables + UC functions). Parameterised SQL only; agents call `fn()`, never raw SQL.

Two interchangeable backends:
- 'databricks': Databricks SQL warehouse via databricks-sql-connector (native `:name` parameters).
- 'local': a Postgres schema `wh` that mirrors the Delta tables and UC functions (dbx/local/*.sql), for offline dev/tests.
"""
import re
import threading
from functools import lru_cache
from pathlib import Path

from backend.config import settings
from backend.db import lakebase

HERE = Path(__file__).parent
# Matches `:name` parameters but not `::casts` or times like '05:00'.
_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def T(name: str) -> str:
    """Fully qualified table/function name for the active backend."""
    return f"{settings.uc_catalog}.{settings.uc_schema}.{name}" if settings.warehouse_mode == "databricks" else f"wh.{name}"


class _Databricks:
    """Databricks SQL warehouse client (one connection, serialised by a lock)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._conn = None

    def _connect(self):
        from databricks import sql
        from databricks.sdk.core import Config

        cfg = Config()  # resolves host + auth (PAT locally, service principal inside Databricks Apps)
        return sql.connect(
            server_hostname=cfg.host.replace("https://", ""),
            http_path=f"/sql/1.0/warehouses/{settings.warehouse_id}",
            credentials_provider=lambda: cfg.authenticate,
        )

    def query(self, sql: str, params: dict | None = None, timeout: float | None = None) -> list[dict]:
        with self._lock:
            self._conn = self._conn or self._connect()
            with self._conn.cursor() as cur:
                cur.execute(sql, parameters=params or {})
                if not cur.description:
                    return []
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]


class _Local:
    """Postgres mirror: rewrites `:name` to psycopg's `%(name)s` style and reuses the app pool."""

    def query(self, sql: str, params: dict | None = None, timeout: float | None = None) -> list[dict]:
        return lakebase.q(_PARAM.sub(r"%(\1)s", sql.replace("%", "%%")), params or {})


@lru_cache
def client():
    """The configured warehouse backend."""
    return _Databricks() if settings.warehouse_mode == "databricks" else _Local()


def query(sql: str, params: dict | None = None) -> list[dict]:
    """Run parameterised SQL. Table names are interpolated only via T(); values always go through params."""
    return client().query(sql, params)


def fn(name: str, **params) -> list[dict]:
    """Call a UC table function, e.g. fn('calculate_shortage', ingredient=..., production_date=...)."""
    args = ", ".join(f":{k}" for k in params)
    return query(f"SELECT * FROM {T(name)}({args})", params)


def insert(table: str, rows: list[dict], batch: int = 20) -> None:
    """Parameterised multi-row INSERT in small batches (keeps warehouse parameter counts low)."""
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        cols = list(chunk[0])
        values, params = [], {}
        for n, row in enumerate(chunk):
            values.append("(" + ", ".join(f":{c}_{n}" for c in cols) + ")")
            params.update({f"{c}_{n}": row[c] for c in cols})
        query(f"INSERT INTO {T(table)} ({', '.join(cols)}) VALUES {', '.join(values)}", params)


def statements(path: Path) -> list[str]:
    """Split a Databricks SQL file into statements (each ends with ';' at end of line), skipping comment-only chunks."""
    text = path.read_text(encoding="utf-8").replace("{S}", f"{settings.uc_catalog}.{settings.uc_schema}")
    chunks = (s.strip() for s in re.split(r";\s*\n", text))
    return [c for c in chunks if any(l.strip() and not l.strip().startswith("--") for l in c.splitlines())]


def setup() -> None:
    """Create the Delta tables and UC functions (or their local Postgres mirror)."""
    if settings.warehouse_mode == "databricks":
        for f in ("tables.sql", "uc_functions.sql"):
            for stmt in statements(HERE / f):
                query(stmt)
    else:  # Postgres runs each whole script in one round trip (no params, so multi-statement is allowed)
        for f in ("local/tables_pg.sql", "local/functions_pg.sql"):
            lakebase.q((HERE / f).read_text(encoding="utf-8"))
