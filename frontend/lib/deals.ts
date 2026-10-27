/**
 * Deal evaluator data (Negotiate `data.deals`, shapes: docs/api-contract.md). Defensive readers, like lib/stages.ts:
 * backend data is loosely typed, so every field is checked and missing pieces degrade to empty values.
 */
import type { StageResult } from "./runs";
import { inrCompact } from "./format";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const nums = (v: unknown): number[] => arr(v).filter((x): x is number => typeof x === "number" && Number.isFinite(x));
const strs = (v: unknown): string[] => arr(v).filter((x): x is string => typeof x === "string");

export type DealDecision = "accept" | "reject_structure" | "needs_human" | "not_assessable";
export type DealMetric = "units" | "gmv_inr" | "sell_through_pct" | string;

export type DealTier = { threshold: number; bonusPts: number; incrementalPts: number; probability: number; counted: boolean };
export type DealDistribution = {
  metric: DealMetric;
  windowDays: number;
  mean: number;
  p10: number;
  p50: number;
  p90: number;
  threshold: number;
  bins: number[];
  density: number[];
};
export type DealCounter = {
  kind: "threshold" | "convert_to_base" | "window" | "scope" | string;
  text: string;
  threshold: number | null;
  windowDays: number | null;
  probability: number | null;
  requiredBasePts: number | null;
  upliftPts: number | null;
  fairConversionPts: number | null;
  countedPtsAfter: number;
  meetsRequirement: boolean;
};
export type DealAssessment = {
  termId: string;
  kind: string;
  term: string;
  label: string;
  source: string;
  turn: number;
  quote: string;
  decision: DealDecision;
  call: string;
  reasoning: string[];
  basePts: number;
  facePts: number;
  expectedBonusPts: number;
  countedBonusPts: number;
  expectedPts: number;
  guaranteedPts: number;
  countedPts: number;
  requiredPts: number;
  shortfallPts: number;
  probability: number | null;
  tiers: DealTier[];
  distribution: DealDistribution | null;
  counters: DealCounter[];
  recommendedCounter: number | null;
  netPts: number | null;
  baseAssumed: boolean;
};
export type DealTalk = { talkTrack: string; emailParagraph: string; source: string; struck: string[] };
export type DealsData = {
  decision: string;
  headline: string;
  assessments: DealAssessment[];
  rejectedTerms: { id: string; label: string; reasons: string[] }[];
  assumptions: {
    minProbability: number;
    valueBasis: string;
    rampByMonth: number[];
    cv: number;
    mcDraws: number;
    seed: number;
    costOfCapital: number;
    carrying: number;
  };
  talk: DealTalk | null;
  claimStatus: Record<string, string>;
  verification: { total: number; verified: number; rejected: number } | null;
};

const DECISIONS: DealDecision[] = ["accept", "reject_structure", "needs_human", "not_assessable"];

function readAssessment(a: Obj): DealAssessment {
  const d = isObj(a.distribution) ? a.distribution : null;
  const decision = str(a.decision);
  return {
    termId: str(a.term_id) ?? "",
    kind: str(a.kind) ?? "",
    term: str(a.term) ?? "",
    label: str(a.label) ?? "Conditional offer",
    source: str(a.source) ?? "transcript",
    turn: num(a.turn) ?? 0,
    quote: str(a.quote) ?? "",
    decision: (DECISIONS as string[]).includes(decision ?? "") ? (decision as DealDecision) : "not_assessable",
    call: str(a.call) ?? "",
    reasoning: strs(a.reasoning),
    basePts: num(a.base_pts) ?? 0,
    facePts: num(a.face_pts) ?? 0,
    expectedBonusPts: num(a.expected_bonus_pts) ?? 0,
    countedBonusPts: num(a.counted_bonus_pts) ?? 0,
    expectedPts: num(a.expected_pts) ?? 0,
    guaranteedPts: num(a.guaranteed_pts) ?? 0,
    countedPts: num(a.counted_pts) ?? 0,
    requiredPts: num(a.required_pts) ?? 0,
    shortfallPts: num(a.shortfall_pts) ?? 0,
    probability: num(a.probability),
    tiers: arr(a.tiers)
      .filter(isObj)
      .map((t) => ({
        threshold: num(t.threshold) ?? 0,
        bonusPts: num(t.bonus_pts) ?? 0,
        incrementalPts: num(t.incremental_pts) ?? 0,
        probability: num(t.probability) ?? 0,
        counted: t.counted === true,
      })),
    distribution: d
      ? {
          metric: str(d.metric) ?? "units",
          windowDays: num(d.window_days) ?? 0,
          mean: num(d.mean) ?? 0,
          p10: num(d.p10) ?? 0,
          p50: num(d.p50) ?? 0,
          p90: num(d.p90) ?? 0,
          threshold: num(d.threshold) ?? 0,
          bins: nums(d.bins),
          density: nums(d.density),
        }
      : null,
    counters: arr(a.counters)
      .filter(isObj)
      .map((c) => ({
        kind: str(c.kind) ?? "",
        text: str(c.text) ?? "",
        threshold: num(c.threshold),
        windowDays: num(c.window_days),
        probability: num(c.probability),
        requiredBasePts: num(c.required_base_pts),
        upliftPts: num(c.uplift_pts),
        fairConversionPts: num(c.fair_conversion_pts),
        countedPtsAfter: num(c.counted_pts_after) ?? 0,
        meetsRequirement: c.meets_requirement === true,
      })),
    recommendedCounter: num(a.recommended_counter),
    netPts: num(a.net_pts),
    baseAssumed: a.base_assumed === true,
  };
}

/** Parse a `deals` object (a stage's `data.deals`, or a live-call snapshot). */
export function parseDeals(raw: unknown): DealsData | null {
  if (!isObj(raw)) return null;
  const ass = isObj(raw.assumptions) ? raw.assumptions : {};
  const talk = isObj(raw.talk) ? raw.talk : null;
  const ver = isObj(raw.verification) ? raw.verification : null;
  const status: Record<string, string> = {};
  if (isObj(raw.claim_status)) for (const [k, v] of Object.entries(raw.claim_status)) if (typeof v === "string") status[k] = v;
  return {
    decision: str(raw.decision) ?? "none",
    headline: str(raw.headline) ?? "",
    assessments: arr(raw.assessments).filter(isObj).map(readAssessment),
    rejectedTerms: arr(raw.rejected_terms)
      .filter(isObj)
      .map((r) => ({ id: str(r.id) ?? "", label: str(r.label) ?? "", reasons: strs(r.reasons) })),
    assumptions: {
      minProbability: num(ass.min_probability) ?? 0.6,
      valueBasis: str(ass.value_basis) ?? "risk_adjusted",
      rampByMonth: nums(ass.ramp_by_month),
      cv: num(ass.cv) ?? 0.45,
      mcDraws: num(ass.mc_draws) ?? 0,
      seed: num(ass.seed) ?? 0,
      costOfCapital: num(ass.cost_of_capital_pct_annual) ?? 0,
      carrying: num(ass.inventory_carrying_pct_monthly) ?? 0,
    },
    talk: talk
      ? {
          talkTrack: str(talk.talk_track) ?? "",
          emailParagraph: str(talk.email_paragraph) ?? "",
          source: str(talk.source) ?? "rules",
          struck: strs(talk.struck),
        }
      : null,
    claimStatus: status,
    verification: ver ? { total: num(ver.total) ?? 0, verified: num(ver.verified) ?? 0, rejected: num(ver.rejected) ?? 0 } : null,
  };
}

export function readDeals(stage: StageResult | undefined | null): DealsData | null {
  const d = stage?.data;
  if (!stage || !isObj(d)) return null;
  const deals = parseDeals(d.deals);
  return deals && deals.assessments.length + deals.rejectedTerms.length > 0 ? deals : null;
}

// ---- formatting ----

/** Chance as a percent; anything under 0.1% reads "<0.1%" so a near-impossible target is not shown as exactly 0. */
export function fmtProb(p: number | null | undefined): string {
  if (p == null || Number.isNaN(p)) return "—";
  return p < 0.001 ? "<0.1%" : `${(p * 100).toFixed(1)}%`;
}

export const fmtPts = (x: number): string => x.toFixed(1);

/** A metric value: units, rupees (₹5.00L) or sell-through percent. */
export function fmtMetric(metric: DealMetric, v: number): string {
  if (metric === "gmv_inr") return inrCompact(v);
  if (metric === "sell_through_pct") return `${Math.round(v * 10) / 10}%`;
  return `${Math.round(v).toLocaleString("en-IN")}`;
}

export function metricNoun(metric: DealMetric): string {
  return metric === "gmv_inr" ? "GMV" : metric === "sell_through_pct" ? "sell-through" : "units";
}

/** "verified" when every claim whose id contains `marker` was verified; "rejected" if any was; else "unknown". */
export function claimState(status: Record<string, string>, marker: string): "verified" | "rejected" | "unknown" {
  const hits = Object.entries(status).filter(([id]) => id.includes(marker));
  if (!hits.length) return "unknown";
  if (hits.some(([, s]) => s === "rejected")) return "rejected";
  return hits.every(([, s]) => s === "verified") ? "verified" : "unknown";
}

export const DECISION_LABEL: Record<DealDecision, string> = {
  accept: "Accept",
  reject_structure: "Reject structure",
  needs_human: "Needs a human",
  not_assessable: "Not assessable",
};

/** The one-line gap-table annotation: "15% base + 20% bonus … → P(hit) <0.1% → counts as 15%". */
export function dealNote(a: DealAssessment): string {
  const p = a.probability != null ? ` → P(hit) ${fmtProb(a.probability)}` : "";
  if (a.netPts != null) return `${a.label} → net ${a.netPts >= 0 ? "+" : "−"}${fmtPts(Math.abs(a.netPts))} pts`;
  return `${a.label}${p} → counts as ${fmtPts(a.countedPts)}%`;
}
