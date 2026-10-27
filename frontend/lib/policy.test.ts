import { describe, expect, it } from "vitest";
import { boundsFromPolicy, DEFAULT_LEVER_BOUNDS } from "./leverPolicy";
import { targetBreakdownText } from "./format";
import { vendorOutcome } from "./outcome";
import { diffPolicy, setPath, touches } from "./policy";
import type { DecideSummary } from "./api";

const summary = (counts: DecideSummary["counts"]): DecideSummary => ({
  counts, moq: 0, shortlisted: 0, capital_at_risk_inr: 0, days_of_cover: null, est_monthly_gmv: 0, moq_flag: false,
});

describe("diffPolicy", () => {
  const base = { research: { demand_min: 0.4, fit_weights: { margin: 0.4, demand: 0.3 } }, tags: ["a"] };
  it("is empty when unchanged", () => {
    expect(diffPolicy(structuredClone(base), base)).toEqual({ partial: {}, paths: [] });
  });
  it("sends only changed keys, nested", () => {
    const d = setPath(base, "research.fit_weights.margin", 0.5);
    expect(diffPolicy(d, base)).toEqual({
      partial: { research: { fit_weights: { margin: 0.5 } } },
      paths: ["research.fit_weights.margin"],
    });
  });
  it("replaces arrays whole and tombstones removed keys", () => {
    const b = { m: { brands: { A: { x: 1 }, B: { x: 2 } } }, tags: ["a"] };
    const d = { m: { brands: { A: { x: 1 } } }, tags: ["a", "b"] };
    expect(diffPolicy(d, b).partial).toEqual({ m: { brands: { B: null } }, tags: ["a", "b"] });
  });
  it("touches matches parents and children", () => {
    expect(touches("a.b", ["a.b.c"])).toBe(true);
    expect(touches("a.b.c", ["a.b"])).toBe(true);
    expect(touches("a.x", ["a.b"])).toBe(false);
  });
});

describe("lever bounds", () => {
  it("falls back to constants", () => {
    expect(boundsFromPolicy(null)).toEqual(DEFAULT_LEVER_BOUNDS);
    expect(boundsFromPolicy({ levers: { margin_offset: { min: 5, max: 1, step: 1 } } })).toEqual(DEFAULT_LEVER_BOUNDS);
  });
  it("reads policy.levers", () => {
    const b = boundsFromPolicy({ levers: { margin_offset: { min: -5, max: 8, step: 0.5 }, moq: { step: 25, max_factor: 3 } } });
    expect(b).toEqual({ offsetMin: -5, offsetMax: 8, offsetStep: 0.5, moqStep: 25, moqMaxFactor: 3 });
  });
});

describe("vendorOutcome", () => {
  it("failed screening wins over SKU counts", () => {
    expect(vendorOutcome(summary({ list: 3 }), true)).toBe("failed_screening");
  });
  it("keeps Negotiate when rejects outnumber negotiates", () => {
    expect(vendorOutcome(summary({ negotiate: 4, reject: 6 }), false)).toBe("negotiate");
  });
  it("shows Reject only when nothing lists or negotiates", () => {
    expect(vendorOutcome(summary({ reject: 5 }), false)).toBe("reject");
  });
  it("keeps list/negotiate otherwise", () => {
    expect(vendorOutcome(summary({ list: 1, reject: 9 }), false)).toBe("list");
    expect(vendorOutcome(summary({ negotiate: 3, reject: 1 }), false)).toBe("negotiate");
  });
});

describe("targetBreakdownText", () => {
  it("explains the sum", () => {
    expect(targetBreakdownText({ category_pct: 27, vendor_type_pp: -3, brand_pp: 0, lever_pp: 2 }, 0.26)).toBe(
      "27% category −3 pp vendor type 0 pp brand +2 pp lever = 26%",
    );
  });
});
