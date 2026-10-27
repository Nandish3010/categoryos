import { post, request, type Claim } from "./api";
import type { ImpactCoverage, TraceRow, Verification } from "./ops";

/** Run: catalog fixes for existing listings. Types mirror backend/app/ops/catalog_qc (live shapes are the mock/replay shapes). */

export type Severity = "low" | "medium" | "high";
export type Decision = "pending" | "approved" | "rejected" | "blocked" | "none";

export type Signals = { gmv: number; severity: number; return_rate: number };

export type QueueRow = {
  id: string;
  rank: number;
  listing_id: string;
  vendor_id: string;
  brand: string;
  sku_code: string;
  listing_title: string;
  type: string;
  severity: Severity;
  message: string;
  detail: Record<string, unknown>;
  score: number;
  signals: Signals;
  gmv_at_risk_inr: number;
  nad_rate_pct: number | null;
  fix_id: string | null;
  fix_status: "ready" | "blocked" | "none";
  no_fix_reason: string | null;
  decision: Decision;
};

export type FixChange = { field: string; label: string; before: unknown; after: unknown; before_text: string; after_text: string };

export type Fix = {
  id: string;
  listing_id: string;
  vendor_id: string;
  sku_code: string;
  kind: string;
  source: "deterministic" | "label" | "model";
  title: string;
  issue_ids: string[];
  issue_types: string[];
  changes: FixChange[];
  claim_ids: string[];
  status: "ready" | "blocked";
  reason: string | null;
  notes: string[];
  claims_verified: number;
  claims_total: number;
  decision: Decision;
  decided_at: string | null;
};

export type LabelRow = {
  field: string;
  field_label: string;
  label_value: string;
  listing_value: string;
  status: "match" | "mismatch" | "unreliable";
  claim_id: string | null;
  claim_status: string;
};

export type Listing = {
  listing_id: string;
  vendor_id: string;
  brand: string;
  sku_code: string;
  title: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  fixes: string[];
  issue_ids: string[];
  gmv_at_risk_inr: number;
  top_score: number;
  label: { doc: string; title: string; url: string; rows: LabelRow[]; mismatches: number } | null;
};

export type Summary = {
  issues: number;
  fixes_total: number;
  fixes_ready: number;
  fixes_blocked: number;
  fixes_approved: number;
  fixes_rejected: number;
  listings_ready: number;
  minutes_per_listing: number;
  minutes_saved: number;
  minutes_saved_approved: number;
  baseline_status: string;
};

export type CatalogUpdate = { id: string; listing_id: string; fix_ids: string[]; changes: FixChange[]; status: string; simulated: boolean; queued_at: string };

export type CatalogQueue = {
  as_of: string;
  mode: string;
  degraded: boolean;
  degraded_reason: string | null;
  vendors: { id: string; brand: string }[];
  issue_types: string[];
  rows: QueueRow[];
  listings: Listing[];
  fixes: Record<string, Fix>;
  claims: Claim[];
  verification: Verification;
  corrected: string[];
  unresolved: string[];
  counts: { listings: number; listings_with_issues: number; issues: number; by_type: Record<string, number> };
  trace: TraceRow[];
  limits: { bulk_approve: number };
  summary: Summary;
  updates: CatalogUpdate[];
  simulated: true;
  impact_coverage: ImpactCoverage;
};

export type BulkResult = { simulated?: boolean; approved?: string[]; rejected?: string[]; skipped: { fix_id: string; reason: string }[] };

export const fetchCatalog = (inject: boolean, signal?: AbortSignal) => request<CatalogQueue>("GET", `/api/ops/catalog${inject ? "?inject=1" : ""}`, { signal });
export const approveFix = (id: string) => post<{ fix_id: string; status: string }>(`/api/ops/catalog/fixes/${encodeURIComponent(id)}/approve`, {});
export const rejectFix = (id: string) => post<{ fix_id: string; status: string }>(`/api/ops/catalog/fixes/${encodeURIComponent(id)}/reject`, {});
export const bulkApprove = (ids: string[]) => post<BulkResult>("/api/ops/catalog/bulk-approve", { fix_ids: ids });
export const bulkReject = (ids: string[]) => post<BulkResult>("/api/ops/catalog/bulk-reject", { fix_ids: ids });

export const ISSUE_LABEL: Record<string, string> = {
  title_too_long: "Title too long",
  title_missing_attributes: "Title missing words",
  missing_attribute: "Missing attribute",
  banned_claim: "Banned claim",
  mrp_mismatch: "MRP mismatch",
  pack_mismatch: "Pack mismatch",
  duplicate_listing: "Duplicate",
  wrong_category: "Wrong category",
  missing_image: "No image",
  low_res_image: "Low-res image",
  high_returns_not_as_described: "Returns: not as described",
  expired_licence: "Expired licence",
  label_mismatch: "Label mismatch",
};

export const SEVERITY_TONE: Record<Severity, "bad" | "warn" | "neutral"> = { high: "bad", medium: "warn", low: "neutral" };

export const DECISION_LABEL: Record<Decision, string> = {
  pending: "Ready",
  approved: "Approved (simulated)",
  rejected: "Rejected",
  blocked: "Not verified",
  none: "No automatic fix",
};

/** The queue rows that pass both filters ("all" turns a filter off). */
export function filterRows(rows: QueueRow[], type: string, vendor: string): QueueRow[] {
  return rows.filter((r) => (type === "all" || r.type === type) && (vendor === "all" || r.vendor_id === vendor));
}

/** Fix ids a bulk action may act on in this view: pending fixes that verified, once each, capped at the playbook limit. */
export function selectable(rows: QueueRow[], fixes: Record<string, Fix>, limit: number): string[] {
  const ids: string[] = [];
  for (const r of rows) {
    const f = r.fix_id ? fixes[r.fix_id] : undefined;
    if (f && f.decision === "pending" && f.status === "ready" && !ids.includes(f.id)) ids.push(f.id);
  }
  return ids.slice(0, limit);
}

/** The headline counter: "N fixes ready · est. X minutes saved". Minutes come from the playbook's impact baseline. */
export function counterText(s: Summary): string {
  const mins = Math.round(s.minutes_saved);
  return `${s.fixes_ready} ${s.fixes_ready === 1 ? "fix" : "fixes"} ready · est. ${mins.toLocaleString("en-IN")} ${mins === 1 ? "minute" : "minutes"} saved`;
}

/** Fields shown in a listing's diff: those any live (pending or approved) fix changes, in a stable order. */
export function diffChanges(fixes: Fix[]): FixChange[] {
  const merged = new Map<string, FixChange>();
  for (const f of fixes) {
    if (f.status !== "ready" || (f.decision !== "pending" && f.decision !== "approved")) continue;
    for (const c of f.changes) {
      const prev = merged.get(c.field);
      merged.set(c.field, prev ? { ...prev, after: c.after, after_text: c.after_text } : c);
    }
  }
  return [...merged.values()];
}
