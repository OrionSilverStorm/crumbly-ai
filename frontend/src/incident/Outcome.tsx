// Execute/confirm (field-by-field match + stock on order vs on hand) and the resolved summary.
import { useState } from "react";
import { api, type J } from "../api";
import { gbp, hhmm, kg } from "../format";
import { Badge, Button, Card, Mark, Row, Stat, Title, Waiting } from "../ui";

/** Customers whose bake is covered now. */
function covered(snap: J) {
  const st = snap.incident.state;
  const ok = new Set((st.coverage_now ?? []).filter((s: J) => s.covered).map((s: J) => s.bake_time));
  return st.orders.map((o: J) => ({ ...o, ok: ok.has(o.bake_time) }));
}

export function Confirmation({ snap, reload }: { snap: J; reload: () => void }) {
  const pos: J[] = snap.purchase_orders;
  const inc = snap.incident, s = snap.stock;
  const [busy, setBusy] = useState("");
  if (!pos.length) return <><Title>No order placed yet.</Title><Waiting>Once an offer passes your rules (or you approve one), the purchase order appears here.</Waiting></>;
  const confirmedAll = pos.every((p) => ["confirmed", "accepted_adjusted", "received"].includes(p.status));
  const last = pos.filter((p) => p.confirmation).pop();
  const orders = covered(snap);
  return (
    <>
      <Title sub={last ? `${last.supplier} replied. We matched every field against what was agreed before accepting it.` : `Waiting for ${pos.map((p) => p.supplier).join(" and ")} to confirm.`}>
        {confirmedAll ? "Confirmation received — and checked." : "Order sent. Waiting for confirmation."}
      </Title>
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">{pos.map((p) => (
          <Card key={p.po_id}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h2 className="text-2xl font-bold">{p.po_id} · {p.supplier}</h2>
              {p.match_result ? <Badge tone={p.match_result.all_ok ? "sage" : "rose"}>{p.match_result.all_ok ? "✓" : "!"} {p.match_result.matched} of {p.match_result.of} match</Badge> : <Badge>Sent {hhmm(p.sent_at)} · awaiting reply</Badge>}</div>
            {p.match_result ? (
              <table className="w-full text-sm">
                <thead><tr className="bg-lilac text-left text-[11px] uppercase tracking-wide text-muted">{["Field", "Agreed", "Confirmed", "Match"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
                <tbody>{p.match_result.fields.map((f: J) => (
                  <tr key={f.field} className="border-b border-line last:border-0"><td className="px-3 py-3 font-medium">{f.field}</td><td className="px-3 text-muted">{f.agreed}</td>
                    <td className={`px-3 ${f.ok ? "text-muted" : "font-semibold text-rose-ink"}`}>{f.confirmed}</td>
                    <td className="px-3"><span className="flex items-center gap-2"><Mark ok={f.ok} />{f.ok ? "Match" : "Differs"}</span></td></tr>))}</tbody>
              </table>) : (
              <div className="text-sm">{p.lines.map((l: J) => <div key={l.quote_id}>{l.packs} × {kg(l.pack_size_kg)} {l.product} at {gbp(l.unit_price, 2)}, delivery {gbp(l.delivery, 2)}, total {gbp(l.total, 2)}, arriving {l.arrival}</div>)}</div>)}
            <p className="mt-3 text-xs text-muted">Anything that doesn’t match gets flagged to you — never quietly accepted.</p>
            {["confirmed", "accepted_adjusted"].includes(p.status) && (
              <div className="mt-3"><Button kind="secondary" disabled={!!busy} onClick={async () => { setBusy(p.po_id); await api(`/api/purchase-orders/${p.po_id}/received`, {}); setBusy(""); reload(); }}>
                Mark as received (checks it into stock)</Button></div>)}
            {p.status === "received" && <div className="mt-3"><Badge tone="sage">✓ Received and checked in</Badge></div>}
          </Card>))}
        </div>
        <Card tint="lilac" className="self-start">
          <h2 className="text-2xl font-bold">Updating your records</h2>
          <p className="mb-4 mt-1 text-sm text-muted">Flour on its way is tracked separately from flour on your shelf.</p>
          <div className="rounded-2xl bg-white p-4">
            <Row k="On hand" v={kg(s.on_hand_kg)} strong />
            <Row k={`On order${s.on_order_arrival ? ` · arriving ${hhmm(s.on_order_arrival)}` : ""}`} v={<span className="text-plum">+ {kg(s.on_order_kg)}</span>} strong />
            <div className="my-2 border-t border-line" />
            <Row k="Available for tomorrow" v={kg(s.available_kg)} strong />
            <Row k="Needed for tomorrow" v={kg(s.needed_kg)} strong />
            <Row k={s.spare_kg >= 0 ? "Spare" : "Short"} v={<span className={s.spare_kg >= 0 ? "text-sage-ink" : "text-rose-ink"}>{kg(Math.abs(s.spare_kg))}</span>} strong />
          </div>
          <p className="mt-3 rounded-2xl bg-white/60 p-3 text-xs text-plum">{s.on_order_kg > 0
            ? `Physical stock stays at ${kg(s.on_hand_kg)} until the delivery is received and checked in.`
            : `Delivery checked in: ${kg(s.on_hand_kg)} is now on your shelf.`}</p>
          <p className="mt-2 text-xs text-muted">coverage_by_slot · {hhmm(snap.events.filter((e: J) => e.type === "coverage_recalculated").pop()?.ts)}</p>
        </Card>
      </div>
      {confirmedAll && (
        <section className="mt-6 rounded-3xl bg-sage p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-2xl font-bold">{orders.every((o: J) => o.ok) ? `All ${orders.length} orders are covered again.` : `${orders.filter((o: J) => o.ok).length} of ${orders.length} orders covered.`}</h2>
              <p className="text-sm text-sage-ink">Coverage recalculated with the confirmed delivery.</p></div>
            <Button href={`#/incident/${inc.id}/summary`}>See summary →</Button>
          </div>
          <Customers orders={orders} />
        </section>)}
    </>
  );
}

/** Customer chips with a check or a cross. */
const Customers = ({ orders }: { orders: J[] }) => (
  <div className="mt-4 grid gap-3 md:grid-cols-3">{orders.map((o) => (
    <div key={o.order_id} className="flex items-center gap-3 rounded-2xl bg-white p-4 text-sm"><Mark ok={o.ok} /><span className="font-medium">{o.customer}</span><span className="text-xs text-muted">{o.description}</span></div>))}
  </div>
);

/** Friendly bun illustration for the summary hero. */
const Bun = () => (
  <svg viewBox="0 0 160 110" className="h-28 w-40" aria-hidden="true">
    <ellipse cx="70" cy="70" rx="58" ry="36" fill="#f3c46b" stroke="#5b4636" strokeWidth="3" />
    <path d="M40 50 q8 -10 14 2 M64 42 q8 -10 14 2 M88 46 q8 -10 14 2" stroke="#c98a2e" strokeWidth="4" fill="none" strokeLinecap="round" />
    <circle cx="55" cy="74" r="4" fill="#5b4636" /><circle cx="85" cy="74" r="4" fill="#5b4636" />
    <path d="M62 84 q8 7 16 0" stroke="#5b4636" strokeWidth="3" fill="none" strokeLinecap="round" />
    <circle cx="44" cy="82" r="6" fill="#f2a3a3" opacity=".7" /><circle cx="96" cy="82" r="6" fill="#f2a3a3" opacity=".7" />
    <path d="M128 60 q14 -6 20 10 q4 22 -14 26 q-18 2 -20 -16 q0 -14 14 -20z" fill="#f6ead7" stroke="#5b4636" strokeWidth="3" />
    <path d="M140 18 l3 8 8 3 -8 3 -3 8 -3 -8 -8 -3 8 -3z M14 30 l2 5 5 2 -5 2 -2 5 -2 -5 -5 -2 5 -2z" fill="#b9a2dc" />
  </svg>
);

export function Summary({ snap }: { snap: J }) {
  const inc = snap.incident, st = inc.state, s = snap.stock;
  const pos: J[] = snap.purchase_orders.filter((p: J) => ["confirmed", "accepted_adjusted", "received"].includes(p.status));
  if (!inc.status.startsWith("resolved")) return <><Title>Not sorted yet.</Title><Waiting>We’re still working on {inc.id}. The summary appears once a replacement is confirmed.</Waiting></>;
  const packs = pos.reduce((n, p) => n + (p.confirmation?.packs ?? p.lines[0].packs), 0);
  const total = pos.reduce((n, p) => n + Number(p.total), 0);
  const delivery = pos.reduce((n, p) => n + Number(p.lines[0].delivery), 0);
  const orders = covered(snap);
  // Follow-up exchange: from the first reply of a followed-up supplier to their answer (not the PO confirmation).
  const thread = snap.threads.find((t: J) => t.followups > 0);
  const ex = snap.emails.filter((m: J) => thread && m.supplier === thread.supplier && ["reply", "followup"].includes(m.kind));
  const fu = ex.findIndex((m: J) => m.kind === "followup");
  const followup = fu < 0 ? [] : ex.slice(0, fu + 2);
  const clean = (b: string) => b.split("\n").filter((l) => l.trim() && !/^Ref:|^Hello|^Hi,|^Thank|^Morning Loaf|^Thanks for your quote/.test(l.trim()) && !snap.threads.some((t: J) => t.supplier === l.trim())).map((l) => l.trim().replace(/^- /, "")).join(" ");
  return (
    <>
      <section className="flex items-center justify-between gap-6 rounded-3xl bg-butter p-8">
        <div>
          <Badge tone="white">✓ Replacement confirmed</Badge>
          <h1 className="mt-4 text-4xl font-extrabold">{inc.status === "resolved" ? "Tomorrow’s bake is back on track." : "Sorted, with a small gap you accepted."}</h1>
          <p className="mt-2 max-w-xl text-muted">A {st.kind ?? "cancelled"} {inc.ingredient.split(" ").pop()} delivery? Handled. Your replacement is confirmed and {orders.filter((o: J) => o.ok).length} of {orders.length} customer commitments have coverage.</p>
          <p className="mt-3 text-xs text-muted">{inc.id} · {inc.ingredient}</p>
        </div>
        <div className="hidden sm:block"><Bun /></div>
      </section>
      <div className="mt-6 flex flex-col divide-y divide-line rounded-3xl border border-line bg-white p-6 md:flex-row md:divide-x md:divide-y-0">
        <Stat label="Shortage" value={kg(inc.shortage_kg)} note="needed for tomorrow" />
        <Stat label="Replacement" value={kg(packs * st.pack_size_kg)} note={`${packs} bags · ${kg(st.pack_size_kg)} each`} tone="sage" />
        <Stat label="Total cost" value={gbp(total)} note={`including ${gbp(delivery)} delivery`} />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <Card>
          <h2 className="text-2xl font-bold">Your {inc.ingredient.split(" ").pop()} replacement</h2>
          {pos.map((p) => (
            <div key={p.po_id} className="mt-4">
              <div className="flex items-center justify-between"><div className="text-lg font-semibold">{p.supplier}</div><Badge tone={p.approved_by === "auto" ? "sage" : "plum"}>{p.approved_by === "auto" ? "Approved supplier" : "Approved by you"}</Badge></div>
              <div className="text-sm text-muted">{inc.ingredient} · {p.confirmation?.packs ?? p.lines[0].packs} × {kg(p.lines[0].pack_size_kg)} bags · {p.po_id}</div>
              <div className="mt-3 flex items-center gap-6 rounded-2xl bg-lilac p-4"><div><div className="text-xs text-muted">Arriving tomorrow</div>
                <div className="font-display text-2xl font-extrabold text-plum">{p.confirmation?.arrival_time ?? p.lines[0].arrival}</div></div>
                <div className="text-sm text-plum">Before production starts at {hhmm(inc.deadline)}</div></div>
            </div>))}
          <p className="mt-4 text-sm text-muted">Within your {gbp(snap.rules.spending_limit_per_incident)} limit.</p>
          <div className="mt-3"><Button href={`#/incident/${inc.id}/execute`}>View purchase order ↗</Button></div>
        </Card>
        <Card tint="lilac">
          <h2 className="text-2xl font-bold">The little details, sorted</h2>
          <p className="mb-3 mt-1 text-sm text-muted">We followed up, so you didn’t have to.</p>
          {followup.length ? followup.map((m: J) => (
            <div key={m.message_id} className={`mb-3 ${m.direction === "outbound" ? "rounded-2xl bg-white p-3" : ""}`}>
              <div className={`text-[11px] uppercase ${m.direction === "outbound" ? "text-plum" : "text-muted"}`}>{m.direction === "outbound" ? "Your sourcing agent" : m.supplier}</div>
              <p className="text-sm">“{clean(m.body)}”</p></div>)) : <p className="text-sm text-muted">Every quote came back complete.</p>}
          <div className="text-xs text-sage-ink">✓ Order confirmed and checked</div>
        </Card>
      </div>
      <section className="mt-6 rounded-3xl bg-sage p-6">
        <h2 className="text-2xl font-bold">{orders.every((o: J) => o.ok) ? "A good morning for everyone." : "Most of the morning is covered."}</h2>
        <p className="text-sm text-sage-ink">{orders.filter((o: J) => o.ok).length} customer commitments covered</p>
        <Customers orders={orders} />
      </section>
      <div className="mt-4 flex flex-wrap justify-between gap-3 text-xs text-muted">
        <span>{kg(s.on_hand_kg)} on hand + {kg(s.on_order_kg)} incoming. Physical stock updates only after receipt.</span>
        <a className="text-sm text-plum" href={`#/incident/${inc.id}/log`}>View full incident →</a>
      </div>
    </>
  );
}
