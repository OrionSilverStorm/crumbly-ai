"""FastAPI app: serves /api and the built frontend; runs the email poller, timers and (optionally) the supplier bot."""
import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import feedback, store, tracing, views
from backend.agents import orchestrator
from backend.assistant import chat as assistant
from backend.config import ROOT, settings
from backend.db import lakebase
from backend.db.lakebase import one, q
from backend.dbx import sql
from backend.demo import reset as demo_reset
from backend.demo.supplier_bot import SupplierBot, send_cancellation
from backend.email.outbox import bakery
from backend.execution import service as ex

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("crumbly")
DIST = ROOT / "frontend" / "dist"
stop = threading.Event()


def _loop(name: str, every: float, fn) -> None:
    """Run fn forever in a daemon thread; errors are logged, never fatal."""
    def run():
        while not stop.is_set():
            try:
                fn()
            except Exception:
                log.exception("%s failed", name)
            stop.wait(every)
    threading.Thread(target=run, daemon=True, name=name).start()


def poll_inbox() -> None:
    """IMAP (or in-memory) poll: process each new email, then acknowledge it (crash before ack = reprocessed safely)."""
    for mail in bakery().fetch_new():
        orchestrator.on_inbound(mail)
        bakery().ack(mail)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup: migrations, warehouse objects (local mode), first-run seed, tracing, resume, background loops."""
    lakebase.migrate()
    if settings.warehouse_mode == "local":
        sql.setup()
    if not store.rules():
        demo_reset.reset()
    tracing.init()
    orchestrator.resume()  # a crash resumes, it doesn't restart
    _loop("poller", 1.0 if settings.email_mode == "memory" else settings.poll_seconds, poll_inbox)
    _loop("timers", 1.0, orchestrator.tick)
    if settings.bot_inprocess:
        threading.Thread(target=SupplierBot().run, args=(stop,), daemon=True, name="supplier-bot").start()
    yield
    stop.set()


app = FastAPI(title="Crumbly", lifespan=lifespan)


async def _io(fn, *a, **kw):
    """Run blocking DB/warehouse work off the event loop."""
    return await asyncio.to_thread(fn, *a, **kw)


# ---------------------------------------------------------------- read endpoints

@app.get("/api/config")
async def get_config():
    return await _io(views.config)


@app.get("/api/incidents")
async def list_incidents():
    return await _io(views.incidents)


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    snap = await _io(views.snapshot, incident_id)
    if not snap:
        raise HTTPException(404, "No such incident")
    return snap


@app.get("/api/incidents/{incident_id}/stream")
async def stream(incident_id: str):
    """Server-Sent Events: emits the latest event id whenever the incident changes (the UI then refetches)."""
    async def gen():
        last = None
        while True:
            row = await _io(one, "SELECT COALESCE(MAX(e.id), 0) AS id, (SELECT md5(i.status || i.stage || i.state::text) FROM incidents i "
                                 "WHERE i.id = %s) AS h FROM incident_events e WHERE e.incident_id = %s", [incident_id, incident_id])
            sig = f"{row['id']}:{row['h']}"
            if sig != last:
                last = sig
                yield f"data: {json.dumps({'event_id': row['id']})}\n\n"
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/incidents/{incident_id}/export")
async def export(incident_id: str):
    """The append-only event log as downloadable JSON."""
    snap = await _io(views.snapshot, incident_id)
    body = json.dumps({"incident": snap["incident"], "events": snap["events"]}, indent=2, default=str)
    return JSONResponse(json.loads(body), headers={"Content-Disposition": f'attachment; filename="{incident_id}-events.json"'})


@app.get("/api/metrics")
async def metrics():
    return await _io(views.metrics)


@app.get("/api/suppliers")
async def suppliers():
    return await _io(views.suppliers)


@app.get("/api/tables/{name}")
async def table(name: Literal["production_orders", "inventory", "incoming_deliveries", "approved_products"]):
    return await _io(views.table, name)


@app.get("/api/decisions")
async def open_decisions():
    """Open decisions not tied to one incident (e.g. rule suggestions) plus all open ones."""
    return store.jsonable(await _io(q, "SELECT * FROM pending_decisions WHERE status = 'open' ORDER BY id DESC"))


# ---------------------------------------------------------------- owner actions (all go through the execution service)

class DecisionIn(BaseModel):
    option: str


@app.post("/api/decisions/{decision_id}")
async def decide(decision_id: int, body: DecisionIn):
    return await _io(orchestrator.resolve_decision, decision_id, body.option)


class FeedbackIn(BaseModel):
    incident_id: str
    reason: Literal["too_expensive", "dont_trust_supplier", "later_is_fine", "other"]
    note: str | None = None
    quote_id: int | None = None
    supplier: str | None = None


@app.post("/api/feedback")
async def give_feedback(body: FeedbackIn):
    def run():
        with orchestrator.lock:
            return store.jsonable(feedback.submit(body.incident_id, body.reason, body.note, body.quote_id, body.supplier))
    return await _io(run)


class RulesIn(BaseModel):
    spending_limit_per_incident: float | None = None
    auto_order_enabled: bool | None = None
    arrival_buffer_min: int | None = None
    delivery_window_start: str | None = None
    delivery_window_end: str | None = None
    chase_after_min: int | None = None
    drop_after_min: int | None = None


@app.get("/api/rules")
async def get_rules():
    return await _io(views.rules_summary)


@app.put("/api/rules")
async def put_rules(body: RulesIn):
    """Owner edits hard rules (the only way they change)."""
    changes = body.model_dump(exclude_none=True)
    if changes:
        await _io(q, "UPDATE rules SET " + ", ".join(f"{k} = %({k})s" for k in changes) + " WHERE id = 1", changes)
    return await _io(views.rules_summary)


@app.post("/api/purchase-orders/{po_id}/received")
async def received(po_id: str):
    return store.jsonable(await _io(ex.mark_received, po_id))


class ChatIn(BaseModel):
    text: str
    page: str = "home"
    incident_id: str | None = None


@app.post("/api/assistant/chat")
async def assistant_chat(body: ChatIn):
    return store.jsonable(await _io(assistant.chat, body.text, body.page, body.incident_id))


@app.get("/api/assistant/history")
async def assistant_history():
    return store.jsonable(await _io(q, "SELECT * FROM assistant_messages WHERE owner_id = %s ORDER BY id", [settings.owner_id]))


# ---------------------------------------------------------------- demo controls

class ResetIn(BaseModel):
    scenario: Literal["happy", "short_confirm", "new_supplier_wins", "owner_rejects"] = "happy"


@app.post("/api/demo/reset")
async def reset(body: ResetIn):
    def run():
        with orchestrator.lock:  # never reset in the middle of a step
            return demo_reset.reset(body.scenario)
    return {"scenario": await _io(run)}


@app.post("/api/demo/send-cancellation")
async def cancellation():
    """Sends the real Millers Supply cancellation email to the bakery inbox."""
    mail = await _io(send_cancellation)
    return {"message_id": mail.message_id, "to": mail.to_addr}


# ---------------------------------------------------------------- frontend (built by Vite)

if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    """Serve the single-page app (hash routing, so every non-API path returns index.html)."""
    f = DIST / path
    if path and f.is_file():
        return FileResponse(f)
    if (DIST / "index.html").exists():
        return FileResponse(DIST / "index.html")
    return JSONResponse({"detail": "Frontend not built yet: run `make build`"}, status_code=404)
