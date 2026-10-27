import { post, request, type Claim } from "./api";
import type { Draft, ImpactCoverage, TraceRow, Verification } from "./ops";

/**
 * Run: competitor price monitor. Types mirror backend/app/ops/pricewatch (live shapes are the mock/replay shapes).
 * Fractions (0.07 = 7%) everywhere unless a key says otherwise: `thresholds.*_pct` are percent numbers (3.0 = 3%).
 */

export type PwKind = "undercut" | "breach" | "blip" | "trend";
export type PwRecommendation = "match" | "hold" | "ask_vendor_funding" | "flag_breach" | "escalate";
export type PwState = "ok" | "sustained" | "blip" | "trend";

export type PwDecision = {
  status: "pending" | "approved" | "rejected";
  decided_at?: string;
  note?: string | null;
  simulated?: boolean;
  effect?: PwEffect | null;
  recommendation?: PwRecommendation;
};

export type PwEffect =
  | { type: "price_change"; sku_code: string; from_price: number; to_price: number; reason: string }
  | { type: "vendor_message"; draft_id: string; vendor_id: string; draft_status?: string }
  | { type: "escalation"; sku_code: string; to: string }
  | { type: "watch"; sku_code: string; recheck: string };

export type PwCompetitor = {
  state: PwState;
  marketplace: string;
  price: number;
  sustained_marketplaces: number;
  // present once a match was costed (sustained undercut and blip)
  match_price?: number;
  cut_pct?: number;
  margin_now_pct?: number;
  floor_pct?: number;
  margin_after_match_pct?: number;
  margin_hold_inr?: number;
  margin_match_inr?: number;
  /** Margin over the horizon if we match minus if we hold. Negative: matching costs margin. */
  margin_impact_inr?: number;
  units_hold?: number;
  units_match?: number;
  volume_loss_if_hold_pct?: number;
  protection_ask_unit_inr?: number;
  protection_ask_inr?: number;
  elasticity?: number;
  horizon_days?: number;
  // trend only: fractional change per day
  slope_pct_per_day?: number;
};

export type PwVendorBreach = {
  marketplace: string;
  price: number;
  gap_below_pct: number;
  parity_days: number;
  map_price: number | null;
  map_days: number;
  parity_breach: boolean;
  map_breach: boolean;
  breach: boolean;
  lost_units: number;
  lost_margin_inr: number;
  price_premium_pct: number;
  dates: string[];
  prices: number[];
};

export type PwVendorSeries = { marketplace: string; prices: number[]; dates: string[]; map_price: number | null };

export type PwSeries = {
  dates: string[];
  our_price: number;
  competitors: Record<string, number[]>;
  vendor: PwVendorSeries | null;
};

export type PwAction = {
  id: string;
  sku_code: string;
  vendor_id: string;
  brand: string;
  name: string;
  category: string;
  our_price: number;
  kind: PwKind;
  recommendation: PwRecommendation;
  reasons: string[];
  competitor?: PwCompetitor;
  vendor?: PwVendorBreach;
  claims: Claim[];
  series: PwSeries;
  email_id: string | null;
  decision: PwDecision;
};

export type PwSku = {
  sku_code: string;
  vendor_id: string;
  brand: string;
  name: string;
  our_price: number;
  lowest_competitor: number | null;
  lowest_marketplace: string | null;
  gap_pct: number | null;
  state: PwState;
  vendor_breach: boolean;
};

export type PwCounts = {
  skus: number;
  marketplaces: number;
  snapshots: number;
  sustained: number;
  blips: number;
  trends: number;
  breaches: number;
  match: number;
  ask_vendor_funding: number;
  hold: number;
  escalate: number;
};

export type PwThresholds = {
  undercut_threshold_pct: number;
  min_sustained_days: number;
  parity_tolerance_pct: number;
  parity_min_days: number;
  max_cut_pct: number;
  horizon_days: number;
  comparison_share_pct: number;
};

export type PriceWatch = {
  as_of: string;
  window_days: number;
  marketplaces: string[];
  mode: string;
  degraded: boolean;
  counts: PwCounts;
  headline: string;
  narrative: string;
  struck: string[];
  actions: PwAction[];
  skus: PwSku[];
  drafts: Draft[];
  claims: Claim[];
  verification: Verification;
  thresholds: PwThresholds;
  impact_coverage: ImpactCoverage;
  trace: TraceRow[];
  decisions: unknown[];
};

export type PwDecisionResult = {
  action_id: string;
  status: "approved" | "rejected";
  decided_at: string;
  note: string | null;
  simulated: boolean;
  effect: PwEffect | null;
  recommendation: PwRecommendation;
};

export const fetchPriceWatch = (signal?: AbortSignal) => request<PriceWatch>("GET", "/api/ops/price-watch", { signal });
export const approveAction = (id: string, note?: string) => post<PwDecisionResult>(`/api/ops/price-watch/actions/${encodeURIComponent(id)}/approve`, note ? { note } : {});
export const rejectAction = (id: string, note?: string) => post<PwDecisionResult>(`/api/ops/price-watch/actions/${encodeURIComponent(id)}/reject`, note ? { note } : {});

// ---------- labels and helpers ----------

export const KIND_LABEL: Record<PwKind, string> = {
  undercut: "Sustained undercut",
  breach: "Vendor parity breach",
  blip: "Blip",
  trend: "Falling trend",
};

export const kindLabel = (k: string): string => KIND_LABEL[k as PwKind] ?? k.replace(/_/g, " ");

export const RECOMMENDATION_LABEL: Record<PwRecommendation, string> = {
  match: "Match",
  hold: "Hold",
  ask_vendor_funding: "Ask vendor for price protection",
  flag_breach: "Flag breach to vendor",
  escalate: "Escalate",
};

export const recommendationLabel = (r: string): string => RECOMMENDATION_LABEL[r as PwRecommendation] ?? r.replace(/_/g, " ");

export type Tone = "ok" | "warn" | "bad" | "neutral";

export const RECOMMENDATION_TONE: Record<PwRecommendation, Tone> = {
  match: "ok",
  ask_vendor_funding: "warn",
  flag_breach: "warn",
  hold: "neutral",
  escalate: "bad",
};

export const recommendationTone = (r: string): Tone => RECOMMENDATION_TONE[r as PwRecommendation] ?? "neutral";

export const STATE_LABEL: Record<PwState, string> = { ok: "Fine", sustained: "Sustained undercut", blip: "Blip", trend: "Falling trend" };
export const stateLabel = (s: string): string => STATE_LABEL[s as PwState] ?? s;
export const stateTone = (s: string): Tone | "accent" => (s === "sustained" ? "bad" : s === "blip" ? "neutral" : s === "trend" ? "warn" : "ok");

/** Cards that only watch (hold, blip, trend) are acknowledged; the others are approved. */
export const isAcknowledge = (a: Pick<PwAction, "recommendation">): boolean => a.recommendation === "hold";

export const approveLabel = (a: Pick<PwAction, "recommendation">): string => (isAcknowledge(a) ? "Acknowledge" : "Approve (simulated)");

/** A blip is never matched: the card must say so. */
export const isBlip = (a: Pick<PwAction, "kind">): boolean => a.kind === "blip";

/** What a decision did, in words. */
export function effectText(e: PwEffect | null | undefined, inr: (n: number) => string): string {
  if (!e) return "No change was made.";
  switch (e.type) {
    case "price_change":
      return `Price change queued (simulated): ${e.sku_code} from ${inr(e.from_price)} to ${inr(e.to_price)} (${e.reason}).`;
    case "vendor_message":
      return e.draft_status === "sent_simulated" || e.draft_status === undefined
        ? `Vendor message sent (simulated) to ${e.vendor_id}. Nothing left this app.`
        : `Vendor message ${e.draft_status.replace(/_/g, " ")}.`;
    case "escalation":
      return `Escalated to the ${e.to.replace(/_/g, " ")} (simulated).`;
    case "watch":
      return `Watching: re-check at ${e.recheck}.`;
  }
}

/** Days in a row, ending on the last date, that the marketplace has been at least `thresholdPct` percent under our price. */
export function daysUnder(series: PwSeries, marketplace: string, thresholdPct: number): number {
  const prices = series.competitors[marketplace];
  if (!prices) return 0;
  const limit = series.our_price * (1 - thresholdPct / 100);
  let n = 0;
  for (let i = prices.length - 1; i >= 0; i--) {
    if (prices[i] <= limit) n++;
    else break;
  }
  return n;
}

export type ChartLine = { key: string; label: string; values: number[]; dashed?: boolean; role: "ours" | "competitor" | "vendor" | "map" };

/** The lines of a card's price chart: ours (flat), each marketplace, and the vendor storefront on breach cards. */
export function chartLines(a: Pick<PwAction, "kind" | "series">): ChartLine[] {
  const s = a.series;
  const n = s.dates.length;
  const lines: ChartLine[] = [{ key: "ours", label: "Our price", values: Array(n).fill(s.our_price), role: "ours" }];
  for (const [m, v] of Object.entries(s.competitors)) lines.push({ key: m, label: m, values: v, role: "competitor" });
  if (a.kind === "breach" && s.vendor) {
    lines.push({ key: "vendor", label: `Vendor on ${s.vendor.marketplace}`, values: s.vendor.prices, role: "vendor" });
    if (s.vendor.map_price != null) lines.push({ key: "map", label: "MAP price", values: Array(n).fill(s.vendor.map_price), dashed: true, role: "map" });
  }
  return lines;
}
