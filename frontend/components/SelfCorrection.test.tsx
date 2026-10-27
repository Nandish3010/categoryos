import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Claim } from "@/lib/api";
import { readResearch } from "@/lib/runs";
import { describeEvent } from "@/lib/trace";
import { stage, traceEvent } from "../test-utils/mockBackend";
import { ClaimRow, formatClaimValue, isCorrected } from "./ClaimRow";
import { NarrativeCard } from "./workspace/RunPanels";
import { VerifierCard } from "./workspace/RightPanel";
import { TracePanel } from "./workspace/TracePanel";

const base: Claim = {
  id: "V001:HP-D01:cost:extracted",
  text: "HP-D01 cost is ₹956.5 (sheet row 2, Cost to Us)",
  value: 956.5,
  metric: "cost",
  unit: "inr",
  status: "verified",
  recomputed: 956.5,
  origin: "model_extraction",
  source_ref: { file: "vendors/V001/sku_sheet.csv", key: "V001:HP-D01", column: "Cost to Us" },
  evidence: { row: 2, header: "Cost to Us", raw_value: "Rs. 956.50", normalized_value: 956.5 },
  attempts: [
    { attempt: 0, value: 965.5, status: "rejected", reason: "sheet cell 'Rs. 956.50' parses to 956.5, claim says 965.5", recomputed: 956.5 },
    { attempt: 1, value: 956.5, status: "verified", reason: null, recomputed: 956.5 },
  ],
};

describe("ClaimRow self-correction", () => {
  it("shows a caught-then-corrected claim with the timeline of attempts", () => {
    render(<ul><ClaimRow claim={base} /></ul>);
    const row = screen.getAllByRole("listitem")[0];
    expect(row).toHaveAttribute("data-status", "corrected");
    expect(within(row).getByText("Caught → corrected")).toBeInTheDocument();
    const attempts = within(row).getByRole("list", { name: "Attempts" });
    const items = within(attempts).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("First answer: ₹965.50 · rejected");
    expect(items[0]).toHaveTextContent("parses to 956.5");
    expect(items[1]).toHaveTextContent("Retry 1: ₹956.50 · verified");
    // the corrected claim is not struck through and shows no red diff box
    expect(within(row).queryByText(/Agent said/)).toBeNull();
    expect(row.querySelector(".line-through")).toBeNull();
    expect(within(row).getByLabelText("Caught, then corrected")).toBeInTheDocument();
  });

  it("marks a claim that never got right as unresolved and keeps the red diff", () => {
    const unresolved: Claim = {
      ...base,
      status: "rejected",
      value: 965,
      reason: "sheet cell 'Rs. 956.50' parses to 956.5, claim says 965",
      attempts: [
        { attempt: 0, value: 965.5, status: "rejected", reason: "wrong" },
        { attempt: 1, value: 965, status: "rejected", reason: "still wrong" },
        { attempt: 2, value: 965, status: "rejected", reason: "still wrong" },
      ],
    };
    render(<ul><ClaimRow claim={unresolved} /></ul>);
    const row = screen.getAllByRole("listitem")[0];
    expect(row).toHaveAttribute("data-status", "rejected");
    expect(within(row).getByText("Unresolved after 2 retries")).toBeInTheDocument();
    expect(within(row).getByText(/Agent said ₹965 /)).toBeInTheDocument();
    expect(within(row).getAllByRole("listitem")).toHaveLength(3);
  });

  it("does not add a timeline to an ordinary claim", () => {
    render(<ul><ClaimRow claim={{ ...base, attempts: [] }} /></ul>);
    expect(screen.queryByRole("list", { name: "Attempts" })).toBeNull();
    expect(isCorrected({ ...base, attempts: [] })).toBe(false);
  });

  it("formats quantity claims", () => {
    expect(formatClaimValue(1500, "qty")).toBe("1500");
    expect(formatClaimValue(1.5, "qty")).toBe("1.5");
  });
});

describe("VerifierCard", () => {
  it("counts caught-and-corrected claims in the summary", () => {
    const claims = [base, { ...base, id: "x", attempts: [] }];
    render(
      <VerifierCard
        base={{ total: 2, verified: 2, rejected: 0, unverifiable: 0, claims }}
        baseLoading={false}
        baseError={null}
        injected={null}
        injectedLoading={false}
        injectOn={false}
        onToggleInject={() => {}}
      />,
    );
    expect(screen.getByText(/2 verified · 1 caught and corrected/)).toBeInTheDocument();
  });
});

describe("research data", () => {
  const extractions = [
    { sku_code: "HP-D01", field: "cost", value: 956.5, original_value: 965.5, status: "verified", attempts: [{}, {}] },
    { sku_code: "HP-D02", field: "cost", value: 3150, status: "verified" },
    { sku_code: "HP-D03", field: "mrp", value: 1699, original_value: 1969, status: "rejected", attempts: [{}, {}, {}] },
  ];

  it("lists only the extractions that were corrected and verified", () => {
    const r = readResearch(stage("research", { data: { extractions } }))!;
    expect(r.corrections).toEqual([{ code: "HP-D01", field: "cost", original: 965.5, corrected: 956.5, attempts: 2 }]);
  });

  it("shows them on the narrative as caught and corrected, next to the struck list", () => {
    const research = readResearch(stage("research", { data: { headline: "h", extractions } }))!;
    render(<NarrativeCard research={research} stale={false} replanning={false} onReplan={() => {}} />);
    const list = screen.getByRole("list", { name: "Corrected by the agent" });
    expect(within(list).getByText("Caught → corrected")).toBeInTheDocument();
    expect(within(list).getByText("₹965.50")).toBeInTheDocument();
    expect(within(list).getByText("₹956.50")).toBeInTheDocument();
    expect(within(list).getByText(/The narrative uses the corrected value/)).toBeInTheDocument();
  });

  it("shows no corrected block when nothing was corrected", () => {
    const research = readResearch(stage("research", { data: { headline: "h" } }))!;
    render(<NarrativeCard research={research} stale={false} replanning={false} onReplan={() => {}} />);
    expect(screen.queryByRole("list", { name: "Corrected by the agent" })).toBeNull();
  });
});

describe("trace", () => {
  const claim = { text: "HP-D01 cost is ₹965.5", reason: "sheet cell parses to 956.5" };

  it("describes the four self-correction events", () => {
    expect(describeEvent(traceEvent(1, { type: "claim_rejected", payload: { claim, attempt: 0 } }))).toEqual({
      title: "research · claim rejected",
      detail: "HP-D01 cost is ₹965.5 · sheet cell parses to 956.5",
    });
    expect(describeEvent(traceEvent(2, { type: "claim_rejected", payload: { claim, attempt: 1 } })).title).toBe("research · claim rejected (retry 1)");
    expect(
      describeEvent(traceEvent(3, { type: "self_correction", payload: { attempt: 1, of: 2, answered: true, feedback: ["Claim X rejected: you said ₹965.50. Re-read and correct."] } })),
    ).toEqual({ title: "research · self-correction 1/2", detail: "Claim X rejected: you said ₹965.50. Re-read and correct." });
    expect(describeEvent(traceEvent(4, { type: "self_correction", payload: { attempt: 1, of: 2, answered: false, note: "fixture_missing: no corrected answer available" } })).detail).toMatch(/fixture_missing/);
    expect(describeEvent(traceEvent(5, { type: "claim_verified", payload: { claim } }))).toEqual({ title: "research · claim corrected", detail: "HP-D01 cost is ₹965.5" });
    expect(describeEvent(traceEvent(6, { type: "claim_unresolved", payload: { claim } })).title).toBe("research · claim unresolved");
  });

  it("renders them in the trace panel with their own icons", () => {
    const events = [
      traceEvent(1, { type: "claim_rejected", payload: { claim, attempt: 0 } }),
      traceEvent(2, { type: "self_correction", payload: { attempt: 1, of: 2, answered: true, feedback: ["f"] } }),
      traceEvent(3, { type: "claim_verified", payload: { claim, attempt: 1 } }),
      traceEvent(4, { type: "claim_unresolved", payload: { claim } }),
    ];
    render(<TracePanel events={events} conn="idle" running={false} hasRun />);
    expect(screen.getByText("research · self-correction 1/2")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "self correction" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "claim unresolved" })).toBeInTheDocument();
  });
});
