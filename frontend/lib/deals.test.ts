import { describe, expect, it } from "vitest";
import { claimState, dealNote, fmtMetric, fmtProb, parseDeals, readDeals } from "./deals";
import { dealsFixture } from "../test-utils/deals";
import { stage } from "../test-utils/mockBackend";

describe("deal formatting", () => {
  it("never shows an impossible target as exactly 0", () => {
    expect(fmtProb(0)).toBe("<0.1%");
    expect(fmtProb(0.0004)).toBe("<0.1%");
    expect(fmtProb(0.605)).toBe("60.5%");
    expect(fmtProb(null)).toBe("—");
  });
  it("formats metrics by kind", () => {
    expect(fmtMetric("units", 2000)).toBe("2,000");
    expect(fmtMetric("gmv_inr", 500000)).toBe("₹5.00L");
    expect(fmtMetric("sell_through_pct", 70)).toBe("70%");
  });
});

describe("readDeals", () => {
  it("is null without deals, and reads a full assessment", () => {
    expect(readDeals(stage("negotiate", { data: { gap_table: [] } }))).toBeNull();
    const d = readDeals(stage("negotiate", { data: { deals: dealsFixture() } }))!;
    expect(d.assessments).toHaveLength(1);
    const a = d.assessments[0];
    expect(a.decision).toBe("reject_structure");
    expect(a.probability).toBe(0);
    expect(a.countedPts).toBe(15);
    expect(a.counters.map((c) => c.kind)).toEqual(["threshold", "convert_to_base"]);
    expect(a.distribution?.p50).toBe(245);
    expect(d.assumptions.minProbability).toBe(0.6);
    expect(d.talk?.source).toBe("model");
  });
  it("survives junk", () => {
    expect(parseDeals("x")).toBeNull();
    const d = parseDeals({ assessments: [{ decision: "bogus", tiers: "no", counters: [null] }] })!;
    expect(d.assessments[0].decision).toBe("not_assessable");
    expect(d.assessments[0].tiers).toEqual([]);
    expect(d.assessments[0].counters).toEqual([]);
  });
  it("writes the gap-table annotation", () => {
    const a = parseDeals(dealsFixture())!.assessments[0];
    expect(dealNote(a)).toBe("20% marketing support if 2,000 units in 90 days (on a 15% margin base) → P(hit) <0.1% → counts as 15.0%");
  });
  it("summarises claim states by id", () => {
    const status = { "V002:dealterm:t2:value": "verified", "V002:dealterm:t2:threshold": "verified", "V002:deal:t2:deal_probability:tier:0": "rejected" };
    expect(claimState(status, ":dealterm:t2:")).toBe("verified");
    expect(claimState(status, ":deal:t2:deal_probability:")).toBe("rejected");
    expect(claimState(status, ":dealterm:t9:")).toBe("unknown");
  });
});
