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
  baseline_status: "research_estimate" | "measured";
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
  basis: "measured" | "research_estimate";
  edits: number;
  overrides: number;
  replans: number;
  max_review_minutes: number;
};

export type ImpactModule = {
  key: string;
  label: string;
  status: "shipped" | "not_built";
  in_scope_pct: number;
  saved_pct: number;
  tasks: { task: string; label: string; in_scope_pct: number }[];
};

/** `GET /api/impact`. */
export type TeamImpact = {
  basis: "measured" | "research_estimate";
  measured_runs: number;
  partly_measured_runs: number;
  baseline_status: "research_estimate" | "measured";
  /** Team week in scope of shipped modules, and saved, in % of the week. */
  in_scope_pct: number;
  saved_pct: number;
  /** Saving if every listed module were built (an estimate). */
  potential_saved_pct: number;
  target_pct: number;
  meets_target: boolean;
  team_hours_per_month: number;
  hours_saved_per_month: number;
  roles: { role: string; label: string; headcount: number; in_scope_pct: number; saved_pct: number }[];
  modules: ImpactModule[];
  onboarding: {
    typical_skus: number;
    baseline_hours_per_vendor: number;
    human_share_pct: number | null;
    saved_pct_basis: "measured" | "research_estimate";
    vendors_per_month: number;
    demand_hours_per_month: number;
    team_hours_on_task_per_month: number;
  };
  formula: string;
  mode: string;
  team: { category_managers: number; category_executives: number; work_hours_per_week: number; weeks_per_month: number; vendors_onboarded_per_month: number; typical_skus_per_vendor: number };
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
