"use client";

import { Check, ChevronDown, ChevronRight, Copy, Loader2, Play, RefreshCw, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { ResearchData, ScreenData } from "@/lib/runs";
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

export function ScreenCard({ screen }: { screen: ScreenData }) {
  const [open, setOpen] = useState(true);
  return (
    <section aria-label="Screen" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Screen"
        right={
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="inline-flex min-h-8 items-center gap-1 hover:text-text"
          >
            {open ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
            {open ? "Collapse" : "Expand"}
          </button>
        }
      />
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
        {screen.injection_detected ? (
          <Tag tone="bad">
            <ShieldAlert size={16} aria-hidden="true" />
            Prompt injection detected — ignored
          </Tag>
        ) : null}
        {screen.decision ? <Tag tone="neutral">Decision: {screen.decision}</Tag> : null}
      </div>
      {open ? (
        <div className="flex flex-col gap-3 p-4 text-sm">
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">Documents</h3>
            {screen.documents.length ? (
              <ul className="flex flex-col gap-1">
                {screen.documents.map((d) => (
                  <li key={d.label} className="flex items-center justify-between gap-2">
                    <span>{d.label}</span>
                    {d.status ? <Tag tone={/miss|absent|fail/i.test(d.status) ? "bad" : "ok"}>{d.status}</Tag> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-text-dim">No documents listed.</p>
            )}
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">Risk flags</h3>
            {screen.risk_flags.length ? (
              <ul className="flex flex-col gap-2">
                {screen.risk_flags.map((f, i) => (
                  <li key={`${f.type}-${i}`}>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{f.type}</span>
                      <Tag tone={/high|critical/i.test(f.severity) ? "bad" : "warn"}>{f.severity}</Tag>
                    </div>
                    {f.quote ? (
                      <blockquote className="mt-1 border-l-2 border-border pl-3 text-text-dim">
                        “{f.quote}”
                      </blockquote>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-text-dim">No risk flags.</p>
            )}
          </div>
          {screen.followup_questions.length ? (
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">Follow-up questions</h3>
              <ul className="list-disc pl-5 text-text-dim">
                {screen.followup_questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
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
