import { describe, expect, it } from "vitest";
import { runImpact } from "../test-utils/impact";
import { duration, impactChipLabel, impactHeadline, reduction, reviewTime } from "./impact";

describe("impact formatting", () => {
  it("shows hours above an hour and minutes below", () => {
    expect(duration(855)).toBe("14.3 h");
    expect(duration(45)).toBe("45 min");
    expect(duration(0.2)).toBe("0.2 min");
  });

  it("signs the reduction", () => {
    expect(reduction(92.4)).toBe("−92%");
    expect(reduction(-5)).toBe("+5%");
    expect(reduction(null)).toBe("—");
  });

  it("says nothing was recorded yet when no step was reviewed", () => {
    const i = runImpact({ measured_gates: 0, reduction_pct: null, human_minutes: 0, basis: "baseline_estimate", edits: 0 });
    expect(impactHeadline(i)).toBe("Baseline 14.3 h by hand · human review not recorded yet");
    expect(impactChipLabel(i)).toBe("Impact · 14.3 h baseline");
  });

  it("says 'so far' on a partly reviewed run and names how many steps", () => {
    const i = runImpact();
    expect(impactHeadline(i)).toBe("So far: baseline 4.0 h → 10 min human review (−96%) on 1 of 3 review steps · 2 edits");
    expect(impactChipLabel(i)).toBe("Impact −96% so far");
  });

  it("reads as the product sentence once every step is reviewed", () => {
    const i = runImpact({ complete: true, measured_gates: 3, baseline_measured_minutes: 855, human_minutes: 72, reduction_pct: 91.6, edits: 3 });
    expect(impactHeadline(i)).toBe("This vendor: baseline 14.3 h → 1.2 h human review (−92%) · 3 edits");
    expect(impactChipLabel(i)).toBe("Impact −92%");
    expect(impactHeadline({ ...i, edits: 1 })).toContain("· 1 edit");
  });

  it("shows how a capped gap was counted", () => {
    const g = runImpact().gates[0];
    expect(reviewTime(g)).toBe("10 min");
    expect(reviewTime({ ...g, review_seconds: 18000, counted_minutes: 120, capped: true })).toBe("5.0 h (counted as 2.0 h)");
    expect(reviewTime({ ...g, review_seconds: 42 })).toBe("42 s");
    expect(reviewTime(runImpact().gates[1])).toBe("not reviewed yet");
  });
});
