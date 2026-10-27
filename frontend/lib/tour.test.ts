import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOUR_STEPS, TOUR_STORAGE_KEY, clampStep, markTourSeen, readTourSeen, shouldAutoStart } from "./tour";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("tour steps", () => {
  it("has 5 to 6 steps with Meera waving first, celebrating last, pointing between", () => {
    expect(TOUR_STEPS.length).toBeGreaterThanOrEqual(5);
    expect(TOUR_STEPS.length).toBeLessThanOrEqual(6);
    expect(TOUR_STEPS[0].pose).toBe("waving");
    expect(TOUR_STEPS.at(-1)?.pose).toBe("celebrating");
    expect(TOUR_STEPS.slice(1, -1).every((s) => s.pose === "pointing")).toBe(true);
  });
  it("walks board, V001, verifier, V002 negotiation, run inbox, impact", () => {
    expect(TOUR_STEPS.map((s) => s.href)).toEqual(["/", "/vendors/V001", "/vendors/V001", "/vendors/V002?stage=negotiate", "/run", "/"]);
  });
  it("clamps indexes", () => {
    expect(clampStep(-3)).toBe(0);
    expect(clampStep(99)).toBe(TOUR_STEPS.length - 1);
  });
});

describe("tour seen flag", () => {
  it("is unseen until marked, then remembered", () => {
    expect(readTourSeen()).toBe(false);
    markTourSeen();
    expect(localStorage.getItem(TOUR_STORAGE_KEY)).toBe("done");
    expect(readTourSeen()).toBe(true);
  });
  it("never throws when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readTourSeen()).toBe(false);
    expect(() => markTourSeen()).not.toThrow();
  });
  it("auto-starts only for a first-time visitor on the board at 900px or wider", () => {
    expect(shouldAutoStart("/", 1280, false)).toBe(true);
    expect(shouldAutoStart("/", 1280, true)).toBe(false);
    expect(shouldAutoStart("/", 600, false)).toBe(false);
    expect(shouldAutoStart("/vendors/V001", 1280, false)).toBe(false);
  });
});
