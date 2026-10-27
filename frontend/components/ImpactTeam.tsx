"use client";

import { Tag } from "./Chip";
import { PanelHeader } from "./PanelHeader";
import { Stat } from "./Stat";
import type { TeamImpact } from "@/lib/impact";

const h = (n: number) => `${n.toLocaleString("en-IN", { maximumFractionDigits: 1 })} h`;
const p = (n: number) => `${n.toFixed(1)}%`;

/** Team projection on the vendors board: share of the team's week in scope of shipped modules, share saved, per module. */
export function ImpactTeam({ impact }: { impact: TeamImpact }) {
  const measured = impact.basis === "measured";
  const t = impact.team;
  const estimate = impact.baseline_status === "research_estimate";
  return (
    <section aria-label="Team impact" className="mb-4 rounded-card border border-border bg-surface">
      <PanelHeader
        title="Team impact (projection)"
        right={
          <span className="flex flex-wrap items-center gap-2">
            {measured ? (
              <Tag tone="ok">Onboarding measured on {impact.measured_runs} {impact.measured_runs === 1 ? "run" : "runs"}</Tag>
            ) : (
              <Tag tone="warn" title="No run has had all its review steps approved yet, so onboarding uses the research estimate">
                Estimate, not measured
              </Tag>
            )}
            {estimate ? <Tag tone="warn" title="docs/research/category-manager-workload.md">Research estimate (not measured)</Tag> : null}
            {impact.mode !== "live" ? <Tag>{impact.mode}</Tag> : null}
          </span>
        }
      />
      <div className="grid grid-cols-2 gap-4 p-4 md:grid-cols-4">
        <Stat label="Team week in scope of shipped modules" value={p(impact.in_scope_pct)} hint={`${t.category_managers} CM + ${t.category_executives} CE, ${t.work_hours_per_week} h week`} />
        <Stat label="Of the team's workload saved" value={p(impact.saved_pct)} hint={`goal ${impact.target_pct}% · ${impact.meets_target ? "met" : "not met"}`} />
        <Stat label="Hours saved per month" value={h(impact.hours_saved_per_month)} hint={`of ${h(impact.team_hours_per_month)}`} />
        <Stat label="If every module were built" value={p(impact.potential_saved_pct)} hint="estimate" />
      </div>
      <div className="overflow-x-auto px-4 pb-3">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">Modules</caption>
          <thead className="text-text-dim">
            <tr>
              <th scope="col" className="py-1 pr-2 font-medium">Module</th>
              <th scope="col" className="py-1 pr-2 font-medium">Status</th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">In scope</th>
              <th scope="col" className="py-1 text-right font-medium">Would save</th>
            </tr>
          </thead>
          <tbody>
            {impact.modules.map((m) => (
              <tr key={m.key} className="border-t border-border" data-status={m.status}>
                <th scope="row" className="py-1.5 pr-2 font-normal">{m.label}</th>
                <td className="py-1.5 pr-2">
                  {m.status === "shipped" ? <Tag tone="ok">Shipped</Tag> : <Tag>Not yet built</Tag>}
                </td>
                <td className="num py-1.5 pr-2 text-right">{p(m.in_scope_pct)}</td>
                <td className="num py-1.5 text-right">{p(m.saved_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="border-t border-border px-4 py-2 text-xs text-text-dim">
        <summary className="cursor-pointer text-accent">How this is calculated</summary>
        <p className="mt-1">{impact.formula}</p>
        <p className="num mt-1">
          {impact.roles.map((r) => `${r.label} (${r.headcount}): ${p(r.in_scope_pct)} in scope, ${p(r.saved_pct)} saved`).join(" · ")}.
        </p>
        <p className="mt-1">
          Onboarding a {impact.onboarding.typical_skus}-SKU vendor takes {h(impact.onboarding.baseline_hours_per_vendor)} by hand;{" "}
          {impact.onboarding.vendors_per_month} vendors a month is {h(impact.onboarding.demand_hours_per_month)}, against{" "}
          {h(impact.onboarding.team_hours_on_task_per_month)} the workload table gives the team for that task.{" "}
          {measured && impact.onboarding.human_share_pct != null
            ? `Onboarding's saved share is measured: human review took ${impact.onboarding.human_share_pct}% of the by-hand time over ${impact.measured_runs} fully reviewed ${impact.measured_runs === 1 ? "run" : "runs"}.`
            : `No run has been fully reviewed yet${impact.partly_measured_runs ? ` (${impact.partly_measured_runs} partly)` : ""}, so onboarding uses the table's estimate.`}{" "}
          {estimate
            ? "Times, task shares and team size are a research estimate (docs/research/category-manager-workload.md), not measured; replace them in the Playbook (Impact)."
            : "Times, task shares and team size come from the Playbook (Impact)."}{" "}
          Only shipped modules count; register a module and its task coverage in the Playbook.
        </p>
      </details>
    </section>
  );
}
