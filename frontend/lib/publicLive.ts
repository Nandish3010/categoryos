/** The public live budget as the API reports it, and the one sentence the UI shows when it runs out. */

export type PublicLiveStatus = {
  enabled: boolean;
  features: string[];
  budget_usd: number;
  remaining_usd: number;
  per_ip_usd: number;
  ip_remaining_usd?: number;
  exhausted?: boolean;
};

export const BUDGET_EXHAUSTED_CODE = "public_budget_exhausted";
export const BUDGET_EXHAUSTED_MESSAGE = "Public live budget used up: showing the recorded run";

/** True when public live is configured for this feature and still has room (shared remainder only). */
export function publicLiveOpen(p: PublicLiveStatus | null | undefined, feature: "byo" | "copilot"): boolean {
  return !!p && p.enabled && p.features.includes(feature) && p.remaining_usd > 0 && !p.exhausted;
}

/** The message for a budget-exhausted state, from the status or from an API error body. */
export function budgetMessage(p: PublicLiveStatus | null | undefined, errorCode?: string): string | null {
  if (errorCode === BUDGET_EXHAUSTED_CODE) return BUDGET_EXHAUSTED_MESSAGE;
  if (p && p.enabled && (p.remaining_usd <= 0 || p.exhausted)) return BUDGET_EXHAUSTED_MESSAGE;
  return null;
}
