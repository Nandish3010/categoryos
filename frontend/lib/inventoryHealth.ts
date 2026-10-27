import { post, request, type Claim } from "./api";
import type { Draft, ImpactCoverage, TraceRow, Verification } from "./ops";

/**
 * Run: inventory health review. Types mirror backend/app/ops/inventory_health (live shapes are the mock/replay shapes).
 * Fractions (0.25 = 25%) for `discount_pct`; `thresholds.*` are plain numbers (days, ratios).
 */

export type IhKind = "stock_out" | "overbuy" | "dead" | "aged" | "excess";
export type IhRecommendation = "reorder" | "expedite_po" | "pause_po" | "return_to_vendor" | "liquidate";
export type IhSeverity = "critical" | "high" | "medium" | "low";
export type IhBandState = "below" | "in" | "above" | "not_moving";

export type IhEffect =
  | { type: "po_draft"; sku_code: string; vendor_id: string; qty: number; lead_time_days: number; lands_on: string }
  | { type: "promo_nomination"; sku_code: string; units: number; discount_pct: number; price_inr: number }
  | { type: "vendor_message"; draft_id: string; vendor_id: string; action: string; sku_code: string; po_id?: string; units?: number; credit_inr?: number; draft_status?: string };

export type IhDecision = {
  status: "pending" | "approved" | "rejected";
  decided_at?: string;
  note?: string | null;
  simulated?: boolean;
  effect?: IhEffect | null;
  recommendation?: IhRecommendation;
};

export type IhReorder = {
  qty: number;
  needed_units: number;
  moq_units: number;
  lead_time_days: number;
  order_by: string;
  cost_inr: number;
  overbuy_units: number;
  moq_driven: boolean;
};

export type IhPause = {
  po_id: string;
  pause_units: number;
  promised: string;
  arrives_in_days: number;
  cover_without_po_days: number;
  cover_with_po_days: number;
  needed_units: number;
  overbuy_units: number;
  moq_units: number;
  moq_driven: boolean;
  value_inr: number;
};

export type IhRtv = {
  units: number;
  credit_inr: number;
  days_left: number;
  window_ends: string;
  open: boolean;
  urgent: boolean;
  restocking_fee_pct: number;
};

export type IhLiquidate = {
  units: number;
  discount_pct: number;
  price_inr: number;
  recovery_inr: number;
  write_down_inr: number;
  clear_days: number | null;
  floor_applied: boolean;
};

export type IhClear = {
  kind: IhKind;
  units: number;
  excess_units: number;
  aged_units: number;
  value_inr: number;
  liquidate: IhLiquidate;
  rtv: IhRtv | null;
};

export type IhLanding = { po_id: string; qty: number; promised: string; arrives_in_days: number; overdue: boolean; received: number; ordered: number };

export type IhStock = {
  on_hand: number;
  daily_demand: number;
  cover_days: number | null;
  inbound_units: number;
  cover_inbound_days: number | null;
  run_out_day: number | null;
  short_days: number;
  lead_time_days: number;
  moq_units: number;
  band: { min_days: number; target_days: number; max_days: number };
  landings: IhLanding[];
  stock_value_inr: number;
  days_since_sale: number | null;
  oldest_age_days: number;
  aged_units: number;
  legacy: boolean;
  band_state: IhBandState;
};

export type IhAction = {
  id: string;
  sku_code: string;
  vendor_id: string;
  brand: string;
  name: string;
  category: string;
  legacy: boolean;
  kind: IhKind;
  recommendation: IhRecommendation;
  severity: IhSeverity;
  reasons: string[];
  reorder?: IhReorder | null;
  pause?: IhPause;
  clear?: IhClear;
  stock: IhStock;
  note: string | null;
  claims: Claim[];
  email_id: string | null;
  decision: IhDecision;
};

export type IhVendor = {
  vendor_id: string;
  brand: string;
  skus: number;
  stock_value_inr: number;
  stuck_value_inr: number;
  stockout_skus: number;
  actions: number;
  lead_time_days: number;
  claims: Claim[];
};

export type IhSku = {
  sku_code: string;
  vendor_id: string;
  brand: string;
  name: string;
  legacy: boolean;
  on_hand: number;
  daily_demand: number;
  cover_days: number | null;
  inbound_units: number;
  cover_inbound_days: number | null;
  stock_value_inr: number;
  days_since_sale: number | null;
  band_state: IhBandState;
  kind: IhKind | null;
  recommendation: IhRecommendation | null;
};

export type IhCounts = {
  skus: number;
  live_skus: number;
  legacy_lots: number;
  actions: number;
  stock_out: number;
  overbuy: number;
  dead: number;
  aged: number;
  excess: number;
  reorder: number;
  expedite_po: number;
  pause_po: number;
  return_to_vendor: number;
  liquidate: number;
  stock_value_inr: number;
  stuck_value_inr: number;
};

export type IhThresholds = {
  cover_min_days: number;
  cover_target_days: number;
  cover_max_days: number;
  aged_days: number;
  dead_no_sale_days: number;
  critical_days: number;
  safety_days: number;
  review_days: number;
  overdue_assumed_days: number;
  overbuy_ratio: number;
  rtv_urgent_window_days: number;
  max_clear_days: number;
  forecast_window_days: number;
};

export type InventoryHealth = {
  as_of: string;
  mode: string;
  degraded: boolean;
  counts: IhCounts;
  headline: string;
  narrative: string;
  struck: string[];
  actions: IhAction[];
  vendors: IhVendor[];
  skus: IhSku[];
  drafts: Draft[];
  claims: Claim[];
  verification: Verification;
  thresholds: IhThresholds;
  impact_coverage: ImpactCoverage;
  trace: TraceRow[];
  decisions: unknown[];
};

export type IhDecisionResult = {
  action_id: string;
  status: "approved" | "rejected";
  decided_at: string;
  note: string | null;
  simulated: boolean;
  effect: IhEffect | null;
  recommendation: IhRecommendation;
};

export const fetchInventoryHealth = (signal?: AbortSignal) => request<InventoryHealth>("GET", "/api/ops/inventory-health", { signal });
export const approveAction = (id: string, note?: string) => post<IhDecisionResult>(`/api/ops/inventory-health/actions/${encodeURIComponent(id)}/approve`, note ? { note } : {});
export const rejectAction = (id: string, note?: string) => post<IhDecisionResult>(`/api/ops/inventory-health/actions/${encodeURIComponent(id)}/reject`, note ? { note } : {});

// ---------- labels and helpers ----------

export const KIND_LABEL: Record<IhKind, string> = {
  stock_out: "Stock-out risk",
  overbuy: "MOQ overbuy",
  dead: "Dead stock",
  aged: "Aged stock",
  excess: "Excess stock",
};
export const kindLabel = (k: string): string => KIND_LABEL[k as IhKind] ?? k.replace(/_/g, " ");

export const RECOMMENDATION_LABEL: Record<IhRecommendation, string> = {
  reorder: "Reorder",
  expedite_po: "Expedite the late PO",
  pause_po: "Pause the PO",
  return_to_vendor: "Return to vendor",
  liquidate: "Liquidate on a promo",
};
export const recommendationLabel = (r: string): string => RECOMMENDATION_LABEL[r as IhRecommendation] ?? r.replace(/_/g, " ");

export type Tone = "ok" | "warn" | "bad" | "neutral";

export const SEVERITY_TONE: Record<IhSeverity, Tone> = { critical: "bad", high: "warn", medium: "neutral", low: "neutral" };
export const severityTone = (s: string): Tone => SEVERITY_TONE[s as IhSeverity] ?? "neutral";

export const BAND_LABEL: Record<IhBandState, string> = { below: "Below band", in: "In band", above: "Above band", not_moving: "Not moving" };
export const bandLabel = (s: string): string => BAND_LABEL[s as IhBandState] ?? s;
export const bandTone = (s: string): Tone => (s === "below" ? "bad" : s === "above" ? "warn" : s === "in" ? "ok" : "neutral");

/** The verb on the approve button: what approving does, in the simulator. */
export const approveLabel = (a: Pick<IhAction, "recommendation">): string => {
  switch (a.recommendation) {
    case "reorder":
      return "Draft the PO (simulated)";
    case "liquidate":
      return "Nominate for promo (simulated)";
    default:
      return "Approve message (simulated)";
  }
};

/** What a decision did, in words. */
export function effectText(e: IhEffect | null | undefined, inr: (n: number) => string): string {
  if (!e) return "No change was made.";
  switch (e.type) {
    case "po_draft":
      return `PO draft queued (simulated): ${e.qty} units of ${e.sku_code} from ${e.vendor_id}, lands about ${e.lands_on} (${e.lead_time_days}-day lead time).`;
    case "promo_nomination":
      return `Promo nomination queued (simulated): ${e.units} units of ${e.sku_code} at ${inr(e.price_inr)}.`;
    case "vendor_message":
      return e.draft_status === "sent_simulated" || e.draft_status === undefined
        ? `Vendor message sent (simulated) to ${e.vendor_id}. Nothing left this app.`
        : `Vendor message ${e.draft_status.replace(/_/g, " ")}.`;
  }
}

/** Position of a cover figure on the band bar: 0 to 1 over 0..(max band * 1.5), capped. */
export function coverPosition(days: number | null, band: { max_days: number }): number {
  if (days == null) return 1;
  return Math.max(0, Math.min(1, days / (band.max_days * 1.5)));
}
