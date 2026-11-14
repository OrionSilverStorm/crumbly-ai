// Decide (checks + ranking + outcome), Needs your decision (mismatch options and other open decisions), feedback dialog.
import { useState } from "react";
import { api, type J } from "../api";
import { gbp, hhmm, kg, list, pct } from "../format";
import { Badge, Button, Card, Mark, Title, Waiting } from "../ui";

const REASONS: [string, string][] = [["too_expensive", "Too expensive"], ["dont_trust_supplier", "I don’t trust this supplier"],
  ["later_is_fine", "Later is fine for this bake"], ["other", "Something else"]];

/** "Not this one" button + dialog: reason + optional note -> /api/feedback (the agent re-plans immediately). */
export function NotThisOne({ incident, plan, onDone }: { incident: string; plan: J; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (reason: string) => {
    setBusy(true);
    try { await api("/api/feedback", { incident_id: incident, reason, note: note || null, quote_id: plan.lines[0]?.quote_id, supplier: plan.suppliers[0] }); onDone(); }
    finally { setBusy(false); setOpen(false); }
  };
  if (!open) return <button className="min-h-10 rounded-full border border-line bg-white px-4 text-xs font-medium text-plum hover:bg-lilac" onClick={() => setOpen(true)}>Not this one</button>;
  return (
    <div role="dialog" aria-label="Why not this one?" className="mt-3 w-full rounded-2xl border border-line bg-white p-4">
      <div className="mb-2 text-sm font-semibold">Why not {list(plan.suppliers)}?</div>
      <div className="grid gap-2 sm:grid-cols-2">{REASONS.map(([id, label]) =>
        <button key={id} disabled={busy} onClick={() => send(id)} className="min-h-12 rounded-xl bg-lilac px-3 text-left text-sm text-plum hover:bg-lilac-2">{label}</button>)}</div>
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note (optional)" className="mt-3 w-full rounded-xl border border-line p-3 text-sm" />
      <button className="mt-2 text-xs text-muted underline" onClick={() => setOpen(false)}>Cancel</button>
    </div>
  );
}

/** One ranked offer row. */
function Offer({ p, n, incident, reload, top }: { p: J; n?: number; incident: string; reload: () => void; top?: boolean }) {
  const rel = p.reliability ?? {};
  const relText = p.lines.length > 1 ? `Split: ${p.lines.map((l: J) => `${l.packs} bags from ${l.supplier}`).join(" + ")}`
    : rel.deliveries ? `${pct(rel.on_time_rate)} on time · ${pct(rel.quantity_accuracy)} right quantity · ${rel.deliveries} deliveries` : "No delivery history yet · new supplier";
  return (
    <div className={`rounded-2xl p-4 ${top ? "bg-white" : "border border-line"}`}>
      <div className="flex items-start gap-3">
        {n !== undefined && <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm ${top ? "bg-plum text-white" : "bg-white"}`}>{n}</span>}
        <div className="flex-1"><div className="font-semibold">{list(p.suppliers)}</div><div className="text-xs text-muted">{relText}</div></div>
        <div className="text-right"><div className="font-display text-xl font-extrabold">{gbp(p.total)}</div>
          {p.qualifies ? <Badge tone="sage">✓ Qualifies{p.needs_owner.length ? " · needs your OK" : ""}</Badge> : <Badge tone="rose">{p.reasons.join(" · ")}</Badge>}</div>
      </div>
      {p.qualifies && <div className="mt-2 flex justify-end"><NotThisOne incident={incident} plan={p} onDone={reload} /></div>}
    </div>
  );
}

export function Decide({ snap, reload }: { snap: J; reload: () => void }) {
  const inc = snap.incident, st = inc.state;
  const proposal = st.proposal, ranking = st.ranking;
  const approve = snap.decisions.find((d: J) => d.status === "open" && ["approve_order", "no_qualifying", "relax_slot"].includes(d.kind));
  const pos = snap.purchase_orders;
  const picked = snap.events.filter((e: J) => e.type === "offer_selected").pop();
  if (!ranking) return <><Title>Weighing up the offers.</Title><Waiting>Waiting for complete quotes. We decide as soon as no slower reply could beat the best offer.</Waiting></>;
  const passed = proposal?.checks.filter((c: J) => c.status === "pass").length;
  return (
    <>
      <Title sub={proposal ? `Updated ${hhmm(picked?.ts)}: ${gbp(proposal.total)} in total for ${kg(proposal.kg)}. Here’s how we checked it.` : "No single offer passes every rule yet."}>
        {proposal ? (proposal.qualifies && !proposal.needs_owner.length ? `${list(proposal.suppliers)} ticks every box.` : `${list(proposal.suppliers)} is our best option.`) : "Still weighing up the offers."}
      </Title>
      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <Card>
          <div className="mb-3 flex items-center justify-between"><h2 className="text-2xl font-bold">Every check, done by code</h2>
            {proposal && <Badge tone={passed === proposal.checks.length ? "sage" : "amber"}>{passed} of {proposal.checks.length} passed</Badge>}</div>
          {proposal ? proposal.checks.map((c: J) => (
            <div key={c.id} className="flex items-center gap-3 border-b border-line py-3 text-sm last:border-0">
              <Mark ok={c.status === "pass" ? true : c.status === "approval" ? "warn" : false} /><span className="flex-1">{c.label}</span><span className="text-right text-muted">{c.detail}</span>
            </div>)) : <Waiting>Checks run on every offer as soon as it’s complete.</Waiting>}
        </Card>
        <Card tint="lilac">
          <h2 className="text-2xl font-bold">How the offers rank</h2>
          <p className="mb-4 mt-1 text-sm text-muted">Reliability first, then cost — a cheap order that turns up late doesn’t help.</p>
          <div className="space-y-3">
            {ranking.qualifying.map((p: J, i: number) => <Offer key={p.signature} p={p} n={i + 1} top={i === 0} incident={inc.id} reload={reload} />)}
            {ranking.disqualified.length > 0 && <div className="pt-2 text-xs uppercase tracking-wide text-muted">Doesn’t qualify</div>}
            {ranking.disqualified.map((p: J) => <Offer key={p.signature} p={p} incident={inc.id} reload={reload} />)}
          </div>
          <p className="mt-3 text-xs text-muted">Reliability from your delivery history · re-checked against live coverage at {hhmm(ranking.checked_at)}.</p>
        </Card>
      </div>
      {approve && <DecisionCard d={approve} incident={inc.id} reload={reload} />}
      {!approve && pos.length > 0 && (
        <section className="mt-6 flex flex-wrap items-center gap-4 rounded-3xl bg-sage p-5">
          <Mark ok />
          <div className="flex-1">
            <div className="text-lg font-semibold">{pos.every((p: J) => p.approved_by === "auto") ? "Within your rules, so we placed the order." : "You approved it, so we placed the order."}</div>
            <div className="text-sm text-sage-ink">{pos.map((p: J) => `${p.po_id} emailed to ${p.supplier} at ${hhmm(p.sent_at)}`).join(" · ")}{pos[0].approved_by === "auto" ? ` · approved automatically under your ${gbp(snap.rules.spending_limit_per_incident)} limit` : ""}.</div>
          </div>
          <Button href={`#/incident/${inc.id}/execute`}>View purchase order ↗</Button>
        </section>)}
    </>
  );
}

/** Generic open decision (approve an order, no qualifying offer, which bake can wait). */
function DecisionCard({ d, incident, reload }: { d: J; incident: string; reload: () => void }) {
  const [err, setErr] = useState("");
  const choose = async (option: string) => {
    const r = await api(`/api/decisions/${d.id}`, { option });
    if (!r.ok) setErr(r.reason); else reload();
  };
  return (
    <Card tint="lilac" className="mt-6">
      <Badge tone="rose">! Needs your decision</Badge>
      <h2 className="mt-2 text-2xl font-bold">{d.title}</h2>
      {d.context.why?.length > 0 && <p className="mt-1 text-sm text-muted">Why we’re asking: {d.context.why.join("; ")}.</p>}
      <div className="mt-4 flex flex-wrap items-start gap-3">
        {d.options.map((o: J) => o.id === "not_this" ? <NotThisOne key={o.id} incident={incident} plan={d.options[0].plan} onDone={reload} />
          : <Button key={o.id} kind={o.recommended ? "primary" : "secondary"} onClick={() => choose(o.id)}>{o.label}{o.customers ? ` (${list(o.customers)})` : ""}</Button>)}
      </div>
      {d.options.find((o: J) => o.coverage) && (
        <p className="mt-3 text-sm text-muted">Saves: {d.options.find((o: J) => o.coverage).coverage.map((s: J) => `${hhmm(s.bake_time)} ${s.covered ? "✓" : "✕"}`).join(" · ")}</p>)}
      {err && <p className="mt-3 text-sm text-rose-ink">{err}</p>}
    </Card>
  );
}

export function NeedsYou({ snap, reload }: { snap: J; reload: () => void }) {
  const inc = snap.incident;
  const open = snap.decisions.filter((d: J) => d.status === "open");
  const mismatch = open.find((d: J) => d.kind === "confirmation_mismatch");
  if (!open.length) return <><Title>Nothing needs you.</Title><Waiting>Anything outside your rules will show up here first.</Waiting><History snap={snap} /></>;
  return (
    <>
      {mismatch && <Mismatch d={mismatch} snap={snap} reload={reload} />}
      {open.filter((d: J) => d !== mismatch).map((d: J) => <DecisionCard key={d.id} d={d} incident={inc.id} reload={reload} />)}
      <div className="mt-6 rounded-2xl border border-line bg-white p-4 text-sm text-muted">
        <span className="mr-3 text-[11px] uppercase tracking-wide">Also handled</span>
        No supplier qualifies · Only part of the quantity available (we split the order) · Price or time changes after ordering · A new supplier needs your approval
      </div>
    </>
  );
}

/** Earlier decisions and what was chosen. */
function History({ snap }: { snap: J }) {
  const done = snap.decisions.filter((d: J) => d.status === "resolved");
  if (!done.length) return null;
  return <Card className="mt-6"><h2 className="mb-2 text-xl font-bold">Earlier decisions</h2>{done.map((d: J) =>
    <div key={d.id} className="py-1 text-sm">{d.title} — <span className="text-muted">you chose “{d.options.find((o: J) => o.id === d.chosen)?.label}”</span></div>)}</Card>;
}

/** The confirmation-mismatch view with the three options. */
function Mismatch({ d, snap, reload }: { d: J; snap: J; reload: () => void }) {
  const [err, setErr] = useState("");
  const po = snap.purchase_orders.find((p: J) => p.po_id === d.context.po_id);
  const fields = d.context.match.fields.filter((f: J) => !f.ok || f.field === "Arrival");
  const short = Number(d.context.shortfall_kg);
  const adjust = d.options.find((o: J) => o.id === "accept_adjust");
  const hit = adjust?.slots?.[0]?.customers?.[0];
  const choose = async (option: string) => { const r = await api(`/api/decisions/${d.id}`, { option }); if (!r.ok) setErr(r.reason); else reload(); };
  const conf = d.context.confirmation ?? {};
  return (
    <>
      <section className="grid gap-6 rounded-3xl bg-rose p-6 md:grid-cols-[1.2fr_1fr]">
        <div className="self-center">
          <Badge tone="white"><span className="text-rose-ink">! Needs your decision</span></Badge>
          <h1 className="mt-3 text-3xl font-extrabold">{po.supplier} confirmed {conf.packs ? `${conf.packs} bags, not ${po.lines[0].packs}` : "something different"}.</h1>
          <p className="mt-3 text-muted">We didn’t accept it.{short > 0 && hit ? ` With ${kg((conf.packs ?? 0) * po.lines[0].pack_size_kg)} arriving you’d be ${kg(short)} short tomorrow — enough to affect ${hit.customer}’s ${hit.description.replace(/^\d+ /, "")}.` : ""}</p>
        </div>
        <div className="rounded-2xl bg-white p-4 text-sm">
          <div className="mb-2 text-[11px] uppercase tracking-wide text-muted">{po.supplier}’s confirmation · {hhmm(snap.emails.filter((m: J) => m.supplier === po.supplier).pop()?.sent_or_received_at)}</div>
          <table className="w-full"><thead><tr className="text-left text-[11px] uppercase text-muted"><th className="py-1">Field</th><th>Agreed</th><th>Confirmed</th><th /></tr></thead>
            <tbody>{fields.map((f: J) => <tr key={f.field} className={f.ok ? "" : "text-rose-ink"}><td className="py-2 text-ink">{f.field}</td><td className="text-muted">{f.agreed}</td><td className="font-semibold">{f.confirmed}</td><td><Mark ok={f.ok} /></td></tr>)}</tbody></table>
        </div>
      </section>
      <h2 className="mb-3 mt-8 text-xl font-bold">Your options</h2>
      <div className="grid gap-4 md:grid-cols-3">
        {d.options.map((o: J) => {
          const line = o.plan?.lines?.[0];
          return (
            <Card key={o.id} tint={o.recommended ? "lilac" : undefined} className="flex flex-col">
              {o.recommended && <div className="mb-2"><Badge tone="white">Recommended</Badge></div>}
              <h3 className="text-xl font-bold">{o.label}</h3>
              {o.id === "top_up" && <>
                <p className="mt-1 text-sm text-muted">{line.packs} × {kg(line.pack_size_kg)} {line.label ? `on their ${line.label}` : ""}, so tomorrow is fully covered.</p>
                <div className="mt-3 space-y-1 text-sm">
                  <div className="flex justify-between"><span>✓ Arrives</span><span>{hhmm(line.arrival_at)}</span></div>
                  <div className="flex justify-between"><span>✓ Cost</span><span>{gbp(o.plan.total)} incl. delivery</span></div>
                  <div className="flex justify-between"><span>✓ New total</span><span>{gbp(o.new_total)} of {gbp(snap.rules.spending_limit_per_incident)}</span></div>
                  <div className="text-xs text-sage-ink">Passes all {o.plan.checks.length} of your rules</div>
                </div></>}
              {o.id === "ask_correct" && <p className="mt-1 text-sm text-muted">We reply asking them to correct the confirmation. If they say no, we come back to you.</p>}
              {o.id === "accept_adjust" && <>
                <p className="mt-1 text-sm text-muted">Keep what they confirmed and plan around the gap.</p>
                <div className="mt-3 space-y-1 text-sm">
                  <div className="flex justify-between"><span>Shortfall</span><span>{kg(o.shortfall_kg)}</span></div>
                  {o.slots.map((s: J) => s.customers.map((c: J) => <div key={c.customer} className="flex justify-between gap-3"><span>Affects</span><span>~{c.units} {c.description.replace(/^\d+ /, "")} ({c.customer}, {hhmm(s.bake_time)})</span></div>))}
                </div></>}
              <div className="mt-auto pt-4"><Button kind={o.recommended ? "primary" : "secondary"} onClick={() => choose(o.id)}>
                {o.id === "top_up" ? "Approve top-up" : o.id === "ask_correct" ? "Send reply" : "Accept and adjust"}</Button></div>
            </Card>);
        })}
      </div>
      {err && <p className="mt-3 text-sm text-rose-ink">{err}</p>}
    </>
  );
}
