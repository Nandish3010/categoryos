import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Claim } from "@/lib/api";
import { Markdown } from "../Markdown";
import { dealsFixture } from "../../test-utils/deals";
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

describe("Deal evaluator", () => {
  const withDeals = (over: Record<string, unknown> = {}) =>
    stage("negotiate", {
      summary: "4 of 6 terms meet",
      data: {
        gap_table: [gap({})],
        transcript: { turns: [{ turn: 18, speaker: "vendor", text: "Well. On top of that I will give you 20 percent marketing support on sales if you sell 2,000 units across the range within the first 90 days." }] },
        transcript_source: "canonical",
        refusals: [],
        counter_offer: { asks: [], email_draft: "" },
        deals: dealsFixture(over),
      },
    });

  it("leads with the probability, the risk-adjusted value, the decision and the counters", () => {
    render(<NegotiateView stage={withDeals()} />);
    const section = screen.getByRole("region", { name: "Deal evaluator" });
    expect(within(section).getByTestId("probability")).toHaveTextContent("<0.1%");
    expect(within(section).getByText("Reject structure")).toBeInTheDocument();
    expect(within(section).getByTestId("counted-pts")).toHaveTextContent("15.0%");
    expect(within(section).getByTestId("worth-bars")).toHaveTextContent("we need 22.0%");
    expect(within(section).getByTestId("worth-bars")).toHaveTextContent("Short by");
    const counters = within(section).getByTestId("counters");
    expect(within(counters).getByText("Recommended")).toBeInTheDocument();
    expect(counters).toHaveTextContent("Set the target at 250 units in 90 days");
    expect(counters).toHaveTextContent("Make it guaranteed");
    expect(within(section).getByTestId("distribution-chart")).toHaveAccessibleName(/P50 245.*beyond the chart/);
    expect(within(section).getByTestId("deal-talk")).toHaveTextContent("We cannot accept the litter structure");
  });

  it("annotates the margin row of the gap table and opens the card from it", () => {
    render(<NegotiateView stage={withDeals()} />);
    const table = screen.getByRole("region", { name: "Gap table" });
    const note = table.querySelector("tr[data-deal-note=t2]")!;
    expect(note).toHaveTextContent("P(hit) <0.1% → counts as 15.0%");
    fireEvent.click(within(note as HTMLElement).getByRole("button", { name: "See the probability and counters" }));
    expect(screen.getByRole("button", { name: /20% marketing support/ })).toHaveAttribute("aria-expanded", "true");
  });

  it("collapses and expands a card", () => {
    render(<NegotiateView stage={withDeals()} />);
    const header = screen.getByRole("button", { name: /20% marketing support/ });
    expect(header).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("probability")).not.toBeInTheDocument();
  });

  it("highlights the vendor's words on the call", () => {
    render(<NegotiateView stage={withDeals()} />);
    fireEvent.click(screen.getByRole("button", { name: "Show on the call" }));
    expect(document.querySelector("mark")?.textContent).toContain("20 percent marketing support");
  });

  it("shows tiers with their own probabilities for an accepted rebate", () => {
    const accepted = {
      decision: "accept",
      assessments: [{
        ...dealsFixture().assessments[0], decision: "accept", kind: "tiered", label: "back margin slabs: 2% above ₹5,00,000, 4% above ₹10,00,000 in 90 days",
        probability: 0.84, base_pts: 34, face_pts: 38, counted_pts: 35.7, required_pts: 27.3, shortfall_pts: 8.4, counted_bonus_pts: 1.7, expected_bonus_pts: 2,
        tiers: [{ threshold: 500000, bonus_pts: 2, incremental_pts: 2, probability: 0.84, counted: true }, { threshold: 1000000, bonus_pts: 4, incremental_pts: 2, probability: 0.12, counted: false }],
        distribution: { metric: "gmv_inr", window_days: 90, mean: 700000, p10: 450000, p50: 700000, p90: 1086000, threshold: 500000, bins: [300000, 600000, 900000, 1200000], density: [0.2, 0.5, 0.3] },
        counters: [], recommended_counter: null, call: "Accept: counted 35.7% against 27.3% required.",
      }],
      talk: null,
    };
    render(<NegotiateView stage={withDeals(accepted)} />);
    const tiers = screen.getByTestId("tiers");
    expect(within(tiers).getAllByRole("listitem")).toHaveLength(2);
    expect(tiers).toHaveTextContent("84.0%");
    expect(tiers).toHaveTextContent("counts as 0");
    expect(screen.getAllByText("Accept").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("deal-talk")).not.toBeInTheDocument();
  });

  it("renders for a vendor with no gap table (nothing to negotiate) and lists terms that failed verification", () => {
    const st = stage("negotiate", {
      summary: "No negotiation needed",
      data: { gap_table: [], deals: dealsFixture({ assessments: [], rejected_terms: [{ id: "t3", label: "5% rebate", reasons: ["threshold: the quote states 2000"] }] }) },
    });
    render(<NegotiateView stage={st} />);
    expect(screen.getByText("No negotiation needed")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Deal evaluator" })).toHaveTextContent("Not valued: could not verify against the call");
  });
});
