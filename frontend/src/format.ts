// Formatting helpers (British English, £, kg, Europe/London times as sent by the backend).

/** £165 or £165.50; '—' when unknown. */
export const gbp = (v: unknown, dp?: number) => {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return `£${n.toFixed(dp ?? (Number.isInteger(n) ? 0 : 2))}`;
};

/** 160 kg (no trailing .0). */
export const kg = (v: unknown) => (v === null || v === undefined ? "—" : `${+Number(v).toFixed(1)} kg`);

/** HH:MM from an ISO timestamp (the backend already sends local time with offset). */
export const hhmm = (iso?: string | null) => (iso ? iso.slice(11, 16) : "");

/** "Today, 16:42" / "3 Nov" style label. */
export const when = (iso?: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? `Today, ${hhmm(iso)}` : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
};

/** 0.964 -> 96% */
export const pct = (v?: number | null) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

/** Human list: A, B and C */
export const list = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** snake_case field -> words */
export const words = (s: string) => s.replace(/_at$/, " time").replace(/_/g, " ");
