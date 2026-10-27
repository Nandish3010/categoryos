"use client";

import { ChevronDown, ChevronRight, ScanSearch, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { isProblem, scannedSummary, type Scanned } from "@/lib/docs";
import type { ScreenData } from "@/lib/runs";
import { screenDefaultOpen, screenSummary } from "@/lib/screen";
import { Tag } from "../Chip";
import { PanelHeader } from "../PanelHeader";
import { DocViewer } from "./DocViewer";

const docTone = (status: string) => (/miss|absent|fail|expired|invalid/i.test(status) ? "bad" : /expiring|pending/i.test(status) ? "warn" : "ok");

/** What the vision models read off the vendor's scans, and where it disagrees with what the vendor declared. */
export function ScannedDocuments({ scanned }: { scanned: Scanned }) {
  const [open, setOpen] = useState(false);
  const problems = scanned.findings.filter(isProblem);
  const agreed = scanned.findings.length - problems.length;
  return (
    <div aria-label="Scanned documents" role="group" className="flex flex-col gap-2" data-testid="scanned-documents">
      <h3 className="text-xs font-medium uppercase tracking-wide text-text-dim">Scanned documents</h3>
      <p className="num text-text-dim">{scannedSummary(scanned)}</p>
      {problems.length ? (
        <ul className="flex flex-col gap-1">
          {problems.map((f) => (
            <li key={f.id} className="flex items-start gap-2 rounded-chip border border-bad/40 bg-bad/10 px-2 py-1.5" data-finding={f.check}>
              <Tag tone={f.severity === "high" ? "bad" : "warn"}>{f.status === "mismatch" ? "Mismatch" : f.status === "injection" ? "Injection" : "Unclear"}</Tag>
              <span className="min-w-0 flex-1">{f.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {agreed > 0 ? <p className="text-xs text-text-dim">{agreed} check{agreed === 1 ? " agrees" : "s agree"} with the application and the SKU sheet.</p> : null}
      <ul className="flex flex-col gap-1">
        {scanned.documents.map((d) => (
          <li key={d.file} className="flex flex-wrap items-center gap-2">
            <span>{d.title}</span>
            {d.expiry ? (
              <Tag tone={d.expiry.state === "expired" ? "bad" : d.expiry.state === "expiring_soon" ? "warn" : "ok"}>
                {d.expiry.state === "valid" ? "valid until" : d.expiry.state.replace("_", " ")} {d.expiry.validUntil}
              </Tag>
            ) : null}
            {d.error ? <Tag tone="warn">not used</Tag> : null}
          </li>
        ))}
      </ul>
      {scanned.documents.length ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="inline-flex min-h-8 w-fit items-center gap-1 text-accent hover:underline"
        >
          <ScanSearch size={16} aria-hidden="true" />
          {open ? "Hide the scans" : "Show the scans with what was read"}
        </button>
      ) : null}
      {open ? <DocViewer documents={scanned.documents} findings={scanned.findings} /> : null}
    </div>
  );
}

/**
 * Screen result. A pass collapses to a one-line summary; a fail (V004) or a detected
 * prompt injection starts expanded. The Screen stage view passes `forceOpen`.
 */
export function ScreenCard({ screen, forceOpen = false }: { screen: ScreenData; forceOpen?: boolean }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? (forceOpen || screenDefaultOpen(screen));
  const failed = screen.decision != null && /fail|reject|block|deny|denied/i.test(screen.decision);

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
                  <span>
                    {d.label}
                    {d.source === "scan" && d.declaredValidUntil && d.declaredValidUntil !== d.validUntil ? (
                      <span className="ml-2 text-xs text-text-dim">
                        declared {d.declaredStatus ?? "valid"} until {d.declaredValidUntil}
                      </span>
                    ) : null}
                  </span>
                  <span className="flex items-center gap-1">
                    {d.source === "scan" ? <Tag tone="accent" title="The scanned certificate decided this status, not the application">from scan</Tag> : null}
                    {d.status ? <Tag tone={docTone(d.status)}>{d.status.replace("_", " ")}</Tag> : null}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-text-dim">No documents listed.</p>
          )}
        </div>
        {screen.scanned ? <ScannedDocuments scanned={screen.scanned} /> : null}
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
