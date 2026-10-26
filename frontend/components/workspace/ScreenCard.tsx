"use client";

import { ChevronDown, ChevronRight, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { ScreenData } from "@/lib/runs";
import { screenDefaultOpen, screenSummary } from "@/lib/screen";
import { Tag } from "../Chip";
import { PanelHeader } from "../PanelHeader";

/**
 * Screen result. A pass collapses to a one-line summary; a fail (V004) or a detected
 * prompt injection starts expanded. The Screen stage view passes `forceOpen`.
 */
export function ScreenCard({ screen, forceOpen = false }: { screen: ScreenData; forceOpen?: boolean }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? (forceOpen || screenDefaultOpen(screen));
  const failed = screenDefaultOpen(screen);

  if (!open) {
    return (
      <section aria-label="Screen" className="rounded-card border border-border bg-surface">
        <button
          type="button"
          aria-expanded={false}
          onClick={() => setUserOpen(true)}
          className="flex min-h-11 w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-surface-2"
        >
          <span className="text-xs font-medium uppercase tracking-wide text-text-dim">Screen</span>
          <span className="num min-w-0 flex-1 truncate text-text-dim">{screenSummary(screen)}</span>
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </section>
    );
  }

  return (
    <section aria-label="Screen" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Screen"
        right={
          <button
            type="button"
            aria-expanded={true}
            onClick={() => setUserOpen(false)}
            className="inline-flex min-h-8 items-center gap-1 hover:text-text"
          >
            <ChevronDown size={16} aria-hidden="true" />
            Collapse
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
        {screen.decision ? <Tag tone={failed ? "bad" : "neutral"}>Decision: {screen.decision}</Tag> : null}
        <span className="num text-xs text-text-dim">{screenSummary(screen)}</span>
      </div>
      <div className="flex flex-col gap-3 p-4 text-sm">
        {screen.reasons.length ? (
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">Reasons</h3>
            <ul className="list-disc pl-5 text-text-dim">
              {screen.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <div>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-dim">Documents</h3>
          {screen.documents.length ? (
            <ul className="flex flex-col gap-1">
              {screen.documents.map((d, i) => (
                <li key={`${d.label}-${i}`} className="flex items-center justify-between gap-2">
                  <span>{d.label}</span>
                  {d.status ? <Tag tone={/miss|absent|fail|expire|invalid/i.test(d.status) ? "bad" : "ok"}>{d.status}</Tag> : null}
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
    </section>
  );
}
