"""Pre-recording smoke test: drive scenarios through the RUNNING app's HTTP API, exactly as the demo buttons do.

    python -m backend.demo.smoke                      # all four scenarios once
    python -m backend.demo.smoke happy happy happy    # P0 check: three happy runs with timings

Owner decisions are answered the way the video does (approve the top-up, reject Borough Mill as too expensive,
approve the new supplier). Needs `make dev` running; nothing here talks to real suppliers.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("CRUMBLY_URL", "http://127.0.0.1:8000")


def call(path: str, body: dict | None = None) -> dict | list:
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"content-type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def snap() -> dict | None:
    live = [i for i in call("/api/incidents") if not i.get("history")]
    return call(f"/api/incidents/{live[0]['id']}") if live else None


def wait(cond, timeout: float, what: str):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if value := cond():
                return value
        except (TimeoutError, urllib.error.URLError) as e:  # one slow status poll is not a failed run; keep polling
            print(f"     (slow status poll, retrying: {e})")
        time.sleep(1)
    s = snap()
    stuck = f"{s['incident']['status']}/{s['incident']['stage']}" if s else "no incident"
    raise TimeoutError(f"no {what} after {timeout:.0f}s (incident is {stuck})")


def open_decision(kind: str, not_id: int | None = None):
    s = snap()
    return s and next((d for d in s["decisions"] if d["kind"] == kind and d["status"] == "open" and d["id"] != not_id), None)


def resolved():
    s = snap()
    return s if s and s["incident"]["status"] in ("resolved", "resolved_partial") else None


def decide(decision: dict, option: str) -> None:
    out = call(f"/api/decisions/{decision['id']}", {"option": option})
    if not out.get("ok"):
        raise RuntimeError(f"decision {option!r} refused: {out.get('reason')}")


def run(scenario: str) -> tuple[dict, str]:
    call("/api/demo/reset", {"scenario": scenario})
    call("/api/demo/send-cancellation", {})
    note = ""
    if scenario == "short_confirm":
        d = wait(lambda: open_decision("confirmation_mismatch"), 240, "confirmation-mismatch decision")
        decide(d, "top_up")
        note = "6-bag mismatch refused, 1-bag top-up approved"
    elif scenario == "owner_rejects":
        d = wait(lambda: open_decision("approve_order"), 240, "approval decision")
        s = snap()
        line = s["incident"]["state"]["proposal"]["lines"][0]
        call("/api/feedback", {"incident_id": s["incident"]["id"], "reason": "too_expensive", "note": "Bit steep",
                               "quote_id": line.get("quote_id"), "supplier": line.get("supplier")})
        decide(wait(lambda: open_decision("approve_order", not_id=d["id"]), 60, "replanned decision"), "approve")
        note = "rejected as too expensive, split order approved"
    elif scenario == "new_supplier_wins":
        decide(wait(lambda: open_decision("approve_order"), 240, "approval decision"), "approve")
        note = "new supplier approved by owner"
    return wait(resolved, 240, "resolution"), note


def main(scenarios: list[str]) -> int:
    try:
        cfg = call("/api/config")
    except (urllib.error.URLError, ConnectionError):
        print(f"Crumbly isn't running at {BASE}. Start it with `make dev` first.")
        return 2
    if cfg["time_scale"] < 10:
        print(f"! Demo time is {cfg['time_scale']:g}x, so suppliers reply in real minutes. Restart with DEMO_TIME_SCALE=60.")
        return 2
    print(f"Crumbly at {BASE} · {cfg['time_scale']:g}x demo time · {cfg['footer']}\n")
    failures = 0
    for name in scenarios:
        if name == "new_supplier_wins" and not cfg["scenario_availability"]["new_supplier_wins"]["enabled"]:
            print(f"  -  {name:<18} skipped: needs LINKUP_MODE=fixture")
            continue
        t0 = time.time()
        try:
            s, note = run(name)
            pos = ", ".join(f"{p['po_id']} {p['supplier']} £{float(p['total']):.0f}" for p in s["purchase_orders"])
            covered = sum(c["covered"] for c in s["incident"]["state"].get("coverage_now", []))
            total = len(s["incident"]["state"].get("coverage_now", []))
            print(f"  ✓  {name:<18} {time.time() - t0:5.0f}s  {covered}/{total} bakes covered · {pos}" + (f" · {note}" if note else ""))
        except Exception as e:  # report and carry on with the next scenario
            failures += 1
            print(f"  ✗  {name:<18} {time.time() - t0:5.0f}s  {type(e).__name__}: {e}")
    print(f"\n{len(scenarios) - failures} of {len(scenarios)} runs recovered tomorrow's bake.")
    return 1 if failures else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:] or ["happy", "short_confirm", "owner_rejects", "new_supplier_wins"]))
