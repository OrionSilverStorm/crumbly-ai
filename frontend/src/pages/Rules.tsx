// Purchasing rules: editable, saved to Lakebase. Only the owner changes these (the agents never do).
import { useEffect, useState } from "react";
import { api, type J, useApi } from "../api";
import { gbp } from "../format";
import { Badge, Button, Card, Row, Title } from "../ui";

export default function Rules() {
  const { data: rules, reload } = useApi("/api/rules");
  const { data: products } = useApi("/api/tables/approved_products");
  const { data: suppliers } = useApi("/api/suppliers");
  const [draft, setDraft] = useState<J>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (rules) setDraft(rules); }, [rules]);
  if (!draft) return null;
  const set = (k: string, v: unknown) => { setDraft({ ...draft, [k]: v }); setSaved(false); };
  const save = async () => {
    const { spending_limit_per_incident, auto_order_enabled, arrival_buffer_min, delivery_window_start, delivery_window_end, chase_after_min, drop_after_min } = draft;
    await api("/api/rules", { spending_limit_per_incident: Number(spending_limit_per_incident), auto_order_enabled, arrival_buffer_min: Number(arrival_buffer_min),
      delivery_window_start, delivery_window_end, chase_after_min: Number(chase_after_min), drop_after_min: Number(drop_after_min) }, "PUT");
    setSaved(true); reload();
  };
  const field = (k: string, label: string, type = "number", suffix = "") => (
    <label className="flex items-center justify-between gap-4 py-2 text-sm"><span className="text-muted">{label}</span>
      <span className="flex items-center gap-2"><input aria-label={label} type={type} value={draft[k]} onChange={(e) => set(k, e.target.value)} className="w-28 rounded-xl border border-line p-2 text-right" />{suffix}</span></label>);
  // Group approved products by ingredient, suppliers in preference order.
  const rank = Object.fromEntries((suppliers ?? []).map((s: J) => [s.supplier, s.preference_rank]));
  const byIngredient: Record<string, J[]> = {};
  (products ?? []).forEach((p: J) => (byIngredient[p.ingredient] ??= []).push(p));

  return (
    <>
      <Title sub="Set these once. Anything inside them can happen automatically; anything outside comes to you first.">You set the rules. We stick to them.</Title>
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <div className="text-xs text-muted">Spending limit</div>
          <div className="mt-1 flex items-baseline gap-2"><span className="font-display text-4xl font-extrabold">{gbp(rules.spending_limit_per_incident)}</span><span className="text-sm text-muted">per incident</span></div>
          <p className="mt-2 text-sm text-muted">Includes delivery and VAT. Anything over comes to you.</p>
          {field("spending_limit_per_incident", "New limit (£)")}
        </Card>
        <Card>
          <div className="text-xs text-muted">Automatic ordering</div>
          <div className="mt-1 flex items-center justify-between">
            <span className="font-display text-4xl font-extrabold">{draft.auto_order_enabled ? "On" : "Off"}</span>
            <button role="switch" aria-checked={draft.auto_order_enabled} aria-label="Automatic ordering" onClick={() => set("auto_order_enabled", !draft.auto_order_enabled)}
              className={`h-8 w-14 rounded-full p-1 transition ${draft.auto_order_enabled ? "bg-plum" : "bg-lilac-2"}`}>
              <span className={`block h-6 w-6 rounded-full bg-white transition ${draft.auto_order_enabled ? "translate-x-6" : ""}`} /></button>
          </div>
          <p className="mt-2 text-sm text-muted">Only from approved suppliers, for approved products.</p>
        </Card>
        <Card>
          <div className="text-xs text-muted">New suppliers</div>
          <Row k="Research & contact" v={<span className="text-sage-ink">Allowed</span>} strong />
          <Row k="Buying" v={<span className="text-amber-ink">Needs your OK</span>} strong />
          <p className="mt-2 text-sm text-muted">We check claims against more than one source before suggesting them.</p>
        </Card>
      </div>
      <Card className="mt-6">
        <h2 className="mb-3 text-2xl font-bold">Approved ingredients & suppliers</h2>
        <table className="w-full text-sm">
          <thead><tr className="bg-lilac text-left text-[11px] uppercase tracking-wide text-muted">{["Ingredient", "Approved products", "Pack", "Suppliers (in order of preference)", "Auto-order"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
          <tbody>{Object.entries(byIngredient).map(([ing, ps]) => {
            const sorted = [...ps].sort((a, b) => (rank[a.supplier] ?? 9) - (rank[b.supplier] ?? 9));
            const auto = ps.every((p) => p.auto_order_allowed);
            return (
              <tr key={ing} className="border-b border-line last:border-0"><td className="px-3 py-4 capitalize">{ing}</td><td className="px-3 text-muted">{sorted.map((p) => p.sku).join(" · ")}</td>
                <td className="px-3 text-muted">{ps[0].pack_size_kg} kg</td><td className="px-3 text-muted">{sorted.map((p) => p.supplier).join(" · ")}</td>
                <td className="px-3">{auto ? <Badge tone="plum">On</Badge> : <Badge tone="amber">Ask me first</Badge>}</td></tr>);
          })}</tbody>
        </table>
      </Card>
      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <Card><h2 className="mb-2 text-2xl font-bold">Delivery requirements</h2>
          {field("arrival_buffer_min", "Arrive before production by at least", "number", "min")}
          <Row k="Production starts" v={`${rules.production_start} weekdays`} strong />
          <Row k="Deliver to" v={`Morning Loaf · ${rules.postcode_area}`} strong />
          {field("delivery_window_start", "Accepted delivery window from", "time")}
          {field("delivery_window_end", "…until", "time")}
        </Card>
        <Card><h2 className="mb-2 text-2xl font-bold">Follow-ups & alerts</h2>
          {field("chase_after_min", "Chase a quiet supplier after", "number", "min")}
          {field("drop_after_min", "Drop them from consideration after", "number", "min")}
          <Row k="Tell me when" v="An order is placed" strong />
          <Row k="Ask me when" v="Anything is outside these rules" strong />
        </Card>
      </div>
      <div className="mt-6 flex items-center gap-3"><Button onClick={save}>Save rules</Button>{saved && <span className="text-sm text-sage-ink">✓ Saved</span>}</div>
    </>
  );
}
