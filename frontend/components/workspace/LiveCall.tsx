"use client";

import { Headphones, Mic, Play, PhoneOff, Send, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchMode } from "@/lib/api";
import { useCall, type CallView, type NextAsk } from "@/lib/call";
import { getDemoKey } from "@/lib/demoKey";
import { fmtProb, readDeals } from "@/lib/deals";
import { PushToTalk, type Speaker } from "@/lib/recorder";
import { readNegotiate } from "@/lib/stages";
import { useAsync } from "@/lib/useAsync";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { PanelHeader } from "../PanelHeader";
import { DealEvaluator } from "./DealEvaluator";
import { GapTable } from "./NegotiateView";

const KIND_LABEL: Record<string, string> = {
  reject_conditional: "Don't accept this",
  gap: "Close the biggest gap",
  ask_term: "Ask about",
  hold: "Hold off",
  done: "Wrap up",
  listen: "Listen",
};

export function NextAskCard({ ask, ended }: { ask: NextAsk | null; ended: boolean }) {
  if (!ask) return null;
  const warn = ask.kind === "reject_conditional" || ask.kind === "hold";
  return (
    <section
      aria-label="Next ask"
      data-testid="next-ask"
      data-kind={ask.kind}
      className={`rounded-card border p-4 ${warn ? "border-warn/50 bg-warn/10" : "border-accent/40 bg-accent/10"}`}
    >
      <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-text-dim">
        <Sparkles size={16} aria-hidden="true" />
        {ended ? "Last suggestion" : "Say next"} · {KIND_LABEL[ask.kind] ?? ask.kind}
      </div>
      <p className="text-base font-medium" data-testid="next-ask-line">
        “{ask.line}”
      </p>
      <p className="mt-1 text-sm text-text-dim" data-testid="next-ask-reason">
        {ask.reason}
      </p>
    </section>
  );
}

function Transcript({ view }: { view: CallView }) {
  const end = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    if (end.current && typeof end.current.scrollIntoView === "function") end.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [view.turns.length]);
  return (
    <section aria-label="Live transcript" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Transcript"
        right={
          <span className="flex items-center gap-2">
            {view.status === "running" ? (
              <Tag tone="ok">
                <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-ok" aria-hidden="true" />
                On the call
              </Tag>
            ) : null}
            {view.mode ? <Tag tone="neutral">{view.mode === "simulate" ? "Simulated" : "Microphone"}</Tag> : null}
          </span>
        }
      />
      {view.turns.length ? (
        <ol className="max-h-[32rem] overflow-y-auto" aria-live="polite">
          {view.turns.map((t) => (
            <li key={t.turn} data-turn={t.turn} className="flex gap-3 border-b border-border px-4 py-2 text-sm last:border-b-0">
              <span className={`w-14 shrink-0 text-xs font-medium uppercase tracking-wide ${t.speaker === "buyer" ? "text-accent" : "text-text-dim"}`}>{t.speaker}</span>
              <p className="min-w-0 flex-1">{t.text}</p>
            </li>
          ))}
          <li ref={end} aria-hidden="true" />
        </ol>
      ) : (
        <p className="p-4 text-sm text-text-dim">{view.status === "running" ? "Waiting for the first words…" : "The call transcript appears here as people speak."}</p>
      )}
    </section>
  );
}

function PushToTalkBar({ onChunk, onLine, disabled }: { onChunk: (wav: Blob, s: Speaker) => void; onLine: (s: Speaker, text: string) => void; disabled: boolean }) {
  const ptt = useRef<PushToTalk | null>(null);
  const [holding, setHolding] = useState<Speaker | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [line, setLine] = useState("");
  const [speaker, setSpeaker] = useState<Speaker>("buyer");
  useEffect(() => {
    ptt.current = new PushToTalk((wav, s) => onChunk(wav, s));
    const current = ptt.current;
    return () => void current.close();
  }, [onChunk]);
  const down = async (s: Speaker) => {
    setMicError(null);
    try {
      await ptt.current?.start(s);
      setHolding(s);
    } catch (e) {
      setMicError(e instanceof Error ? e.message : "The microphone could not be opened");
    }
  };
  const up = async () => {
    setHolding(null);
    await ptt.current?.stop();
  };
  const btn = (s: Speaker, label: string) => (
    <button
      type="button"
      disabled={disabled || !PushToTalk.supported()}
      aria-pressed={holding === s}
      onPointerDown={() => void down(s)}
      onPointerUp={() => void up()}
      onPointerLeave={() => holding === s && void up()}
      onKeyDown={(e) => (e.key === " " || e.key === "Enter") && !e.repeat && void down(s)}
      onKeyUp={(e) => (e.key === " " || e.key === "Enter") && void up()}
      className={`inline-flex min-h-11 items-center gap-2 rounded-card border px-4 text-sm font-medium disabled:opacity-50 ${holding === s ? "border-bad bg-bad/20 text-bad" : "border-border bg-surface-2 hover:border-accent"}`}
    >
      <Mic size={16} aria-hidden="true" />
      {holding === s ? `${label}… release to send` : `Hold: ${label}`}
    </button>
  );
  return (
    <div className="flex flex-col gap-2" data-testid="push-to-talk">
      <div className="flex flex-wrap gap-2">
        {btn("buyer", "Buyer speaking")}
        {btn("vendor", "Vendor speaking")}
      </div>
      {!PushToTalk.supported() ? <p className="text-xs text-text-dim">This browser cannot record audio; type a line instead.</p> : null}
      {micError ? <p role="alert" className="text-xs text-bad">{micError}</p> : null}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (line.trim()) onLine(speaker, line.trim());
          setLine("");
        }}
      >
        <label className="sr-only" htmlFor="typed-line">Type a line</label>
        <select aria-label="Speaker" value={speaker} onChange={(e) => setSpeaker(e.target.value as Speaker)} className="min-h-9 rounded-chip border border-border bg-surface-2 px-2 text-sm">
          <option value="buyer">Buyer</option>
          <option value="vendor">Vendor</option>
        </select>
        <input id="typed-line" value={line} onChange={(e) => setLine(e.target.value)} placeholder="or type what was said" className="min-h-9 min-w-0 flex-1 rounded-chip border border-border bg-surface-2 px-3 text-sm" />
        <button type="submit" disabled={disabled || !line.trim()} className="inline-flex min-h-9 items-center gap-1 rounded-chip border border-border px-3 text-sm disabled:opacity-50">
          <Send size={16} aria-hidden="true" /> Add
        </button>
      </form>
    </div>
  );
}

export function LiveCall({ vendorId }: { vendorId: string }) {
  const { view, start, end, say, chunk, reset } = useCall(vendorId);
  const mode = useAsync(fetchMode, "mode");
  const [fast, setFast] = useState(false);
  const liveOk = mode.data?.mode === "live" && !!getDemoKey();
  const stage = view.stage;
  const neg = useMemo(() => readNegotiate(stage), [stage]);
  const deals = useMemo(() => readDeals(stage), [stage]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const running = view.status === "running" || view.status === "starting";
  const refused = deals?.assessments.find((a) => a.decision === "reject_structure");

  return (
    <div className="flex flex-col gap-4" data-testid="live-call">
      <section aria-label="Call controls" className="rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Headphones size={16} aria-hidden="true" />
          <h2 className="text-base font-semibold">Live negotiation copilot</h2>
          {view.status === "ended" ? <Tag tone="neutral">Call ended</Tag> : null}
          {view.mode === "live" ? <span className="num text-xs text-text-dim">spend ${view.spendUsd.toFixed(3)}</span> : null}
        </div>
        <p className="mt-1 text-sm text-text-dim">
          Transcribes the call, reads what the vendor commits to, updates the gap table, prices conditional offers and suggests what to say next. Every figure is checked against the call.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {!running ? (
            <>
              <button type="button" onClick={() => void start("simulate", fast ? 4 : 1)} className="inline-flex min-h-11 items-center gap-2 rounded-card bg-accent px-4 text-sm font-medium text-bg">
                <Play size={16} aria-hidden="true" /> {view.status === "ended" ? "Simulate again" : "Simulate call"}
              </button>
              <label className="inline-flex items-center gap-1 text-xs text-text-dim">
                <input type="checkbox" checked={fast} onChange={(e) => setFast(e.target.checked)} /> 4× speed
              </label>
              <button
                type="button"
                disabled={!liveOk}
                title={liveOk ? "Listen on the microphone" : "Needs live mode and the demo key. Simulate call is free."}
                onClick={() => void start("live")}
                className="inline-flex min-h-11 items-center gap-2 rounded-card border border-border px-4 text-sm font-medium disabled:opacity-50"
              >
                <Mic size={16} aria-hidden="true" /> Start live call (microphone)
              </button>
              {!liveOk ? <span className="text-xs text-text-dim">Microphone calls need live mode and the demo key; the simulation runs the same pipeline at no cost.</span> : null}
              {view.status === "ended" ? (
                <button type="button" onClick={reset} className="min-h-11 px-2 text-sm text-accent hover:underline">Clear</button>
              ) : null}
            </>
          ) : (
            <button type="button" onClick={() => void end()} disabled={view.busy} className="inline-flex min-h-11 items-center gap-2 rounded-card border border-bad/60 px-4 text-sm font-medium text-bad">
              <PhoneOff size={16} aria-hidden="true" /> End call
            </button>
          )}
        </div>
        {running && view.mode === "live" ? (
          <div className="mt-3">
            <PushToTalkBar onChunk={(w, s) => void chunk(w, s)} onLine={(s, t) => void say(s, t)} disabled={view.busy || view.status !== "running"} />
          </div>
        ) : null}
      </section>

      {view.error ? (
        <Banner tone="warn" title={view.error.problem}>
          {[view.error.cause, view.error.fix].filter(Boolean).join(" ")}
        </Banner>
      ) : null}

      {refused ? (
        <div role="alert" data-testid="dont-accept" className="rounded-card border border-bad/50 bg-bad/10 p-3 text-sm">
          <strong>Don&apos;t accept: {refused.probability != null ? `${fmtProb(refused.probability)} chance` : "poor odds"}.</strong>{" "}
          {refused.label} counts as {refused.countedPts.toFixed(1)}% against {refused.requiredPts.toFixed(1)}% required.
        </div>
      ) : null}

      <NextAskCard ask={view.nextAsk} ended={view.status === "ended"} />

      <div className="grid gap-4 xl:grid-cols-2">
        <Transcript view={view} />
        <div className="flex min-w-0 flex-col gap-4">
          {neg && neg.gaps.length ? (
            <GapTable gaps={neg.gaps} selected={null} onSelect={() => undefined} deals={deals?.assessments ?? []} onOpenDeal={(id) => setOpen((m) => ({ ...m, [id]: true }))} flash={view.flash.terms} />
          ) : (
            <p className="rounded-card border border-border bg-surface p-4 text-sm text-text-dim">The gap table fills in as the vendor commits to terms.</p>
          )}
        </div>
      </div>

      {deals ? (
        <DealEvaluator
          deals={deals}
          isOpen={(a) => open[a.termId] ?? true}
          onToggle={(id) => setOpen((m) => ({ ...m, [id]: !(m[id] ?? true) }))}
        />
      ) : null}
      {view.status === "ended" ? (
        <p className="text-sm text-text-dim">
          {view.mode === "live"
            ? "This call is now the canonical transcript: run the agents to verify its commitments in the Negotiate stage."
            : "The recorded call is already the canonical transcript, so the Negotiate stage uses the same words."}
        </p>
      ) : null}
    </div>
  );
}
