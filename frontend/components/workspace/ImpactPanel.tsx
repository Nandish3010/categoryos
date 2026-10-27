"use client";

import { Timer, X } from "lucide-react";
import Link from "next/link";
import { duration, impactChipLabel, impactHeadline, reviewTime, type RunImpact } from "@/lib/impact";
import { Tag } from "../Chip";
import { PanelHeader } from "../PanelHeader";

export function ImpactChip({ impact, open, onToggle }: { impact: RunImpact; open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-controls="impact-panel"
      title={impactHeadline(impact)}
      className="inline-flex h-8 items-center gap-1 rounded-chip border border-border bg-surface px-2 text-xs text-text-dim hover:text-text max-[899px]:hidden"
    >
      <Timer size={16} aria-hidden="true" />
      <span className="num">{impactChipLabel(impact)}</span>
    </button>
  );
}

/** Per-vendor impact drawer: the baseline by hand against the human review time the app recorded. */
export function ImpactPanel({ impact, onClose }: { impact: RunImpact; onClose: () => void }) {
  const placeholder = impact.baseline_status === "research_estimate";
  return (
    <section
      id="impact-panel"
      aria-label="Impact"
      className="fixed right-4 top-14 z-50 flex max-h-[calc(100vh-4.5rem)] w-[min(30rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-card border border-border bg-surface shadow-2xl"
    >
      <PanelHeader
        title="Impact on this vendor"
        right={
          <button
            type="button"
            onClick={onClose}
            aria-label="Close impact"
            className="inline-flex h-8 w-8 items-center justify-center rounded-chip text-text-dim hover:text-text"
          >
            <X size={16} aria-hidden="true" />
          </button>
        }
      />
      <div className="flex flex-col gap-3 overflow-y-auto p-4 text-sm">
        <p className="num text-base font-medium">{impactHeadline(impact)}</p>
        <div className="flex flex-wrap gap-2">
          {impact.basis === "measured" ? (
            <Tag tone="ok" title="Human time is the time between the stage reaching review and your approve click">
              Measured review time
            </Tag>
          ) : (
            <Tag tone="warn">Baseline estimate: nothing reviewed yet</Tag>
          )}
          {placeholder ? (
            <Tag tone="warn" title="From docs/research/category-manager-workload.md. Set impact.baseline_status to measured in the Playbook once you replace the times with your own">
              Research estimate (not measured)
            </Tag>
          ) : null}
          {impact.mode !== "live" ? <Tag>{impact.mode} run</Tag> : null}
        </div>

        <table className="w-full text-left text-xs">
          <caption className="sr-only">Review steps</caption>
          <thead className="text-text-dim">
            <tr>
              <th scope="col" className="py-1 pr-2 font-medium">Review step</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">By hand</th>
              <th scope="col" className="py-1 pr-2 font-medium">Human review</th>
              <th scope="col" className="py-1 text-right font-medium">Edits</th>
            </tr>
          </thead>
          <tbody>
            {impact.gates.map((g) => (
              <tr key={g.stage} className="border-t border-border" data-status={g.status}>
                <th scope="row" className="py-1.5 pr-2 font-normal">{g.label}</th>
                <td className="num py-1.5 pr-2 text-right">{duration(g.baseline_minutes)}</td>
                <td className="num py-1.5 pr-2">{reviewTime(g)}</td>
                <td className="num py-1.5 text-right">{g.status === "measured" ? g.edits : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <details className="text-xs">
          <summary className="cursor-pointer text-accent">Baseline by task ({impact.n_skus} SKUs)</summary>
          <ul className="mt-1 flex flex-col gap-0.5">
            {impact.tasks.map((t) => (
              <li key={t.task} className="flex justify-between gap-2">
                <span>{t.label}{t.per_sku ? ` × ${t.count}` : ""}</span>
                <span className="num">{duration(t.total_minutes)}</span>
              </li>
            ))}
          </ul>
        </details>

        <p className="text-xs text-text-dim">
          Human time runs from a stage reaching review to the approve click, counted up to {impact.max_review_minutes} minutes per
          step. Edits are verdict overrides and re-plans.{" "}
          {placeholder ? "The by-hand times are a research estimate (docs/research/category-manager-workload.md) until you replace them in the " : "The by-hand times come from the "}
          <Link href="/rules" className="text-accent hover:underline">Playbook</Link> (Impact).
        </p>
      </div>
    </section>
  );
}
