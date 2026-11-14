// App shell (sidebar, header, footer, demo controls) and a tiny hash router.
import { useEffect, useState } from "react";
import { api, useApi } from "./api";
import { gbp } from "./format";
import Assistant from "./Assistant";
import Home from "./pages/Home";
import Incident from "./incident/Incident";
import Rules from "./pages/Rules";
import Suppliers from "./pages/Suppliers";
import Table from "./pages/Table";

/** Current hash path split into segments, e.g. "#/incident/INC-0042/decide" -> ["incident","INC-0042","decide"]. */
function useRoute() {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => { setRoute(read()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

const NAV = [
  { href: "#/", label: "Incidents", key: "" },
  { href: "#/production", label: "Production", key: "production" },
  { href: "#/inventory", label: "Inventory", key: "inventory" },
  { href: "#/suppliers", label: "Suppliers", key: "suppliers" },
];

export default function App() {
  const route = useRoute();
  const { data: cfg } = useApi("/api/config", 15000);
  const { data: incidents } = useApi("/api/incidents", 3000);
  const open = (incidents ?? []).filter((i: { status: string }) => !i.status.startsWith("resolved")).length;
  const section = route[0] ?? "";
  const page = section === "incident" ? <Incident id={route[1]} tab={route[2]} />
    : section === "rules" ? <Rules />
    : section === "suppliers" ? <Suppliers />
    : section === "production" ? <Table name="production_orders" title="Tomorrow's production" />
    : section === "inventory" ? <Table name="inventory" title="Inventory" also="incoming_deliveries" />
    : <Home />;

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col bg-lilac p-6 md:flex">
        <a href="#/" className="mb-10 block">
          <div className="font-display text-3xl font-extrabold text-plum">crumbly</div>
          <div className="text-xs text-muted">A little less worry.</div>
        </a>
        <nav className="flex flex-col gap-1" aria-label="Main">
          {NAV.map((n) => (
            <a key={n.key} href={n.href}
              className={`flex min-h-12 items-center justify-between rounded-2xl px-4 text-sm ${
                section === n.key || (n.key === "" && section === "incident") ? "bg-lilac-2 font-semibold text-plum" : "text-muted hover:bg-lilac-2"}`}>
              {n.label}
              {n.key === "" && open > 0 && <span className="rounded-full bg-white px-2 py-0.5 text-xs text-plum">{open}</span>}
            </a>
          ))}
        </nav>
        <div className="mt-auto space-y-6">
          <div className="rounded-2xl bg-lilac-2 p-4 text-sm">
            <div className="font-semibold">You set the rules.</div>
            <div className="mt-1 text-xs text-muted">Approved suppliers.<br />Up to {gbp(cfg?.rules?.spending_limit_per_incident)} per incident.</div>
            <a href="#/rules" className="mt-3 inline-block text-xs font-medium text-plum">Manage rules ↗</a>
          </div>
          <div><div className="text-sm font-semibold">Morning Loaf</div><div className="text-xs text-muted">Your bakery workspace</div></div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-10">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <a href="#/" className="font-display text-2xl font-extrabold text-plum md:hidden">crumbly</a>
            <Crumbs route={route} />
            <DemoMenu cfg={cfg} />
          </div>
          {page}
        </main>
        <footer className="px-4 pb-6 text-xs text-muted md:px-10">{cfg?.footer ?? "Real email & tool calls · fictional bakery data · scripted supplier replies"}</footer>
      </div>
      <Assistant route={route} />
    </div>
  );
}

const TAB_NAMES: Record<string, string> = { understand: "Impact", investigate: "Sourcing", coordinate: "Quotes", decide: "Decision",
  execute: "Confirmation", "needs-you": "Needs you", summary: "Summary", log: "Full incident" };

/** Breadcrumbs like "Incidents / Flour recovery / Impact". */
function Crumbs({ route }: { route: string[] }) {
  const parts = route[0] === "incident" ? ["Incidents", `${route[1]}`, TAB_NAMES[route[2]] ?? ""]
    : route[0] === "rules" ? ["Settings", "Purchasing rules"] : [route[0] ? route[0][0].toUpperCase() + route[0].slice(1) : "Incidents"];
  return <div className="text-sm text-muted">{parts.filter(Boolean).join("  /  ")}</div>;
}

/** "Demo workspace" badge with scenario reset, trigger email and the time-scale badge. */
function DemoMenu({ cfg }: { cfg: any }) { // eslint-disable-line @typescript-eslint/no-explicit-any
  const [openMenu, setOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [scenario, setScenario] = useState("happy");
  useEffect(() => { if (cfg?.scenario) setScenario(cfg.scenario); }, [cfg?.scenario]);
  const run = async (label: string, fn: () => Promise<unknown>) => { setBusy(label); try { await fn(); } finally { setBusy(""); } };
  return (
    <div className="relative flex items-center gap-2">
      {cfg && cfg.time_scale > 1 && <span className="rounded-full bg-amber px-3 py-1 text-xs text-amber-ink" title="Timers run faster for the demo">{cfg.time_scale}× demo time</span>}
      <button onClick={() => setOpen(!openMenu)} className="rounded-full bg-lilac-2 px-4 py-1.5 text-xs font-medium text-plum" aria-expanded={openMenu}>Demo workspace</button>
      {openMenu && (
        <div className="absolute right-0 top-10 z-30 w-72 space-y-3 rounded-2xl border border-line bg-white p-4 text-sm shadow-lg">
          <label className="block text-xs text-muted">Scenario
            <select value={scenario} onChange={(e) => setScenario(e.target.value)} className="mt-1 block w-full rounded-xl border border-line p-2 text-sm">
              {["happy", "short_confirm", "new_supplier_wins", "owner_rejects"].map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <button className="w-full rounded-full bg-lilac px-3 py-2 font-medium text-plum" disabled={!!busy}
            onClick={() => run("reset", async () => { await api("/api/demo/reset", { scenario }); window.location.hash = "#/"; })}>
            {busy === "reset" ? "Resetting…" : "Reset demo data"}</button>
          <button className="w-full rounded-full bg-plum px-3 py-2 font-medium text-white" disabled={!!busy}
            onClick={() => run("send", () => api("/api/demo/send-cancellation", {}))}>
            {busy === "send" ? "Sending…" : "Send the cancellation email"}</button>
          <p className="text-xs text-muted">Modes: {cfg && Object.entries(cfg.modes).filter(([k]) => k !== "tracing").map(([k, v]) => `${k} ${v}`).join(" · ")}</p>
        </div>
      )}
    </div>
  );
}
