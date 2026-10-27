import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockBackend, researchData, snapshot, stage } from "../test-utils/mockBackend";
import { runImpact, teamImpact } from "../test-utils/impact";
import VendorsBoard from "../app/page";
import { ImpactTeam } from "./ImpactTeam";
import { ImpactChip, ImpactPanel } from "./workspace/ImpactPanel";
import { Workspace } from "./workspace/Workspace";

afterEach(() => vi.unstubAllGlobals());

describe("ImpactPanel", () => {
  it("shows the headline, the review steps and labels placeholder baselines", () => {
    render(<ImpactPanel impact={runImpact()} onClose={() => {}} />);
    const panel = screen.getByRole("region", { name: "Impact" });
    expect(within(panel).getByText(/So far: baseline 4.0 h → 10 min human review \(−96%\)/)).toBeInTheDocument();
    expect(within(panel).getByText("Measured review time")).toBeInTheDocument();
    expect(within(panel).getByText("Research estimate (not measured)")).toBeInTheDocument();
    const rows = within(panel).getAllByRole("row");
    expect(rows.some((r) => r.getAttribute("data-status") === "pending")).toBe(true);
    expect(within(panel).getAllByText("not reviewed yet", { selector: "td" })).toHaveLength(2);
    expect(within(panel).getByText("Decision review")).toBeInTheDocument();
    expect(within(panel).getByText(/up to 120 minutes per step/)).toBeInTheDocument();
  });

  it("calls itself a baseline estimate when nothing has been reviewed", () => {
    render(<ImpactPanel impact={runImpact({ measured_gates: 0, basis: "research_estimate", reduction_pct: null, human_minutes: 0 })} onClose={() => {}} />);
    expect(screen.getByText("Baseline estimate: nothing reviewed yet")).toBeInTheDocument();
    expect(screen.queryByText("Measured review time")).toBeNull();
  });

  it("drops the placeholder label once the playbook says the baselines are measured", () => {
    render(<ImpactPanel impact={runImpact({ baseline_status: "measured" })} onClose={() => {}} />);
    expect(screen.queryByText("Research estimate (not measured)")).toBeNull();
  });

  it("closes", () => {
    const onClose = vi.fn();
    render(<ImpactPanel impact={runImpact()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close impact" }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("ImpactChip", () => {
  it("is a toggle with the headline as its title", () => {
    const onToggle = vi.fn();
    render(<ImpactChip impact={runImpact()} open={false} onToggle={onToggle} />);
    const chip = screen.getByRole("button", { name: /Impact −96% so far/ });
    expect(chip).toHaveAttribute("aria-expanded", "false");
    expect(chip.getAttribute("title")).toMatch(/So far: baseline/);
    fireEvent.click(chip);
    expect(onToggle).toHaveBeenCalled();
  });
});

describe("ImpactTeam", () => {
  it("is honest that it is a research estimate, and lists every module as shipped or not yet built", () => {
    render(<ImpactTeam impact={teamImpact()} />);
    const sec = screen.getByRole("region", { name: "Team impact" });
    expect(within(sec).getByText("Estimate, not measured")).toBeInTheDocument();
    expect(within(sec).getByText("Research estimate (not measured)")).toBeInTheDocument();
    expect(within(sec).getAllByText("18.5%").length).toBeGreaterThan(0); // in scope
    expect(within(sec).getAllByText("8.8%").length).toBeGreaterThan(0); // saved
    expect(within(sec).getByText(/goal 33.3% · not met/)).toBeInTheDocument();
    expect(within(sec).getByText("1 CM + 2 CE, 45 h week")).toBeInTheDocument();
    const rows = within(sec).getAllByRole("row");
    expect(rows.find((r) => r.getAttribute("data-status") === "shipped")).toHaveTextContent("Shipped");
    expect(rows.find((r) => r.getAttribute("data-status") === "not_built")).toHaveTextContent("Not yet built");
    fireEvent.click(within(sec).getByText("How this is calculated"));
    expect(within(sec).getByText(/saved % of the week = sum over tasks/)).toBeInTheDocument();
    expect(within(sec).getByText(/Category executives \(2\): 18.8% in scope, 9.1% saved/)).toBeInTheDocument();
    expect(within(sec).getByText(/No run has been fully reviewed yet/)).toBeInTheDocument();
  });

  it("says measured on N runs once onboarding has fully reviewed runs", () => {
    const base = teamImpact();
    render(
      <ImpactTeam
        impact={teamImpact({ basis: "measured", measured_runs: 3, baseline_status: "measured", meets_target: true, onboarding: { ...base.onboarding, human_share_pct: 8.4, saved_pct_basis: "measured" } })}
      />,
    );
    const sec = screen.getByRole("region", { name: "Team impact" });
    expect(within(sec).getByText("Onboarding measured on 3 runs")).toBeInTheDocument();
    expect(within(sec).queryByText("Research estimate (not measured)")).toBeNull();
    expect(within(sec).getByText(/goal 33.3% · met/)).toBeInTheDocument();
    fireEvent.click(within(sec).getByText("How this is calculated"));
    expect(within(sec).getByText(/human review took 8.4% of the by-hand time over 3 fully reviewed runs/)).toBeInTheDocument();
  });
});

describe("Vendors board impact wiring", () => {
  it("fetches /api/impact and shows the team projection above the vendors", async () => {
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input)).pathname;
        if (path === "/api/vendors") return json([]);
        if (path === "/api/impact") return json(teamImpact());
        return json({ run_id: null });
      }),
    );
    render(<VendorsBoard />);
    expect(await screen.findByRole("region", { name: "Team impact" })).toBeInTheDocument();
    expect(screen.getByText("Hours saved per month")).toBeInTheDocument();
  });

  it("shows no team block on a backend without the endpoint", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ problem: "nope" }), { status: 404 })));
    render(<VendorsBoard />);
    await screen.findByText("CategoryOS");
    expect(screen.queryByRole("region", { name: "Team impact" })).toBeNull();
  });
});

describe("Workspace impact wiring", () => {
  it("shows the impact chip once the run carries an impact block and opens the panel", async () => {
    const run = {
      ...snapshot({ research: stage("research", { status: "review", needs_approval: true, narrative_hash: "hash-lever-1", data: researchData }) }),
      impact: runImpact(),
    };
    vi.stubGlobal("fetch", mockBackend({ run }));
    render(<Workspace vendorId="V001" />);
    const chip = await screen.findByRole("button", { name: /Impact −96% so far/ });
    expect(screen.queryByRole("region", { name: "Impact" })).toBeNull();
    fireEvent.click(chip);
    expect(await screen.findByRole("region", { name: "Impact" })).toBeInTheDocument();
  });
});
