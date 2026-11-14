// Read-only view of an operational Delta table (Production, Inventory + incoming deliveries).
import { type J, useApi } from "../api";
import { hhmm } from "../format";
import { Card, Title, Waiting } from "../ui";

/** Render any cell: timestamps as dates/times, booleans as words. */
const cell = (v: unknown) => typeof v === "boolean" ? (v ? "Yes" : "No")
  : typeof v === "string" && /^\d{4}-\d\d-\d\dT/.test(v) ? `${new Date(v).toLocaleDateString("en-GB", { day: "numeric", month: "short" })} ${hhmm(v)}` : String(v ?? "—");

function Grid({ name }: { name: string }) {
  const { data } = useApi(`/api/tables/${name}`, 5000);
  if (!data) return <Waiting>Loading…</Waiting>;
  if (!data.length) return <Waiting>Nothing here.</Waiting>;
  const cols = Object.keys(data[0]);
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm">
      <thead><tr className="bg-lilac text-left text-[11px] uppercase tracking-wide text-muted">{cols.map((c) => <th key={c} className="px-3 py-2 font-medium">{c.replace(/_/g, " ")}</th>)}</tr></thead>
      <tbody>{data.map((r: J, i: number) => <tr key={i} className="border-b border-line last:border-0">{cols.map((c) => <td key={c} className="px-3 py-3">{cell(r[c])}</td>)}</tr>)}</tbody>
    </table></div>
  );
}

export default function Table({ name, title, also }: { name: string; title: string; also?: string }) {
  return (
    <>
      <Title sub="Live from your operational data in Databricks (read-only here).">{title}</Title>
      <Card><Grid name={name} /></Card>
      {also && <><h2 className="mb-3 mt-8 text-xl font-bold">Deliveries on their way</h2><Card><Grid name={also} /></Card>
        <p className="mt-3 text-xs text-muted">Confirmed deliveries count as “on order”. Physical stock only changes when you mark a delivery received.</p></>}
    </>
  );
}
