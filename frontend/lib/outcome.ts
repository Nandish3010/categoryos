import type { DecideSummary, Verdict } from "./api";

export type VendorOutcome = "failed_screening" | Verdict;

/**
 * Headline outcome for a vendor card. A failed screen wins over the SKU counts;
 * Reject only when nothing lists, negotiates or needs data.
 */
export function vendorOutcome(summary: DecideSummary, screeningFailed: boolean): VendorOutcome {
  if (screeningFailed) return "failed_screening";
  const c = summary.counts;
  const list = c.list ?? 0;
  const neg = c.negotiate ?? 0;
  const nd = c.needs_data ?? 0;
  if (list > 0) return "list";
  if (neg > 0) return "negotiate";
  if (nd > 0) return "needs_data";
  return "reject";
}
