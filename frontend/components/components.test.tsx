import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Claim, Verdict } from "@/lib/api";
import { parseErrorBody } from "@/lib/api";
import { Chip } from "./Chip";
import { ClaimRow } from "./ClaimRow";

describe("Chip", () => {
  const cases: [Verdict, string][] = [
    ["list", "List"],
    ["negotiate", "Negotiate"],
    ["reject", "Reject"],
    ["needs_data", "Needs data"],
  ];
  it.each(cases)("renders text and an icon for %s", (verdict, label) => {
    const { container } = render(<Chip verdict={verdict} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelector(`[data-verdict="${verdict}"]`)).not.toBeNull();
  });
});

const rejected: Claim = {
  id: "c1",
  text: "Cost of HP-D01 is ₹412",
  value: 412,
  metric: "cost",
  unit: "inr",
  status: "rejected",
  recomputed: 421,
  origin: "model_extraction",
  reason: "Value differs from source cell",
  source_ref: { file: "sku_sheet.csv", key: "V001:HP-D01", column: "Cost" },
  evidence: { row: 7, header: "Cost", raw_value: "421", normalized_value: 421 },
};

describe("ClaimRow", () => {
  it("shows both agent and sheet values when rejected", () => {
    render(<ul><ClaimRow claim={rejected} /></ul>);
    expect(screen.getByText(/Agent said ₹412/)).toBeInTheDocument();
    expect(screen.getByText(/Sheet says ₹421/)).toBeInTheDocument();
    expect(screen.getByText(/sku_sheet\.csv · row 7 · Cost/)).toBeInTheDocument();
  });

  it("labels injected tests", () => {
    render(<ul><ClaimRow claim={{ ...rejected, origin: "injected_test" }} /></ul>);
    expect(screen.getByText("Injected test")).toBeInTheDocument();
  });

  it("does not show a diff for verified claims", () => {
    render(<ul><ClaimRow claim={{ ...rejected, status: "verified" }} /></ul>);
    expect(screen.queryByText(/Agent said/)).toBeNull();
  });
});

describe("parseErrorBody", () => {
  it("parses code/problem/cause/fix", () => {
    expect(parseErrorBody(500, { code: "x", problem: "p", cause: "c", fix: "f" })).toEqual({
      code: "x",
      problem: "p",
      cause: "c",
      fix: "f",
    });
  });
  it("falls back to FastAPI detail", () => {
    expect(parseErrorBody(404, { detail: "unknown vendor" }).problem).toBe("unknown vendor");
  });
});
