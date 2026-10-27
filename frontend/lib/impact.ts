import { request } from "./api";

export type ImpactGate = {
  stage: string;
  label: string;
  status: "measured" | "pending";
  baseline_minutes: number;
  review_seconds: number | null;
  counted_minutes: number | null;
  capped: boolean;
  overrides: number;
  replans: number;
  edits: number;
};

export type ImpactTask = {
  task: string;
  label: string;
  gate: string;
  minutes: number;
  per_sku: boolean;
  count: number;
  total_minutes: number;
};

/** Per-run block from `GET /api/runs/{id}` (`impact`). */
export type RunImpact = {
  run_id: string;
  vendor_id: string;
  mode: string;
  baseline_status: "placeholder" | "measured";
  n_skus: number;
  tasks: ImpactTask[];
  gates: ImpactGate[];
  baseline_minutes: number;
  baseline_measured_minutes: number;
  human_minutes: number;
  reduction_pct: number | null;
  measured_gates: number;
  total_gates: number;
  complete: boolean;
  basis: "measured" | "baseline_estimate";
  edits: number;
  overrides: number;
  replans: number;
  max_review_minutes: number;
};

/** `GET /api/impact`. */
export type TeamImpact = {
  basis: "measured" | "baseline_estimate";
  measured_runs: number;
  partly_measured_runs: number;
  baseline_status: "placeholder" | "measured";
  human_share_pct: number;
  baseline_hours_per_vendor: number;
  human_hours_per_vendor: number;
  vendors_per_month: number;
  demand_hours_per_month: number;
  hours_saved_per_month: number;
  workload_hours_per_month: number;
  task_capacity_hours_per_month: number;
  pct_of_workload: number | null;
  pct_of_task_time: number | null;
  demand_vs_capacity_pct: number | null;
  target_pct: number;
  meets_target: boolean;
  formula: string;
  mode: string;
  team: {
    category_managers: number;
    vendors_onboarded_per_month: number;
    share_of_week_on_these_tasks_pct: number;
    work_hours_per_week: number;
    weeks_per_month: number;
  };
  vendors: { vendor_id: string; run_id: string; baseline_minutes: number; human_minutes: number; measured_gates: number; complete: boolean; reduction_pct: number | null }[];
};

export const fetchTeamImpact = (signal?: AbortSignal) =>
  request<TeamImpact>("GET", "/api/impact", { signal });

const MINUS = "−";

/** 855 -> "14.3 h", 45 -> "45 min", 0.2 -> "0.2 min". */
export function duration(minutes: number): string {
  if (minutes >= 60) return `${(minutes / 60).toFixed(1)} h`;
  if (minutes >= 10) return `${Math.round(minutes)} min`;
  return `${(Math.round(minutes * 10) / 10).toString()} min`;
}

export function reduction(pct: number | null): string {
  if (pct == null) return "—";
  return `${pct < 0 ? "+" : MINUS}${Math.abs(pct).toFixed(0)}%`;
}

/** The sentence shown in the impact drawer and the top-bar chip title. */
export function impactHeadline(i: RunImpact): string {
  const edits = `${i.edits} ${i.edits === 1 ? "edit" : "edits"}`;
  if (i.measured_gates === 0) return `Baseline ${duration(i.baseline_minutes)} by hand · human review not recorded yet`;
  if (i.complete) {
    return `This vendor: baseline ${duration(i.baseline_minutes)} → ${duration(i.human_minutes)} human review (${reduction(i.reduction_pct)}) · ${edits}`;
  }
  return `So far: baseline ${duration(i.baseline_measured_minutes)} → ${duration(i.human_minutes)} human review (${reduction(i.reduction_pct)}) on ${i.measured_gates} of ${i.total_gates} review steps · ${edits}`;
}

/** Short top-bar label. */
export function impactChipLabel(i: RunImpact): string {
  if (i.measured_gates === 0) return `Impact · ${duration(i.baseline_minutes)} baseline`;
  return `Impact ${reduction(i.reduction_pct)}${i.complete ? "" : " so far"}`;
}

export function reviewTime(g: ImpactGate): string {
  if (g.review_seconds == null) return "not reviewed yet";
  const shown = g.review_seconds < 60 ? `${Math.round(g.review_seconds)} s` : duration(g.review_seconds / 60);
  return g.capped ? `${shown} (counted as ${duration(g.counted_minutes ?? 0)})` : shown;
}
