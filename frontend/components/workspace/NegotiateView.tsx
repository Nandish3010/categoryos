"use client";

import { CheckCircle2, CircleHelp, Lock, MinusCircle, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { StageResult } from "@/lib/runs";
import {
  gapValue,
  readNegotiate,
  termValue,
  type GapRow,
  type NegotiateData,
  type TranscriptTurn,
} from "@/lib/stages";
import { Banner } from "../Banner";
import { Tag } from "../Chip";
import { CopyButton } from "../CopyButton";
import { PanelHeader } from "../PanelHeader";
import { Skeleton } from "../Skeleton";

type Selection = { turn: number; quote: string; term: string } | null;

const STATUS_CHIP = {
  met: { tone: "ok", label: "Met", Icon: CheckCircle2 },
  gap: { tone: "bad", label: "Gap", Icon: XCircle },
  not_stated: { tone: "neutral", label: "Not stated", Icon: MinusCircle },
} as const;

export function GapStatusChip({ status }: { status: GapRow["status"] }) {
  const s = STATUS_CHIP[status];
  return (
    <Tag tone={s.tone}>
      <s.Icon size={16} aria-hidden="true" />
      {s.label}
    </Tag>
  );
}

/** Split a turn into [before, quote, after]; null when the quote is not in the text. */
export function splitQuote(text: string, quote: string): [string, string, string] | null {
  if (!quote) return null;
  const at = text.indexOf(quote);
  if (at < 0) return null;
  return [text.slice(0, at), quote, text.slice(at + quote.length)];
}

function GapTable({ gaps, selected, onSelect }: { gaps: GapRow[]; selected: Selection; onSelect: (s: Selection) => void }) {
  return (
    <section aria-label="Gap table" className="rounded-card border border-border bg-surface">
      <PanelHeader title="Terms: application vs call vs our requirement" />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Negotiation gap table</caption>
          <thead>
            <tr className="border-b border-border text-left text-xs text-text-dim">
              <th scope="col" className="h-9 px-3 font-medium">Term</th>
              <th scope="col" className="h-9 px-3 text-right font-medium">Application</th>
              <th scope="col" className="h-9 px-3 text-right font-medium">Offered on call</th>
              <th scope="col" className="h-9 px-3 text-right font-medium">Required</th>
              <th scope="col" className="h-9 px-3 text-right font-medium">Gap</th>
              <th scope="col" className="h-9 px-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {gaps.map((g) => {
              const isSel = selected?.term === g.term;
              const clickable = g.offered != null && g.turn != null;
              return (
                <tr
                  key={g.term}
                  data-term={g.term}
                  data-status={g.status}
                  className={`h-10 border-b border-border last:border-b-0 ${isSel ? "bg-accent/10" : ""}`}
                >
                  <th scope="row" className="px-3 text-left font-normal">{g.label}</th>
                  <td className="num px-3 text-right text-text-dim">{termValue(g.application, g.unit)}</td>
                  <td className="num px-3 text-right">
                    {clickable ? (
                      <button
                        type="button"
                        aria-pressed={isSel}
                        title={g.quote ? `Turn ${g.turn}: “${g.quote}”` : `Turn ${g.turn}`}
                        onClick={() => onSelect(isSel ? null : { turn: g.turn!, quote: g.quote ?? "", term: g.term })}
                        className="num rounded-chip px-1 text-accent underline decoration-dotted underline-offset-4 hover:bg-accent/10"
                      >
                        {termValue(g.offered, g.unit)}
                      </button>
                    ) : (
                      <span className="text-text-dim">{termValue(g.offered, g.unit)}</span>
                    )}
                  </td>
                  <td className="num px-3 text-right">{termValue(g.required, g.unit)}</td>
                  <td className={`num px-3 text-right ${g.status === "gap" ? "text-bad" : g.status === "met" ? "text-ok" : "text-text-dim"}`}>
                    {g.status === "not_stated" ? "—" : gapValue(g.gap, g.unit)}
                  </td>
                  <td className="px-3">
                    <span className="flex flex-wrap items-center gap-1">
                      <GapStatusChip status={g.status} />
                      {g.verification === "rejected" ? <Tag tone="bad">Quote rejected</Tag> : null}
                      {g.verification === "verified" && g.status !== "not_stated" ? (
                        <span title="Quote verified against the transcript" className="text-ok">
                          <CheckCircle2 size={16} aria-label="Commitment verified" />
                        </span>
                      ) : null}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TurnText({ turn, selected }: { turn: TranscriptTurn; selected: Selection }) {
  const isSel = selected?.turn === turn.turn;
  if (!isSel) return <>{turn.text}</>;
  const parts = splitQuote(turn.text, selected.quote);
  if (!parts) return <mark className="rounded-chip bg-warn/25 px-0.5 text-text">{turn.text}</mark>;
  return (
    <>
      {parts[0]}
      <mark className="rounded-chip bg-warn/25 px-0.5 text-text">{parts[1]}</mark>
      {parts[2]}
    </>
  );
}

function TranscriptPanel({ data, selected, quoteTurns }: { data: NegotiateData; selected: Selection; quoteTurns: Set<number> }) {
  const refs = useRef<Map<number, HTMLLIElement>>(new Map());
  useEffect(() => {
    if (!selected) return;
    const el = refs.current.get(selected.turn);
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  return (
    <section aria-label="Call transcript" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Call transcript"
        right={
          <span className="flex items-center gap-2">
            <Tag tone={data.source === "asr" ? "accent" : "neutral"} title={data.source === "asr" ? "Voice call transcribed; canonical text shown beside it" : "Canonical transcript"}>
              {data.source === "asr" ? "ASR" : "Canonical"}
            </Tag>
            {data.source === "asr" && data.similarityPct != null ? (
              <span className="num">{data.similarityPct}% match</span>
            ) : null}
          </span>
        }
      />
      {data.turns && data.turns.length ? (
        <ol className="max-h-[28rem] overflow-y-auto">
          {data.turns.map((t) => {
            const isSel = selected?.turn === t.turn;
            return (
              <li
                key={t.turn}
                ref={(el) => {
                  if (el) refs.current.set(t.turn, el);
                  else refs.current.delete(t.turn);
                }}
                data-turn={t.turn}
                data-selected={isSel}
                className={`flex gap-3 border-b border-border px-4 py-2 text-sm last:border-b-0 ${
                  isSel ? "bg-accent/10" : quoteTurns.has(t.turn) ? "border-l-2 border-l-accent/40" : ""
                }`}
              >
                <span className={`w-14 shrink-0 text-xs font-medium uppercase tracking-wide ${t.speaker === "buyer" ? "text-accent" : "text-text-dim"}`}>
                  {t.speaker}
                </span>
                <p className="min-w-0 flex-1">
                  <TurnText turn={t} selected={selected} />
                </p>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="p-4 text-sm text-text-dim">No call transcript on file. Every term below is shown as not stated.</p>
      )}
    </section>
  );
}

function Refusals({ data }: { data: NegotiateData }) {
  if (!data.refusals.length) return null;
  return (
    <section aria-label="Refusals" className="rounded-card border border-border bg-surface">
      <PanelHeader title="Refused on the call" />
      <ul className="flex flex-col divide-y divide-border">
        {data.refusals.map((r, i) => (
          <li key={`${r.term}-${i}`} className="px-4 py-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="font-medium">{r.term.replace(/_/g, " ")}</span>
              {r.turn != null ? <span className="num text-xs text-text-dim">turn {r.turn}</span> : null}
              {r.verified ? <Tag tone="ok">Quote verified</Tag> : <Tag tone="warn">Quote unverified</Tag>}
            </div>
            {r.quote ? <blockquote className="mt-1 border-l-2 border-border pl-3 text-text-dim">“{r.quote}”</blockquote> : null}
            {r.note ? <p className="mt-1 text-text-dim">{r.note}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function CounterOffer({ data }: { data: NegotiateData }) {
  if (!data.asks.length && !data.emailDraft) return null;
  return (
    <section aria-label="Counter-offer" className="rounded-card border border-border bg-surface">
      <PanelHeader title="Counter-offer" />
      <div className="flex flex-col gap-3 p-4 text-sm">
        {data.asks.length ? (
          <ul className="list-disc pl-5">
            {data.asks.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        ) : null}
        {data.emailDraft ? (
          <div className="rounded-card border border-border bg-surface-2 p-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs text-text-dim">Email draft</span>
              <CopyButton text={data.emailDraft} />
            </div>
            <pre className="whitespace-pre-wrap font-sans text-sm">{data.emailDraft}</pre>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function NegotiateView({ stage }: { stage: StageResult | undefined | null }) {
  const [selected, setSelected] = useState<Selection>(null);
  const data = readNegotiate(stage);
  const status = stage?.status ?? "pending";

  if (status === "locked") {
    return (
      <Banner tone="bad" title="Negotiate is locked">
        <span className="inline-flex items-center gap-1">
          <Lock size={16} aria-hidden="true" />
          {stage?.locked_reason ?? "An earlier stage has not passed."}
        </span>
      </Banner>
    );
  }
  if (!data) {
    return (
      <section aria-label="Negotiate" className="rounded-card border border-border bg-surface p-4" aria-busy={status === "running"}>
        {status === "pending" || status === "running" ? (
          <div className="flex flex-col gap-2" role="status" aria-label="Waiting for negotiation">
            <p className="text-sm text-text-dim">
              {status === "running"
                ? "Negotiating…"
                : "Negotiate runs after you approve the Decide plan."}
            </p>
            {status === "running" ? (
              <>
                <Skeleton className="h-4 w-64" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-text-dim">{stage?.error ?? "No negotiation output."}</p>
        )}
      </section>
    );
  }
  if (!data.gaps.length) {
    return (
      <section aria-label="Negotiate" className="rounded-card border border-border bg-surface p-4 text-sm">
        <div className="flex items-center gap-2">
          <CircleHelp size={16} aria-hidden="true" />
          <span className="font-medium">{stage?.summary || "No negotiation needed"}</span>
        </div>
        <p className="mt-1 text-text-dim">No SKU needed negotiating, so there is no call to review.</p>
      </section>
    );
  }

  const quoteTurns = new Set(data.gaps.filter((g) => g.turn != null && g.offered != null).map((g) => g.turn!));
  return (
    <div className="flex flex-col gap-4" data-testid="negotiate-view">
      <section aria-label="Negotiate summary" className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-base font-semibold">{stage?.summary}</h2>
        <p className="num mt-1 text-sm text-text-dim">
          {data.negotiatedSkus.length ? `${data.negotiatedSkus.length} SKUs negotiated · ` : ""}
          {data.verification ? `${data.verification.verified}/${data.verification.total} commitments verified` : ""}
          {data.verification && data.verification.rejected > 0 ? ` · ${data.verification.rejected} rejected` : ""}
        </p>
        <p className="mt-1 text-xs text-text-dim">Click an offered value to highlight where it was said on the call.</p>
      </section>
      <GapTable gaps={data.gaps} selected={selected} onSelect={setSelected} />
      <TranscriptPanel data={data} selected={selected} quoteTurns={quoteTurns} />
      <Refusals data={data} />
      <CounterOffer data={data} />
    </div>
  );
}
