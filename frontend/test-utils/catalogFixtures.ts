import type { Claim } from "@/lib/api";
import type { CatalogQueue, Fix, Listing, QueueRow, Summary } from "@/lib/catalog";

const claim = (id: string, text: string, over: Partial<Claim> = {}): Claim =>
  ({
    id,
    text,
    value: 1100,
    metric: "qc_mrp",
    unit: "inr",
    source_ref: { file: "ops/vendor_price_list.csv", key: "E001:BK-02" },
    evidence: null,
    origin: "engine",
    status: "verified",
    recomputed: 1100,
    reason: null,
    attempts: [],
    ...over,
  }) as unknown as Claim;

export const priceFix = (over: Partial<Fix> = {}): Fix => ({
  id: "fix:L-BK-02:price",
  listing_id: "L-BK-02",
  vendor_id: "E001",
  sku_code: "BK-02",
  kind: "price",
  source: "deterministic",
  title: "Set MRP to ₹1,100",
  issue_ids: ["L-BK-02:mrp_mismatch"],
  issue_types: ["mrp_mismatch"],
  changes: [{ field: "mrp", label: "MRP", before: 1050, after: 1100, before_text: "1050", after_text: "1100" }],
  claim_ids: ["c1"],
  status: "ready",
  reason: null,
  notes: [],
  claims_verified: 1,
  claims_total: 1,
  decision: "pending",
  decided_at: null,
  ...over,
});

export const copyFix = (over: Partial<Fix> = {}): Fix => ({
  ...priceFix(),
  id: "fix:L-BK-01:copy",
  listing_id: "L-BK-01",
  sku_code: "BK-01",
  kind: "copy",
  source: "model",
  title: "Rewrite the title and bullets",
  issue_ids: ["L-BK-01:banned_claim"],
  issue_types: ["banned_claim"],
  changes: [
    { field: "title", label: "Title", before: "BEST dog food", after: "Dog food", before_text: "BEST dog food", after_text: "Dog food" },
  ],
  claim_ids: ["c2", "c3"],
  claims_total: 2,
  claims_verified: 2,
  ...over,
});

const row = (over: Partial<QueueRow>): QueueRow => ({
  id: "L-BK-02:mrp_mismatch",
  rank: 1,
  listing_id: "L-BK-02",
  vendor_id: "E001",
  brand: "Barkley & Co",
  sku_code: "BK-02",
  listing_title: "Barkley & Co Lamb & Rice 3 kg",
  type: "mrp_mismatch",
  severity: "high",
  message: "MRP on the listing is ₹1050; the latest price list says ₹1100",
  detail: {},
  score: 60.5,
  signals: { gmv: 70, severity: 100, return_rate: 0 },
  gmv_at_risk_inr: 800000,
  nad_rate_pct: null,
  fix_id: "fix:L-BK-02:price",
  fix_status: "ready",
  no_fix_reason: null,
  decision: "pending",
  ...over,
});

const listing = (over: Partial<Listing>): Listing => ({
  listing_id: "L-BK-02",
  vendor_id: "E001",
  brand: "Barkley & Co",
  sku_code: "BK-02",
  title: "Barkley & Co Lamb & Rice 3 kg",
  before: {},
  after: {},
  fixes: ["fix:L-BK-02:price"],
  issue_ids: ["L-BK-02:mrp_mismatch"],
  gmv_at_risk_inr: 800000,
  top_score: 60.5,
  label: null,
  ...over,
});

export const summary = (over: Partial<Summary> = {}): Summary => ({
  issues: 3,
  fixes_total: 2,
  fixes_ready: 2,
  fixes_blocked: 0,
  fixes_approved: 0,
  fixes_rejected: 0,
  listings_ready: 2,
  minutes_per_listing: 12,
  minutes_saved: 24,
  minutes_saved_approved: 0,
  baseline_status: "research_estimate",
  ...over,
});

export function queue(over: Partial<CatalogQueue> = {}): CatalogQueue {
  return {
    as_of: "2026-10-26",
    mode: "mock",
    degraded: false,
    degraded_reason: null,
    vendors: [{ id: "E001", brand: "Barkley & Co" }, { id: "E002", brand: "Purrline Foods" }],
    issue_types: ["banned_claim", "mrp_mismatch", "missing_image"],
    rows: [
      row({}),
      row({ id: "L-BK-01:banned_claim", rank: 2, listing_id: "L-BK-01", sku_code: "BK-01", type: "banned_claim", severity: "high", score: 55, fix_id: "fix:L-BK-01:copy" }),
      row({ id: "L-PL-05:missing_image", rank: 3, listing_id: "L-PL-05", vendor_id: "E002", brand: "Purrline Foods", sku_code: "PL-05", type: "missing_image", severity: "high", score: 40, fix_id: null, fix_status: "none", no_fix_reason: "This needs a person: no automatic fix", decision: "none" }),
    ],
    listings: [
      listing({}),
      listing({ listing_id: "L-BK-01", sku_code: "BK-01", title: "BEST dog food", fixes: ["fix:L-BK-01:copy"], issue_ids: ["L-BK-01:banned_claim"] }),
      listing({ listing_id: "L-PL-05", vendor_id: "E002", brand: "Purrline Foods", sku_code: "PL-05", title: "Purrline Tuna Pouch", fixes: [], issue_ids: ["L-PL-05:missing_image"] }),
    ],
    fixes: { "fix:L-BK-02:price": priceFix(), "fix:L-BK-01:copy": copyFix() },
    claims: [claim("c1", "BK-02 MRP is ₹1,100 on the latest price list"), claim("c2", "The proposed title is 40 characters", { metric: "qc_title_chars", unit: "units" }), claim("c3", "The proposed text uses no claim the playbook bans", { metric: "qc_banned_claims", unit: "units", value: 0 })],
    verification: { total: 3, verified: 3, rejected: 0, unverifiable: 0 },
    corrected: [],
    unresolved: [],
    counts: { listings: 38, listings_with_issues: 3, issues: 3, by_type: { banned_claim: 1, mrp_mismatch: 1, missing_image: 1 } },
    trace: [],
    limits: { bulk_approve: 25 },
    summary: summary(),
    updates: [],
    simulated: true,
    impact_coverage: { module: "catalog_qc_queue", registered: true, status: "shipped", tasks: [], units: { catalog_fix_per_sku: 3 }, baseline_minutes: { catalog_fix_per_sku: 12 }, manual_minutes_replaced: 36, baseline_status: "research_estimate" },
    ...over,
  };
}
