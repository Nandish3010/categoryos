"use client";

import { Tag } from "./Chip";
import { PanelHeader } from "./PanelHeader";
import { Stat } from "./Stat";
import type { TeamImpact } from "@/lib/impact";

const h = (n: number) => `${n.toLocaleString("en-IN", { maximumFractionDigits: 1 })} h`;

/** Team projection on the vendors board. Says what it is built from: measured runs, or baseline estimates. */
export function ImpactTeam({ impact }: { impact: TeamImpact }) {
  const measured = impact.basis === "measured";
  const t = impact.team;
  return (
    <section aria-label="Team impact" className="mb-4 rounded-card border border-border bg-surface">
      <PanelHeader
        title="Team impact (projection)"
        right={
          <span className="flex flex-wrap items-center gap-2">
            {measured ? (
              <Tag tone="ok">Measured on {impact.measured_runs} {impact.measured_runs === 1 ? "run" : "runs"}</Tag>
            ) : (
              <Tag tone="warn" title="No run has had all its review steps approved yet, so the human share is the playbook's assumption">
                Baseline estimate
              </Tag>
            )}
            {impact.baseline_status === "placeholder" ? <Tag tone="warn">Placeholder baselines</Tag> : null}
            {impact.mode !== "live" ? <Tag>{impact.mode}</Tag> : null}
          </span>
        }
      />
      <div className="grid grid-cols-2 gap-4 p-4 md:grid-cols-4">
        <Stat
          label="Hours saved per month"
          value={h(impact.hours_saved_per_month)}
          hint={`${t.vendors_onboarded_per_month} vendors a month`}
        />
        <Stat
          label="Of category-team workload"
          value={impact.pct_of_workload == null ? "—" : `${impact.pct_of_workload.toFixed(1)}%`}
          hint={`goal ${impact.target_pct}% · ${impact.meets_target ? "met" : "not met"}`}
        />
        <Stat
          label="By hand, per vendor"
          value={h(impact.baseline_hours_per_vendor)}
          hint="placeholder times from the Playbook"
        />
        <Stat
          label="Human review, per vendor"
          value={h(impact.human_hours_per_vendor)}
          hint={measured ? `${impact.human_share_pct.toFixed(1)}% of by-hand time, measured` : `${impact.human_share_pct.toFixed(0)}% assumed`}
        />
      </div>
      <details className="border-t border-border px-4 py-2 text-xs text-text-dim">
        <summary className="cursor-pointer text-accent">How this is calculated</summary>
        <p className="mt-1">{impact.formula}.</p>
        <p className="num mt-1">
          {t.vendors_onboarded_per_month} vendors × {impact.baseline_hours_per_vendor.toFixed(1)} h × (1 − {impact.human_share_pct.toFixed(1)}%) ={" "}
          {h(impact.hours_saved_per_month)} saved of {h(impact.workload_hours_per_month)} ({t.category_managers} managers × {t.work_hours_per_week} h × {t.weeks_per_month} weeks).
        </p>
        <p className="mt-1">
          {measured
            ? `The human share is the recorded review time over ${impact.measured_runs} fully reviewed ${impact.measured_runs === 1 ? "run" : "runs"}.`
            : `No run has been fully reviewed yet${impact.partly_measured_runs ? ` (${impact.partly_measured_runs} partly)` : ""}, so the human share is the Playbook's assumption.`}{" "}
          {impact.baseline_status === "placeholder"
            ? "Team size, vendor volume and the by-hand times are Playbook placeholders until you replace them"
            : "Team size, vendor volume and the by-hand times come from the Playbook"}
          {impact.demand_vs_capacity_pct != null
            ? `; together they put by-hand demand at ${impact.demand_vs_capacity_pct.toFixed(0)}% of the ${h(impact.task_capacity_hours_per_month)} the team has for these tasks.`
            : "."}
        </p>
      </details>
    </section>
  );
}
