/** A deal-evaluator payload shaped like V002's rejected contingent litter offer (docs/api-contract.md). */
export function dealsFixture(over: Record<string, unknown> = {}) {
  const bins = Array.from({ length: 33 }, (_, i) => 100 + i * 12);
  const density = bins.slice(0, 32).map((_, i) => Math.exp(-((i - 10) ** 2) / 40) / 30);
  return {
    decision: "reject_structure",
    headline: "Reject the conditional structure and counter",
    assessments: [
      {
        term_id: "t2",
        kind: "conditional",
        term: "marketing_pct",
        label: "20% marketing support if 2,000 units in 90 days (on a 15% margin base)",
        source: "transcript",
        turn: 18,
        quote: "On top of that I will give you 20 percent marketing support on sales if you sell 2,000 units across the range within the first 90 days.",
        decision: "reject_structure",
        call: "Reject this structure and counter. The chance of 2,000 units in 90 days is <0.1%, so the bonus counts as 0.0 points and the offer is worth 15.0% against 22.0% required.",
        reasoning: ["Demand over 90 days: P10 165 units, P50 245 units, P90 362 units."],
        base_pts: 15,
        face_pts: 35,
        expected_bonus_pts: 0,
        counted_bonus_pts: 0,
        expected_pts: 15,
        guaranteed_pts: 15,
        counted_pts: 15,
        required_pts: 22,
        shortfall_pts: -7,
        probability: 0,
        tiers: [{ threshold: 2000, bonus_pts: 20, incremental_pts: 20, probability: 0, counted: false }],
        distribution: { metric: "units", window_days: 90, mean: 256, p10: 165, p50: 245, p90: 362, threshold: 2000, bins, density },
        counters: [
          { kind: "threshold", text: "set the target at 250 units in 90 days (P = 60.5%); counted value becomes 27.1% against 22.0% required.", threshold: 250, probability: 0.605, counted_pts_after: 27.1, meets_requirement: true },
          { kind: "convert_to_base", text: "ask for a guaranteed base of 22.0% (+7.0 points) in place of the volume-linked bonus, which is worth 0.0 points risk-adjusted.", required_base_pts: 22, uplift_pts: 7, fair_conversion_pts: 0, counted_pts_after: 22, meets_requirement: true },
        ],
        recommended_counter: 0,
        net_pts: null,
        base_assumed: false,
      },
    ],
    base_terms: [],
    rejected_terms: [],
    assumptions: { min_probability: 0.6, value_basis: "risk_adjusted", ramp_by_month: [0.5, 0.75, 0.9, 1], cv: 0.45, mc_draws: 20000, seed: 42, cost_of_capital_pct_annual: 14, inventory_carrying_pct_monthly: 2 },
    talk: { talk_track: "We cannot accept the litter structure as offered.", email_paragraph: "On the cat litter, we cannot accept it.", source: "model", struck: [] },
    claim_status: { "V002:dealterm:t2:value": "verified", "V002:deal:t2:deal_probability:tier:0": "verified" },
    verification: { total: 14, verified: 14, rejected: 0, unverifiable: 0 },
    ...over,
  };
}
