// Full incident event log: append-only timeline with actors, evidence and MLflow trace links; Replay and Export.
import { useEffect, useState } from "react";
import { type J, useApi } from "../api";
import { hhmm } from "../format";
import { Badge, Button, Card, Row, Title } from "../ui";

const ACTOR: Record<string, [string, Parameters<typeof Badge>[0]["tone"], string]> = {
  production_agent: ["Production agent", "amber", "bg-amber-ink"], sourcing_agent: ["Sourcing agent", "plum", "bg-plum"],
  recovery_agent: ["Recovery agent", "sage", "bg-sage-ink"], execution_service: ["Execution service", "grey", "bg-ink"],
  owner: ["You", "rose", "bg-rose-ink"], system: ["System", "grey", "bg-muted"],
};

export default function Log({ snap }: { snap: J }) {
  const inc = snap.incident, events: J[] = snap.events;
  const { data: cfg } = useApi("/api/config", 15000);
  const [step, setStep] = useState<number | null>(null); // null = show everything; a number = replaying up to that event
  useEffect(() => {
    if (step === null || step >= events.length) return;
    const t = setTimeout(() => setStep(step + 1), 900);
    return () => clearTimeout(t);
  }, [step, events.length]);
  const shown = step === null ? events : events.slice(0, step);
  const mins = inc.resolved_at ? Math.round((Date.parse(inc.resolved_at) - Date.parse(inc.opened_at)) / 60000) : null;
  return (
    <>
      <Title sub={`An append-only record of ${inc.id}: every message, tool call and decision, with the evidence behind it.`}>Everything that happened, in order.</Title>
      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <div className="mb-4 flex items-baseline justify-between"><h2 className="text-2xl font-bold">Event log</h2><span className="text-xs text-muted">{shown.length} of {events.length} events</span></div>
          <ol className="relative">
            {shown.map((e) => {
              const [name, tone, dot] = ACTOR[e.actor] ?? ACTOR.system;
              const refs: string[] = e.evidence?.refs ?? [];
              return (
                <li key={e.id} className="grid grid-cols-[3.5rem_1rem_1fr] gap-3 pb-5">
                  <span className="text-sm font-semibold">{hhmm(e.ts)}</span>
                  <span className="relative flex justify-center"><span className={`mt-1.5 h-3 w-3 rounded-full ${dot}`} /><span className="absolute top-5 h-full w-px bg-line" /></span>
                  <div>
                    <div className="flex flex-wrap items-center gap-2"><span className="text-[10px] uppercase tracking-wide text-muted">{e.stage}</span><Badge tone={tone}>{name}</Badge></div>
                    <div className="mt-1 text-sm">{e.summary}</div>
                    {(refs.length > 0 || e.trace_url || e.evidence?.trace_id) && (
                      <div className="mt-1 text-xs text-plum">{refs.length > 0 && `Evidence: ${refs.join(" · ")}`}
                        {e.trace_url ? <>{refs.length > 0 && " · "}<a className="underline" href={e.trace_url} target="_blank" rel="noreferrer">MLflow trace ↗</a></>
                          : e.evidence?.trace_id ? <span className="text-muted">{refs.length > 0 && " · "}MLflow trace {String(e.evidence.trace_id).slice(-8)}</span> : null}</div>)}
                  </div>
                </li>);
            })}
          </ol>
        </Card>
        <div className="space-y-6">
          <Card tint="lilac">
            <div className="flex items-center justify-between"><h2 className="text-2xl font-bold">{inc.id}</h2>
              <Badge tone="white">{inc.status.startsWith("resolved") ? "✓ Resolved" : "Open"}</Badge></div>
            <div className="mt-3 rounded-2xl bg-white p-4">
              <Row k="Opened" v={hhmm(inc.opened_at)} strong />
              <Row k="Resolved" v={hhmm(inc.resolved_at) || "—"} strong />
              <Row k="Time to recover" v={<span className="text-sage-ink">{mins !== null ? `${mins} min` : "—"}</span>} strong />
              <div className="my-2 border-t border-line" />
              <Row k="Emails sent" v={snap.stats.emails_sent} strong />
              <Row k="Replies received" v={snap.stats.replies} strong />
              <Row k="Decisions needing you" v={snap.stats.owner_decisions} strong />
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <Button onClick={() => setStep(step === null ? 1 : null)}>{step === null ? "Replay incident" : "Show all"}</Button>
              <Button kind="secondary" href={`/api/incidents/${inc.id}/export`}>Export log</Button>
            </div>
          </Card>
          <Card>
            <h2 className="text-xl font-bold">Behind the scenes</h2>
            <p className="mb-3 mt-1 text-sm text-muted">State is saved after every step, so a restart picks up where it left off. Every tool call and decision is traced.</p>
            <div className="flex flex-wrap gap-2">
              <Badge>{cfg?.modes?.warehouse === "databricks" ? "Operational data in Databricks" : "Local mirror of Databricks schema"}</Badge>
              <Badge>{cfg?.modes?.linkup === "live" ? "Live supplier research by Linkup" : "Controlled Linkup research fixture"}</Badge>
              <Badge>{String(cfg?.modes?.tracing?.location ?? "").startsWith("unity_catalog:") ? "MLflow traces in Unity Catalog" : "Local MLflow traces"}</Badge>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
