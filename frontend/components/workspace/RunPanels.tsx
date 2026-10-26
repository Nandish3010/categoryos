"use client";

import { Check, Copy, Loader2, Play, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { ResearchData } from "@/lib/runs";
import { Tag } from "../Chip";
import { PanelHeader } from "../PanelHeader";

export function RunBar({
  running,
  hasRun,
  disabled,
  unavailable,
  onRun,
}: {
  running: boolean;
  hasRun: boolean;
  disabled?: boolean;
  unavailable?: boolean;
  onRun: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="text-xs text-text-dim">
        {unavailable
          ? "Agent runs are not available on this backend."
          : running
            ? "Agents are working. Results appear as each stage finishes."
            : hasRun
              ? "Showing the latest agent run."
              : "No agent run yet. The numbers below are from the rules engine."}
      </p>
      <button
        type="button"
        onClick={onRun}
        disabled={running || disabled || unavailable}
        aria-busy={running}
        className="inline-flex h-11 shrink-0 items-center gap-2 rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:cursor-not-allowed disabled:opacity-60"
      >
        {running ? (
          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
        ) : (
          <Play size={16} aria-hidden="true" />
        )}
        {running ? "Running…" : hasRun ? "Re-run agents" : "Run agents"}
      </button>
    </div>
  );
}


export function NarrativeCard({
  research,
  stale,
  replanning,
  replanError,
  onReplan,
}: {
  research: ResearchData;
  stale: boolean;
  replanning: boolean;
  replanError?: string | null;
  onReplan: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(research.email_draft ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked */
    }
  };
  return (
    <section
      aria-label="Agent narrative"
      data-stale={stale}
      className="rounded-card border border-border bg-surface"
    >
      <PanelHeader
        title="Agent narrative"
        right={
          <span className="flex items-center gap-2">
            {research.replanned ? <Tag tone="accent">Re-planned</Tag> : null}
            {stale ? <Tag tone="warn">stale</Tag> : null}
          </span>
        }
      />
      <div className={`flex flex-col gap-3 p-4 text-sm ${stale ? "opacity-50" : ""}`}>
        {research.headline ? <p className="text-base font-medium">{research.headline}</p> : null}

        {research.rationale.length ? (
          <ul className="flex flex-col gap-1">
            {research.rationale.map((r) => (
              <li key={r.code}>
                <span className="font-mono text-xs text-text-dim">{r.code}</span>{" "}
                {r.verdict ? <span className="text-xs text-text-dim">({r.verdict})</span> : null} {r.why}
              </li>
            ))}
          </ul>
        ) : null}

        {research.struck.length ? (
          <ul className="flex flex-col gap-2">
            {research.struck.map((s, i) => (
              <li key={`${s.code}-${i}`}>
                <s className="text-text-dim">{s.text}</s>
                <div className="text-xs text-bad">Removed by verifier: {s.reason}</div>
              </li>
            ))}
          </ul>
        ) : null}

        {research.terms.length || research.email_draft ? (
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">Counter-offer</h3>
            {research.terms.length ? (
              <ul className="list-disc pl-5">
                {research.terms.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            ) : null}
            {research.email_draft ? (
              <div className="mt-2 rounded-card border border-border bg-surface-2 p-3">
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs text-text-dim">Email draft</span>
                  <button
                    type="button"
                    onClick={copy}
                    className="inline-flex min-h-8 items-center gap-1 text-xs text-accent hover:underline"
                  >
                    {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                    {copied ? "Copied" : "Copy"}
                  </button>
                </div>
                <pre className="whitespace-pre-wrap font-sans text-sm">{research.email_draft}</pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {stale ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
          <button
            type="button"
            onClick={onReplan}
            disabled={replanning}
            className="inline-flex h-11 items-center gap-2 rounded-card border border-accent px-3 text-sm font-medium text-accent disabled:opacity-60"
          >
            {replanning ? (
              <Loader2 size={16} className="animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw size={16} aria-hidden="true" />
            )}
            {replanning ? "Re-planning…" : "Re-plan with agent"}
          </button>
          <span className="text-xs text-text-dim">
            {replanError ? `Re-plan failed, showing previous: ${replanError}` : "Lever moved since this narrative was written."}
          </span>
        </div>
      ) : null}
    </section>
  );
}
