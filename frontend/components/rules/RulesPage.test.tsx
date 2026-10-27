import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PolicyResponse } from "@/lib/policy";
import { RulesPage, READ_ONLY_TEXT, SAVED_TOAST } from "./RulesPage";

afterEach(() => vi.unstubAllGlobals());

const policy = {
  onboarding: { required_terms: ["margin_offered_pct"], vendor_types: { d2c: { label: "D2C", target_offset_pp: 0 } } },
  taxonomy: {
    categories: [{ name: "Skincare", patterns: ["serum"], subcategories: { face: ["serum"] } }],
    fallback_category: "Skincare",
    segments: [],
  },
  screening: { documents: [{ type: "GST", blocking: true, categories: "all" }], claim_rules: [] },
  research: { demand_min: 0.4, mystery_knob: 7, flag: true },
  verifier: { tolerances: { pct: 0.01, inr: 1 }, max_self_corrections: 2 },
  impact: {
    baseline_status: "placeholder",
    baseline_minutes: { screening: 30, catalog_listing_per_sku: 20 },
    team: { category_managers: 6 },
    target_reduction_pct: 33.3,
  },
  margins: { categories: { Skincare: { target_pct: 30, min_pct: 20, payment_terms_days: 30 } }, brands: {} },
};

function resp(over: Partial<PolicyResponse> = {}): PolicyResponse {
  return {
    policy, defaults: structuredClone(policy), overridden_paths: [], hash: "h1", editable: true,
    schema_hints: {
      "research.demand_min": { label: "Minimum demand", unit: "0 to 1", min: 0, max: 1, step: 0.05, kind: "number", used_in: ["research"] },
      "research.flag": { label: "Strict mode", kind: "bool" },
      "onboarding.required_terms": { label: "Required terms", kind: "string_list" },
      "verifier.max_self_corrections": { label: "Self-corrections", help: "How many retries the agent gets.", unit: "retries", min: 0, max: 5, step: 1, kind: "number", used_in: ["research", "negotiate", "catalog"] },
      "impact.baseline_status": { label: "Baseline status", help: "placeholder: the times and team numbers here are guesses.", kind: "enum", options: ["placeholder", "measured"], used_in: ["impact"] },
      "impact.baseline_minutes": { label: "Baseline minutes per task", help: "How long the team spends today. Placeholders until you replace them.", used_in: ["impact"] },
      "impact.baseline_minutes.screening": { label: "Screening", unit: "min", min: 0, max: 6000, step: 5, kind: "number", used_in: ["impact"] },
      "impact.baseline_minutes.catalog_listing_per_sku": { label: "Catalog listing, per SKU", unit: "min", kind: "number", used_in: ["impact"] },
      "impact.team.category_managers": { label: "Category managers", help: "People on the category team (placeholder).", kind: "number", used_in: ["impact"] },
      "impact.target_reduction_pct": { label: "Workload target", unit: "%", kind: "number", used_in: ["impact"] },
    },
    ...over,
  };
}

const json = (b: unknown, s = 200) =>
  new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });

function setup(r = resp(), put?: (body: unknown) => Response) {
  const puts: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "PUT") {
      const body = JSON.parse(String(init?.body));
      puts.push(body);
      return put ? put(body) : json(r);
    }
    return json(r);
  }));
  render(<RulesPage />);
  return puts;
}

const open = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

describe("RulesPage", () => {
  it("renders fields from schema_hints and falls back by value type when a hint is missing", async () => {
    setup();
    open("Research");
    const demand = await screen.findByRole("spinbutton", { name: "Minimum demand" });
    expect(demand).toHaveValue(0.4);
    expect(demand).toHaveAttribute("max", "1");
    expect(screen.getByRole("switch", { name: "Strict mode" })).toBeChecked();
    // no hint: humanized key, number input
    expect(screen.getByRole("spinbutton", { name: "Mystery knob" })).toHaveValue(7);
  });

  it("tracks dirty fields and saves a minimal partial", async () => {
    const puts = setup(resp(), () => json(resp({ hash: "h2", overridden_paths: ["research.demand_min"] })));
    open("Research");
    const demand = await screen.findByRole("spinbutton", { name: "Minimum demand" });
    expect(screen.queryByText(/unsaved change/)).not.toBeInTheDocument();
    fireEvent.change(demand, { target: { value: "0.5" } });
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(SAVED_TOAST);
    expect(puts).toEqual([{ research: { demand_min: 0.5 } }]);
    expect(screen.queryByText(/unsaved change/)).not.toBeInTheDocument();
  });

  it("discard restores the saved values", async () => {
    setup();
    open("Research");
    const demand = await screen.findByRole("spinbutton", { name: "Minimum demand" });
    fireEvent.change(demand, { target: { value: "0.9" } });
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: "Minimum demand" })).toHaveValue(0.4));
  });

  it("disables inputs and shows the banner when read-only", async () => {
    setup(resp({ editable: false }));
    open("Research");
    expect(await screen.findByText(READ_ONLY_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Minimum demand" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Strict mode" })).toBeDisabled();
  });

  it("shows a 422 inline under the field", async () => {
    setup(resp(), () =>
      json({ code: "policy_invalid", problem: "demand_min must be at most 1", fix: "Use 0 to 1.", path: "research.demand_min" }, 422),
    );
    open("Research");
    fireEvent.change(await screen.findByRole("spinbutton", { name: "Minimum demand" }), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const field = (await screen.findByText(/must be at most 1/)).closest("[data-path]");
    expect(field).toHaveAttribute("data-path", "research.demand_min");
  });

  it("removing a table row sends a null tombstone; scopes pick from the taxonomy", async () => {
    const puts = setup();
    open("Onboarding");
    fireEvent.click(await screen.findByRole("button", { name: "Remove d2c" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({ onboarding: { vendor_types: { d2c: null } } });
    open("Screening");
    const gst = await screen.findByRole("checkbox", { name: "GST applies to all categories" });
    fireEvent.click(gst);
    expect(within(document.body).getByRole("checkbox", { name: "GST category Skincare" })).toBeInTheDocument();
  });

  it("edits the self-correction retry limit under Verifier", async () => {
    const puts = setup(resp(), () => json(resp({ hash: "h3" })));
    open("Verifier");
    const limit = await screen.findByRole("spinbutton", { name: "Self-corrections" });
    expect(limit).toHaveValue(2);
    expect(limit).toHaveAttribute("max", "5");
    fireEvent.change(limit, { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({ verifier: { max_self_corrections: 1 } });
  });

  it("renders the Impact section from schema_hints and says the baselines are placeholders", async () => {
    const puts = setup(resp(), () => json(resp({ hash: "h4" })));
    open("Impact");
    const screening = await screen.findByRole("spinbutton", { name: "Screening" });
    expect(screening).toHaveValue(30);
    expect(screen.getByRole("spinbutton", { name: "Catalog listing, per SKU" })).toHaveValue(20);
    expect(screen.getByRole("spinbutton", { name: "Category managers" })).toHaveValue(6);
    expect(screen.getByText(/Placeholders until you replace them/)).toBeInTheDocument();
    expect(screen.getByText(/guesses/)).toBeInTheDocument();
    fireEvent.change(screening, { target: { value: "45" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({ impact: { baseline_minutes: { screening: 45 } } });
  });

  it("links to the starter playbooks", async () => {
    setup();
    const a = await screen.findByRole("link", { name: "config/examples" });
    expect(a).toHaveAttribute("href", "https://github.com/Nandish3010/categoryos/tree/main/config/examples");
  });
});
