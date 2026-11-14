// Suppliers with reliability computed in SQL from delivery_history.
import { type J, useApi } from "../api";
import { pct } from "../format";
import { Badge, Card, Title, Waiting } from "../ui";

export default function Suppliers() {
  const { data } = useApi("/api/suppliers");
  return (
    <>
      <Title sub="Reliability comes straight from your delivery history: on time (with half credit up to 15 minutes late) and the share of each order that actually arrived.">Your suppliers</Title>
      <Card>
        {!data ? <Waiting>Loading…</Waiting> : (
          <table className="w-full text-sm">
            <thead><tr className="bg-lilac text-left text-[11px] uppercase tracking-wide text-muted">{["Supplier", "Status", "On time", "Right quantity", "Deliveries", "Area"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{data.map((s: J) => (
              <tr key={s.supplier} className="border-b border-line last:border-0">
                <td className="px-3 py-4 font-medium">{s.supplier}<div className="text-xs text-muted">{s.website}</div></td>
                <td className="px-3">{s.status === "approved" ? <Badge tone="sage">Approved</Badge> : <Badge tone="amber">New · needs your OK</Badge>}</td>
                <td className="px-3">{pct(s.on_time_rate)}</td><td className="px-3">{pct(s.quantity_accuracy)}</td>
                <td className="px-3">{s.deliveries}</td><td className="px-3 text-muted">{s.delivery_area}</td>
              </tr>))}</tbody>
          </table>)}
      </Card>
    </>
  );
}
