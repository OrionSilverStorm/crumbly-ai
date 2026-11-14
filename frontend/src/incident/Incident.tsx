// Incident page: live snapshot (SSE), the stage stepper on every view, and the per-stage screens.
import type { ReactElement } from "react";
import { useIncident, type J } from "../api";
import { bestTab, STAGE_LABEL, STAGE_TAB, STAGES, stepsDone } from "../stages";
import { Waiting } from "../ui";
import Impact from "./Impact";
import { Coordinate, Investigate } from "./Sourcing";
import { Decide, NeedsYou } from "./Decisions";
import { Confirmation, Summary } from "./Outcome";
import Log from "./Log";

const VIEWS: Record<string, (p: { snap: J; reload: () => void }) => ReactElement> = {
  understand: Impact, investigate: Investigate, coordinate: Coordinate, decide: Decide, execute: Confirmation,
  "needs-you": NeedsYou, summary: Summary, log: Log,
};

export default function Incident({ id, tab }: { id: string; tab?: string }) {
  const { snap, reload } = useIncident(id);
  if (!snap) return <Waiting>Loading {id}…</Waiting>;
  const current = tab && VIEWS[tab] ? tab : bestTab(snap);
  const View = VIEWS[current];
  return (
    <>
      <Stepper snap={snap} current={current} />
      <View snap={snap} reload={reload} />
      <nav className="mt-8 flex flex-wrap gap-2 text-sm" aria-label="Incident views">
        {[["summary", "Summary"], ["needs-you", "Decisions"], ["log", "Full incident log"]].map(([k, l]) => (
          <a key={k} href={`#/incident/${id}/${k}`} className={`rounded-full px-4 py-2 ${current === k ? "bg-plum text-white" : "bg-lilac text-plum"}`}>{l}</a>))}
      </nav>
    </>
  );
}

// Which step a screen belongs to (Detect has no screen of its own).
const TAB_STAGE: Record<string, string> = { understand: "understand", investigate: "investigate", coordinate: "coordinate",
  decide: "decide", execute: "execute", "needs-you": "execute", summary: "update" };

/** Seven-step stepper; done steps get a check, the current one is highlighted, a blocked step turns red. */
function Stepper({ snap, current }: { snap: J; current: string }) {
  const inc = snap.incident;
  const done = stepsDone(inc);
  const blocked = snap.decisions.some((d: J) => d.status === "open" && d.kind === "confirmation_mismatch");
  return (
    <ol className="mb-8 grid grid-cols-2 gap-2 rounded-3xl border border-line bg-white p-3 sm:grid-cols-4 lg:grid-cols-7">
      {STAGES.map((s, n) => {
        const isDone = n < done, here = s === TAB_STAGE[current];
        const red = blocked && s === "execute";
        return (
          <li key={s}>
            <a href={`#/incident/${inc.id}/${STAGE_TAB[s]}`}
              className={`flex min-h-11 items-center gap-2 rounded-2xl px-3 text-sm ${red ? "bg-rose font-semibold text-rose-ink" : here ? "bg-lilac font-semibold text-plum" : "text-muted"}`}
              aria-current={here ? "step" : undefined}>
              <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                red ? "bg-rose-ink text-white" : isDone && !here ? "bg-sage text-sage-ink" : here ? "bg-plum text-white" : "bg-lilac text-muted"}`}>
                {red ? "!" : isDone && !here ? "✓" : n + 1}</span>
              {STAGE_LABEL[s]}
            </a>
          </li>);
      })}
    </ol>
  );
}
