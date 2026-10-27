import type { RunImpact, TeamImpact } from "@/lib/impact";

/** A run with only the first review step approved: 10 minutes against 240 by hand. */
export function runImpact(over: Partial<RunImpact> = {}): RunImpact {
  return {
    run_id: "run1",
    vendor_id: "V001",
    mode: "mock",
    baseline_status: "research_estimate",
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
    basis: "research_estimate",
    measured_runs: 0,
    partly_measured_runs: 0,
    baseline_status: "research_estimate",
    in_scope_pct: 18.5,
    saved_pct: 8.8,
    potential_saved_pct: 34.6,
    target_pct: 33.3,
    meets_target: false,
    team_hours_per_month: 584.6,
    hours_saved_per_month: 51.4,
    roles: [
      { role: "category_manager", label: "Category managers", headcount: 1, in_scope_pct: 17.8, saved_pct: 8.2 },
      { role: "category_executive", label: "Category executives", headcount: 2, in_scope_pct: 18.8, saved_pct: 9.1 },
    ],
    modules: [
      { key: "new_vendor_onboarding", label: "New-vendor onboarding", status: "shipped", in_scope_pct: 18.5, saved_pct: 8.8, tasks: [] },
      { key: "weekly_review_mis", label: "Weekly review and MIS generator", status: "not_built", in_scope_pct: 11.7, saved_pct: 7.6, tasks: [] },
    ],
    onboarding: { typical_skus: 12, baseline_hours_per_vendor: 18.1, human_share_pct: null, saved_pct_basis: "research_estimate", vendors_per_month: 3.2, demand_hours_per_month: 57.9, team_hours_on_task_per_month: 62.4 },
    formula: "saved % of the week = sum over tasks of (share of the week x share covered x share saved)",
    mode: "mock",
    team: { category_managers: 1, category_executives: 2, work_hours_per_week: 45, weeks_per_month: 4.33, vendors_onboarded_per_month: 3.2, typical_skus_per_vendor: 12 },
    vendors: [],
    ...over,
  };
}
