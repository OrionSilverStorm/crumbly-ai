// Understand: needed / on hand / shortage / production start, orders at risk per bake slot, and how we worked it out.
import type { J } from "../api";
import { hhmm, kg } from "../format";
import { Badge, Button, Card, Row, Stat, Title, Waiting } from "../ui";

export default function Impact({ snap }: { snap: J }) {
  const inc = snap.incident, st = inc.state, s = st.shortage;
  if (!s) return <Waiting>Working out the damage…</Waiting>;
  const atRisk = st.orders.filter((o: J) => st.at_risk.includes(o.order_id));
  const slots: J[] = st.baseline_coverage ?? [];
  const r = snap.rules;
  return (
    <>
      <Title sub="Before contacting anyone, we checked your stock, recipes and tomorrow’s production. Every number below is calculated from your data, not estimated.">
        Here’s what tomorrow needs.
      </Title>
      <div className="flex flex-col divide-y divide-line rounded-3xl border border-line bg-white p-6 md:flex-row md:divide-x md:divide-y-0">
        <Stat label="Needed tomorrow" value={kg(s.needed_kg)} note={`across ${st.orders.length} orders`} />
        <Stat label="On hand" value={kg(s.on_hand_kg)} note={s.reserved_kg ? `${kg(s.reserved_kg)} reserved` : "none reserved elsewhere"} />
        <Stat label="Shortage" value={kg(s.shortage_kg)} note="to replace" tone="rose" />
        <Stat label="Production starts" value={hhmm(inc.deadline)} note="tomorrow" tone="plum" />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <div className="flex items-center justify-between"><h2 className="text-2xl font-bold">Orders at risk</h2><Badge tone="amber">{atRisk.length} customers affected</Badge></div>
          <p className="mb-4 mt-1 text-sm text-muted">Without a replacement, these bakes can’t go ahead in the morning.</p>
          {slots.map((sl) => (
            <div key={sl.bake_time} className="mb-3">
              {st.orders.filter((o: J) => o.bake_time === sl.bake_time).map((o: J) => (
                <div key={o.order_id} className={`flex items-center gap-3 rounded-2xl border p-4 ${sl.covered ? "border-line bg-white" : "border-amber bg-amber/40"}`}>
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-amber text-sm font-bold text-amber-ink">{sl.covered ? "✓" : "!"}</span>
                  <div className="flex-1"><div className="font-medium">{o.customer}</div><div className="text-xs text-muted">{o.description}</div></div>
                  <span className="font-semibold">{kg(o.kg_required)} {inc.ingredient.split(" ").pop()}</span>
                  <Badge tone="amber">Bake {hhmm(o.bake_time)}</Badge>
                </div>))}
              <div className="mt-1 pl-2 text-xs text-muted">By {hhmm(sl.bake_time)}: need {kg(sl.cumulative_required)} in total, have {kg(sl.cumulative_available)}</div>
            </div>))}
          <p className="text-xs text-muted">Customer details stay inside Crumbly. They’re never used in supplier searches.</p>
        </Card>
        <Card tint="lilac">
          <h2 className="text-2xl font-bold">How we worked it out</h2>
          <p className="mb-4 mt-1 text-sm text-muted">Models read the email. Code does the maths.</p>
          <div className="rounded-2xl bg-white p-4">
            <Row k={`Recipes for tomorrow’s ${st.orders.length} orders`} v={kg(s.needed_kg)} strong />
            <Row k={`On hand (inventory, ${hhmm(st.refreshed_at)})`} v={`− ${kg(s.on_hand_kg)}`} strong />
            <Row k="Reserved for other bakes" v={kg(s.reserved_kg)} strong />
            <Row k={`Cancelled delivery · ${inc.original_po}`} v={<span className="text-rose-ink">{kg(s.incoming_kg)} arriving</span>} strong />
            <div className="my-2 border-t border-line" />
            <Row k="Shortage" v={<span className="text-rose-ink">{kg(s.shortage_kg)}</span>} strong />
            <Row k={`Rounded up to ${kg(st.pack_size_kg)} bags`} v={<span className="text-plum">{st.packs} bags · {kg(st.packs * st.pack_size_kg)}</span>} strong />
          </div>
          <p className="mt-3 text-xs text-muted">calculate_shortage · get_affected_orders · coverage_by_slot · data refreshed {hhmm(st.refreshed_at)}</p>
        </Card>
      </div>
      <section className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-3xl bg-sage p-5">
        <div><div className="font-semibold">Next: asking your approved suppliers</div>
          <div className="text-sm text-sage-ink">{st.packs} × {kg(st.pack_size_kg)} {inc.ingredient}, delivered to {r.postcode_area} between {r.delivery_window_start} and {r.delivery_window_end} tomorrow.</div></div>
        <Button href={`#/incident/${inc.id}/investigate`}>Watch sourcing →</Button>
      </section>
    </>
  );
}
