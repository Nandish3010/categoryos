import { post, request, type Claim } from "./api";
import type { Draft, ImpactCoverage, TraceRow, Verification } from "./ops";

/**
 * Run: promotions and event planner. Types mirror backend/app/ops/promotions (live shapes are the mock/replay shapes).
 * Fractions (0.07 = 7%) everywhere unless a key says otherwise: `*_pct` on `event`, `assumptions` and reading terms are percent numbers.
 */

export type PromoDecisionStatus = "pending" | "approved" | "rejected";

export type PromoDecision = {
  status: PromoDecisionStatus;
  decided_at?: string;
  note?: string | null;
  simulated?: boolean;
  n_skus?: number;
  stock_up_inr?: number;
  prices?: PlanPrice[];
  pos?: PromoPo[];
};

export type PromoEvent = {
  id: string;
  name: string;
  start: string;
  end: string;
  days: number;
  /** Percent number (10.0 = 10%). */
  traffic_lift_pct: number;
  banner_slots: number;
  days_away: number;
};

export type PromoEventSummary = PromoEvent & {
  planned_skus: number;
  gmv_inr: number;
  funding_ask_inr: number;
  stock_up_inr: number;
  incremental_margin_inr: number;
  decision: PromoDecision;
};

export type PromoList = { as_of: string; events: PromoEventSummary[] };

export type PromoTotals = {
  planned_skus: number;
  excluded_skus: number;
  gmv_inr: number;
  units: number;
  incremental_margin_inr: number;
  funding_ask_inr: number;
  stock_up_inr: number;
  stock_up_units: number;
  margin_unfunded_pct: number;
  margin_at_ask_pct: number;
  capped_by_stock: number;
  stock_up_pos: number;
};

export type ExclusionCode = "outranked" | "unprofitable" | "cannibalises" | (string & {});

export type Exclusion = { code: ExclusionCode; text: string };

export type OpenPo = { po_id: string; qty: number; arrives: string };

export type StockUp = { feasible: true; qty: number; cost_inr: number; order_by: string; arrives: string; lead_days: number };

/** A stock-up that could not be placed. `reason` says why (lead time too long, or it would take cover too high). */
export type StockUpBlocked = { feasible: false; reason: string; order_by?: string; arrives?: string };

export type DeepOption = {
  depth: number;
  promo_price: number;
  uplift: number;
  units: number;
  stockout_day: number | null;
  short_units: number;
  lost_gmv_inr: number;
  net_inr: number;
  why?: string;
};

export type Sibling = { sku_code: string; name: string; similarity: number; on_promo: boolean };

export type Cannibalisation = { siblings: Sibling[]; cost_inr: number; share_pct: number };

export type RowVerification = { total: number; verified: number; rejected: number };

/** Every row has the first block of fields; the second block exists only on planned rows. */
export type PromoRow = {
  sku_code: string;
  vendor_id: string;
  brand: string;
  name: string;
  category: string;
  status: "planned" | "excluded";
  exclusion: Exclusion | null;
  selling_price: number;
  cost: number;
  mrp: number;
  daily_units: number;
  on_hand: number;
  lead_days: number;
  open_pos: OpenPo[];
  stock_at_start: number;
  incremental_margin_inr: number | null;
  stock_up: StockUp | null;
  stock_up_blocked: StockUpBlocked | null;
  capped_by_stock: boolean;
  deep_option: DeepOption | null;
  banner_rank: number | null;
  banner_candidate: boolean;
  cannibalisation: Cannibalisation | null;
  verification: RowVerification;
  // planned rows only
  discount_pct?: number;
  promo_price?: number;
  uplift?: number;
  baseline_units?: number;
  promo_units?: number;
  incremental_units?: number;
  gmv?: number;
  margin_unfunded_pct?: number;
  margin_at_ask_pct?: number;
  floor_promo_pct?: number;
  funding_needed_share?: number;
  funding_ask_share?: number;
  funding_ask_inr?: number;
  pull_forward_inr?: number;
  cannibalisation_inr?: number;
  need_units?: number;
  stockout_day?: number | null;
  stock_ok?: boolean;
};

export type PoLineItem = { sku_code: string; name: string; qty: number; cost: number; cost_inr: number };

export type PromoPo = {
  po_ref: string;
  vendor_id: string;
  brand: string;
  lines: PoLineItem[];
  qty: number;
  cost_inr: number;
  order_by: string;
  arrives: string;
  status?: string;
};

export type OfferDecision = "accept" | "counter" | "reject_structure" | "declined" | "no_offer";

export type OfferCounter = {
  kind: string;
  text: string;
  /** Nested structured counter (present on a rejected structure). */
  counter?: {
    kind: string;
    text: string;
    threshold: number | null;
    window_days: number | null;
    scope: string[];
    probability: number | null;
    meets_requirement: boolean;
  };
};

export type Offer = {
  vendor_id?: string;
  share?: number;
  scope?: string[];
  threshold_units?: number | null;
  banner_top_n?: number | null;
  markdown_inr?: number;
  face_inr: number;
  counted_inr: number;
  banner_cost_inr?: number;
  /** Chance the sales target is reached; null when the offer has no target or was declined. */
  probability: number | null;
  decision: OfferDecision;
  call: string;
  ask_inr: number;
  covers_ask_pct: number;
  required_pts?: number;
  offer_key: string | null;
  counter: OfferCounter;
  reply_id?: string;
  quote?: string;
};

export type AssessmentCounter = {
  kind: string;
  text: string;
  threshold: number | null;
  window_days: number | null;
  probability: number | null;
  meets_requirement: boolean;
};

/** The deal evaluator's reading of a conditional offer (a subset of the Onboard DealAssessment). */
export type PromoAssessment = {
  term_id: string;
  kind: string;
  label: string;
  quote: string;
  decision: string;
  call: string;
  reasoning: string[];
  probability: number | null;
  required_pts: number | null;
  counted_pts: number;
  shortfall_pts: number | null;
  counters: AssessmentCounter[];
  recommended_counter: number | null;
};

export type VendorBlock = {
  vendor_id: string;
  brand: string;
  skus: string[];
  n_skus: number;
  markdown_inr: number;
  ask_inr: number;
  ask_share: number;
  gmv: number;
  best_banner_rank: number | null;
  offer: Offer | null;
  assessment: PromoAssessment | null;
  stated_lead_time_days: number | null;
  reading_note: string | null;
};

export type TermClaim = {
  id: string;
  metric: string;
  value: number;
  status: string;
  reason: string | null;
  first_value: number | null;
  corrected: boolean;
};

export type FundingTerm = {
  /** Percent number (50.0 = 50%). */
  share_pct: number | null;
  scope: string[];
  threshold_units: number | null;
  window_days: number | null;
  banner_top_n: number | null;
  quote: string;
  claims: TermClaim[];
};

export type PromoReading = {
  reply_id: string;
  vendor_id: string;
  received_at: string;
  from: string;
  subject: string;
  body: string;
  stance: string;
  summary: string;
  lead_time_days: number | null;
  terms: FundingTerm[];
};

export type PromoPlan = {
  event: PromoEvent;
  as_of: string;
  mode: string;
  degraded: boolean;
  totals: PromoTotals;
  rows: PromoRow[];
  vendors: VendorBlock[];
  pos: PromoPo[];
  headline: string;
  brief: string;
  struck: string[];
  readings: PromoReading[];
  drafts: Draft[];
  claims: Claim[];
  verification: Verification;
  corrected: string[];
  unresolved: string[];
  assumptions: Record<string, unknown>;
  impact_coverage: ImpactCoverage;
  trace: TraceRow[];
  decision: PromoDecision;
};

export type PlanPrice = { sku_code: string; from_price: number; to_price: number };

export type PlanDecisionResult = {
  event_id: string;
  status: "approved" | "rejected";
  decided_at: string;
  note: string | null;
  simulated: boolean;
  skus: string[];
  n_skus: number;
  prices: PlanPrice[];
  pos: PromoPo[];
  stock_up_inr: number;
};

const enc = encodeURIComponent;

export const fetchPromotions = (signal?: AbortSignal) => request<PromoList>("GET", "/api/ops/promotions", { signal });
export const fetchPromoPlan = (id: string, signal?: AbortSignal) => request<PromoPlan>("GET", `/api/ops/promotions/${enc(id)}`, { signal });
export const approvePlan = (id: string, body: { sku_codes?: string[]; note?: string } = {}) => post<PlanDecisionResult>(`/api/ops/promotions/${enc(id)}/approve`, body);
export const rejectPlan = (id: string, note?: string) => post<PlanDecisionResult>(`/api/ops/promotions/${enc(id)}/reject`, note ? { note } : {});

// ---------- labels and helpers ----------

export const EXCLUSION_LABEL: Record<string, string> = {
  outranked: "Outranked",
  unprofitable: "Does not pay",
  cannibalises: "Cannibalises a sibling",
};

export const exclusionLabel = (code: string): string => EXCLUSION_LABEL[code] ?? code.replace(/_/g, " ");

export const OFFER_LABEL: Record<string, string> = {
  accept: "Accept",
  counter: "Counter",
  reject_structure: "Reject structure and counter",
  declined: "Declined",
  no_offer: "No offer",
};

export const offerLabel = (d: string): string => OFFER_LABEL[d] ?? d.replace(/_/g, " ");

export const OFFER_TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = {
  accept: "ok",
  counter: "warn",
  reject_structure: "bad",
  declined: "neutral",
  no_offer: "neutral",
};

export const offerTone = (d: string): "ok" | "warn" | "bad" | "neutral" => OFFER_TONE[d] ?? "neutral";

export const STANCE_LABEL: Record<string, string> = {
  offer: "Offer",
  conditional_offer: "Conditional offer",
  decline: "Declined",
};

export const stanceLabel = (s: string): string => STANCE_LABEL[s] ?? s.replace(/_/g, " ");

/** "starts in 11 days", "starts tomorrow", "started 2 days ago". */
export function startsText(daysAway: number): string {
  if (daysAway === 0) return "starts today";
  if (daysAway === 1) return "starts tomorrow";
  if (daysAway > 1) return `starts in ${daysAway} days`;
  const n = -daysAway;
  return `started ${n} ${n === 1 ? "day" : "days"} ago`;
}

/** "x2.7" for an uplift multiple. */
export const upliftText = (u: number | null | undefined): string => (u == null || Number.isNaN(u) ? "—" : `x${u.toFixed(1)}`);

/** A fraction that may carry rounding noise as a whole-number percent: 0.2492 -> "25%". */
export const wholePct = (f: number | null | undefined): string => (f == null || Number.isNaN(f) ? "—" : `${Math.round(f * 100)}%`);

/** Percent number (already x100) as text: 10 -> "10%", 12.5 -> "12.5%". */
export const pctNumber = (n: number | null | undefined): string => (n == null || Number.isNaN(n) ? "—" : `${Math.round(n * 10) / 10}%`);

export const planned = (rows: PromoRow[]): PromoRow[] => rows.filter((r) => r.status === "planned");
export const excluded = (rows: PromoRow[]): PromoRow[] => rows.filter((r) => r.status === "excluded");
export const atRisk = (rows: PromoRow[]): PromoRow[] => planned(rows).filter((r) => r.deep_option != null);

export function cannibalText(c: Cannibalisation): string {
  return c.siblings.map((s) => `${s.name} (${s.on_promo ? "also on promo" : "not on promo"})`).join(", ");
}

/** What the plan did about a stock-out risk, in words. */
export function stockRiskResolution(r: PromoRow): string {
  if (r.stock_up) return `Stock-up PO of ${r.stock_up.qty} units, order by ${r.stock_up.order_by}, arrives ${r.stock_up.arrives}`;
  if (r.stock_up_blocked) return `Stock-up not possible: ${r.stock_up_blocked.reason}`;
  if (r.capped_by_stock) return `Discount capped at ${wholePct(r.discount_pct)}`;
  return "No change needed";
}

const ASSUMPTION_LABEL: Record<string, string> = {
  elasticity_default: "Default price elasticity",
  max_uplift: "Largest sales uplift allowed",
  pull_forward_pct: "Sales pulled forward from after the event",
  max_discount_pct: "Deepest discount",
  promo_floor_below_regular_pp: "Promo margin floor below regular (points)",
  safety_buffer_pct: "Stock safety buffer",
  baseline_cover_days: "Baseline cover (days)",
  funding_target_pct: "Funding target (share of markdown)",
  funding_max_ask_pct: "Largest funding ask (share of markdown)",
  banner_slot_cost_inr: "Cost of a banner slot (INR)",
  cannibalised_share_pct: "Share of a sibling's sales taken",
  deal_evaluator: "Deal evaluator",
};

export const assumptionLabel = (k: string): string => ASSUMPTION_LABEL[k] ?? k.replace(/_/g, " ");

/** Flatten the assumptions into label/value pairs (the nested deal evaluator becomes `Deal evaluator: key`). */
export function assumptionItems(a: Record<string, unknown>): { key: string; label: string; value: string }[] {
  const out: { key: string; label: string; value: string }[] = [];
  const text = (v: unknown): string => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v));
  for (const [k, v] of Object.entries(a)) {
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      for (const [k2, v2] of Object.entries(v as Record<string, unknown>)) out.push({ key: `${k}.${k2}`, label: `${assumptionLabel(k)}: ${k2.replace(/_/g, " ")}`, value: text(v2) });
    } else out.push({ key: k, label: assumptionLabel(k), value: text(v) });
  }
  return out;
}
