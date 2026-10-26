import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Claim } from "@/lib/api";
import { Markdown } from "../Markdown";
import { stage } from "../../test-utils/mockBackend";
import { CatalogStudio } from "./CatalogStudio";
import { NegotiateView } from "./NegotiateView";
import { PoCard } from "./LaunchPacket";

const gap = (over: Record<string, unknown>) => ({
  term: "margin_pct", label: "Margin", unit: "pct", direction: "higher", application: 17, offered: 21, required: 35,
  gap: -14, status: "gap", turn: 2, quote: "I can move to 21 percent.", claim_id: "c", verification: "verified", ...over,
});

describe("NegotiateView", () => {
  const st = stage("negotiate", {
    summary: "1 of 2 terms meet",
    data: {
      gap_table: [gap({}), gap({ term: "payment_days", label: "Payment", unit: "days", application: 15, offered: 30, required: 21, gap: 9, status: "met", turn: 4, quote: "30 days works." })],
      transcript: { turns: [
        { turn: 1, speaker: "buyer", text: "Where can you get to?" },
        { turn: 2, speaker: "vendor", text: "Well, I can move to 21 percent. Done." },
        { turn: 4, speaker: "vendor", text: "30 days works." },
      ] },
      transcript_source: "canonical",
      refusals: [{ term: "returns", transcript_quote: "No returns.", turn: 3, note: "refused", quote_verified: true }],
      counter_offer: { asks: ["Lower MOQ"], email_draft: "Hi" },
    },
  });
  it("renders the gap table and highlights the quote when an offered value is clicked", () => {
    render(<NegotiateView stage={st} />);
    const table = screen.getByRole("region", { name: "Gap table" });
    expect(within(table).getByText("−14%")).toBeInTheDocument();
    expect(table.querySelector("tr[data-status=gap]")).not.toBeNull();
    expect(within(table).getByText("Met")).toBeInTheDocument();
    fireEvent.click(within(table).getByRole("button", { name: "21%" }));
    const mark = document.querySelector("mark");
    expect(mark?.textContent).toBe("I can move to 21 percent.");
    expect(screen.getByText("Canonical")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Refusals" })).toBeInTheDocument();
    expect(screen.getByText("Lower MOQ")).toBeInTheDocument();
  });
});

describe("PoCard", () => {
  const claim = (metric: string, status: Claim["status"]): Claim => ({
    id: metric, text: metric, value: 1, metric, unit: "inr", status, origin: "engine", source_ref: { file: "f", key: "k" },
  });
  it("renders totals with paise and verified ticks, and the delay alert", () => {
    const st = stage("po", {
      status: "review",
      claims: [claim("po_total", "verified"), claim("po_grand_total", "rejected")],
      data: {
        po_number: "PO-1", lines: [{ code: "A", name: "Item", units: 10, unit_cost: 95.5, line_total: 955 }],
        subtotal: 955.5, gst_rate: 0.18, gst: 171.99, grand_total: 1127.49,
        timeline: [{ step: "raised", status: "done", delay_days: 0 }, { step: "shipped", status: "delayed", delay_days: 3, alert: "3 days late" }],
        alerts: [],
      },
    });
    render(<PoCard stage={st} />);
    expect(screen.getByTestId("po-subtotal")).toHaveTextContent("₹955.50");
    expect(screen.getByLabelText("Subtotal verified")).toBeInTheDocument();
    expect(screen.queryByLabelText("Grand total verified")).not.toBeInTheDocument();
    expect(screen.getByTestId("po-grand")).toHaveTextContent("₹1,127.49");
    expect(screen.getAllByText("3 days late").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Approve PO" })).toBeEnabled();
  });
});

describe("CatalogStudio", () => {
  it("shows raw row, classification and placeholder tag", () => {
    const st = stage("catalog", {
      status: "review",
      data: {
        classifier_agreement_pct: 71.4,
        skus: [{ code: "X1", name: "Thing", verdict: "list", raw_row: { "Our Cost": "Rs. 956.50" },
          classification: { rules: { category: "a", subcategory: "b" }, model: { category: "a", subcategory: "c", valid: true }, agreement: false },
          copy: { title: "T", bullets: ["b1"], description: "d", attributes: { pack_g: 60 }, compliance_flags: [{ rule: "r", text: "t", severity: "high", source: "rules" }] },
          images: { packshot: "/api/assets/V/X1-packshot.png", cutout: "unavailable", lifestyle: null, image_source: "placeholder" }, hero: false }],
      },
    });
    render(<CatalogStudio stage={st} />);
    expect(screen.getByText("Rs. 956.50")).toBeInTheDocument();
    expect(screen.getByTestId("classification")).toHaveTextContent("Rules: a / b · Muse Spark Open: a / c · disagree");
    expect(screen.getByTestId("agreement")).toHaveTextContent("71.4%");
    expect(screen.getByText("placeholder · live image pending")).toBeInTheDocument();
    expect(screen.getByText("cutout unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve catalog" })).toBeEnabled();
  });
});

describe("Markdown", () => {
  it("escapes HTML and renders structure", () => {
    const { container } = render(<Markdown source={'# Title\n\n<script>alert(1)</script> **bold**\n\n- a\n\n| H |\n|---|\n| <img src=x onerror=1> |'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelectorAll("li")).toHaveLength(1);
  });
});
