"""Test setup: fully offline (embedded Postgres, local warehouse mirror, in-memory mail, stub LLM, Linkup fixtures).
Env vars must be set before any backend module is imported."""
import os
import time

os.environ.update(
    DB_MODE="embedded", PGDATA_DIR=os.path.join(os.path.dirname(__file__), "..", "..", ".pgdata-test"), WAREHOUSE_MODE="local",
    LLM_PROVIDER="stub", EMAIL_MODE="memory", LINKUP_MODE="fixture", LINKUP_CACHE="0", TRACING_ENABLED="0",
    DEMO_TIME_SCALE="600", SUPPLIER_BOT_INPROCESS="0",
    EMAIL_BAKERY_ADDRESS="bakery@crumbly.test", EMAIL_SUPPLIERS_ADDRESS="suppliers@crumbly.test",
)

import pytest  # noqa: E402

from backend import store  # noqa: E402
from backend.agents import orchestrator  # noqa: E402
from backend.db.lakebase import q  # noqa: E402
from backend.demo.reset import reset  # noqa: E402
from backend.demo.supplier_bot import SupplierBot, send_cancellation  # noqa: E402
from backend.main import poll_inbox  # noqa: E402


@pytest.fixture
def scenario():
    """Reset to a scenario and return a driver that runs the demo loop (bot, inbox poll, timers) until a condition."""

    def start(name: str = "happy"):
        reset(name)
        bot = SupplierBot()

        def drive(cond, timeout: float = 40.0) -> bool:
            end = time.time() + timeout
            while time.time() < end:
                bot.poll_once()
                poll_inbox()
                orchestrator.tick()
                if cond():
                    return True
                time.sleep(0.05)
            return False

        return drive

    return start


def incident() -> dict | None:
    """The live (non-history) incident, if any."""
    rows = q("SELECT id FROM incidents WHERE NOT (state ? 'history') ORDER BY opened_at DESC LIMIT 1")
    return store.incident(rows[0]["id"]) if rows else None


def trigger() -> None:
    """Send the Millers Supply cancellation email."""
    send_cancellation()
