import { describe, expect, it } from "vitest";
import type { Claim } from "./api";
import { isNarrativeStale, mergeClaims, readResearch, screeningFailure } from "./runs";
import { researchData, snapshot, stage } from "../test-utils/mockBackend";

const claim = (id: string, status: Claim["status"], origin: Claim["origin"] = "engine"): Claim => ({
  id,
  text: id,
  value: 1,
  metric: "cost",
  unit: "inr",
  status,
  origin,
  source_ref: { file: "f", key: "k" },
});

describe("mergeClaims", () => {
  it("de-dupes by id with run claims winning and recomputes totals", () => {
    const base = {
      total: 2,
      verified: 2,
      rejected: 0,
      unverifiable: 0,
      claims: [claim("a", "verified"), claim("b", "verified")],
    };
    const run = snapshot({
      research: stage("research", { claims: [claim("b", "rejected", "model_extraction"), claim("c", "verified")] }),
    });
    const m = mergeClaims(base, run)!;
    expect(m.claims.map((c) => c.id).sort()).toEqual(["a", "b", "c"]);
    expect(m).toMatchObject({ total: 3, verified: 2, rejected: 1 });
    expect(m.claims.find((c) => c.id === "b")!.origin).toBe("model_extraction");
  });

  it("returns null with nothing to show", () => {
    expect(mergeClaims(null, null)).toBeNull();
  });
});

describe("narrative staleness", () => {
  const run = snapshot({ research: stage("research", { narrative_hash: "h1" }) });
  it("is stale only when hashes differ", () => {
    expect(isNarrativeStale(run, "h2")).toBe(true);
    expect(isNarrativeStale(run, "h1")).toBe(false);
    expect(isNarrativeStale(null, "h1")).toBe(false);
  });
});

describe("readers", () => {
  it("flags screening failure from the decision", () => {
    const run = snapshot({
      intake: stage("intake", { data: { decision: "fail", reasons: ["Missing GST certificate"] } }),
    });
    expect(screeningFailure(run)).toEqual(["Missing GST certificate"]);
    expect(screeningFailure(snapshot({ intake: stage("intake", { data: { decision: "pass" } }) }))).toBeNull();
  });

  it("reads research output defensively", () => {
    const r = readResearch(stage("research", { data: researchData }))!;
    expect(r.terms).toEqual(["Cost down 3%", "MOQ: ask 150"]);
    expect(r.struck[0].reason).toBe("sheet says 421");
    expect(readResearch(stage("research", { data: null }))).toBeNull();
  });
});
