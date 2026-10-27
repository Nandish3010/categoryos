"use client";

import { Check, Send, X } from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/lib/api";
import { approveDraft, rejectDraft, type Draft } from "@/lib/ops";
import { Banner } from "../Banner";
import { Tag } from "../Chip";

const STATUS: Record<Draft["status"], { label: string; tone: "warn" | "ok" | "neutral" }> = {
  pending: { label: "Waiting for approval", tone: "warn" },
  sent_simulated: { label: "Sent (simulated)", tone: "ok" },
  rejected: { label: "Rejected", tone: "neutral" },
};

/** A drafted vendor message. Approving marks it sent in the simulator: nothing leaves the app. */
export function DraftCard({ draft, onChange }: { draft: Draft; onChange?: (d: Draft) => void }) {
  const [body, setBody] = useState(draft.body);
  const [current, setCurrent] = useState(draft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const pending = current.status === "pending";
  const st = STATUS[current.status];
  const bad = current.figures.filter((f) => f.status !== "verified" && f.shown && body.includes(f.shown));

  const act = async (fn: () => Promise<Draft>) => {
    setBusy(true);
    setError(null);
    try {
      const next = await fn();
      setCurrent(next);
      setBody(next.body);
      onChange?.(next);
    } catch (e) {
      setError(e instanceof ApiError ? e : null);
      if (!(e instanceof ApiError)) throw e;
    } finally {
      setBusy(false);
    }
  };

  return (
    <article aria-label={`Draft ${current.subject}`} className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold">{current.subject}</div>
          <div className="num text-xs text-text-dim">
            To {current.to} {"·"} {current.channel}
            {current.rung ? ` · ${current.rung}` : ""}
            {current.owner ? ` · owner: ${current.owner}` : ""}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {current.source === "template" ? <Tag title="The agent wrote no draft for this item, so the standard template was used">Template</Tag> : <Tag tone="accent">Agent draft</Tag>}
          <Tag tone={st.tone}>{st.label}</Tag>
        </div>
      </div>
      <div className="flex flex-col gap-3 p-4">
        {pending ? (
          <textarea
            aria-label="Message"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={Math.min(14, Math.max(5, body.split("\n").length + 1))}
            className="w-full resize-y rounded-card border border-border bg-bg p-3 font-sans text-sm leading-relaxed"
          />
        ) : (
          <pre className="whitespace-pre-wrap rounded-card border border-border bg-bg p-3 font-sans text-sm leading-relaxed">{current.body}</pre>
        )}
        {current.figures.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-text-dim">
            <span>Numbers checked:</span>
            {current.figures.map((f) => (
              <Tag key={f.claim_id} tone={f.status === "verified" ? "ok" : "bad"} title={f.reason ?? undefined}>
                {f.shown || "figure"} {f.status === "verified" ? "verified" : f.status}
              </Tag>
            ))}
          </div>
        ) : null}
        {pending && bad.length > 0 ? (
          <Banner tone="bad" title="This message states a number the verifier rejected">
            Remove or correct {bad.map((f) => f.shown).join(", ")} before approving.
          </Banner>
        ) : null}
        {current.warnings.length > 0 ? (
          <Banner tone="warn" title="Check your edit">
            {current.warnings.join("; ")}
          </Banner>
        ) : null}
        {error ? (
          <Banner tone="bad" title={error.body.problem}>
            {error.body.cause} {error.body.fix}
          </Banner>
        ) : null}
        {pending ? (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy || bad.length > 0}
              onClick={() => act(() => approveDraft(current.id, body !== current.body ? body : undefined))}
              className="inline-flex h-11 items-center gap-1.5 rounded-card bg-accent px-4 text-sm font-semibold text-bg disabled:opacity-50"
            >
              <Send size={16} aria-hidden="true" />
              Approve and send (simulated)
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => act(() => rejectDraft(current.id))}
              className="inline-flex h-11 items-center gap-1.5 rounded-card border border-border px-4 text-sm text-text-dim hover:bg-surface-2 disabled:opacity-50"
            >
              <X size={16} aria-hidden="true" />
              Reject
            </button>
            <span className="text-xs text-text-dim">Nothing is sent to the vendor: this is a simulator.</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-xs text-text-dim">
            <Check size={16} aria-hidden="true" />
            {current.status === "sent_simulated" ? "Marked sent in the simulator" : "Rejected"}
            {current.decided_at ? ` at ${current.decided_at.slice(11, 16)} UTC` : ""}. No message left this app.
          </div>
        )}
      </div>
    </article>
  );
}
