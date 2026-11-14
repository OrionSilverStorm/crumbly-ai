// Small presentational building blocks shared by every screen.
import type { ReactNode } from "react";

type Tone = "plum" | "sage" | "amber" | "rose" | "grey" | "white";
const TONES: Record<Tone, string> = {
  plum: "bg-lilac-2 text-plum",
  sage: "bg-sage text-sage-ink",
  amber: "bg-amber text-amber-ink",
  rose: "bg-rose text-rose-ink",
  grey: "bg-lilac text-muted",
  white: "bg-white text-plum",
};

/** Rounded pill label. */
export const Badge = ({ tone = "grey", children }: { tone?: Tone; children: ReactNode }) => (
  <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}>{children}</span>
);

/** Soft card; `tint` gives the lilac/sage/butter/rose panels from the design. */
export const Card = ({ children, tint, className = "" }: { children: ReactNode; tint?: "lilac" | "sage" | "butter" | "rose"; className?: string }) => {
  const bg = { lilac: "bg-lilac border-transparent", sage: "bg-sage border-transparent", butter: "bg-butter border-transparent", rose: "bg-rose border-transparent" };
  return <section className={`rounded-3xl border border-line p-6 ${tint ? bg[tint] : "bg-white"} ${className}`}>{children}</section>;
};

/** Primary (filled plum) or secondary (outlined) button, 48px tall for easy tapping. */
export const Button = ({ children, onClick, kind = "primary", disabled, href, title }: {
  children: ReactNode; onClick?: () => void; kind?: "primary" | "secondary"; disabled?: boolean; href?: string; title?: string;
}) => {
  const cls = `inline-flex min-h-12 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold transition disabled:opacity-50 ${
    kind === "primary" ? "bg-plum text-white hover:bg-plum-dark" : "border border-line bg-white text-plum hover:bg-lilac"}`;
  return href ? <a className={cls} href={href} title={title}>{children}</a>
    : <button className={cls} onClick={onClick} disabled={disabled} title={title}>{children}</button>;
};

/** Check / warn / cross icon in a circle. */
export const Mark = ({ ok }: { ok: boolean | "warn" }) => (
  <span aria-label={ok === true ? "pass" : ok === "warn" ? "needs attention" : "fail"}
    className={`inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
      ok === true ? "bg-sage text-sage-ink" : ok === "warn" ? "bg-amber text-amber-ink" : "bg-rose text-rose-ink"}`}>
    {ok === true ? "✓" : ok === "warn" ? "!" : "✕"}
  </span>
);

/** Big number with a caption, as in the impact strip. */
export const Stat = ({ label, value, note, tone }: { label: string; value: ReactNode; note?: string; tone?: "rose" | "plum" | "sage" }) => (
  <div className="flex-1 px-5 first:pl-0">
    <div className="text-xs text-muted">{label}</div>
    <div className="flex items-baseline gap-3">
      <span className={`whitespace-nowrap font-display text-3xl font-extrabold ${tone === "rose" ? "text-rose-ink" : tone === "plum" ? "text-plum" : tone === "sage" ? "text-sage-ink" : ""}`}>{value}</span>
      {note && <span className="text-xs text-muted">{note}</span>}
    </div>
  </div>
);

/** Page title + friendly subtitle. */
export const Title = ({ children, sub }: { children: ReactNode; sub?: ReactNode }) => (
  <header className="mb-6">
    <h1 className="text-4xl font-extrabold tracking-tight">{children}</h1>
    {sub && <p className="mt-2 max-w-3xl text-muted">{sub}</p>}
  </header>
);

/** Two-column label/value row. */
export const Row = ({ k, v, strong }: { k: ReactNode; v: ReactNode; strong?: boolean }) => (
  <div className="flex justify-between gap-4 py-1.5 text-sm"><span className="text-muted">{k}</span><span className={strong ? "font-semibold" : ""}>{v}</span></div>
);

/** Empty / waiting state. */
export const Waiting = ({ children }: { children: ReactNode }) => <p className="rounded-2xl bg-lilac p-4 text-sm text-muted">{children}</p>;
