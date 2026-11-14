// Incident stages (shared by the stepper, home page and default tab choice).
import type { J } from "./api";

export const STAGES = ["detect", "understand", "investigate", "coordinate", "decide", "execute", "update"] as const;
export const STAGE_LABEL: Record<string, string> = { detect: "Detect", understand: "Understand", investigate: "Investigate",
  coordinate: "Coordinate", decide: "Decide", execute: "Execute", update: "Update" };
// Which screen each stage opens.
export const STAGE_TAB: Record<string, string> = { detect: "understand", understand: "understand", investigate: "investigate",
  coordinate: "coordinate", decide: "decide", execute: "execute", update: "execute" };

/** Number of completed steps (a resolved incident has all 7). */
export const stepsDone = (inc: J) => inc.status?.startsWith("resolved") ? 7 : STAGES.indexOf(inc.stage);

/** The most useful screen for the incident right now. */
export function bestTab(snap: J): string {
  const inc = snap.incident;
  if (inc.status?.startsWith("resolved")) return "summary";
  const open = snap.decisions.find((d: J) => d.status === "open");
  if (open?.kind === "confirmation_mismatch") return "needs-you";
  if (open) return "decide";
  return STAGE_TAB[inc.stage] ?? "understand";
}
