import { post, request } from "./api";

/** Run: existing-vendor price-increase requests. Types mirror backend/app/pricereq.py. Percent fields are percent numbers (4.0 = 4%). */

export type PrDecision = "accept" | "accept_partial" | "pass_through" | "delay" | "delist" | "needs_review";

export const DECISION_LABEL: Record<PrDecision, string> = {
  accept: "Accept",
  accept_partial: "Accept partly",
  pass_through: "Pass through to price",
  delay: "Delay",
  delist: "Delist / find alternate",
  needs_review: "Needs review",
};

export const DECISION_TONE: Record<PrDecision, "ok" | "warn" | "bad" | "neutral" | "accent"> = {
  accept: "ok",
  accept_partial: "warn",
  pass_through: "accent",
  delay: "warn",
  delist: "bad",
  needs_review: "neutral",
};

export type PrScenario = {
  label: string;
  cost_pct: number;
  price: number;
  units: number;
  gmv: number;
  margin_inr: number;
  margin_pct: number | null;
  gmv_delta: number;
  margin_delta: number;
};

export type PrLine = {
  sku_code: string;
  name: string;
  category: string;
  status: "ok" | "unmatched" | "no_cost_or_price";
  quote: string;
  old_cost: number | null;
  new_cost: number | null;
  old_cost_mismatch: boolean;
  pct_change: number | null;
  effective_pct: number | null;
  selling_price: number | null;
  competitor_median: number | null;
  current_margin_pct: number | null;
  new_margin_pct: number | null;
  target_margin_pct: number | null;
  floor_margin_pct: number | null;
  needed_retail: number | null;
  retail_rise_pct: number | null;
  gap_if_passed_pct: number | null;
  volume_change_pct: number | null;
  elasticity: number | null;
  elasticity_risk: "low" | "medium" | "high" | null;
  absorb_limit_pct: number | null;
  pass_through_limit_pct: number | null;
  justified_ceiling_pct: number | null;
  justified: boolean | null;
  effective_date: string | null;
  notice_days: number | null;
  short_notice: boolean;
  ask_effective_date: string | null;
  decision: PrDecision;
  then_decision: PrDecision | null;
  counter_pct: number | null;
  counter_cost: number | null;
  counter_basis: "absorb" | "pass_through" | null;
  reasons: string[];
  scenarios: PrScenario[];
  recommended: string;
};

export type PrSweetener = {
  id: string;
  kind: "absorb_if_volume" | "support_if_full_acceptance";
  label: string;
  quote: string;
  engine: "deals" | "acceptance";
  decision: string;
  call: string;
  value_pts: number;
  counted_pts: number;
  probability: number | null;
  counted_share_pct: number | null;
  net_pts: number | null;
};

export type PrTier = { role: string; label: string; above_pct: number };

export type PrEvaluation = {
  vendor_id: string;
  received_date: string;
  effective_date: string | null;
  lines: PrLine[];
  sweeteners: PrSweetener[];
  decision: PrDecision;
  headline: string;
  counts: Record<string, number>;
  approval: { pct: number; asked_pct: number; tier: PrTier; asked_tier: PrTier; reasons: string[]; matrix: PrTier[] };
  counter_offer: {
    lines: { sku_code: string; decision: PrDecision; counter_cost: number | null; counter_pct: number | null; asked_cost: number | null; asked_pct: number | null }[];
    effective_date_ask: string | null;
    sweetener_asks: string[];
  };
  impact: {
    horizon_days: number;
    baseline_gmv: number;
    baseline_margin_inr: number;
    absorb: { gmv_delta: number; margin_delta: number };
    pass_through: { gmv_delta: number; margin_delta: number };
    recommended: { gmv_delta: number; margin_delta: number };
  };
  justification: { index_name: string; index_change_pct: number | null; tolerance_pp: number; assessed: boolean; unjustified_skus: string[]; asked_max_pct: number; ceiling_pct: number | null };
  assumptions: Record<string, unknown>;
  notes: string[];
};

export type PrStatus = { status: "pending" | "approved" | "rejected"; by?: string; at?: string; note?: string; tier_required?: string; sent?: { simulated: boolean; to: string; subject: string; body: string } };

export type PrClaim = { id: string; text: string; metric: string; value: number; status: string; reason: string | null; quote: string | null; attempts: { attempt: number; value: number; status: string; reason: string | null }[]; sku: string };

export type PrRow = { id: string; vendor_id: string; brand: string; received_at: string; sender: string; subject: string; submitted: boolean; status: string };

export type PrDetail = {
  request: PrRow;
  email: string;
  price_list: string;
  price_list_name: string;
  reason: string;
  reason_quote: string;
  effective_date: string | null;
  evaluation: PrEvaluation;
  deals: Record<string, unknown> | null;
  reply: { subject: string; body: string; source: "model" | "rules"; struck: string[]; model: string | null; note?: string };
  claims: PrClaim[];
  verification: { total: number; verified: number; rejected: number; self_corrected: number };
  rejected: { kind: string; id: string; label: string; reasons: string[] }[];
  trace: Record<string, unknown>[];
  mode: string;
  model: string;
  status: PrStatus;
};

export const fetchInbox = (signal?: AbortSignal) => request<{ requests: PrRow[] }>("GET", "/api/price-requests", { signal });
export const fetchRequest = (id: string, signal?: AbortSignal) => request<PrDetail>("GET", `/api/price-requests/${encodeURIComponent(id)}`, { signal });
export const approveRequest = (id: string, role: string, emailBody?: string, note?: string) =>
  post<PrStatus & { id: string }>(`/api/price-requests/${encodeURIComponent(id)}/approve`, { role, email_body: emailBody, note });
export const rejectRequest = (id: string, role: string, note?: string) => post<PrStatus & { id: string }>(`/api/price-requests/${encodeURIComponent(id)}/reject`, { role, note });

// ---------- formatting ----------

export const pctText = (x: number | null | undefined, digits = 1): string => (x == null ? "—" : `${x.toFixed(digits)}%`);
export const signedPct = (x: number | null | undefined, digits = 1): string => (x == null ? "—" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(digits)}%`);
export const rupees = (x: number | null | undefined): string =>
  x == null ? "—" : `₹${x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const signedInr = (x: number): string => `${x > 0 ? "+" : x < 0 ? "−" : ""}₹${Math.abs(Math.round(x)).toLocaleString("en-IN")}`;

export function dateText(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** The decision a line leads to once any delay is over. */
export const effectiveDecision = (l: PrLine): PrDecision => (l.decision === "delay" && l.then_decision ? l.then_decision : l.decision);

export const RISK_TONE = { low: "ok", medium: "warn", high: "bad" } as const;
