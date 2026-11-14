// Investigate (supplier threads + Linkup research) and Coordinate (quotes, follow-up conversation, why we asked).
import type { J } from "../api";
import { gbp, hhmm, kg, list, pct, words } from "../format";
import { Badge, Card, Mark, Title, Waiting } from "../ui";

// Thread status -> (badge tone, label)
const THREAD: Record<string, [Parameters<typeof Badge>[0]["tone"], string]> = {
  contacted: ["grey", "Waiting for reply"], quoted: ["sage", "✓ Quote in"], incomplete: ["amber", "Follow-up sent"],
  chased: ["amber", "Chased once"], dropped: ["grey", "Dropped"], excluded: ["grey", "Excluded"], ordered: ["sage", "✓ Ordered"],
  declined: ["grey", "Can’t supply"],
};
const CLAIM: Record<string, [Parameters<typeof Badge>[0]["tone"], string]> = {
  confirmed: ["sage", "✓ Confirmed"], conflicting: ["amber", "≠ Conflicting"], unverified: ["grey", "? Unverified"] };

/** Plain-English line under a supplier's name. */
function threadNote(t: J, rules: J): string {
  const rel = t.reliability?.deliveries ? `${pct(t.reliability.on_time_rate)} on time over ${t.reliability.deliveries} deliveries` : "No delivery history yet";
  if (t.status === "excluded") return t.note ?? "Excluded";
  if (t.status === "dropped") return `No reply after ${rules.drop_after_min} min · dropped`;
  if (t.status === "chased") return `No reply after ${rules.chase_after_min} min · chased once at ${hhmm(t.last_contact_at)} · dropped at ${hhmm(t.drop_due_at)} if still quiet`;
  if (t.replied_at) return `Replied ${hhmm(t.replied_at)} · ${rel}`;
  return `Asked at ${hhmm(t.last_contact_at)} · ${rel}`;
}

export function Investigate({ snap }: { snap: J }) {
  const inc = snap.incident, st = inc.state, r = snap.rules;
  const approved = snap.threads.filter((t: J) => !t.is_new);
  const contacted = snap.threads.filter((t: J) => t.status !== "excluded");
  const sent = snap.events.find((e: J) => e.type === "enquiries_sent");
  const conflicts = snap.events.filter((e: J) => e.type === "claim_conflict");
  return (
    <>
      <Title sub={`${contacted.length} suppliers contacted for ${st.packs} × ${kg(st.pack_size_kg)} ${inc.ingredient}, delivered to ${r.postcode_area} between ${r.delivery_window_start} and ${r.delivery_window_end}. Replies land in this incident automatically.`}>
        Asking around, so you don’t have to.
      </Title>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <div className="mb-4 flex items-baseline justify-between"><h2 className="text-2xl font-bold">Your approved suppliers</h2>{sent && <span className="text-xs text-muted">Enquiries sent {hhmm(sent.ts)}</span>}</div>
          <div className="space-y-3">{approved.map((t: J) => (
            <div key={t.supplier} className={`rounded-2xl border border-line p-4 ${t.status === "excluded" ? "bg-paper text-muted" : ""}`}>
              <div className="flex items-center justify-between"><span className="font-semibold">{t.supplier}</span><Badge tone={THREAD[t.status]?.[0]}>{THREAD[t.status]?.[1] ?? t.status}</Badge></div>
              <div className="mt-1 text-xs text-muted">{threadNote(t, r)}</div>
            </div>))}</div>
          <p className="mt-3 text-xs text-muted">Approved suppliers can be ordered from automatically, within your rules.</p>
        </Card>
        <Card tint="lilac">
          <div className="flex items-center justify-between"><h2 className="text-2xl font-bold">New supplier found</h2><Badge tone="white">Researched with Linkup</Badge></div>
          <p className="mb-4 mt-1 text-sm text-muted">We also looked beyond your list, in case your usual suppliers can’t make it in time.</p>
          {!st.research_done ? <Waiting>Researching with Linkup…</Waiting> : !st.new_suppliers?.length ? <Waiting>No new suppliers found for {r.postcode_area}.</Waiting> :
            st.new_suppliers.map((s: J) => {
              const thread = snap.threads.find((t: J) => t.supplier === s.supplier);
              return (
                <div key={s.supplier} className="mb-3 rounded-2xl bg-white p-5">
                  <div className="flex items-start justify-between gap-3 border-b border-line pb-3">
                    <div><div className="text-lg font-semibold">{s.supplier}</div><div className="text-xs text-muted">{s.location}</div></div>
                    <Badge tone="amber">New · buying needs your OK</Badge>
                  </div>
                  {s.claims.map((c: J) => (
                    <div key={c.claim} className="flex items-center justify-between gap-3 py-2 text-sm">
                      <span>{c.claim}{c.field === "trade_minimum" || c.field === "earliest_delivery_time" ? ` ${c.status === "conflicting" ? "" : c.value ?? ""}` : ""}</span>
                      <Badge tone={CLAIM[c.status][0]}>{CLAIM[c.status][1]} · {c.status === "conflicting" ? c.values.join(" vs ") : `${c.source_urls.length} source${c.source_urls.length === 1 ? "" : "s"}`}</Badge>
                    </div>))}
                  <div className="mt-2 border-t border-line pt-3 text-xs">
                    <div className="mb-1 uppercase tracking-wide text-muted">Sources</div>
                    {s.sources.map((src: J) => <div key={src.url}><a className="text-plum underline" href={src.url} target="_blank" rel="noreferrer">{src.url.replace(/^https?:\/\//, "")}</a> <span className="text-muted">· retrieved {hhmm(src.retrieved_at)}</span></div>)}
                  </div>
                  {thread && <div className="mt-3 text-xs text-muted">Enquiry: <Badge tone={THREAD[thread.status]?.[0]}>{THREAD[thread.status]?.[1]}</Badge></div>}
                </div>);
            })}
          <p className="text-xs text-muted">Published info isn’t live stock. We’ve emailed them to confirm price and delivery.</p>
        </Card>
      </div>
      {conflicts.map((e: J) => <div key={e.id} className="mt-4 rounded-2xl bg-amber p-4 text-sm text-amber-ink">≠ {e.summary}</div>)}
      <div className="mt-6 rounded-2xl bg-sage p-4 text-sm text-sage-ink">
        ✓ Searches use only the ingredient, spec and postcode area — never your customer orders or recipes.
        {st.linkup_queries?.[0] && <div className="mt-1 text-xs">Search sent: “{st.linkup_queries[0]}”</div>}
      </div>
    </>
  );
}

/** Status cell for a quote, from the execution service's ranking (reasons) and code-detected missing fields. */
function quoteStatus(q: J, ranking: J) {
  if (q.excluded_reason) return <Badge tone="grey">Excluded · {q.excluded_reason}</Badge>;
  if (q.missing_fields.length) return <Badge tone="amber">Missing {list(q.missing_fields.map(words))}</Badge>;
  const p = [...(ranking?.qualifying ?? []), ...(ranking?.disqualified ?? [])].find((x: J) => x.lines[0]?.quote_id === q.quote_id);
  if (!p) return <Badge>Checking</Badge>;
  if (p.qualifies) return <Badge tone="sage">✓ Qualifies{p.needs_owner.length ? " · needs your OK" : ""}</Badge>;
  return <Badge tone="rose">{p.reasons.join(" · ")}{p.lines[0].approved ? "" : " · new supplier"}</Badge>;
}

export function Coordinate({ snap }: { snap: J }) {
  const inc = snap.incident, st = inc.state, r = snap.rules;
  const quotes = snap.quotes.filter((q: J) => !q.superseded);
  const followed = snap.threads.filter((t: J) => t.followups > 0);
  const incomplete = snap.quotes.filter((q: J) => q.missing_fields.length).length;
  return (
    <>
      <Title sub="To compare like with like, every quote needs a price, delivery charge, VAT and a firm arrival time. When something’s missing, we ask.">
        {quotes.length ? `${quotes.length} quote${quotes.length === 1 ? "" : "s"} in. ${followed.length ? `${followed.length === 1 ? "One was" : `${followed.length} were`} missing something.` : incomplete ? "" : "All complete."}` : "Waiting for quotes."}
      </Title>
      <Card>
        <div className="mb-3 flex items-baseline justify-between"><h2 className="text-2xl font-bold">Quotes so far</h2>
          <span className="text-xs text-muted">{st.packs} × {kg(st.pack_size_kg)} {inc.ingredient} · needed by {hhmm(inc.deadline)}</span></div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead><tr className="bg-lilac text-left text-[11px] uppercase tracking-wide text-muted">
              {["Supplier", "Goods", "Delivery", "VAT", "Total", "Arrival", "Status"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{quotes.map((q: J) => (
              <tr key={q.quote_id} className="border-b border-line last:border-0">
                <td className="px-3 py-4">{q.supplier}{q.label && <span className="text-xs text-muted"> · {q.label}{q.max_packs ? ` (up to ${q.max_packs} bags)` : ""}</span>}</td>
                <td className="px-3 text-muted">{q.goods_price ? gbp(q.goods_price) : q.unit_price ? `${gbp(q.unit_price)}/bag` : "—"}</td>
                <td className={`px-3 ${q.delivery_charge === null ? "text-amber-ink" : "text-muted"}`}>{q.delivery_charge === null ? "Not stated" : Number(q.delivery_charge) === 0 ? "Included" : gbp(q.delivery_charge)}</td>
                <td className="px-3 text-muted">{q.vat_rate === null ? "Not stated" : `${Number(q.vat_rate) * 100}%${Number(q.vat_rate) === 0 ? " · zero-rated" : ""}`}</td>
                <td className="px-3 font-semibold">{gbp(q.total)}</td>
                <td className={`px-3 ${q.arrival_at ? "" : "text-amber-ink"}`}>{q.arrival_at ? hhmm(q.arrival_at) : `“${q.arrival_text ?? "not given"}”`}</td>
                <td className="px-3">{quoteStatus(q, st.ranking)}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
      {followed.map((t: J) => <FollowUp key={t.supplier} snap={snap} thread={t} chaseMin={r.chase_after_min} />)}
    </>
  );
}

/** The follow-up conversation with one supplier, plus the code checklist that explains why we asked. */
function FollowUp({ snap, thread, chaseMin }: { snap: J; thread: J; chaseMin: number }) {
  // The exchange from the first reply up to the answer to our follow-up (later mail, e.g. the PO confirmation, is elsewhere).
  const all = snap.emails.filter((m: J) => m.supplier === thread.supplier && ["reply", "followup"].includes(m.kind));
  const fu = all.findIndex((m: J) => m.kind === "followup");
  const mails = fu < 0 ? all : all.slice(0, fu + 2);
  const first = snap.quotes.find((q: J) => q.supplier === thread.supplier && q.missing_fields.length) ?? snap.quotes.find((q: J) => q.supplier === thread.supplier);
  const checks: [string, string | null][] | undefined = first && [
    ["Price", first.goods_price ? gbp(first.goods_price) : null],
    ["Pack size", first.packs ? `${first.packs} × ${kg(first.pack_size_kg)}` : null],
    ["VAT", first.vat_rate !== null ? `${Number(first.vat_rate) * 100}% · zero-rated` : null],
    ["Delivery charge", first.delivery_charge !== null ? gbp(first.delivery_charge) : null],
    ["Arrival time", first.arrival_at ? hhmm(first.arrival_at) : null],
  ];
  const clean = (b: string) => b.split("\n").filter((l) => l.trim() && !/^Ref:|^Hello|^Hi,|^Thank|^Morning Loaf|^Thanks for your quote|^Thanks,$/.test(l.trim()) && l.trim() !== thread.supplier).map((l) => l.trim().replace(/^- /, "")).join(" ");
  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
      <Card tint="lilac">
        <h2 className="text-2xl font-bold">The follow-up</h2>
        <p className="mb-4 mt-1 text-sm text-muted">{thread.supplier}’s quote left something out, so we asked for just those details.</p>
        {mails.map((m: J) => (
          <div key={m.message_id} className={`mb-3 ${m.direction === "outbound" ? "rounded-2xl bg-white p-4" : "px-1"}`}>
            <div className={`text-[11px] uppercase tracking-wide ${m.direction === "outbound" ? "text-plum" : "text-muted"}`}>{m.direction === "outbound" ? "Your sourcing agent" : thread.supplier} · {hhmm(m.sent_or_received_at)}</div>
            <p className="mt-1 text-sm">“{clean(m.body)}”</p>
          </div>))}
        {thread.status === "incomplete" && <div className="text-xs text-muted"><Badge tone="white">Waiting for reply…</Badge> We chase once after {chaseMin} minutes.</div>}
      </Card>
      {checks && (
        <Card>
          <h2 className="text-2xl font-bold">Why we asked</h2>
          <p className="mb-3 mt-1 text-sm text-muted">Code checks each quote against the fields we need.</p>
          {checks.map(([k, v]) => <div key={k} className="flex items-center gap-3 py-2 text-sm"><Mark ok={v ? true : "warn"} /><span className="flex-1">{k}</span><span className={v ? "" : "text-amber-ink"}>{v ?? (k === "Arrival time" ? "Not specific" : "Missing")}</span></div>)}
          <p className="mt-3 rounded-2xl bg-lilac p-3 text-xs text-plum">No reply in {chaseMin} minutes? We chase once, then move on to the next option.</p>
        </Card>)}
    </div>
  );
}
