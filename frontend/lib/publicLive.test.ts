import { describe, expect, it } from "vitest";
import { BUDGET_EXHAUSTED_MESSAGE, budgetMessage, publicLiveOpen, type PublicLiveStatus } from "./publicLive";

const on: PublicLiveStatus = { enabled: true, features: ["copilot"], budget_usd: 10, remaining_usd: 4, per_ip_usd: 0.5 };

describe("public live budget", () => {
  it("is open only for a listed feature with room left", () => {
    expect(publicLiveOpen(on, "copilot")).toBe(true);
    expect(publicLiveOpen(on, "byo")).toBe(false);
    expect(publicLiveOpen({ ...on, remaining_usd: 0 }, "copilot")).toBe(false);
    expect(publicLiveOpen({ ...on, exhausted: true }, "copilot")).toBe(false);
    expect(publicLiveOpen({ ...on, enabled: false }, "copilot")).toBe(false);
    expect(publicLiveOpen(undefined, "copilot")).toBe(false);
  });
  it("gives the exhausted message from the status or the API error code", () => {
    expect(budgetMessage({ ...on, remaining_usd: 0 })).toBe(BUDGET_EXHAUSTED_MESSAGE);
    expect(budgetMessage(on, "public_budget_exhausted")).toBe(BUDGET_EXHAUSTED_MESSAGE);
    expect(budgetMessage(on)).toBeNull();
    expect(budgetMessage({ ...on, enabled: false, remaining_usd: 0 })).toBeNull();
    expect(budgetMessage(undefined)).toBeNull();
  });
});
