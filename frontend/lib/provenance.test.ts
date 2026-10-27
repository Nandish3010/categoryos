import { describe, expect, it } from "vitest";
import { provenanceLabel } from "./provenance";

describe("provenanceLabel", () => {
  it("names a live recording with date and cost", () => {
    expect(provenanceLabel({ source: "live", recorded_at: "2026-10-26T10:00:00Z", cost_usd: 0.4321, degraded: false })).toBe(
      "Replay of live run · recorded 26 Oct 2026 · $0.43",
    );
  });
  it("never calls a scripted run live", () => {
    expect(provenanceLabel({ source: "mock", recorded_at: "2026-10-26T10:00:00Z", cost_usd: 0, degraded: false })).toBe("Replay of scripted run");
    expect(provenanceLabel({ source: "mock", recorded_at: null, cost_usd: 0, degraded: true })).toBe("Replay of scripted run");
  });
  it("is empty outside replay", () => {
    expect(provenanceLabel(null)).toBeNull();
    expect(provenanceLabel(undefined)).toBeNull();
  });
  it("copes with a live run missing its date or cost", () => {
    expect(provenanceLabel({ source: "live", recorded_at: null, cost_usd: 0, degraded: false })).toBe("Replay of live run");
  });
});
