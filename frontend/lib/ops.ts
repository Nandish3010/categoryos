import { post, request, type Claim } from "./api";

const get = <T>(path: string, signal?: AbortSignal) => request<T>("GET", path, { signal });
import { days, inrCompact, pct, pctSigned } from "./format";

/** Run: existing vendors. Types mirror backend/app/ops (assumed live shapes are the same as mock/replay). */

export type TraceRow = {
  seq: number;
  t_rel_ms: number;
  type: string;
  stage: string | null;
  model: string | null;
  latency_ms: number | null;
  cost_usd: number | null;
  payload: Record<string, unknown>;
};

export type Verification = { total: number; verified: number; rejected: number; unverifiable: number };

export type SkuRow = {
  sku_code: string;
  name: string;
  gmv: number;
  units: number;
  units_prev: number;
  growth_wow: number | null;
  units_z: number | null;
  on_hand: number;
  daily_rate: number;
  cover_days: number | null;
  return_rate: number | null;
  rating: number | null;
  rating_change: number | null;
  series: number[];
};

export type AgeBucket = { label: string; units: number; value_inr: number };

export type Scorecard = {
  vendor_id: string;
  brand: string;
  company_name: string;
  category: string;
  week_start: string;
  week_end: string;
  gmv: number;
  units: number;
  gmv_growth_wow: number | null;
  gmv_z: number | null;
  margin_pct: number | null;
  fill_rate: number | null;
  fill_rate_recent: number | null;
  fill_rate_prior: number | null;
  otif: number | null;
  min_cover_days: number | null;
  stock_value_inr: number;
  ageing: AgeBucket[];
  aged_pct: number;
  return_rate: number | null;
  rating: number | null;
  rating_change: number | null;
  series: number[];
  skus?: SkuRow[];
};

export type Anomaly = {
  id: string;
  vendor_id: string;
  sku_code: string | null;
  type: string;
  severity: number;
  metric: string;
  key: string;
  value: number;
  threshold: number;
  reason: string;
  explanation?: string | null;
  exposure_inr: number;
};

export type Action = {
  id: string;
  anomaly_id: string;
  vendor_id: string;
  sku_code: string | null;
  type: string;
  title: string;
  severity: number;
  score: number;
  exposure_inr: number;
  rank: number;
  deterministic_rank: number;
  llm_rank: number | null;
  rationale: string | null;
};

export type DraftFigure = { claim_id: string; shown: string; status: string; reason: string | null };

export type Draft = {
  id: string;
  kind: "vendor_review" | "po_followup" | "promo_funding" | "price_watch";
  vendor_id: string;
  po_id: string | null;
  channel: string;
  subject: string;
  body: string;
  to: string;
  source: "agent" | "template";
  status: "pending" | "sent_simulated" | "rejected";
  simulated: boolean;
  edited: boolean;
  decided_at: string | null;
  figures: DraftFigure[];
  blocked_by: string[];
  warnings: string[];
  rung?: string;
  owner?: string;
  note?: string | null;
};

export type ImpactCoverage = {
  module: string;
  registered: boolean;
  status: string;
  tasks: { task: string; in_scope_pct: number }[];
  units: Record<string, number>;
  baseline_minutes: Record<string, number>;
  manual_minutes_replaced: number;
  baseline_status: string;
};

export type Review = {
  as_of: string;
  week_start: string;
  week_end: string;
  mode: string;
  degraded: boolean;
  category: {
    gmv: number;
    gmv_prev: number;
    gmv_growth_wow: number | null;
    units: number;
    margin_pct: number | null;
    fill_rate: number | null;
    fill_rate_recent: number | null;
    otif: number | null;
    vendor_count: number;
    sku_count: number;
    series: number[];
  };
  vendors: Scorecard[];
  anomalies: Anomaly[];
  actions: Action[];
  headline: string;
  narrative: string;
  mis_markdown: string;
  flagged_vendors: string[];
  drafts: Draft[];
  claims: Claim[];
  verification: Verification;
  unclaimed_numbers: string[];
  trace: TraceRow[];
  impact_coverage: ImpactCoverage;
};

export type Rung = { index: number; name: string; channel: string; owner: string; tone: string; bumped_by_vague_reply: boolean; of: number };

export type PoLine = {
  sku_code: string;
  name: string;
  ordered: number;
  received: number;
  open_qty: number;
  on_hand: number;
  daily_rate: number;
  cover_days: number | null;
  arrival: string;
  arrival_basis: "vendor_reply" | "promised_date" | "assumed";
  remaining_lead_days: number;
  stockout_days: number;
  lost_gmv: number;
  risk: Risk;
  suggested_reorder?: number;
};

export type Risk = "critical" | "high" | "medium" | "low";

export type Po = {
  po_id: string;
  vendor_id: string;
  brand: string;
  po_date: string;
  promised_date: string;
  days_overdue: number;
  status: "on_track" | "due_soon" | "overdue";
  partial: boolean;
  ordered_qty: number;
  received_qty: number;
  fill_so_far: number | null;
  eta: string | null;
  vague_reply: boolean;
  reply_ids: string[];
  risk: Risk;
  stockout_days: number;
  lost_gmv: number;
  rung: Rung | null;
  needs_chase: boolean;
  lines: PoLine[];
};

export type Commitment = {
  kind: "eta_date" | "qty";
  quote: string;
  eta_date: string | null;
  qty: number | null;
  note: string | null;
  claim_id: string | null;
  status: string;
  reason: string | null;
  first_value: number | null;
  corrected: boolean;
  resolved_eta: string | null;
};

export type Reading = {
  reply_id: string;
  po_id: string;
  vendor_id: string;
  received_at: string;
  from: string;
  subject: string;
  body: string;
  stance: string;
  summary: string;
  excuse: string | null;
  root_cause: string;
  commitments: Commitment[];
};

export type PoTracker = {
  as_of: string;
  mode: string;
  pos: Po[];
  readings: Reading[];
  ladder: { name: string; days_overdue: number; channel: string; owner: string; tone: string }[];
  ledger: { po_id: string; vendor_id: string; brand: string; sku_code: string; name: string; shortfall_units: number; days_overdue: number; root_cause: string }[];
  drafts: Draft[];
  claims: Claim[];
  verification: Verification;
  corrected: string[];
  unresolved: string[];
  unclaimed_numbers: string[];
  trace: TraceRow[];
  impact_coverage: ImpactCoverage;
};

export type VendorReview = {
  vendor: { id: string; brand: string; company_name: string; contact_name: string; contact_email: string; lead_time_days: number; category: string };
  scorecard: Scorecard;
  anomalies: Anomaly[];
  actions: Action[];
  email: Draft | null;
  pos: Po[];
  readings: Reading[];
  drafts: Draft[];
  claims: Claim[];
  week_start: string;
  week_end: string;
};

export const fetchReview = (inject: boolean, signal?: AbortSignal) => get<Review>(`/api/ops/review${inject ? "?inject=1" : ""}`, signal);
export const fetchPoTracker = (inject: boolean, signal?: AbortSignal) => get<PoTracker>(`/api/ops/pos${inject ? "?inject=1" : ""}`, signal);
export const fetchVendorReview = (id: string, signal?: AbortSignal) => get<VendorReview>(`/api/ops/vendors/${encodeURIComponent(id)}`, signal);
export const approveDraft = (id: string, body?: string) => post<Draft>(`/api/ops/outbox/${encodeURIComponent(id)}/approve`, body !== undefined ? { body } : {});
export const rejectDraft = (id: string, note?: string) => post<Draft>(`/api/ops/outbox/${encodeURIComponent(id)}/reject`, note ? { note } : {});

// ---------- navigation (extensible: a branch adds "Price requests" by appending one entry) ----------

export type RunNavItem = { href: string; label: string; match: (path: string) => boolean };

export const RUN_NAV: RunNavItem[] = [
  { href: "/run", label: "Category MIS", match: (p) => p === "/run" || p.startsWith("/run/vendors") },
  { href: "/run/pos", label: "PO tracker", match: (p) => p.startsWith("/run/pos") },
  { href: "/run/price-requests", label: "Price requests", match: (p) => p.startsWith("/run/price-requests") },
  { href: "/run/catalog", label: "Catalog fixes", match: (p) => p.startsWith("/run/catalog") },
  { href: "/run/promotions", label: "Promotions", match: (p) => p.startsWith("/run/promotions") },
  { href: "/run/price-watch", label: "Price watch", match: (p) => p.startsWith("/run/price-watch") },
];

// ---------- formatting ----------

export const ACTION_LABEL: Record<string, string> = {
  stockout: "Stock-out",
  fill_rate: "Fill rate",
  otif: "OTIF",
  ageing: "Ageing",
  overstock: "Overstock",
  returns: "Returns",
  rating: "Rating",
  sales_drop: "Sales drop",
  sales_spike: "Sales spike",
};

export const RISK_TONE: Record<Risk, "bad" | "warn" | "neutral" | "ok"> = { critical: "bad", high: "bad", medium: "warn", low: "ok" };

export function overdueText(d: number): string {
  if (d > 0) return `${d} ${d === 1 ? "day" : "days"} overdue`;
  if (d === 0) return "due today";
  return `due in ${-d} ${d === -1 ? "day" : "days"}`;
}

export function statusLabel(s: Po["status"]): string {
  return s === "overdue" ? "Overdue" : s === "due_soon" ? "Due soon" : "On track";
}

export function weekLabel(start: string, end: string): string {
  const f = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
  return `${f(start)} to ${f(end)}`;
}

export function unverified(drafts: Draft[]): number {
  return drafts.reduce((n, d) => n + d.figures.filter((f) => f.status !== "verified").length, 0);
}

export { days, inrCompact, pct, pctSigned };
