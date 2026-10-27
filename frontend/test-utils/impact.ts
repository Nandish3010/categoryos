import type { RunImpact, TeamImpact } from "@/lib/impact";

/** A run with only the first review step approved: 10 minutes against 240 by hand. */
export function runImpact(over: Partial<RunImpact> = {}): RunImpact {
  return {
    run_id: "run1",
    vendor_id: "V001",
    mode: "mock",
    baseline_status: "placeholder",
    n_skus: 7,
    tasks: [
      { task: "screening", label: "Screening", gate: "research", minutes: 30, per_sku: false, count: 1, total_minutes: 30 },
      { task: "catalog_listing_per_sku", label: "Catalog listing, per SKU", gate: "catalog", minutes: 20, per_sku: true, count: 7, total_minutes: 140 },
    ],
    gates: [
      { stage: "research", label: "Decision review", status: "measured", baseline_minutes: 240, review_seconds: 600, counted_minutes: 10, capped: false, overrides: 1, replans: 1, edits: 2 },
      { stage: "catalog", label: "Negotiation and catalog review", status: "pending", baseline_minutes: 360, review_seconds: null, counted_minutes: null, capped: false, overrides: 0, replans: 0, edits: 0 },
      { stage: "po", label: "Launch packet review", status: "pending", baseline_minutes: 255, review_seconds: null, counted_minutes: null, capped: false, overrides: 0, replans: 0, edits: 0 },
    ],
    baseline_minutes: 855,
    baseline_measured_minutes: 240,
    human_minutes: 10,
    reduction_pct: 95.8,
    measured_gates: 1,
    total_gates: 3,
    complete: false,
    basis: "measured",
    edits: 2,
    overrides: 1,
    replans: 1,
    max_review_minutes: 120,
    ...over,
  };
}

export function teamImpact(over: Partial<TeamImpact> = {}): TeamImpact {
  return {
    basis: "baseline_estimate",
    measured_runs: 0,
    partly_measured_runs: 0,
    baseline_status: "placeholder",
    human_share_pct: 10,
    baseline_hours_per_vendor: 14.3,
    human_hours_per_vendor: 1.4,
    vendors_per_month: 8,
    demand_hours_per_month: 114,
    hours_saved_per_month: 102.6,
    workload_hours_per_month: 1039.2,
    task_capacity_hours_per_month: 467.6,
    pct_of_workload: 9.9,
    pct_of_task_time: 90,
    demand_vs_capacity_pct: 24.4,
    target_pct: 33.3,
    meets_target: false,
    formula: "hours saved per month = vendors per month x baseline hours per vendor x (1 - human review share)",
    mode: "mock",
    team: { category_managers: 6, vendors_onboarded_per_month: 8, share_of_week_on_these_tasks_pct: 45, work_hours_per_week: 40, weeks_per_month: 4.33 },
    vendors: [],
    ...over,
  };
}
