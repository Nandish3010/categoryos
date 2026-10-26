import { describe, expect, it } from "vitest";
import { inrExact } from "./format";
import { formatClaimValue } from "../components/ClaimRow";
import { leverFromRun, screenDefaultOpen, screenSummary } from "./screen";
import { approvalHash, defaultStage, progressOf, viewForStage } from "./stages";
import { researchData, snapshot, stage } from "../test-utils/mockBackend";
import type { ScreenData } from "./runs";

describe("inr paise", () => {
  it("keeps paise on non-integers so a transposition is visible", () => {
    expect(inrExact(965.5)).toBe("₹965.50");
    expect(inrExact(956.5)).toBe("₹956.50");
    expect(inrExact(1234)).toBe("₹1,234");
    expect(inrExact(221232.7)).toBe("₹2,21,232.70");
    expect(formatClaimValue(965.5, "inr")).toBe("₹965.50");
    expect(formatClaimValue(956.5, "inr")).not.toBe(formatClaimValue(965.5, "inr"));
  });
});

const screen = (over: Partial<ScreenData> = {}): ScreenData => ({
  risk_flags: [
    { type: "a", quote: "", severity: "low" },
    { type: "b", quote: "", severity: "low" },
  ],
  injection_detected: false,
  followup_questions: ["q1", "q2"],
  decision: "pass",
  reasons: [],
  documents: [
    { label: "GST", status: "valid" },
    { label: "FSSAI", status: "valid" },
  ],
  ...over,
});

describe("screen card logic", () => {
  it("collapses on pass with a one-line summary", () => {
    expect(screenDefaultOpen(screen())).toBe(false);
    expect(screenSummary(screen())).toBe("Screening passed · 2 documents OK · 2 low flags · 2 follow-ups");
  });
  it("expands on fail or injection", () => {
    expect(screenDefaultOpen(screen({ decision: "fail" }))).toBe(true);
    expect(screenDefaultOpen(screen({ injection_detected: true }))).toBe(true);
  });
});

describe("lever init from run", () => {
  it("reads research.data.lever", () => {
    const run = snapshot({ research: stage("research", { data: { ...researchData, lever: { target_margin_pct_offset: 3, moq: 400 } } }) });
    expect(leverFromRun(run)).toEqual({ offset: 3, moq: 400 });
    expect(leverFromRun(snapshot({ research: stage("research", { data: researchData }) }))).toBeNull();
    expect(leverFromRun(null)).toBeNull();
  });
});

describe("stage navigation", () => {
  it("maps stages to views", () => {
    expect(viewForStage("intake")).toBe("screen");
    expect(viewForStage("shortlist")).toBe("decide");
    expect(viewForStage("negotiate")).toBe("decide");
    expect(viewForStage("catalog")).toBe("catalog");
    expect(viewForStage("po")).toBe("launch");
  });
  it("defaults to the furthest review/running stage", () => {
    expect(defaultStage(null)).toBe("research");
    expect(defaultStage(snapshot({ intake: stage("intake"), research: stage("research", { status: "review" }) }))).toBe("research");
    expect(
      defaultStage(
        snapshot({
          research: stage("research"),
          negotiate: stage("negotiate"),
          catalog: stage("catalog", { status: "review" }),
        }),
      ),
    ).toBe("catalog");
    expect(defaultStage(snapshot({ research: stage("research"), shortlist: stage("shortlist"), negotiate: stage("negotiate", { status: "pending" }) }))).toBe("negotiate");
    expect(defaultStage(snapshot({ intake: stage("intake", { status: "failed" }) }))).toBe("research");
  });
  it("tracks the approve target and what runs next", () => {
    expect(progressOf(snapshot({ research: stage("research", { status: "review" }) }))).toEqual({ kind: "review", stage: "research" });
    expect(progressOf(snapshot({ research: stage("research"), negotiate: stage("negotiate", { status: "running" }) }))).toMatchObject({ label: "Negotiating…" });
    expect(progressOf(snapshot({ research: stage("research"), negotiate: stage("negotiate") }))).toMatchObject({ label: "Building catalog…" });
    expect(progressOf(snapshot({ research: stage("research"), catalog: stage("catalog", { status: "review" }) }))).toEqual({ kind: "review", stage: "catalog" });
    const run = snapshot({ research: stage("research", { narrative_hash: "h1" }), catalog: stage("catalog", { status: "review" }) });
    expect(approvalHash(run, "catalog", "lever")).toBe("h1");
  });
});
