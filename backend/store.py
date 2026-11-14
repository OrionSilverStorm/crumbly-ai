"""Persistence helpers shared by agents and the execution service. Every step writes here immediately (crash-safe)."""
from decimal import Decimal

from backend.db.lakebase import one, q
from backend.dbx import sql
from backend.demo import clock
from backend.email.transport import Mail
from backend.tracing import active_trace_id

STAGES = ["detect", "understand", "investigate", "coordinate", "decide", "execute", "update"]


def jsonable(v):
    """Make values JSON-safe for JSONB evidence (Decimal -> str, datetimes -> ISO)."""
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def log_event(incident_id: str, stage: str, actor: str, type_: str, summary: str, evidence: dict | None = None) -> dict:
    """Append to the event log (with the current MLflow trace id as evidence)."""
    ev = jsonable(evidence or {})
    if (tid := active_trace_id()) and "trace_id" not in ev:
        ev["trace_id"] = tid
    return one(
        "INSERT INTO incident_events (incident_id, ts, stage, actor, type, summary, evidence) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
        [incident_id, clock.now(), stage, actor, type_, summary, ev],
    )


def incident(incident_id: str) -> dict | None:
    """One incident row."""
    return one("SELECT * FROM incidents WHERE id = %s", [incident_id])


def update_incident(incident_id: str, state: dict | None = None, **cols) -> None:
    """Update columns and shallow-merge `state` (latest computed artefacts) into the JSONB column."""
    sets, params = [], []
    for k, v in cols.items():
        sets.append(f"{k} = %s")
        params.append(v)
    if state:
        sets.append("state = state || %s")
        params.append(jsonable(state))
    if sets:
        q(f"UPDATE incidents SET {', '.join(sets)} WHERE id = %s", params + [incident_id])


def set_stage(incident_id: str, stage: str, status: str | None = None) -> None:
    """Move the incident's stepper (and optionally its status)."""
    update_incident(incident_id, stage=stage, **({"status": status} if status else {}))


def rules() -> dict:
    """The owner's hard rules (single row)."""
    return one("SELECT * FROM rules WHERE id = 1")


def preference(key: str) -> dict | None:
    """A confirmed owner preference, if any."""
    return one("SELECT * FROM preferences WHERE key = %s AND confirmed", [key])


def demo_state(key: str, default: str = "") -> str:
    """Demo key/value (e.g. current scenario)."""
    row = one("SELECT value FROM demo_state WHERE key = %s", [key])
    return row["value"] if row else default


def record_email(mail: Mail, direction: str, kind: str, incident_id=None, supplier=None, thread_id=None) -> None:
    """Store an email in Lakebase and in the bronze table (raw text for the ai_query pipeline). Idempotent."""
    row = one(
        "INSERT INTO email_messages (message_id, thread_id, incident_id, supplier, direction, kind, from_addr, to_addr,"
        " subject, body, in_reply_to, sent_or_received_at, processed) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (message_id) DO NOTHING RETURNING message_id",
        [mail.message_id, thread_id, incident_id, supplier, direction, kind, mail.from_addr, mail.to_addr,
         mail.subject, mail.body, mail.in_reply_to, mail.date or clock.now(), direction == "outbound"],
    )
    if row:  # first time we see it: mirror to bronze
        sql.insert("bronze_emails", [{
            "message_id": mail.message_id, "thread_id": thread_id, "incident_id": incident_id, "direction": direction,
            "from_addr": mail.from_addr, "to_addr": mail.to_addr, "subject": mail.subject, "body": mail.body,
            "received_at": mail.date or clock.now()}])


def thread_for(mail: Mail) -> dict | None:
    """Find the supplier thread a reply belongs to via In-Reply-To / References (never the From address)."""
    ids = [i for i in [mail.in_reply_to, *mail.references] if i]
    if not ids:
        return None
    known = one("SELECT thread_id, incident_id, supplier FROM email_messages WHERE message_id = ANY(%s) AND thread_id IS NOT NULL LIMIT 1", [ids])
    if not known:
        return None
    return one("SELECT * FROM supplier_threads WHERE incident_id = %s AND supplier = %s", [known["incident_id"], known["supplier"]])


def last_inbound(incident_id: str, supplier: str) -> Mail | None:
    """Most recent message in a supplier thread, to reply onto (keeps Gmail threading intact)."""
    r = one("SELECT * FROM email_messages WHERE incident_id = %s AND supplier = %s ORDER BY sent_or_received_at DESC LIMIT 1",
            [incident_id, supplier])
    if not r:
        return None
    refs = [x["message_id"] for x in q("SELECT message_id FROM email_messages WHERE incident_id = %s AND supplier = %s "
                                        "AND message_id <> %s ORDER BY sent_or_received_at", [incident_id, supplier, r["message_id"]])]
    return Mail(r["message_id"], r["from_addr"], r["to_addr"], r["subject"], r["body"], r["in_reply_to"], refs)


def sync_event_history() -> int:
    """Periodic copy of new Lakebase events into Delta (incident_events_history) for analytics. Returns rows copied."""
    import json

    last = sql.query(f"SELECT COALESCE(MAX(id), 0) AS id FROM {sql.T('incident_events_history')}")[0]["id"]
    rows = q("SELECT * FROM incident_events WHERE id > %s ORDER BY id LIMIT 500", [last])
    if rows:
        sql.insert("incident_events_history", [{**{k: r[k] for k in ("id", "incident_id", "ts", "stage", "actor", "type", "summary")},
                                                "evidence": json.dumps(r["evidence"])} for r in rows])
    return len(rows)
