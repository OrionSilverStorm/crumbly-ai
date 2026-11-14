// Incidents home: new-incident banner with the matched email, what happens next, metrics strip, recent incidents.
import { api, type J, useApi } from "../api";
import { gbp, hhmm, when } from "../format";
import { stepsDone, STAGES } from "../stages";
import { Badge, Button, Card, Title, Waiting } from "../ui";

export default function Home() {
  const { data: incidents } = useApi("/api/incidents", 3000);
  const { data: decisions, reload } = useApi("/api/decisions", 3000);
  // The open incident, else the most recent live (non-seeded) one.
  const current = (incidents ?? []).find((i: J) => !i.status.startsWith("resolved")) ?? (incidents ?? []).find((i: J) => !i.history);
  const { data: snap } = useApi(current ? `/api/incidents/${current.id}` : null, 3000);
  const openCount = (incidents ?? []).filter((i: J) => !i.status.startsWith("resolved")).length;

  return (
    <>
      <Title sub={openCount ? `${openCount} open incident · Your agents spotted it in your inbox and started working on it straight away.` : "Crumbly is watching your inbox for supplier problems."}>
        {openCount ? "Something came up. We’re already on it." : "All quiet. Nothing needs you."}
      </Title>
      {snap && <Banner snap={snap} />}
      <RuleSuggestions decisions={(decisions ?? []).filter((d: J) => d.kind === "rule_suggestion")} reload={reload} />
      {snap && <Next snap={snap} />}
      <Metrics />
      <Card className="mt-6">
        <div className="mb-4 flex items-baseline justify-between"><h2 className="text-2xl font-bold">Recent incidents</h2><span className="text-xs text-muted">Last 60 days</span></div>
        {!incidents ? <Waiting>Loading…</Waiting> : (
          <table className="w-full text-sm">
            <thead><tr className="bg-lilac text-left text-[11px] uppercase tracking-wide text-muted">
              {["Incident", "Ingredient", "What happened", "Opened", "Status"].map((h) => <th key={h} className="px-3 py-2 font-medium first:rounded-l-xl last:rounded-r-xl">{h}</th>)}
            </tr></thead>
            <tbody>{incidents.map((i: J) => (
              <tr key={i.id} className="border-b border-line last:border-0 hover:bg-lilac/50">
                <td className="px-3 py-4"><a className="font-medium text-plum" href={`#/incident/${i.id}`}>{i.id}</a></td>
                <td className="px-3 capitalize">{i.ingredient}</td>
                <td className="px-3 text-muted">{i.summary}</td>
                <td className="px-3 text-muted">{when(i.opened_at)}</td>
                <td className="px-3"><Status i={i} /></td>
              </tr>))}</tbody>
          </table>)}
      </Card>
    </>
  );
}

/** Status pill for an incident row. */
export function Status({ i }: { i: J }) {
  if (i.status === "resolved") return <Badge tone="sage">✓ Resolved</Badge>;
  if (i.status === "resolved_partial") return <Badge tone="amber">Resolved with a shortfall</Badge>;
  if (i.status === "needs_owner" || Number(i.open_decisions) > 0) return <Badge tone="rose">! Needs you</Badge>;
  return <Badge tone="plum">Agents working</Badge>;
}

/** The yellow banner: what happened + the matched email. */
function Banner({ snap }: { snap: J }) {
  const inc = snap.incident, st = inc.state, t = st.trigger ?? {};
  const done = stepsDone(inc);
  return (
    <section className="grid gap-6 rounded-3xl bg-butter p-6 md:grid-cols-[1.4fr_1fr]">
      <div>
        <div className="flex gap-2"><Badge tone="white"><span className="text-rose-ink">●</span> {inc.status.startsWith("resolved") ? "Incident" : "New incident"} · {hhmm(inc.opened_at)}</Badge><Badge tone="white">{inc.id}</Badge></div>
        <h2 className="mt-4 text-3xl font-extrabold">Your {inc.ingredient.split(" ").pop()} delivery was {st.kind ?? "cancelled"}.</h2>
        <p className="mt-3 text-muted">{st.original_supplier} can’t deliver tomorrow’s {inc.ingredient}. We matched their email to {inc.original_po} and opened an incident before you had to lift a finger.</p>
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <Button href={`#/incident/${inc.id}`}>Open incident →</Button>
          <span className="text-xs text-muted">{inc.status.startsWith("resolved") ? "Sorted" : "Agents working"} · {done} of {STAGES.length} steps done</span>
        </div>
      </div>
      <div className="rounded-2xl bg-white p-5 text-sm">
        <div className="flex gap-2"><span className="w-16 text-[10px] uppercase text-muted">From</span><span>{t.from}</span></div>
        <div className="mt-1 flex gap-2"><span className="w-16 text-[10px] uppercase text-muted">Subject</span><span>{t.subject}</span></div>
        <p className="mt-3 border-t border-line pt-3 whitespace-pre-line">“{(t.body ?? "").trim().split("\n\n").slice(1, -1).join(" ") || t.body}”</p>
        <div className="mt-3 flex flex-wrap gap-2"><Badge>Message stored</Badge><Badge>Thread linked</Badge><Badge tone="sage">Matched to {inc.original_po}</Badge></div>
      </div>
    </section>
  );
}

/** Three plain-English steps with live status. */
function Next({ snap }: { snap: J }) {
  const inc = snap.incident, done = stepsDone(inc), r = snap.rules;
  const first = snap.events.find((e: J) => e.type === "shortage_calculated");
  const secs = first ? Math.max(1, Math.round((Date.parse(first.ts) - Date.parse(inc.opened_at)) / 1000)) : null;
  const items = [
    { title: "Work out the damage", text: "Checking stock, recipes and tomorrow’s orders to see exactly how much is missing.", state: done >= 2 ? `✓ Done in ${secs ?? 1} s` : "In progress" },
    { title: "Ask around", text: `Contacting your approved suppliers for a replacement that arrives before ${hhmm(inc.deadline)}.`, state: done >= 4 ? "✓ Done" : done >= 2 ? "In progress" : "Waiting" },
    { title: "Stay in your rules", text: `Orders within your ${gbp(r.spending_limit_per_incident)} limit go ahead. Anything else comes to you first.`, state: done >= 5 ? "✓ Done" : done >= 4 ? "In progress" : "Waiting" },
  ];
  return (
    <>
      <h2 className="mb-3 mt-8 text-xl font-bold">What happens next</h2>
      <div className="grid gap-4 md:grid-cols-3">
        {items.map((it, n) => (
          <Card key={it.title} className="!p-5">
            <div className="flex items-center gap-2"><span className="font-display text-lg font-bold text-plum">{n + 1}</span>
              <Badge tone={it.state.startsWith("✓") ? "sage" : it.state === "In progress" ? "plum" : "grey"}>{it.state}</Badge></div>
            <div className="mt-2 font-semibold">{it.title}</div><p className="mt-1 text-sm text-muted">{it.text}</p>
          </Card>))}
      </div>
    </>
  );
}

/** Metrics strip computed by /api/metrics (SQL over Lakebase + Delta). */
function Metrics() {
  const { data: m } = useApi("/api/metrics", 5000);
  if (!m) return null;
  const tiles = [
    ["Average time to recover", `${m.avg_time_to_recover_min} min`, "email in → replacement confirmed"],
    ["Customer orders protected", `${m.orders_protected}`, `worth ${gbp(m.orders_value)}`],
    ["Handled without you", `${m.handled_without_owner} of ${m.incidents_resolved}`, "resolved incidents"],
    ["Extra cost vs normal", `${Number(m.extra_cost) >= 0 ? "+" : "−"}${gbp(Math.abs(Number(m.extra_cost)))}`, "replacements vs original orders"],
  ];
  return (
    <div className="mt-6 grid gap-4 rounded-3xl border border-line bg-white p-5 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map(([k, v, n]) => <div key={k}><div className="text-xs text-muted">{k}</div><div className="font-display text-2xl font-extrabold">{v}</div><div className="text-xs text-muted">{n}</div></div>)}
    </div>
  );
}

/** Rule suggestions: the model never changes rules; only the owner's click does. */
function RuleSuggestions({ decisions, reload }: { decisions: J[]; reload: () => void }) {
  if (!decisions.length) return null;
  return (
    <div className="mt-6 space-y-3">{decisions.map((d) => (
      <Card key={d.id} tint="lilac">
        <Badge tone="white">Suggested rule</Badge>
        <h3 className="mt-2 text-xl font-bold">{d.title}</h3>
        <p className="mt-1 text-sm text-muted">You’ve said “too expensive” {d.context.times} times for {d.context.value.ingredient} over {gbp(d.context.value.amount)}. Nothing changes unless you say yes.</p>
        <div className="mt-4 flex gap-3">
          <Button onClick={() => api(`/api/decisions/${d.id}`, { option: "accept" }).then(reload)}>Yes, make it a rule</Button>
          <Button kind="secondary" onClick={() => api(`/api/decisions/${d.id}`, { option: "decline" }).then(reload)}>No thanks</Button>
        </div>
      </Card>))}
    </div>
  );
}

