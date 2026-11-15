// "Ask for help" assistant: big always-visible button, side panel, suggested questions, optional voice in/out.
// It only ever PREPARES actions; the owner's click on a confirmation card calls the normal endpoints.
import { useEffect, useRef, useState } from "react";
import { api, type J } from "./api";

type Msg = { role: "user" | "assistant"; text: string; cards?: J[]; done?: boolean };

/** Suggested questions change with the screen. */
function chips(route: string[]): string[] {
  const tab = route[0] === "incident" ? route[2] ?? "" : route[0] ?? "";
  if (["decide", "needs-you"].includes(tab)) return ["Which option should I pick?", "How much will it cost?", "What happens if I do nothing?"];
  if (route[0] === "incident") return ["What happened?", "Is tomorrow OK?", "Why did you pick this supplier?"];
  if (tab === "rules") return ["How do I change my spending limit?", "What does auto-order mean?"];
  return ["What's going on with my flour?", "Is tomorrow OK?", "What does 'on order' mean?"];
}

// Browser speech APIs (optional; typed fallback always works).
const Recognition = (window as J).SpeechRecognition || (window as J).webkitSpeechRecognition;
const speak = (text: string) => { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.lang = "en-GB"; speechSynthesis.speak(u); };

export default function Assistant({ route }: { route: string[] }) {
  const starter: Msg = { role: "assistant", text: "Hello! I use the live incident data to explain what’s happening. I can prepare a decision too, but I will never place an order without your confirmation." };
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([starter]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const incidentId = route[0] === "incident" ? route[1] : undefined;
  useEffect(() => { if (open) input.current?.focus(); }, [open]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const ask = async (q: string) => {
    if (!q.trim() || busy) return;
    setMsgs((m) => [...m, { role: "user", text: q }]); setText(""); setBusy(true);
    try {
      const r = await api("/api/assistant/chat", { text: q, page: route.join("/") || "home", incident_id: incidentId ?? null });
      setMsgs((m) => [...m, { role: "assistant", text: r.reply, cards: r.cards }]);
    } catch {
      setMsgs((m) => [...m, { role: "assistant", text: "Sorry, I couldn’t reach Crumbly just now. Please try again.", cards: [{ type: "link", label: "Show me the screen", href: "#/" }] }]);
    } finally { setBusy(false); }
  };

  const listen = () => {
    const rec = new Recognition(); rec.lang = "en-GB"; rec.interimResults = false;
    rec.onresult = (e: J) => ask(e.results[0][0].transcript);
    rec.onend = () => setListening(false);
    setListening(true); rec.start();
  };

  /** Owner pressed a confirmation button: only now does anything happen, through the usual endpoints. */
  const confirm = async (i: number, card: J, yes: boolean) => {
    let reply = "No problem, I haven’t changed anything.";
    try {
      if (yes && card.type === "confirm_feedback") {
        await api("/api/feedback", { incident_id: card.incident_id, reason: card.reason, note: card.note, quote_id: card.quote_id, supplier: card.supplier });
        reply = "Done. Crumbly is looking again now. I’ll show you the new option on the decision screen.";
      } else if (yes && card.type === "confirm_decision") {
        const r = await api(`/api/decisions/${card.decision_id}`, { option: card.option_id });
        reply = r.ok ? "Done. That’s been carried out within your rules." : `I couldn’t do that: ${r.reason}`;
      }
    } catch {
      reply = "I couldn’t carry that out just now. Nothing was changed. Please use the decision screen instead.";
    }
    setMsgs((m) => [...m.map((x, n) => (n === i ? { ...x, done: true } : x)), { role: "assistant", text: reply,
      cards: incidentId ? [{ type: "link", label: "Show me the screen", href: `#/incident/${incidentId}` }] : [] }]);
  };

  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)} className="fixed bottom-6 right-6 z-40 flex min-h-14 items-center gap-2 rounded-full bg-plum px-6 text-lg font-semibold text-white shadow-lg hover:bg-plum-dark">
          <span aria-hidden="true">💬</span> Ask Crumbly <span className="rounded-full bg-white/20 px-2 py-0.5 text-xs">Live</span>
        </button>)}
      {open && (
        <aside role="dialog" aria-label="Help assistant" className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-line bg-white text-lg shadow-2xl">
          <header className="flex items-center justify-between border-b border-line p-4">
            <div><div className="font-display text-xl font-bold">Ask Crumbly</div><div className="text-sm text-muted"><span className="text-sage-ink">●</span> Live bakery data · actions need your click</div></div>
            <div className="flex items-center gap-1">
              <button onClick={() => setMsgs([starter])} className="min-h-10 px-2 text-sm text-plum underline">Clear</button>
              <button onClick={() => setOpen(false)} className="min-h-12 min-w-12 rounded-full bg-lilac text-plum" aria-label="Close help">✕</button>
            </div>
          </header>
          <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
            {msgs.map((m, i) => (
              <div key={i} className={m.role === "user" ? "ml-10 rounded-2xl bg-plum p-3 text-white" : "mr-6"}>
                <p className="whitespace-pre-line leading-relaxed">{m.text}</p>
                {m.role === "assistant" && i > 0 && "speechSynthesis" in window &&
                  <button className="mt-1 text-sm text-plum underline" onClick={() => speak(m.text)}>Read aloud</button>}
                <div className="mt-2 flex flex-wrap gap-2">{(m.cards ?? []).map((c, k) => c.type === "link" ? (
                  <a key={k} href={c.href} className="inline-flex min-h-12 items-center rounded-full bg-lilac px-4 text-base font-medium text-plum">{c.label} →</a>
                ) : m.done ? null : (
                  <span key={k} className="flex gap-2">
                    <button onClick={() => confirm(i, c, true)} className="min-h-12 rounded-full bg-plum px-5 text-base font-semibold text-white">{c.yes}</button>
                    <button onClick={() => confirm(i, c, false)} className="min-h-12 rounded-full border border-line px-5 text-base text-plum">{c.no}</button>
                  </span>))}</div>
              </div>))}
            {busy && <p className="text-muted">Thinking…</p>}
            <div ref={end} />
          </div>
          <div className="border-t border-line p-4" aria-busy={busy}>
            <div className="mb-3 flex flex-wrap gap-2">{chips(route).map((c) => (
              <button key={c} onClick={() => ask(c)} className="min-h-12 rounded-full bg-lilac px-4 text-base text-plum hover:bg-lilac-2">{c}</button>))}</div>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
              <input ref={input} value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your question…" aria-label="Your question"
                className="min-h-12 flex-1 rounded-full border border-line px-4 text-lg" />
              {Recognition && <button type="button" onClick={listen} aria-label="Speak your question"
                className={`min-h-12 min-w-12 rounded-full ${listening ? "bg-rose text-rose-ink" : "bg-lilac text-plum"}`}>🎤</button>}
              <button className="min-h-12 rounded-full bg-plum px-5 font-semibold text-white" disabled={busy}>Ask</button>
            </form>
          </div>
        </aside>)}
    </>
  );
}
