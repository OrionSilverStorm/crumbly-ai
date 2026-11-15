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

import logging  # noqa: E402

import pytest  # noqa: E402

# The embedded Postgres logs from an atexit hook after pytest has closed the streams, which prints a wall of
# harmless "--- Logging error ---" tracebacks after the result line. Keep the end of a test run clean.
logging.raiseExceptions = False
logging.getLogger("pgserver").setLevel(logging.WARNING)

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


# ---------------------------------------------------------------- judge-friendly summary
# Plain-English claim for each test, grouped by what it proves. Printed after every run (with a ✓ or ✗ from the real
# outcome) so the result reads as evidence in the demo video, not as a list of function names.
CLAIMS: dict[str, list[tuple[str, str]]] = {
    "The maths is done by code over your data (Databricks UC functions)": [
        ("test_calculate_shortage_is_160_after_cancellation", "Cancellation leaves 200 kg needed − 40 kg on hand = 160 kg short"),
        ("test_pack_rounding", "160 kg rounds up to seven 25 kg bags, never down"),
        ("test_coverage_by_slot_respects_arrival_buffer", "Flour arriving after a bake's safety buffer does not count for that bake"),
        ("test_affected_orders_and_reliability_come_from_sql", "Affected customers and supplier reliability come from SQL, not the model"),
        ("test_missing_fields_detected_by_code", "Missing delivery charge or arrival time, or a total that doesn't add up, is caught by code, never guessed"),
    ],
    "The agents recover the bake end to end (real email loop, scripted suppliers)": [
        ("test_happy_path_end_to_end", "Happy path: cancellation → 4 suppliers asked → follow-up → PO-0087 to Borough Mill £165, confirmed"),
        ("test_short_confirm_creates_decision_and_top_up_passes_every_rule", "Supplier confirms 6 bags, not 7: refused, one-bag top-up offered and passes every rule"),
        ("test_new_supplier_wins_needs_owner_approval", "A new supplier found by Linkup wins, but nothing is bought until the owner approves"),
        ("test_owner_rejects_replans_with_split_and_suggests_rule", "Owner says 'too expensive': Crumbly replans a split order and suggests a rule"),
        ("test_linkup_verification_fetches_discovered_supplier_page", "Linkup claims are checked against the supplier's own web page"),
    ],
    "Guardrails: Crumbly cannot overspend, double-order or leak data": [
        ("test_execution_checks_pass_for_borough", "A qualifying offer passes every purchasing rule and may be auto-ordered"),
        ("test_execution_checks_fail_reasons", "Late, outside the delivery window, too few bags or over the limit each fail; a new supplier needs approval"),
        ("test_confirmation_matching_never_accepts_a_mismatch", "A confirmation that differs from the PO is never accepted"),
        ("test_rerunning_steps_never_sends_a_second_po", "Re-running a step, even after a crash, never sends a second PO"),
        ("test_crash_resume_continues_instead_of_restarting", "After a crash the incident resumes where it left off, without re-sending emails"),
        ("test_linkup_queries_never_contain_customer_or_recipe_data", "Web searches never contain customer names, orders or recipes"),
        ("test_marking_delivery_received_moves_flour_from_on_order_to_on_hand", "Checking a delivery in moves it from 'on order' to 'on hand', once"),
        ("test_unknown_incident_export_is_404_not_500", "Unknown incidents return a clean 404"),
    ],
    "The help assistant answers from live data and never acts on its own": [
        ("test_assistant_answers_from_tools", "'Is tomorrow OK?' is answered with real numbers (175 kg, 05:00, 3 of 3 bakes)"),
        ("test_assistant_routes_common_owner_questions", "Status, cost, safety and glossary questions each reach the right tool"),
        ("test_assistant_handles_the_words_used_in_the_demo", "Understands the demo's own words: 'what's happening', 'top-up', 'mismatch'"),
        ("test_glossary_prefers_the_specific_term", "Explains the most specific term ('confirmation mismatch' → mismatch)"),
        ("test_supplier_names_ending_in_a_full_stop_are_not_doubled", "Answers read cleanly ('Thames Grain Co.' never becomes 'Co..')"),
        ("test_assistant_too_expensive_prepares_card_and_never_orders", "'Too expensive' prepares a button for the owner; it never orders by itself"),
    ],
    "Configuration is honest about what is live": [
        ("test_config_describes_demo_modes_honestly", "The footer states which integrations are live and which are simulated"),
        ("test_blank_optional_environment_values_use_safe_defaults", "Blank settings fall back to safe offline defaults"),
    ],
}


def pytest_terminal_summary(terminalreporter):
    outcome: dict[str, str] = {}
    for status in ("passed", "failed", "error", "skipped"):
        for rep in terminalreporter.stats.get(status, []):
            if getattr(rep, "when", "call") in ("call", "setup") and hasattr(rep, "nodeid"):
                name = rep.nodeid.split("::")[-1]
                if outcome.get(name) not in ("failed", "error"):
                    outcome[name] = status
    if not outcome:
        return
    tw = terminalreporter
    tw.write_sep("=", "What these tests prove")
    known = set()
    for section, claims in CLAIMS.items():
        ran = [(n, c) for n, c in claims if n in outcome]
        known |= {n for n, _ in claims}
        if not ran:
            continue
        tw.write_line("")
        tw.write_line(section, bold=True)
        for name, claim in ran:
            ok = outcome[name] == "passed"
            tw.write_line(f"  {'✓' if ok else '✗'} {claim}", green=ok, red=not ok)
    extra = sorted(n for n in outcome if n not in known)
    if extra:
        tw.write_line("")
        tw.write_line("Other checks", bold=True)
        for name in extra:
            ok = outcome[name] == "passed"
            tw.write_line(f"  {'✓' if ok else '✗'} {name.removeprefix('test_').replace('_', ' ')}", green=ok, red=not ok)
    passed = sum(v == "passed" for v in outcome.values())
    tw.write_line("")
    tw.write_line(f"{passed} of {len(outcome)} checks passed · fully offline: embedded Postgres, local Databricks-schema "
                  "mirror, in-memory email, deterministic extraction, Linkup fixtures", bold=True)
