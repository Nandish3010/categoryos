"use client";

import { Brain, Calculator, CheckCircle2, Wrench } from "lucide-react";
import type { Claim } from "@/lib/api";
import type { TraceRow, Verification } from "@/lib/ops";
import { ClaimRow } from "../ClaimRow";
import { PanelHeader } from "../PanelHeader";
import { TraceItem } from "../TraceItem";

const ICON = {
  tool_call: <Wrench size={16} aria-hidden="true" />,
  model_call: <Brain size={16} aria-hidden="true" />,
  self_correction: <Brain size={16} aria-hidden="true" />,
  claim_verified: <CheckCircle2 size={16} aria-hidden="true" />,
  claim_rejected: <Calculator size={16} aria-hidden="true" />,
} as const;

function traceTitle(t: TraceRow): string {
  const p = t.payload as Record<string, unknown>;
  switch (t.type) {
    case "tool_call":
      return `Read ${String(p.tool)}`;
    case "model_call":
      return `Model call: ${String(p.task)} (${String(p.mode)})`;
    case "self_correction":
      return `Self-correction ${String(p.attempt)} of ${String(p.of)}`;
    case "claim_rejected":
      return "Verifier rejected a number";
    case "claim_verified":
      return "Corrected answer verified";
    case "claim_unresolved":
      return "Still wrong after the last retry: left rejected";
    case "stage_started":
      return "Run started";
    case "degraded":
      return String(p.reason ?? "Served a fallback fixture");
    default:
      return t.type;
  }
}

function traceDetail(t: TraceRow): string | undefined {
  const p = t.payload as Record<string, unknown>;
  if (t.type === "tool_call") return String(p.result_summary ?? "");
  if (t.type === "self_correction") return (p.feedback as string[] | undefined)?.join(" ");
  if (t.type === "claim_rejected") return String((p.claim as Claim | undefined)?.reason ?? "");
  return undefined;
}

/** What the agent read, which numbers it wrote, and whether the verifier agreed. claim_checked rows are folded into the counts. */
export function VerifierPanel({ verification, claims, trace }: { verification: Verification; claims: Claim[]; trace: TraceRow[] }) {
  const shown = trace.filter((t) => t.type !== "claim_checked");
  const flagged = claims.filter((c) => c.status !== "verified");
  const rest = claims.filter((c) => c.status === "verified");
  return (
    <section aria-label="Verifier" className="rounded-card border border-border bg-surface">
      <PanelHeader
        title="Verifier and trace"
        right={
          <span className="num">
            {verification.verified}/{verification.total} verified
            {verification.rejected ? ` · ${verification.rejected} rejected` : ""}
          </span>
        }
      />
      <div className="grid gap-0 md:grid-cols-2">
        <div className="border-b border-border md:border-b-0 md:border-r">
          <h3 className="px-4 pt-3 text-xs font-medium uppercase tracking-wide text-text-dim">Agent steps</h3>
          <ol className="max-h-96 overflow-y-auto">
            {shown.map((t) => (
              <TraceItem
                key={t.seq}
                time={`${(t.t_rel_ms / 1000).toFixed(1)}s`}
                title={traceTitle(t)}
                icon={ICON[t.type as keyof typeof ICON]}
                meta={t.model ? `${t.model}${t.latency_ms ? ` · ${Math.round(t.latency_ms)} ms` : ""} · $${(t.cost_usd ?? 0).toFixed(2)}` : undefined}
              >
                {traceDetail(t)}
              </TraceItem>
            ))}
          </ol>
        </div>
        <div>
          <h3 className="px-4 pt-3 text-xs font-medium uppercase tracking-wide text-text-dim">Numbers checked</h3>
          <ul className="max-h-96 overflow-y-auto">
            {flagged.map((c) => (
              <ClaimRow key={c.id} claim={c} />
            ))}
            {rest.slice(0, 40).map((c) => (
              <ClaimRow key={c.id} claim={c} />
            ))}
          </ul>
          {rest.length > 40 ? <p className="px-4 py-2 text-xs text-text-dim">{rest.length - 40} more verified numbers not shown.</p> : null}
        </div>
      </div>
    </section>
  );
}
